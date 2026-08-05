from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from .adquisicion.bigquery_source import (
    leer_personas, leer_scvs, listar_estudios, leer_personas_por_proceso)
from .adquisicion.plantilla_client import descargar_plantilla
from .ingesta.composicion import parsear_plantilla, _norm
from .ingesta.anonimizacion import anonimizar
from .ingesta.validacion import marcar_cuarentena
from .ingesta.features_base import agregar_features
from .ingesta.enriquecimiento import unir_scvs

def _una_plantilla(e, base_url, descargar):
    """Descarga+parsea la plantilla de un estudio. Devuelve montos por cédula, o None
    (con aviso) ante 5xx agotado / XLSX corrupto / columna ausente / plantilla inexistente.
    Worker aislado y sin estado compartido: seguro para correr en hilos."""
    try:
        raw = descargar(e.numero_proceso, e.id_version, base_url)
        if not raw:
            return None
        m = parsear_plantilla(raw)[["identificacion", "comisiones", "extras", "otros"]].copy()
    except Exception as exc:                              # noqa: BLE001 — omitir estudio, no el lote
        print(f"[composicion] estudio {e.numero_proceso} omitido: {type(exc).__name__}: {exc}")
        return None
    m["identificacion"] = m["identificacion"].astype(str)
    m["numero_proceso"] = e.numero_proceso
    return m

def _composicion_estudios(estudios, base_url, descargar, max_workers=8):
    """Descarga la plantilla de cada estudio y devuelve solo los montos por (numero_proceso, cedula).

    Resiliencia de lote: un estudio cuya plantilla no descarga o no parsea
    (5xx agotados, XLSX corrupto, columna canónica ausente -> KeyError, etc.)
    se OMITE con un aviso; nunca tumba el lote (~48k estudios). Las personas
    de ese estudio se conservan en la base con composición NULL.
    """
    filas = list(estudios.itertuples())
    partes = []
    if max_workers and max_workers > 1 and len(filas) > 1:
        # I/O de red -> hilos. Cada worker crea su propia requests.Session (no se comparte).
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futuros = [ex.submit(_una_plantilla, e, base_url, descargar) for e in filas]
            for fut in as_completed(futuros):
                m = fut.result()
                if m is not None:
                    partes.append(m)
    else:
        for e in filas:
            m = _una_plantilla(e, base_url, descargar)
            if m is not None:
                partes.append(m)
    if partes:
        comp = pd.concat(partes, ignore_index=True)
        # protege el grano: una plantilla con cedula duplicada no debe inflar el merge
        return comp.drop_duplicates(subset=["numero_proceso", "identificacion"], keep="first")
    # Sin ninguna plantilla en el lote: columnas numéricas explícitas (no "object")
    # para que fillna/sum en agregar_features no degrade el dtype de `total`.
    return pd.DataFrame({
        "identificacion": pd.Series(dtype=str),
        "comisiones": pd.Series(dtype=float),
        "extras": pd.Series(dtype=float),
        "otros": pd.Series(dtype=float),
        "numero_proceso": pd.Series(dtype=str),
    })

def _ensamblar(base, scvs, base_url, settings, descargar, max_workers):
    base = base.copy()
    base["identificacion"] = base["identificacion"].astype(str)
    # tamaño de la nómina del estudio: contexto para juzgar la fiabilidad de la etiqueta de cargo
    base["n_personas_estudio"] = base.groupby("numero_proceso")["identificacion"].transform("size")
    estudios = base[["numero_proceso", "id_version"]].drop_duplicates()
    comp = _composicion_estudios(estudios, base_url, descargar, max_workers=max_workers)
    # enlace por cédula (cruda) ANTES de anonimizar; left join: NaN donde no hubo plantilla
    df = base.merge(comp, how="left", on=["numero_proceso", "identificacion"])
    df["cargo_norm"] = df["cargo"].map(_norm)
    df = anonimizar(df, settings.salt)                 # FRONTERA: elimina cédula (+ nombres si hubiera)
    df = agregar_features(df, settings)                # total/pct NULL-safe, sueldo_sbu, antiguedad...
    df = marcar_cuarentena(df, settings)               # depende de total -> corre despues de features
    return unir_scvs(df, scvs)

def construir_base(runner, base_url, settings, limite=None, descargar=descargar_plantilla, max_workers=None):
    base = leer_personas(runner, limite)               # BASE = estudios BQ, todas las filas
    if base.empty:
        return base
    workers = settings.descargas_concurrentes if max_workers is None else max_workers
    return _ensamblar(base, leer_scvs(runner), base_url, settings, descargar, workers)

def construir_universo(runner, base_url, settings, escribir_lote, batch_size=500,
                       max_workers=None, descargar=descargar_plantilla, hechos=frozenset()):
    workers = settings.descargas_concurrentes if max_workers is None else max_workers
    estudios = listar_estudios(runner)
    # Procesar RECIENTES primero: la composición (feature clave) solo existe en estudios
    # recientes (con plantilla); los viejos rinden filas sin composición. Así cada lote
    # aporta data útil cuanto antes. No afecta la reanudabilidad (se sigue saltando `hechos`).
    if "anio_valoracion" in estudios.columns:
        estudios = estudios.sort_values(
            ["anio_valoracion", "numero_proceso"], ascending=False, na_position="last")
    pendientes = [p for p in estudios["numero_proceso"].astype(str).tolist() if p not in hechos]
    scvs = leer_scvs(runner)                            # una sola vez para toda la corrida
    total = 0
    for i in range(0, len(pendientes), batch_size):
        lote = pendientes[i:i + batch_size]
        base = leer_personas_por_proceso(runner, lote)
        if base.empty:
            continue
        df = _ensamblar(base, scvs, base_url, settings, descargar, workers)
        escribir_lote(df)                              # append atómico (inyectado)
        total += len(df)
        print(f"[universo] lote {i // batch_size + 1}: {len(df)} filas (acumulado {total})")
    return total
