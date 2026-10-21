"""Las nominas que suben los clientes, guardadas para aprender de ellas.

VAN AL DATASET DEL PRODUCTO (`benchmarking`), separado del de la tesis, en tres tablas:

  cargas          una fila por nomina subida: de que empresa, cuando, con que version
  nomina_filas    una fila por empleado: el cargo tal como lo escribio el cliente y su sueldo
  homologaciones  una fila por empleado: lo que respondio el modelo

QUE SE GUARDA del empleado: cargo y sueldo. NADA MAS: ni nombre, ni cedula, ni id de
empleado, ni sexo, ni fechas, ni centro de costo. Se construye por LISTA BLANCA de
columnas, no quitando las prohibidas: una columna nueva en la plantilla no se cuela sola.
La base legal es el contrato: las empresas firman que sus datos se usan para el estudio.

ENCENDIDO POR DEFECTO (`GUARDAR_NOMINAS=no` lo apaga). Y si falla, el informe NO falla:
el cliente recibe su resultado igual y el error queda en el log. Guardar es para nosotros,
el informe es para el.

Lo guardado NO entra solo a la base: pasa por el mismo camino que los estudios (limpieza,
duplicados por `carga_hash`, unidades) antes de una version nueva.
"""
import datetime as _dt
import hashlib
import os
import pathlib

import pandas as pd

DATASET_POR_DEFECTO = "act-cicd-stage-prueba.benchmarking"

# El contrato de las tablas, en el orden de las columnas en BigQuery. Las tres llevan
# `fecha_carga`: es la columna de particion, y sin ella cada join leeria la tabla entera.
ESQUEMAS = {
    "cargas": (
        ("id_carga", "STRING"),             # el id del informe
        ("fecha_carga", "TIMESTAMP"),
        ("carga_hash", "STRING"),           # sha256 del archivo: la misma nomina subida dos veces
        ("anio", "INTEGER"),                # el ano del SBU con que se pidio el informe
        ("empresa_ruc", "STRING"),          # el que mando el cliente; NULL si no lo mando
        ("ciiu", "STRING"),                 # el del padron para ese RUC
        ("segmento", "STRING"),             # el que se uso (pedido o del RUC)
        ("rubro", "STRING"),                # la seccion CIIU con que se comparo
        ("n_filas", "INTEGER"),
        ("columna_cargo", "STRING"),        # como se llamaban en el archivo
        ("columna_sueldo", "STRING"),
        ("correcciones", "INTEGER"),        # filas corregidas por el usuario (`mapeo`)
        ("version_api", "STRING"),
        ("version_base", "STRING"),
    ),
    "nomina_filas": (
        ("id_carga", "STRING"),
        ("fecha_carga", "TIMESTAMP"),
        ("fila", "INTEGER"),                # orden en el archivo
        ("cargo", "STRING"),                # tal como lo escribio el cliente
        ("cargo_corregido_usuario", "STRING"),
        ("sueldo", "FLOAT"),                # NULL si no habia columna o no era un numero
    ),
    "homologaciones": (
        ("id_carga", "STRING"),
        ("fecha_carga", "TIMESTAMP"),
        ("fila", "INTEGER"),
        ("cargo_normalizado", "STRING"),
        ("puesto_asignado", "STRING"),      # el puesto de la base; NULL por analogia
        ("via", "STRING"),                  # datos directos / rubro X / por analogia / por traduccion
        ("estado", "STRING"),
        ("similitud", "FLOAT"),
        ("p_juez", "FLOAT"),
        ("referencia", "FLOAT"),            # lo que le dijimos, en dolares
        ("p25", "FLOAT"),
        ("p75", "FLOAT"),
        ("confianza", "STRING"),
        ("rubro", "STRING"),                # el CIIU al que se bajo en la cascada
        ("rubro_nivel", "STRING"),
    ),
}
# Se escriben las filas antes que la cabecera: una carga en `cargas` esta completa.
ORDEN = ("nomina_filas", "homologaciones", "cargas")


def activo() -> bool:
    return os.environ.get("GUARDAR_NOMINAS", "si").lower() != "no"


def dataset_destino() -> str:
    return os.environ.get("BENCHMARKING_DATASET", DATASET_POR_DEFECTO)


def version_base(ruta_base: str) -> str:
    """`VERSION_BASE` si se definio (en la imagen la base se llama siempre igual); si no,
    el nombre del archivo: `base_v31`."""
    return os.environ.get("VERSION_BASE") or pathlib.Path(str(ruta_base)).stem


