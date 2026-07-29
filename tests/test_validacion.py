import pandas as pd
from benchmarking.ingesta.validacion import motivo_cuarentena, marcar_cuarentena
from benchmarking.config.settings import cargar_settings

def test_motivos(monkeypatch):
    base = dict(cargo_norm="CONTADOR", sueldo=500.0, total=500.0, edad=30)
    assert motivo_cuarentena(base, sbu=460, min_sbu=0.5, edad_min=18, edad_max=80) is None
    assert motivo_cuarentena({**base, "cargo_norm":"0"}, 460,0.5,18,80) == "cargo_placeholder"
    assert motivo_cuarentena({**base, "cargo_norm":"JUBILADO"}, 460,0.5,18,80) == "cargo_jubilado"
    assert motivo_cuarentena({**base, "total":100.0}, 460,0.5,18,80) == "sueldo_bajo_sbu"
    assert motivo_cuarentena({**base, "total":0.0}, 460,0.5,18,80) == "sueldo_no_positivo"
    assert motivo_cuarentena({**base, "edad":95}, 460,0.5,18,80) == "edad_fuera_rango"

def test_marcar_cuarentena(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    s = cargar_settings()
    df = pd.DataFrame([{"cargo_norm":"CONTADOR","sueldo":500.0,"total":500.0,"edad":30,"anio_valoracion":2024},
                       {"cargo_norm":"0","sueldo":500.0,"total":500.0,"edad":30,"anio_valoracion":2024}])
    out = marcar_cuarentena(df, s)
    assert out.loc[0,"en_clean"] and not out.loc[1,"en_clean"]
    assert out.loc[1,"motivo_cuarentena"] == "cargo_placeholder"
