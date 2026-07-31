from unittest.mock import MagicMock
import pandas as pd
import pytest
from benchmarking.escritura.bigquery_sink import escribir


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
