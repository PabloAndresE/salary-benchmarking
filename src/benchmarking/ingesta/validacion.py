import re
import pandas as pd

_PLACEHOLDERS = {"0","-","NA","N/A",".","--","S/N","SN","X",""}

def motivo_cuarentena(fila, sbu, min_sbu, edad_min, edad_max):
    cargo = str(fila.get("cargo_norm") or "")
    total = fila.get("total")
    edad = fila.get("edad")
    if cargo in _PLACEHOLDERS or re.fullmatch(r"[0-9]+", cargo):
        return "cargo_placeholder"
    if "JUBILAD" in cargo:
        return "cargo_jubilado"
    if total is None or pd.isna(total) or total <= 0:
        return "sueldo_no_positivo"
    if total < min_sbu * sbu:
        return "sueldo_bajo_sbu"
    if edad is not None and not (edad_min <= edad <= edad_max):
        return "edad_fuera_rango"
    return None

def marcar_cuarentena(df: pd.DataFrame, settings) -> pd.DataFrame:
    out = df.copy()
    motivos = []
    for r in out.to_dict("records"):
        anio = r.get("anio_valoracion")
        anio = 0 if anio is None or pd.isna(anio) else int(anio)
        motivo = motivo_cuarentena(r, settings.get_sbu(anio),
                                   settings.min_sbu, settings.edad_min, settings.edad_max)
        motivos.append(motivo)
    out["motivo_cuarentena"] = [m or "" for m in motivos]
    out["en_clean"] = [m is None for m in motivos]
    return out
