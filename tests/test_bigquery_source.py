from unittest.mock import MagicMock
import pandas as pd
from benchmarking.adquisicion.bigquery_source import listar_estudios, leer_personas, SQL_ESTUDIOS

def test_listar_estudios_usa_limite_y_devuelve_df():
    runner = MagicMock()
    runner.query.return_value.to_dataframe.return_value = pd.DataFrame(
        {"numero_proceso":["1"],"id_version":["v"],"anio_valoracion":[2024],"empresa_ruc":["17..."]})
    df = listar_estudios(runner, limite=5)
    assert list(df.columns) == ["numero_proceso","id_version","anio_valoracion","empresa_ruc"]
    sql = runner.query.call_args[0][0]
    assert "LIMIT 5" in sql and "estudios_actuariales" in sql

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
    assert set(["identificacion","cargo","sueldo","remuneracion_promedio"]).issubset(df.columns)
