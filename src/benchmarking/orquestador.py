import pandas as pd
from .adquisicion.bigquery_source import leer_personas, leer_scvs
from .adquisicion.plantilla_client import descargar_plantilla
from .ingesta.composicion import parsear_plantilla, _norm
from .ingesta.anonimizacion import anonimizar
from .ingesta.validacion import marcar_cuarentena
from .ingesta.features_base import agregar_features
from .ingesta.enriquecimiento import unir_scvs

def _composicion_estudios(estudios, base_url, descargar):
    """Descarga la plantilla de cada estudio y devuelve solo los montos por (numero_proceso, cedula).

    Resiliencia de lote: un estudio cuya plantilla no descarga o no parsea
    (5xx agotados, XLSX corrupto, columna canónica ausente -> KeyError, etc.)
    se OMITE con un aviso; nunca tumba el lote (~48k estudios). Las personas
    de ese estudio se conservan en la base con composición NULL.
    """
    partes = []
    for e in estudios.itertuples():
        try:
            raw = descargar(e.numero_proceso, e.id_version, base_url)
            if not raw:
                continue                               # 5xx agotados o sin plantilla
            m = parsear_plantilla(raw)[["identificacion", "comisiones", "extras", "otros"]].copy()
        except Exception as exc:                        # noqa: BLE001 — omitir estudio, no el lote
            print(f"[composicion] estudio {e.numero_proceso} omitido: {type(exc).__name__}: {exc}")
            continue
        m["identificacion"] = m["identificacion"].astype(str)
        m["numero_proceso"] = e.numero_proceso
        partes.append(m)
    if partes:
        return pd.concat(partes, ignore_index=True)
    # Sin ninguna plantilla en el lote: columnas numéricas explícitas (no "object")
    # para que fillna/sum en agregar_features no degrade el dtype de `total`.
    return pd.DataFrame({
        "identificacion": pd.Series(dtype=str),
        "comisiones": pd.Series(dtype=float),
        "extras": pd.Series(dtype=float),
        "otros": pd.Series(dtype=float),
        "numero_proceso": pd.Series(dtype=str),
    })

def construir_base(runner, base_url, settings, limite=None, descargar=descargar_plantilla):
    base = leer_personas(runner, limite)               # BASE = estudios BQ, todas las filas
    if base.empty:
        return base
    base["identificacion"] = base["identificacion"].astype(str)
    estudios = base[["numero_proceso", "id_version"]].drop_duplicates()
    comp = _composicion_estudios(estudios, base_url, descargar)
    # enlace por cédula (cruda) ANTES de anonimizar; left join: NaN donde no hubo plantilla
    df = base.merge(comp, how="left", on=["numero_proceso", "identificacion"])
    df["cargo_orig"] = df["cargo"]
    df["cargo_norm"] = df["cargo"].map(_norm)
    df = anonimizar(df, settings.salt)                 # FRONTERA: elimina cédula (+ nombres si hubiera)
    df = agregar_features(df, settings)                # total/pct NULL-safe, sueldo_sbu, antiguedad...
    df = marcar_cuarentena(df, settings)               # depende de total -> corre despues de features
    df = unir_scvs(df, leer_scvs(runner))
    return df
