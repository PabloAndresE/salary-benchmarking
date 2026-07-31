import math, datetime as dt, warnings
import pandas as pd
from benchmarking.config.settings import cargar_settings
from benchmarking.ingesta.features_base import agregar_features

def test_features_con_composicion(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    s = cargar_settings()
    df = pd.DataFrame([{"sueldo":600.0,"comisiones":300.0,"extras":20.0,"otros":0.0,
                        "remuneracion_promedio":None,"anio_valoracion":2024,
                        "fecha_ingreso":dt.date(2014,1,1),"fecha_salida":None}])
    out = agregar_features(df, s)
    assert out.loc[0,"total"] == 920.0
    assert out.loc[0,"tiene_composicion"] == True
    assert abs(out.loc[0,"sueldo_sbu"] - 2.0) < 1e-6          # 920 / 460
    assert abs(out.loc[0,"log_total"] - math.log(920)) < 1e-6
    assert abs(out.loc[0,"pct_fijo"] - 600/920) < 1e-6
    assert abs(out.loc[0,"pct_comisiones"] - 300/920) < 1e-6
    assert out.loc[0,"antiguedad_total"] == 10

def test_features_sin_composicion_usa_respaldo(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    s = cargar_settings()
    df = pd.DataFrame([{"sueldo":700.0,"comisiones":float("nan"),"extras":float("nan"),
                        "otros":float("nan"),"remuneracion_promedio":800.0,
                        "anio_valoracion":2024,"fecha_ingreso":None,"fecha_salida":None}])
    out = agregar_features(df, s)
    assert out.loc[0,"total"] == 800.0                        # respaldo remuneracion_promedio
    assert out.loc[0,"tiene_composicion"] == False
    assert pd.isna(out.loc[0,"pct_fijo"])                     # sin composición -> NULL
    assert pd.isna(out.loc[0,"antiguedad_total"])            # sin fecha_ingreso

def test_features_anio_valoracion_nan_no_falla(monkeypatch):
    # NULL anio_valoracion ocurre en la vista real de BQ; no debe tumbar agregar_features
    monkeypatch.setenv("PIPELINE_SALT","x")
    s = cargar_settings()
    df = pd.DataFrame([{"sueldo":600.0,"comisiones":300.0,"extras":20.0,"otros":0.0,
                        "remuneracion_promedio":None,"anio_valoracion":float("nan"),
                        "fecha_ingreso":dt.date(2014,1,1),"fecha_salida":None}])
    out = agregar_features(df, s)                             # no debe lanzar ValueError
    assert math.isfinite(out.loc[0,"sueldo_sbu"])              # usa la ultima SBU (anio=0)
    assert pd.isna(out.loc[0,"antiguedad_total"])              # sin anio_valoracion -> None/NA

def test_features_sin_warnings_cuando_total_cero(monkeypatch):
    # Verifica que no hay RuntimeWarning de 0/0 cuando total=0 pero hay composición
    monkeypatch.setenv("PIPELINE_SALT","x")
    s = cargar_settings()
    df = pd.DataFrame([{"sueldo":0.0,"comisiones":0.0,"extras":float("nan"),
                        "otros":float("nan"),"remuneracion_promedio":float("nan"),
                        "anio_valoracion":2024,"fecha_ingreso":None,"fecha_salida":None}])
    with warnings.catch_warnings():
        warnings.simplefilter("error")   # any warning becomes an error
        out = agregar_features(df, s)
    assert out.loc[0,"total"] == 0.0
    assert pd.isna(out.loc[0,"pct_fijo"])                     # 0/0 = NaN, pero sin warning
