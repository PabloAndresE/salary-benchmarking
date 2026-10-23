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
import logging
import os
import pathlib
import time
import uuid

import pandas as pd

from src.persistence import bigquery_client
from src.persistence.tablas import ESQUEMAS, ORDEN  # noqa: F401 (ESQUEMAS se reexporta para los tests)
from src.shared.constants import ESQUEMA

logger = logging.getLogger(__name__)

DATASET_POR_DEFECTO = "act-cicd-stage-prueba.benchmarking"


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
    except TypeError, ValueError:
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


def registro(
    df: pd.DataFrame,
    col_cargo: str,
    col_sueldo: str | None,
    detalle: list[dict],
    homologacion: pd.DataFrame | None,
    *,
    id_carga: str,
    carga_hash: str,
    anio: int,
    ruc: str | None,
    ciiu: str | None,
    segmento: str | None,
    rubro: str | None,
    correcciones: dict[int, str] | None,
    version_api: str,
    version_base: str,
    fecha: _dt.datetime | None = None,
) -> dict[str, list[dict]]:
    """Las filas de las tres tablas. Pura: sin red, para poder probarla.

    `df` es el archivo TAL COMO LLEGO (antes de las correcciones del usuario), `detalle`
    el del informe y `homologacion` la salida cruda de `referenciar`, fila por fila: de
    ahi salen `cargo_base` y `p_juez`, que el detalle no siempre trae.
    """
    fecha = (fecha or _dt.datetime.now(_dt.timezone.utc)).isoformat()
    correcciones = correcciones or {}
    det = {int(d["fila"]): d for d in detalle if d.get("fila") is not None}
    hom = homologacion.reset_index(drop=True).to_dict("records") if homologacion is not None else []
    cargos = df[col_cargo].fillna("").astype(str).str.strip()
    sueldos = df[col_sueldo] if col_sueldo else [None] * len(df)

    filas, homs = [], []
    for i, (cargo, sueldo) in enumerate(zip(cargos, sueldos)):
        sueldo = _num(sueldo)
        if not cargo and sueldo is None:
            continue  # fila vacia de la hoja: no dice nada
        d = det.get(i, {})
        h = hom[i] if i < len(hom) else {}
        filas.append(
            {
                "id_carga": id_carga,
                "fecha_carga": fecha,
                "fila": i,
                "cargo": cargo or None,
                "cargo_corregido_usuario": correcciones.get(i),
                "sueldo": sueldo,
            }
        )
        via = _txt(d.get("base") or h.get("base"))
        homs.append(
            {
                "id_carga": id_carga,
                "fecha_carga": fecha,
                "fila": i,
                "cargo_normalizado": _txt(d.get("cargo_normalizado")),
                "puesto_asignado": _puesto(h.get("cargo_base", d.get("cargo_base")), via, d.get("cargo_normalizado")),
                "via": via,
                "estado": _txt(d.get("estado")),
                "similitud": _num(d.get("similitud", h.get("similitud"))),
                "p_juez": _num(h.get("p_juez", d.get("p_juez"))),
                "referencia": _num(d.get("referencia")),
                "p25": _num(d.get("p25")),
                "p75": _num(d.get("p75")),
                "confianza": _txt(d.get("confianza")),
                "rubro": _txt(d.get("rubro")),
                "rubro_nivel": _txt(d.get("rubro_nivel")),
            }
        )
    cabecera = {
        "id_carga": id_carga,
        "fecha_carga": fecha,
        "carga_hash": carga_hash,
        "anio": int(anio),
        "empresa_ruc": _txt(ruc),
        "ciiu": _txt(ciiu),
        "segmento": _txt(segmento),
        "rubro": _txt(rubro),
        "n_filas": len(filas),
        "columna_cargo": col_cargo,
        "columna_sueldo": col_sueldo,
        "correcciones": len(correcciones),
        "version_api": version_api,
        "version_base": version_base,
    }
    return {"cargas": [cabecera], "nomina_filas": filas, "homologaciones": homs}


def guardar(tablas: dict[str, list[dict]], dataset: str) -> None:
    """Escribe la carga en sus tres tablas, la cabecera (`cargas`) al final."""
    for nombre in ORDEN:
        filas = tablas.get(nombre) or []
        claves = [f"{f['id_carga']}:{nombre}:{f.get('fila', '')}" for f in filas]
        bigquery_client.insertar_filas(dataset=dataset, tabla=nombre, filas=filas, claves=claves)


def nuevo_id() -> str:
    return uuid.uuid4().hex


def guardar_carga(
    *,
    df: pd.DataFrame,
    col_cargo: str,
    col_sueldo: str | None,
    detalle: list[dict],
    homologacion: pd.DataFrame | None,
    id_carga: str,
    contenido: bytes,
    anio: int,
    ruc: str | None,
    ciiu: str | None,
    segmento: str | None,
    rubro: str | None,
    correcciones: dict[int, str] | None,
    ruta_base: str,
) -> bool:
    """Guarda la carga si el registro esta encendido. NUNCA lanza: si BigQuery falla, el
    informe sale igual y el error queda en el log. Devuelve si se guardo."""
    if not activo():
        return False
    t0 = time.perf_counter()
    try:
        tablas = registro(
            df,
            col_cargo,
            col_sueldo,
            detalle,
            homologacion,
            id_carga=id_carga,
            carga_hash=hash_carga(contenido),
            anio=anio,
            ruc=ruc,
            ciiu=ciiu,
            segmento=segmento,
            rubro=rubro,
            correcciones=correcciones,
            version_api=os.environ.get("VERSION_API") or f"esquema {ESQUEMA}",
            version_base=version_base(ruta_base),
        )
        guardar(tablas, dataset_destino())
    except Exception:
        logger.error("guardar_carga: fallo la carga %s", id_carga, exc_info=True)
        return False
    logger.info(
        "guardar_carga: %d filas de la carga %s en %.1fms",
        len(tablas["nomina_filas"]),
        id_carga,
        (time.perf_counter() - t0) * 1000,
    )
    return True
