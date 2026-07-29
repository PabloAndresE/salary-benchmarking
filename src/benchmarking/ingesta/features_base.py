import numpy as np
import pandas as pd

_RUBROS = ("comisiones", "extras", "otros")

def agregar_features(df: pd.DataFrame, settings) -> pd.DataFrame:
    out = df.copy()
    for m in _RUBROS:                       # asegura que los rubros existan
        if m not in out.columns:
            out[m] = np.nan
    # tiene_composicion: al menos un rubro NO nulo (la plantilla aportó montos)
    tiene = out[list(_RUBROS)].notna().any(axis=1)
    out["tiene_composicion"] = tiene
    # total: con composición = sueldo + rubros; sin ella = respaldo remuneracion_promedio -> sueldo
    total_comp = out["sueldo"].fillna(0) + out[list(_RUBROS)].fillna(0).sum(axis=1)
    respaldo = out["remuneracion_promedio"] if "remuneracion_promedio" in out else pd.Series(np.nan, index=out.index)
    respaldo = respaldo.fillna(out["sueldo"])
    out["total"] = total_comp.where(tiene, respaldo)
    # pct_*: solo donde hay composición (NaN en el resto)
    with np.errstate(invalid="ignore", divide="ignore"):
        for rubro, pct in [("sueldo","pct_fijo"),("comisiones","pct_comisiones"),
                           ("extras","pct_extras"),("otros","pct_otros")]:
            out[pct] = (out[rubro].fillna(0) / out["total"]).where(tiene)
    sbu = out["anio_valoracion"].map(lambda a: settings.get_sbu(int(a)))
    out["sueldo_sbu"] = out["total"] / sbu
    out["log_total"] = np.log(out["total"].where(out["total"] > 0))
    def _ant(row):
        fi = row.get("fecha_ingreso")
        if fi is None or pd.isna(fi):
            return None
        return int(row["anio_valoracion"]) - fi.year
    out["antiguedad_total"] = out.apply(_ant, axis=1)
    out["tuvo_salidas"] = out.get("fecha_salida").notna() if "fecha_salida" in out else False
    return out