def hash_carga(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _txt(v):
    s = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
    return s or None


def _puesto(cargo_base, via, cargo_normalizado):
    """`cargo_base` viene vacio cuando el titulo ES el puesto (coincidencia exacta):
    entonces el puesto es el titulo normalizado. Por analogia no hay puesto —la cifra
    sale de vecinos— y queda NULL."""
    if _txt(cargo_base):
        return _txt(cargo_base)
    via = str(via or "")
    if via == "datos directos" or via.startswith("rubro"):
        return _txt(cargo_normalizado)
    return None


def registro(df: pd.DataFrame, col_cargo: str, col_sueldo: str | None,
             detalle: list[dict], homologacion: pd.DataFrame | None, *,
             id_carga: str, carga_hash: str, anio: int, ruc: str | None,
             ciiu: str | None, segmento: str | None, rubro: str | None,
             correcciones: dict[int, str] | None, version_api: str, version_base: str,
             fecha: _dt.datetime | None = None) -> dict[str, list[dict]]:
    """Las filas de las tres tablas. Pura: sin red, para poder probarla.

    `df` es el archivo TAL COMO LLEGO (antes de las correcciones del usuario), `detalle`
    el del informe y `homologacion` la salida cruda de `referenciar`, fila por fila: de
    ahi salen `cargo_base` y `p_juez`, que el detalle no siempre trae.
    """
    fecha = (fecha or _dt.datetime.now(_dt.timezone.utc)).isoformat()
    correcciones = correcciones or {}
    det = {int(d["fila"]): d for d in detalle if d.get("fila") is not None}
    hom = (homologacion.reset_index(drop=True).to_dict("records")
           if homologacion is not None else [])
    cargos = df[col_cargo].fillna("").astype(str).str.strip()
    sueldos = df[col_sueldo] if col_sueldo else [None] * len(df)

    filas, homs = [], []
    for i, (cargo, sueldo) in enumerate(zip(cargos, sueldos)):
        sueldo = _num(sueldo)
        if not cargo and sueldo is None:
            continue                        # fila vacia de la hoja: no dice nada
        d = det.get(i, {})
        h = hom[i] if i < len(hom) else {}
        filas.append({"id_carga": id_carga, "fecha_carga": fecha, "fila": i,
                      "cargo": cargo or None,
                      "cargo_corregido_usuario": correcciones.get(i),
                      "sueldo": sueldo})
        via = _txt(d.get("base") or h.get("base"))
        homs.append({"id_carga": id_carga, "fecha_carga": fecha, "fila": i,
                     "cargo_normalizado": _txt(d.get("cargo_normalizado")),
                     "puesto_asignado": _puesto(h.get("cargo_base", d.get("cargo_base")),
                                                via, d.get("cargo_normalizado")),
                     "via": via,
                     "estado": _txt(d.get("estado")),
                     "similitud": _num(d.get("similitud", h.get("similitud"))),
                     "p_juez": _num(h.get("p_juez", d.get("p_juez"))),
                     "referencia": _num(d.get("referencia")),
                     "p25": _num(d.get("p25")),
                     "p75": _num(d.get("p75")),
                     "confianza": _txt(d.get("confianza")),
                     "rubro": _txt(d.get("rubro")),
                     "rubro_nivel": _txt(d.get("rubro_nivel"))})
    cabecera = {"id_carga": id_carga, "fecha_carga": fecha, "carga_hash": carga_hash,
                "anio": int(anio), "empresa_ruc": _txt(ruc), "ciiu": _txt(ciiu),
                "segmento": _txt(segmento), "rubro": _txt(rubro), "n_filas": len(filas),
                "columna_cargo": col_cargo, "columna_sueldo": col_sueldo,
                "correcciones": len(correcciones), "version_api": version_api,
                "version_base": version_base}
    return {"cargas": [cabecera], "nomina_filas": filas, "homologaciones": homs}


def ddl(dataset: str) -> str:
    """El `CREATE TABLE IF NOT EXISTS` de las tres tablas, desde `ESQUEMAS`: el esquema
    tiene una sola fuente, la misma que usa la API al escribir."""
    tipos = {"FLOAT": "FLOAT64", "INTEGER": "INT64"}
    sentencias = []
    for nombre, cols in ESQUEMAS.items():
        campos = ",\n  ".join(f"{n} {tipos.get(t, t)}" for n, t in cols)
        sentencias.append(
            f"CREATE TABLE IF NOT EXISTS `{dataset}.{nombre}` (\n  {campos}\n)\n"
            f"PARTITION BY DATE(fecha_carga)\nCLUSTER BY id_carga;")
    return "\n\n".join(sentencias)


_CLIENTE = None


def guardar(tablas: dict[str, list[dict]], dataset: str) -> None:
    """Anade las filas a cada tabla (la crea si no existe, particionada por dia)."""
    global _CLIENTE
    from google.cloud import bigquery
    if _CLIENTE is None:
        _CLIENTE = bigquery.Client(project=dataset.split(".")[0])
    for nombre in ORDEN:
        filas = tablas.get(nombre) or []
        if not filas:
            continue
        cfg = bigquery.LoadJobConfig(
            schema=[bigquery.SchemaField(n, t) for n, t in ESQUEMAS[nombre]],
            write_disposition="WRITE_APPEND",
            time_partitioning=bigquery.TimePartitioning(field="fecha_carga"),
            clustering_fields=["id_carga"],
        )
        _CLIENTE.load_table_from_json(filas, f"{dataset}.{nombre}", job_config=cfg).result()
