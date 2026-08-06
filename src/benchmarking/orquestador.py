from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from .adquisicion.bigquery_source import (
    leer_personas, leer_scvs, listar_estudios, leer_personas_por_proceso)
from .adquisicion.plantilla_client import (
    descargar_plantilla, DescargaFallida, PlantillaRechazada)
from .ingesta.composicion import parsear_plantilla, _norm
from .ingesta.anonimizacion import anonimizar
from .ingesta.validacion import marcar_cuarentena
from .ingesta.features_base import agregar_features
from .ingesta.enriquecimiento import unir_scvs

def _ced_key(v):
    """Llave de enlace para la cédula. **No sustituye a `identificacion`**: el `id_hash`
    se calcula siempre sobre el valor original, para no romper la comparabilidad con lo
    ya escrito.

    La plantilla guarda las cédulas **sin el cero inicial** (en algún punto pasaron por un
    formato numérico), y a veces con un ".0" espurio si pandas leyó la columna como float.
    La base de BigQuery sí conserva el cero. Enlazando por texto exacto fallaba **toda
    cédula de las provincias 01-09** (Azuay, Bolívar, Cañar, Carchi, Cotopaxi, Chimborazo,
    El Oro, Esmeraldas, Galápagos): no una pérdida al azar, sino un sesgo geográfico en la
    variable principal del modelo. Medido en un estudio real: 56,0% -> 77,1% de enlace,
    que es el techo (la plantilla tenía 84 personas y la base 109).

    Sólo se rellena con ceros lo que es enteramente numérico y mide menos de 10: los RUC
    de 13 dígitos y los pasaportes alfanuméricos quedan intactos.
    """
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(10) if s.isdigit() and len(s) < 10 else s


def _una_plantilla(e, base_url, descargar):
    """Descarga+parsea la plantilla de un estudio.

    Devuelve `(montos_por_cedula | None, motivo)` con motivo en:
      ok             - se obtuvo la composición
      sin_plantilla  - el estudio no tiene plantilla (404): ausencia legítima
      rechazado      - el servidor rechaza siempre (4xx): irrecuperable, no es pérdida
      fallo_descarga - no se pudo bajar tras agotar reintentos: PÉRDIDA de dato existente
      fallo_parseo   - se bajó pero el XLSX no se pudo leer

    La distinción importa: `sin_plantilla` es esperable en estudios de 2022 o antes y
    `rechazado` no se recupera reintentando, mientras que `fallo_descarga` es un dato que
    existía y se perdió. Mezclarlos convertiría el marcador de pérdidas en ruido.

    Worker aislado y sin estado compartido: seguro para correr en hilos.
    """
    try:
        raw = descargar(e.numero_proceso, e.id_version, base_url)
    except PlantillaRechazada as exc:
        print(f"[composicion] estudio {e.numero_proceso} rechazado: {exc}")
        return None, "rechazado"
    except DescargaFallida as exc:
        print(f"[composicion] estudio {e.numero_proceso} PERDIDO: {exc}")
        return None, "fallo_descarga"
    except Exception as exc:                              # noqa: BLE001 — omitir estudio, no el lote
        print(f"[composicion] estudio {e.numero_proceso} omitido: {type(exc).__name__}: {exc}")
        return None, "fallo_descarga"
    if not raw:
        return None, "sin_plantilla"
    try:
        m = parsear_plantilla(raw)[["identificacion", "comisiones", "extras", "otros"]].copy()
    except Exception as exc:                              # noqa: BLE001 — XLSX corrupto / columna ausente
        print(f"[composicion] estudio {e.numero_proceso} ilegible: {type(exc).__name__}: {exc}")
        return None, "fallo_parseo"
    m["identificacion"] = m["identificacion"].astype(str)
    m["_ced_key"] = m["identificacion"].map(_ced_key)
    m["numero_proceso"] = e.numero_proceso
    return m, "ok"

def _composicion_estudios(estudios, base_url, descargar, max_workers=8):
    """Descarga la plantilla de cada estudio y devuelve `(montos, conteo_por_motivo)`.

    Los montos van por (numero_proceso, cedula). El conteo es un Counter con los
    motivos de `_una_plantilla`, para que la degradación sea contable.

    Resiliencia de lote: un estudio cuya plantilla no descarga o no parsea se OMITE
    con un aviso; nunca tumba el lote (~48k estudios). Las personas de ese estudio se
    conservan en la base con composición NULL.
    """
    filas = list(estudios.itertuples())
    partes, conteo = [], Counter()
    if max_workers and max_workers > 1 and len(filas) > 1:
        # I/O de red -> hilos. Cada worker crea su propia requests.Session (no se comparte).
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futuros = [ex.submit(_una_plantilla, e, base_url, descargar) for e in filas]
            resultados = (fut.result() for fut in as_completed(futuros))
            for m, motivo in resultados:
                conteo[motivo] += 1
                if m is not None:
                    partes.append(m)
    else:
        for e in filas:
            m, motivo = _una_plantilla(e, base_url, descargar)
            conteo[motivo] += 1
            if m is not None:
                partes.append(m)
    if partes:
        comp = pd.concat(partes, ignore_index=True)
        # protege el grano: una plantilla con cedula duplicada no debe inflar el merge.
        # Se dedupa por la LLAVE normalizada: "928066398" y "0928066398" son la misma persona.
        comp = comp.drop_duplicates(subset=["numero_proceso", "_ced_key"], keep="first")
        return comp, conteo
    # Sin ninguna plantilla en el lote: columnas numéricas explícitas (no "object")
    # para que fillna/sum en agregar_features no degrade el dtype de `total`.
    return pd.DataFrame({
        "identificacion": pd.Series(dtype=str),
        "comisiones": pd.Series(dtype=float),
        "extras": pd.Series(dtype=float),
        "otros": pd.Series(dtype=float),
        "numero_proceso": pd.Series(dtype=str),
        "_ced_key": pd.Series(dtype=str),
    }), conteo

def _ensamblar(base, scvs, base_url, settings, descargar, max_workers):
    base = base.copy()
    base["identificacion"] = base["identificacion"].astype(str)
    # tamaño de la nómina del estudio: contexto para juzgar la fiabilidad de la etiqueta de cargo
    base["n_personas_estudio"] = base.groupby("numero_proceso")["identificacion"].transform("size")
    estudios = base[["numero_proceso", "id_version"]].drop_duplicates()
    comp, conteo = _composicion_estudios(estudios, base_url, descargar, max_workers=max_workers)
    # "rechazado" y "sin_plantilla" NO son pérdidas: no hay nada que recuperar reintentando.
    perdidos = conteo.get("fallo_descarga", 0) + conteo.get("fallo_parseo", 0)
    aviso = f"  <-- {perdidos} PERDIDOS (dato existente no recuperado)" if perdidos else ""
    print(f"[composicion] {len(estudios)} estudios: {dict(conteo)}{aviso}")
    # enlace por cédula ANTES de anonimizar, usando la llave normalizada de `_ced_key`
    # (la plantilla pierde el cero inicial). `identificacion` queda intacta para que el
    # id_hash siga saliendo del valor original. Left join: NaN donde no hubo plantilla.
    base["_ced_key"] = base["identificacion"].map(_ced_key)
    df = base.merge(comp.drop(columns=["identificacion"]), how="left",
                    on=["numero_proceso", "_ced_key"]).drop(columns=["_ced_key"])
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
