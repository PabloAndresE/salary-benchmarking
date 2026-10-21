"""Las nominas que suben los clientes, guardadas para aprender de ellas.

QUE SE GUARDA: por cada fila, el cargo tal como lo escribio el cliente y su sueldo, mas
lo que hace falta para usarlos —de que empresa (RUC), de que carga, de que ano— y lo que
el modelo respondio, para medir la homologacion. NADA MAS: ni nombre, ni cedula, ni id de
empleado, ni sexo, ni fechas, ni centro de costo. Se construye por LISTA BLANCA de
columnas, no quitando las prohibidas: una columna nueva en la plantilla no se cuela sola.

La base legal es el contrato: las empresas firman que sus datos se usan para el estudio.

APAGADO POR DEFECTO (`GUARDAR_NOMINAS=si` lo enciende). Y si falla, el informe NO falla:
el cliente recibe su resultado igual y el error queda en el log. Guardar es para nosotros,
el informe es para el.

Lo guardado NO entra solo a la base: pasa por el mismo camino que los estudios (limpieza,
duplicados por `carga_hash`, unidades) antes de una version nueva.
"""
import datetime as _dt
import hashlib
import os

import pandas as pd

# El contrato de la tabla. El orden es el de las columnas en BigQuery.
ESQUEMA = (
    ("id_carga", "STRING"),             # el id del informe: une las filas de una carga
    ("carga_hash", "STRING"),           # sha256 del archivo: la misma nomina subida dos veces
    ("fecha_carga", "TIMESTAMP"),
    ("anio", "INTEGER"),                # el ano del SBU con que se pidio el informe
    ("empresa_ruc", "STRING"),          # el que mando el cliente; NULL si no lo mando
    ("ciiu", "STRING"),                 # el del padron para ese RUC
    ("segmento", "STRING"),             # el que se uso en el informe (pedido o del RUC)
    ("fila", "INTEGER"),                # orden en el archivo, para leer la carga como llego
    ("cargo", "STRING"),                # tal como lo escribio el cliente
    ("cargo_corregido_usuario", "STRING"),  # si el usuario lo corrigio en el front (`mapeo`)
    ("sueldo", "FLOAT"),                # el de la columna de sueldo; NULL si no habia
    ("puesto_asignado", "STRING"),      # el puesto de la base al que se homologo
    ("via", "STRING"),                  # datos directos / por analogia / por traduccion...
    ("referencia", "FLOAT"),            # lo que le dijimos
    ("confianza", "STRING"),
)


def activo() -> bool:
    return os.environ.get("GUARDAR_NOMINAS", "no").lower() == "si"


def tabla_destino(settings) -> str:
    t = os.environ.get("NOMINAS_TABLA")
    if t:
        return t
    return f"{settings.bq_project}.{getattr(settings, 'bq_dataset', 'benchmarking')}.nominas_recibidas"


def hash_carga(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def filas_registro(df: pd.DataFrame, col_cargo: str, col_sueldo: str | None,
                   detalle: list[dict], *, id_carga: str, carga_hash: str, anio: int,
                   ruc: str | None, ciiu: str | None, segmento: str | None,
                   correcciones: dict[int, str] | None = None,
                   fecha: _dt.datetime | None = None) -> list[dict]:
    """Las filas a guardar. Pura: sin red, para poder probarla.

    `df` es el archivo TAL COMO LLEGO (antes de aplicar las correcciones del usuario), y
    `detalle` el del informe, que trae lo que respondio el modelo fila por fila.
    """
    fecha = fecha or _dt.datetime.now(_dt.timezone.utc)
    correcciones = correcciones or {}
    por_fila = {int(d["fila"]): d for d in detalle if d.get("fila") is not None}
    cargos = df[col_cargo].fillna("").astype(str).str.strip()
    sueldos = (pd.to_numeric(df[col_sueldo], errors="coerce") if col_sueldo
               else pd.Series([None] * len(df)))
    filas = []
    for i, (cargo, sueldo) in enumerate(zip(cargos, sueldos)):
        if not cargo and pd.isna(sueldo):
            continue                        # fila vacia de la hoja: no dice nada
        d = por_fila.get(i, {})
        filas.append({
            "id_carga": id_carga,
            "carga_hash": carga_hash,
            "fecha_carga": fecha.isoformat(),
            "anio": int(anio),
            "empresa_ruc": (ruc or "").strip() or None,
            "ciiu": ciiu or None,
            "segmento": segmento or None,
            "fila": i,
            "cargo": cargo or None,
            "cargo_corregido_usuario": correcciones.get(i),
            "sueldo": None if pd.isna(sueldo) else float(sueldo),
            "puesto_asignado": _puesto(d),
            "via": d.get("base") or None,
            "referencia": d.get("referencia"),
            "confianza": d.get("confianza") or None,
        })
    return filas


def _puesto(d: dict) -> str | None:
    """El puesto de la base al que se homologo la fila. `cargo_base` viene vacio cuando el
    titulo ES el puesto (coincidencia exacta): entonces el puesto es el titulo
    normalizado. Por analogia no hay puesto —la cifra sale de vecinos— y queda NULL."""
    if d.get("cargo_base"):
        return d["cargo_base"]
    via = str(d.get("base") or "")
    if via == "datos directos" or via.startswith("rubro"):
        return d.get("cargo_normalizado") or None
    return None


_CLIENTE = None


def guardar(filas: list[dict], tabla: str, project: str | None = None) -> None:
    """Anade las filas a la tabla (la crea si no existe, particionada por dia)."""
    if not filas:
        return
    global _CLIENTE
    from google.cloud import bigquery
    if _CLIENTE is None:
        _CLIENTE = bigquery.Client(project=project)
    cfg = bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField(n, t) for n, t in ESQUEMA],
        write_disposition="WRITE_APPEND",
        time_partitioning=bigquery.TimePartitioning(field="fecha_carga"),
        clustering_fields=["empresa_ruc"],
    )
    _CLIENTE.load_table_from_json(filas, tabla, job_config=cfg).result()
