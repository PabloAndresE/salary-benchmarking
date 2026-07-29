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
