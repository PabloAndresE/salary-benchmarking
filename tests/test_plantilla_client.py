from unittest.mock import MagicMock
from benchmarking.adquisicion.plantilla_client import descargar_plantilla

def _resp(status, content=b"xlsxbytes"):
    r = MagicMock(); r.status_code = status; r.content = content
    r.raise_for_status = MagicMock()
    return r

def test_descarga_ok():
    ses = MagicMock(); ses.get.return_value = _resp(200)
    out = descargar_plantilla("140672","abc","http://x", session=ses)
    assert out == b"xlsxbytes"
    assert "estudios/140672/version/abc/plantilla-modificada" in ses.get.call_args[0][0]

def test_reintenta_y_se_rinde_en_503():
    ses = MagicMock(); ses.get.return_value = _resp(503)
    out = descargar_plantilla("1","v","http://x", session=ses, reintentos=2)
    assert out is None
    assert ses.get.call_count == 2
