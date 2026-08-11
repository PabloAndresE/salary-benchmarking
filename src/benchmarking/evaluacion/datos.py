"""Carga del marco de evaluación y cálculo de la variable objetivo."""
import re
import numpy as np
import pandas as pd

# Mismos placeholders que `ingesta.validacion`: una etiqueta de cargo que sea "0", "N/A"
# o similar no describe un puesto.
_PLACEHOLDERS = {"0", "-", "NA", "N/A", ".", "--", "---", "S/N", "SN", "X", "", "NAN", "NONE"}

SQL_MARCO = """
SELECT id_hash, empresa_ruc, numero_proceso, anio_valoracion,
       cargo_norm, centro_de_costo, sueldo, total,
       pct_fijo, pct_comisiones, pct_extras, pct_otros,
       antiguedad_total, tiene_composicion, en_clean,
       segmento, ciiu_n1, provincia
FROM `{proyecto}.{dataset}.nomina_features`
WHERE en_clean AND anio_valoracion IN ({anios})
"""


def cargar_marco(runner, proyecto, dataset, anios=(2024, 2025)):
    sql = SQL_MARCO.format(proyecto=proyecto, dataset=dataset,
                           anios=", ".join(str(int(a)) for a in anios))
    return runner.query(sql).to_dataframe()


def agregar_objetivo(df, settings):
    """Añade `y` = log(sueldo / SBU del año).

    Se usa `sueldo` y no `total` porque `total` sólo está bien definido donde hay
    composición, y un objetivo que cambia de definición entre filas no es comparable.
    Normalizar por el SBU del año evita mezclar la inflación del mínimo —subió ~30% en
    la década— con diferencias de rol.

    OJO: la columna `sueldo_sbu` de la tabla NO sirve para esto: vale `total / SBU`
    (features_base.py:28). Se calcula aquí explícitamente.
    """
    out = df.copy()
    sbu = out["anio_valoracion"].map(lambda a: settings.get_sbu(0 if pd.isna(a) else int(a)))
    sueldo = pd.to_numeric(out["sueldo"], errors="coerce")
    with np.errstate(invalid="ignore", divide="ignore"):
        out["y"] = np.log((sueldo / sbu).where(sueldo > 0))
    return out


def _cargo_utilizable(c):
    s = str(c or "").strip().upper()
    return s not in _PLACEHOLDERS and not re.fullmatch(r"[0-9]+", s)


def marco_evaluable(df):
    """Filas donde la comparación contra `CARGO` es posible: con objetivo y con etiqueta.

    Las filas sin cargo **no se descartan del proyecto**: se reportan aparte como
    cobertura exclusiva del arquetipo (§6.3 del spec del banco). Simplemente no entran en
    una comparación donde el rival no puede jugar.
    """
    return df[df["y"].notna() & df["cargo_norm"].map(_cargo_utilizable)].copy()
