from unittest.mock import MagicMock
import pandas as pd
from benchmarking.adquisicion.bigquery_source import listar_estudios, leer_personas, leer_scvs, leer_personas_por_proceso, SQL_ESTUDIOS, SQL_SCVS

def test_listar_estudios_usa_limite_y_devuelve_df():
    runner = MagicMock()
    runner.query.return_value.to_dataframe.return_value = pd.DataFrame(
        {"numero_proceso":["1"],"id_version":["v"],"anio_valoracion":[2024],"empresa_ruc":["17..."]})
    df = listar_estudios(runner, limite=5)
    assert list(df.columns) == ["numero_proceso","id_version","anio_valoracion","empresa_ruc"]
    sql = runner.query.call_args[0][0]
    assert sql == SQL_ESTUDIOS + "\nLIMIT 5"

def test_leer_personas_limita_por_estudio():
    runner = MagicMock()
    runner.query.return_value.to_dataframe.return_value = pd.DataFrame(
        {"identificacion":["1700000001"],"numero_proceso":["1"],"id_version":["v"],
         "anio_valoracion":[2024],"empresa_ruc":["17"],"cargo":["X"],"sexo":["F"],
         "edad":[30],"sueldo":[500.0],"remuneracion_promedio":[None],"fecha_ingreso":[None]})
    df = leer_personas(runner, limite=3)
    sql = runner.query.call_args[0][0]
    assert "DENSE_RANK() OVER (ORDER BY numero_proceso) <= 3" in sql
    assert "identificacion_persona" in sql
    assert "centro_de_costo" in sql
    assert set(["identificacion","cargo","sueldo","remuneracion_promedio"]).issubset(df.columns)

def test_leer_scvs_deduplica_por_ruc_y_casting():
    runner = MagicMock()
    runner.query.return_value.to_dataframe.return_value = pd.DataFrame(
        {"ruc":["1790000000"],"segmento":["GRANDE"],"ciiu_n1":["A"],"ciiu_n6":["011000"],"n_empleados":[500]})
    df = leer_scvs(runner)
    sql = runner.query.call_args[0][0]
    assert "CAST(ruc AS STRING)" in sql
    assert "ROW_NUMBER()" in sql
    assert "scvs_balances_anuales" in sql
    assert set(["ruc","segmento","ciiu_n1","ciiu_n6","n_empleados"]).issubset(df.columns)

def test_leer_personas_por_proceso_filtra_IN():
    runner = MagicMock()
    runner.query.return_value.to_dataframe.return_value = pd.DataFrame(
        {"identificacion":["1"],"numero_proceso":["140672"],"id_version":["v"],
         "anio_valoracion":[2024],"empresa_ruc":["17"],"cargo":["X"],"centro_de_costo":["C"],
         "sexo":["F"],"edad":[30],"sueldo":[500.0],"remuneracion_promedio":[None],"fecha_ingreso":[None]})
    df = leer_personas_por_proceso(runner, ["140672","140673"])
    sql = runner.query.call_args[0][0]
    assert "numero_proceso IN (" in sql
    assert "'140672'" in sql and "'140673'" in sql
    assert "identificacion_persona" in sql
    assert not df.empty

def test_leer_personas_por_proceso_vacio_no_consulta():
    runner = MagicMock()
    df = leer_personas_por_proceso(runner, [])
    assert df.empty
    runner.query.assert_not_called()
