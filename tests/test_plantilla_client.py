from unittest.mock import MagicMock
import pytest
import requests
from benchmarking.adquisicion.plantilla_client import descargar_plantilla, DescargaFallida

def _resp(status, content=b"xlsxbytes"):
    r = MagicMock(); r.status_code = status; r.content = content
    r.raise_for_status = MagicMock()
    return r

def _sin_espera(_):
    pass

def test_descarga_ok():
    ses = MagicMock(); ses.get.return_value = _resp(200)
    out = descargar_plantilla("140672","abc","http://x", session=ses)
    assert out == b"xlsxbytes"
    assert "estudios/140672/version/abc/plantilla-modificada" in ses.get.call_args[0][0]

def test_reintenta_y_se_rinde_en_503():
    # 5xx agotado ya no devuelve None: es un fallo de servidor, no una ausencia de plantilla.
    ses = MagicMock(); ses.get.return_value = _resp(503)
    with pytest.raises(DescargaFallida):
        descargar_plantilla("1","v","http://x", session=ses, reintentos=2, espera=_sin_espera)
    assert ses.get.call_count == 2

def test_reintenta_ante_caida_de_conexion():
    # Una SSLError es un fallo de red, no "no hay plantilla". Antes escapaba del bucle
    # sin reintentar y el estudio se perdía en silencio (con concurrencia alta, el 80%).
    ses = MagicMock()
    ses.get.side_effect = [requests.exceptions.SSLError("EOF in violation of protocol"),
                           requests.exceptions.ConnectionError("reset by peer"),
                           _resp(200)]
    out = descargar_plantilla("1","v","http://x", session=ses, reintentos=3, espera=_sin_espera)
    assert out == b"xlsxbytes"
    assert ses.get.call_count == 3

def test_caida_de_conexion_persistente_lanza_descarga_fallida():
    ses = MagicMock()
    ses.get.side_effect = requests.exceptions.SSLError("EOF in violation of protocol")
    with pytest.raises(DescargaFallida):
        descargar_plantilla("1","v","http://x", session=ses, reintentos=3, espera=_sin_espera)
    assert ses.get.call_count == 3

def test_timeout_tambien_se_reintenta():
    ses = MagicMock()
    ses.get.side_effect = [requests.exceptions.Timeout("timed out"), _resp(200)]
    out = descargar_plantilla("1","v","http://x", session=ses, reintentos=3, espera=_sin_espera)
    assert out == b"xlsxbytes"
    assert ses.get.call_count == 2

def test_404_es_ausencia_no_fallo():
    # El estudio simplemente no tiene plantilla-modificada (normal en años <= 2022):
    # es un hecho, no un error, y no tiene sentido reintentarlo.
    ses = MagicMock(); ses.get.return_value = _resp(404)
    out = descargar_plantilla("1","v","http://x", session=ses, espera=_sin_espera)
    assert out is None
    assert ses.get.call_count == 1

def test_4xx_distinto_de_404_no_se_silencia():
    # Un 400 indica una petición mal formada: debe verse, no confundirse con "no hay plantilla".
    r = _resp(400)
    r.raise_for_status.side_effect = requests.exceptions.HTTPError("400")
    ses = MagicMock(); ses.get.return_value = r
    with pytest.raises(requests.exceptions.HTTPError):
        descargar_plantilla("1","v","http://x", session=ses, espera=_sin_espera)
    assert ses.get.call_count == 1

def test_espera_progresiva_entre_reintentos():
    esperas = []
    ses = MagicMock()
    ses.get.side_effect = [requests.exceptions.SSLError("x"),
                           requests.exceptions.SSLError("x"),
                           _resp(200)]
    descargar_plantilla("1","v","http://x", session=ses, reintentos=3, espera=esperas.append)
    assert esperas == [2, 4]        # crece con el intento; no espera tras el último
