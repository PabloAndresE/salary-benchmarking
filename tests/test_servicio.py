"""El servicio HTTP, sobre una base SINTETICA.

Nada de esto toca datos reales ni la red: se construye una base de juguete, se guarda a
un `.npz` temporal y el motor la carga como cargaria la de produccion.
"""
import io

import numpy as np
import pandas as pd
import pytest

fastapi = pytest.importorskip("fastapi", reason="extra opcional: pip install -e .[servicio]")
from fastapi.testclient import TestClient  # noqa: E402

from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402


def _sbu(anio, estricto=False):
    if anio != 2025:
        if estricto:
            raise ValueError(f"No hay SBU para {anio}")
        return 470.0
    return 470.0


@pytest.fixture
def base_npz(tmp_path):
    filas, emb = [], {}
    for k, cargo in enumerate(("CONTADOR", "VENDEDOR", "GUARDIA")):
        v = np.zeros(4); v[k] = 1.0
        emb[cargo] = v
        for i in range(14):
            filas.append((f"E{k}{i}", cargo, 1.0 + 0.2 * k + 0.01 * (i % 5)))
    marco = pd.DataFrame(filas, columns=["empresa_ruc", "cargo_norm", "y"])
    b = BaseReferencia.construir(marco, emb, lambda a: 470.0)
    ruta = tmp_path / "base.npz"
    b.guardar(ruta)
    return str(ruta)


@pytest.fixture
def cliente(base_npz, monkeypatch):
    from benchmarking.servicio import api

    class _S:
        sbu = {2025: 470}
        vertex_embedding_model = "x"
        bq_project = "p"
        vertex_location = "l"
        get_sbu = staticmethod(_sbu)

    monkeypatch.setattr(api, "cargar_settings", lambda: _S())
    monkeypatch.setenv("BASE_REFERENCIA", base_npz)
    with TestClient(api.app) as c:
        yield c


def _xlsx(df):
    b = io.BytesIO()
    with pd.ExcelWriter(b) as w:
        df.to_excel(w, index=False)
    return b.getvalue()


def test_salud_declara_lo_que_hay_cargado(cliente):
    d = cliente.get("/salud").json()
    assert d["ok"] and d["puestos"] == 3 and 2025 in d["anios_con_sbu"]


def test_el_informe_completo_de_punta_a_punta(cliente):
    df = pd.DataFrame({"nombre": ["Ana", "Luis", "Eva"],
                       "cargo": ["CONTADOR", "CONTADOR", "VENDEDOR"],
                       "sueldo": ["1500,50", "1400", "800"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"anio": 2025})
    assert r.status_code == 202
    tid = r.json()["id"]
    assert r.json()["columna_cargo"] == "cargo"

    d = cliente.get(f"/informes/{tid}").json()
    assert d["estado"] == "listo"
    assert len(d["detalle"]) == 3 and len(d["por_puesto"]) == 2
    # el sueldo en formato espanol se leyo bien
    assert abs(d["detalle"][0]["sueldo_actual"] - 1500.50) < 1e-9
    # y el Excel se puede descargar
    x = cliente.get(f"/informes/{tid}/excel")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_el_json_declara_UNIDADES_y_el_aviso_de_la_brecha(cliente):
    # Un front que formatee `vs_mercado` como dolares produce un numero creible y falso.
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    tid = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    meta = cliente.get(f"/informes/{tid}").json()["meta"]
    assert meta["unidades"]["vs_mercado"]["unidad"] == "ratio"
    assert meta["unidades"]["referencia"]["unidad"] == "usd"
    assert "NO es una brecha salarial" in meta["aviso"]


def test_estado_explicito_en_vez_de_null(cliente):
    # Un nulo puede significar cinco cosas y cada una lleva a otro mensaje en la interfaz.
    df = pd.DataFrame({"cargo": ["CONTADOR", "CONTADOR"], "sueldo": ["1500", "sin dato"]})
    tid = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    d = cliente.get(f"/informes/{tid}").json()
    estados = {f["estado"] for f in d["detalle"]}
    assert "sueldo_ilegible" in estados, "el sueldo malo no puede salir como 'sin datos'"
    assert "directa" in estados
    assert d["reparto_estado"]


def test_un_anio_sin_SBU_se_rechaza_al_subir_y_no_treinta_segundos_despues(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"anio": 2026})
    assert r.status_code == 400 and "2026" in r.json()["detail"]


def test_una_nomina_ilegible_da_400_y_NO_mata_al_worker(cliente):
    # El CLI usa SystemExit ante una nomina mala: correcto en una terminal, catastrofico
    # en un servidor. Aqui tiene que ser un 400 con el motivo, y el servicio seguir vivo.
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", b"esto no es un excel")})
    assert r.status_code == 400
    df = pd.DataFrame({"otra_cosa": ["x"]})
    r2 = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))})
    assert r2.status_code == 400 and "columna de cargo" in r2.json()["detail"]
    assert cliente.get("/salud").json()["ok"], "el servicio sigue en pie"


def test_segmento_invalido_se_rechaza(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"segmento": "ENORME"})
    assert r.status_code == 400 and "ENORME" in r.json()["detail"]


def test_un_informe_que_no_existe_da_404(cliente):
    assert cliente.get("/informes/noexiste").status_code == 404
    assert cliente.get("/informes/noexiste/excel").status_code == 404


def test_la_consulta_suelta_AVISA_de_que_no_es_el_producto(cliente):
    # Sin la nomina completa no hay ancla de empresa, y sin ancla no hay lectura de
    # equidad interna. Quien monte un front encima tiene que enterarse.
    d = cliente.get("/referencia", params={"cargo": "contador"}).json()
    assert d["referencia"] > 0 and d["confianza"]
    assert "ancla" in d["aviso"] and "POST /informes" in d["aviso"]
    assert not any(str(k).endswith("_log") for k in d), "nada de escala logaritmica"


def test_los_marcadores_de_swagger_NO_son_una_trampa(cliente):
    # `/docs` deja la palabra "string" en los campos opcionales. Mandarla tal cual daba
    # un 400 confuso —«segmento invalido: string»— en la primera prueba de cualquiera
    # que abriera la interfaz. La pantalla de pruebas no puede ser una trampa.
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    for datos in ({"segmento": "string", "rubro": "string", "columna_cargo": "string"},
                  {"segmento": "  ", "rubro": "", "columna_sueldo": "  "},
                  {}):
        r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                         data=datos)
        assert r.status_code == 202, f"{datos} -> {r.status_code} {r.text}"


def test_un_rubro_desconocido_se_rechaza_en_vez_de_caer_al_global_en_silencio(cliente):
    # Antes solo avisaba por `warnings` y devolvia el mercado entero: el cliente recibia
    # un informe completo creyendo que era sectorial.
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"rubro": "ZZZ"})
    assert r.status_code == 400 and "ZZZ" in r.json()["detail"]
    assert cliente.get("/referencia",
                       params={"cargo": "CONTADOR", "rubro": "ZZZ"}).status_code == 400
