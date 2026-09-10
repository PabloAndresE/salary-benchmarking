"""Carga del marco de evaluación y cálculo de la variable objetivo."""
import re
import numpy as np
import pandas as pd

# Mismos placeholders que `ingesta.validacion`: una etiqueta de cargo que sea "0", "N/A"
# o similar no describe un puesto.
_PLACEHOLDERS = {"0", "-", "NA", "N/A", ".", "--", "---", "S/N", "SN", "X", "", "NAN", "NONE"}

# `sexo` se carga SÓLO para auditar la regla de abstención y para el Oaxaca (D-011).
# Las celdas que no alcanzan donantes no son un subconjunto aleatorio —ocupaciones raras,
# empresas pequeñas, provincias fuera de Pichincha y Guayas—, y bajar la cobertura puede
# empeorar el riesgo de un subgrupo aunque el global mejore (Shah et al., ICML 2022). Sin
# esta columna el banco no puede detectarlo.
# NUNCA entra en el agrupamiento: es atributo protegido, no feature.
SQL_MARCO = """
SELECT id_hash, empresa_ruc, numero_proceso, anio_valoracion,
       cargo_norm, centro_de_costo, sueldo, total,
       pct_fijo, pct_comisiones, pct_extras, pct_otros,
       antiguedad_total, tiene_composicion, en_clean,
       segmento, ciiu_n1, ciiu_n6, n_empleados, provincia, sexo
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


def marco_evaluable(df, exigir_sbu=True):
    """Filas donde la comparación contra `CARGO` es posible: con objetivo y con etiqueta.

    Las filas sin cargo **no se descartan del proyecto**: se reportan aparte como
    cobertura exclusiva del arquetipo (§6.3 del spec del banco). Simplemente no entran en
    una comparación donde el rival no puede jugar.

    `exigir_sbu` descarta los sueldos base por debajo del SBU (`y < 0`). Hace falta porque
    la cuarentena del pipeline filtra por `total` —sueldo + comisiones + extras— mientras
    el objetivo se calcula sobre `sueldo`: alguien con sueldo base de 4 dólares y total de
    500 pasaba el filtro. Medido sobre 2024-2025: **78.460 filas, el 7,31%**, con un mínimo
    de `y = -4,76` (el 0,9% del SBU).

    No son observaciones válidas de *"lo que paga este puesto"* —son jornada parcial, mes
    incompleto o error—, y sólo el 36,9% de ellas tiene composición, frente al 90,8% del
    resto. Se filtran aquí y no en el pipeline porque el objetivo se define en este módulo,
    así que su criterio de validez pertenece aquí; alinear la regla de `ingesta.validacion`
    exige reprocesar 1,9 M de filas y va en el próximo reproceso.
    """
    ok = df["y"].notna() & df["cargo_norm"].map(_cargo_utilizable)
    if exigir_sbu:
        ok &= df["y"] >= -1e-9
    return df[ok].copy()
