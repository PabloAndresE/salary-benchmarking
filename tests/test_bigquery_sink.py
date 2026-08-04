from unittest.mock import MagicMock
import pandas as pd
import pytest
from google.api_core.exceptions import NotFound
from benchmarking.escritura.bigquery_sink import escribir, tabla_existe, procesos_existentes


def test_rechaza_pii():
    df = pd.DataFrame({"id_hash": ["a"], "identificacion": ["1700000001"]})
    with pytest.raises(ValueError):
        escribir(df, MagicMock(), "proj", "ds")


def test_escribe_y_devuelve_tabla():
    df = pd.DataFrame({"id_hash": ["a"], "anio_valoracion": [2024], "empresa_ruc": ["17"]})
    client = MagicMock()
    client.load_table_from_dataframe.return_value.result.return_value = None
    tid = escribir(df, client, "proj", "ds")
    assert tid == "proj.ds.nomina_features"
    assert client.load_table_from_dataframe.called
    jc = client.load_table_from_dataframe.call_args.kwargs["job_config"]
    assert jc.write_disposition == "WRITE_TRUNCATE"
    assert jc.clustering_fields == ["empresa_ruc"]
    assert jc.range_partitioning.field == "anio_valoracion"


def test_escribe_con_anio_nan_no_falla_y_castea_a_int64():
    # anio_valoracion NULL -> columna float64; BQ autodetectaria FLOAT y RangePartitioning
    # sobre un campo no-INTEGER falla la carga. Debe castearse a Int64 nullable antes del load.
    df = pd.DataFrame({"id_hash": ["a", "b"],
                        "anio_valoracion": [2024.0, float("nan")],
                        "empresa_ruc": ["17", "17"]})
    client = MagicMock()
    client.load_table_from_dataframe.return_value.result.return_value = None
    tid = escribir(df, client, "proj", "ds")                  # no debe lanzar
    assert tid == "proj.ds.nomina_features"
    assert client.load_table_from_dataframe.called
    df_pasado = client.load_table_from_dataframe.call_args.args[0]
    assert str(df_pasado["anio_valoracion"].dtype) == "Int64"


def test_escribir_respeta_write_disposition():
    df = pd.DataFrame({"id_hash":["a"], "anio_valoracion":[2024], "empresa_ruc":["17"]})
    client = MagicMock()
    client.load_table_from_dataframe.return_value.result.return_value = None
    escribir(df, client, "proj", "ds", write_disposition="WRITE_APPEND")
    jc = client.load_table_from_dataframe.call_args.kwargs["job_config"]
    assert jc.write_disposition == "WRITE_APPEND"


def test_tabla_existe():
    client = MagicMock()
    client.get_table.return_value = object()
    assert tabla_existe(client, "p.d.t") is True
    client.get_table.side_effect = NotFound("x")
    assert tabla_existe(client, "p.d.t") is False


def test_procesos_existentes():
    client = MagicMock()
    # existe -> devuelve set de procesos
    client.get_table.return_value = object()
    client.query.return_value.result.return_value = [{"numero_proceso":"P1"},{"numero_proceso":"P2"}]
    assert procesos_existentes(client, "p.d.t") == {"P1","P2"}
    # no existe -> set vacío, sin query
    client2 = MagicMock(); client2.get_table.side_effect = NotFound("x")
    assert procesos_existentes(client2, "p.d.t") == set()
    client2.query.assert_not_called()
