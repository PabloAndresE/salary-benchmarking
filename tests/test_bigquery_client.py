from unittest.mock import MagicMock, patch

import pytest

from src.persistence import bigquery_client
from src.services import registro_nomina_service as rn

pytestmark = pytest.mark.persistence

_PATCH = "src.persistence.bigquery_client._cliente"


def test_inserta_por_streaming_con_insert_id():
    falso = MagicMock()
    falso.insert_rows_json.return_value = []
    with patch(_PATCH, return_value=falso):
        bigquery_client.insertar_filas(dataset="p.d", tabla="t", filas=[{"a": 1}], claves=["k1"])
    falso.insert_rows_json.assert_called_once_with("p.d.t", [{"a": 1}], row_ids=["k1"])


def test_un_rechazo_de_bigquery_no_pasa_en_silencio():
    falso = MagicMock()
    falso.insert_rows_json.return_value = [{"index": 0, "errors": ["mal"]}]
    with patch(_PATCH, return_value=falso), pytest.raises(RuntimeError, match="rechazo 1 filas"):
        bigquery_client.insertar_filas(dataset="p.d", tabla="t", filas=[{"a": 1}])


def test_guardar_escribe_las_tres_tablas_con_la_cabecera_al_final():
    llamadas = []
    with patch("src.persistence.bigquery_client.insertar_filas", side_effect=lambda **k: llamadas.append(k)):
        rn.guardar(
            {
                "cargas": [{"id_carga": "c1"}],
                "nomina_filas": [{"id_carga": "c1", "fila": 0}],
                "homologaciones": [{"id_carga": "c1", "fila": 0}],
            },
            "p.d",
        )
    assert [k["tabla"] for k in llamadas] == ["nomina_filas", "homologaciones", "cargas"]
    assert llamadas[0]["claves"] == ["c1:nomina_filas:0"], "un reintento de la misma fila no la duplica"
