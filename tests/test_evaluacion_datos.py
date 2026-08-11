import numpy as np
import pandas as pd
import pytest
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion.datos import agregar_objetivo, marco_evaluable, SQL_MARCO


@pytest.fixture
def s(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT", "x")
    return cargar_settings()


def test_objetivo_es_log_de_sueldo_sobre_sbu_no_de_total(s):
    # Trampa heredada: la columna `sueldo_sbu` de la tabla vale total/SBU, no
    # sueldo/SBU (features_base.py:28). Usarla por su nombre mediria otra cosa.
    df = pd.DataFrame({"sueldo": [940.0], "total": [1880.0], "anio_valoracion": [2025]})
    out = agregar_objetivo(df, s)
    assert abs(out["y"].iloc[0] - np.log(940.0 / 470)) < 1e-9      # SBU 2025 = 470
    assert abs(out["y"].iloc[0] - np.log(1880.0 / 470)) > 0.5


def test_objetivo_nulo_si_el_sueldo_no_es_positivo(s):
    df = pd.DataFrame({"sueldo": [0.0, -5.0, np.nan, 500.0],
                       "total": [1.0, 1.0, 1.0, 500.0],
                       "anio_valoracion": [2025] * 4})
    assert agregar_objetivo(df, s)["y"].isna().tolist() == [True, True, True, False]


def test_objetivo_usa_el_sbu_del_anio(s):
    # El SBU subio ~30% en la decada: comparar sin normalizar mezclaria inflacion
    # con diferencias de rol.
    df = pd.DataFrame({"sueldo": [470.0, 470.0], "total": [470.0, 470.0],
                       "anio_valoracion": [2025, 2018]})
    out = agregar_objetivo(df, s)
    assert abs(out["y"].iloc[0] - np.log(470 / 470)) < 1e-9
    assert abs(out["y"].iloc[1] - np.log(470 / 386)) < 1e-9        # SBU 2018 = 386


def test_marco_evaluable_exige_objetivo_y_cargo():
    # El baseline CARGO no puede competir donde no hay etiqueta: esas filas se
    # reportan aparte como cobertura exclusiva, no entran en la comparacion.
    df = pd.DataFrame({"y": [1.0, 1.0, np.nan, 1.0],
                       "cargo_norm": ["CONTADOR", "", "CONTADOR", "0"]})
    out = marco_evaluable(df)
    assert len(out) == 1 and out["cargo_norm"].iloc[0] == "CONTADOR"


def test_marco_evaluable_descarta_placeholders_conocidos():
    df = pd.DataFrame({"y": [1.0] * 6,
                       "cargo_norm": ["CONTADOR", "N/A", "S/N", "---", "nan", "  "]})
    assert marco_evaluable(df)["cargo_norm"].tolist() == ["CONTADOR"]


def test_marco_evaluable_no_muta_la_entrada():
    # Devuelve una copia: el marco original se reutiliza para la cobertura exclusiva
    # (las filas sin cargo), asi que escribir sobre el resultado no debe tocarlo.
    df = pd.DataFrame({"y": [1.0], "cargo_norm": ["CONTADOR"]})
    out = marco_evaluable(df)
    out.loc[out.index[0], "y"] = 99.0
    assert df["y"].iloc[0] == 1.0


def test_sql_no_pide_identificadores():
    # frontera de privacidad: el banco trabaja con id_hash
    assert "identificacion" not in SQL_MARCO
    assert "id_hash" in SQL_MARCO
    assert "en_clean" in SQL_MARCO


def test_sql_carga_los_ejes_de_subgrupo_para_auditar_la_abstencion():
    # D-011: las celdas que no alcanzan donantes no son un subconjunto aleatorio. Sin
    # estos ejes el banco puede reportar un MAE excelente mientras la referencia se
    # degrada para quien mas la necesita, y no enterarse.
    for eje in ("sexo", "provincia", "segmento", "ciiu_n1"):
        assert eje in SQL_MARCO, f"falta {eje}: la regla de abstencion queda sin auditar"


def test_descarta_los_sueldos_base_bajo_el_sbu(s):
    # La cuarentena del pipeline filtra por `total` (sueldo + comisiones + extras) y el
    # objetivo se calcula sobre `sueldo`: alguien con sueldo base de 4 dolares y total de
    # 500 pasaba el filtro. Medido: 78.460 filas, el 7,31% de 2024-2025.
    df = pd.DataFrame({"sueldo": [4.0, 470.0, 940.0], "total": [500.0, 470.0, 940.0],
                       "anio_valoracion": [2025] * 3,
                       "cargo_norm": ["VENDEDOR"] * 3})
    out = marco_evaluable(agregar_objetivo(df, s))
    assert out["sueldo"].tolist() == [470.0, 940.0]


def test_el_filtro_del_sbu_es_reversible(s):
    # Se puede apagar: es una decision de universo, y el pre-registro la declara.
    df = pd.DataFrame({"sueldo": [4.0, 940.0], "total": [500.0, 940.0],
                       "anio_valoracion": [2025] * 2, "cargo_norm": ["VENDEDOR"] * 2})
    assert len(marco_evaluable(agregar_objetivo(df, s), exigir_sbu=False)) == 2
