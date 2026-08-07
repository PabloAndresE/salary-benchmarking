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

def test_motivo_cuarentena_nan_total(monkeypatch):
    base = dict(cargo_norm="CONTADOR", sueldo=500.0, total=float("nan"), edad=30)
    assert motivo_cuarentena(base, sbu=460, min_sbu=0.5, edad_min=18, edad_max=80) == "sueldo_no_positivo"

def test_motivo_cuarentena_cargo_nan_placeholder():
    # cargo nulo se normaliza a la cadena "NAN" (str(NaN).upper()) upstream;
    # debe caer en cuarentena como placeholder, no colarse como cargo real.
    base = dict(cargo_norm="NAN", sueldo=500.0, total=500.0, edad=30)
    assert motivo_cuarentena(base, sbu=460, min_sbu=0.5, edad_min=18, edad_max=80) == "cargo_placeholder"

def test_componente_negativo_va_a_cuarentena():
    # Una comision/extra/otro en negativo en la plantilla del cliente. Son poquisimas
    # (57 de 780.000 en la corrida real) pero la transformacion ILR del clustering toma
    # logaritmos de las partes: un negativo la revienta. Mejor atajarlo en la ingesta.
    base = dict(cargo_norm="VENDEDOR", sueldo=500.0, total=600.0, edad=30,
                comisiones=100.0, extras=0.0, otros=0.0)
    assert motivo_cuarentena(base, 460, 0.5, 18, 80) is None
    for rubro in ("comisiones", "extras", "otros"):
        malo = {**base, rubro: -50.0}
        assert motivo_cuarentena(malo, 460, 0.5, 18, 80) == "composicion_negativa", rubro


def test_componente_negativo_no_afecta_a_filas_sin_composicion():
    # Sin plantilla los rubros llegan NaN: eso no es un negativo, es una ausencia.
    base = dict(cargo_norm="VENDEDOR", sueldo=500.0, total=500.0, edad=30,
                comisiones=float("nan"), extras=float("nan"), otros=float("nan"))
    assert motivo_cuarentena(base, 460, 0.5, 18, 80) is None


def test_sueldo_negativo_tambien_se_atrapa():
    # Un sueldo base negativo con variable que lo compensa dejaria total > 0 y pasaria.
    base = dict(cargo_norm="VENDEDOR", sueldo=-100.0, total=500.0, edad=30,
                comisiones=600.0, extras=0.0, otros=0.0)
    assert motivo_cuarentena(base, 460, 0.5, 18, 80) == "composicion_negativa"


def test_marcar_cuarentena_nan_anio(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    s = cargar_settings()
    df = pd.DataFrame([{"cargo_norm":"CONTADOR","sueldo":500.0,"total":500.0,"edad":30,"anio_valoracion":float("nan")},
                       {"cargo_norm":"CONTADOR","sueldo":500.0,"total":500.0,"edad":30,"anio_valoracion":2024}])
    out = marcar_cuarentena(df, s)
    assert "en_clean" in out.columns and "motivo_cuarentena" in out.columns
    assert out.loc[0,"en_clean"]
    assert out.loc[1,"en_clean"]
