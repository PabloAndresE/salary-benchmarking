"""El contrato HTTP del backend, probado directo (sin el adaptador v1.3): el sobre
`BaseResponseModel`, el camelCase, los codigos de error, el informe sincrono con su
Excel, y que en los logs no quede el RUC."""

import base64
import io
import logging

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.infrastructure import motor as motor_mod
from fakes.ajustes import make_fake_ajustes

pytestmark = pytest.mark.endpoint


@pytest.fixture
def api(base_npz, monkeypatch):
    from src import main

    monkeypatch.setattr("src.config.ajustes.cargar_settings", lambda: make_fake_ajustes())
    monkeypatch.setenv("BASE_REFERENCIA", base_npz)
    with TestClient(main.app) as c:
        yield c


def _csv(df):
    return df.to_csv(index=False).encode()


def _nomina():
    return pd.DataFrame(
        {"cargo": ["CONTADOR", "VENDEDOR", "GUARDIA"], "sueldo": ["1200", "650", "500"], "nombre": ["A", "B", "C"]}
    )


def test_el_informe_es_sincrono_y_viene_en_el_sobre(api):
    r = api.post("/informes", files={"archivo": ("n.csv", _csv(_nomina()))})
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"message", "status", "content"} and d["status"] == 0
    c = d["content"]
    assert len(c["detalle"]) == 3 and c["idCarga"] and c["filas"] == 3
    assert c["excelBase64"] is None, "el Excel solo viaja si se pide"


def test_las_claves_del_modelo_van_en_camelCase_y_las_del_cliente_tal_cual(api):
    c = api.post("/informes", files={"archivo": ("n.csv", _csv(_nomina()))}).json()["content"]
    fila = c["detalle"][0]
    assert {"rangoDesde", "rangoHasta", "cargoNormalizado", "rubroNivel"} <= set(fila)
    assert "rango_desde" not in fila
    assert fila["nombre"] == "A", "las columnas del cliente no se renombran"
    assert "sueldoActual" in c["unidades"], "las unidades nombran los campos como viajan"
    # las claves de `repartoEstado` son VALORES (estados), no nombres de campo
    assert all("_" in k or k.islower() for k in c["repartoEstado"])


def test_el_excel_viaja_en_la_misma_respuesta_si_se_pide(api):
    c = api.post("/informes", files={"archivo": ("n.csv", _csv(_nomina()))}, data={"incluirExcel": "true"}).json()[
        "content"
    ]
    xls = base64.b64decode(c["excelBase64"])
    assert xls[:2] == b"PK"
    assert len(pd.read_excel(io.BytesIO(xls), sheet_name="detalle")) == 3


def test_un_error_de_validacion_sale_en_el_sobre_con_su_codigo(api):
    r = api.post("/informes", files={"archivo": ("n.csv", _csv(_nomina()))}, data={"segmento": "ENORME"})
    assert r.status_code == 400
    d = r.json()
    assert d["status"] == 400 and "ENORME" in d["message"] and d["content"] is None


def test_el_formato_invalido_trae_los_problemas_en_el_contenido(api):
    df = pd.DataFrame({"puesto": ["CONTADOR"], "cedula": ["1700000001"]})
    r = api.post("/informes", files={"archivo": ("n.csv", _csv(df))})
    assert r.status_code == 400
    c = r.json()["content"]
    assert c["formato"] == "estricto" and c["problemas"] and "cargo" in c["obligatorias"]


def test_un_campo_desconocido_da_422_sin_devolver_lo_que_llego(api):
    r = api.post("/informes", files={"archivo": ("n.csv", _csv(_nomina()))}, data={"campo_inventado": "0990001"})
    assert r.status_code == 422
    d = r.json()
    assert d["status"] == 422 and isinstance(d["content"], list)
    assert all(set(e) == {"loc", "msg", "type"} for e in d["content"])
    assert "0990001" not in r.text, "el 422 no devuelve el input"


def test_referencia_y_puestos_en_el_sobre(api):
    r = api.get("/referencia", params={"cargo": "CONTADOR"})
    assert r.status_code == 200 and r.json()["status"] == 0
    assert "rangoDesde" in r.json()["content"]
    p = api.get("/puestos", params={"q": "contador", "pMin": 0})
    assert p.status_code == 200 and isinstance(p.json()["content"], list)


def test_health_no_depende_de_la_base(monkeypatch):
    from src import main

    monkeypatch.setattr(motor_mod, "_MOTOR", None)
    c = TestClient(main.app)  # sin `with`: no arranca ni carga nada
    assert c.get("/health").json() == {"message": "ok", "status": 0, "content": {"ok": True}}
    r = c.get("/salud")
    assert r.status_code == 503 and r.json()["status"] == 503


def test_una_ruta_inexistente_tambien_responde_en_el_sobre(api):
    r = api.get("/no-existe")
    assert r.status_code == 404 and r.json()["status"] == 404


def test_el_log_de_la_peticion_no_lleva_el_ruc(api, caplog):
    caplog.set_level(logging.INFO, logger="src.middleware.logger")
    r = api.get("/referencia", params={"cargo": "CONTADOR", "ruc": "0990001234001"})
    assert r.headers.get("X-Request-Id")
    lineas = [x.getMessage() for x in caplog.records if x.name == "src.middleware.logger"]
    assert lineas and all("0990001234001" not in x for x in lineas)
    assert any("GET /referencia" in x for x in lineas)
