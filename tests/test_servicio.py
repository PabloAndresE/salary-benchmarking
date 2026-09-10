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


def test_una_columna_que_TERMINA_en_espacio_se_encuentra_igual(cliente):
    # La plantilla actuarial real trae 'Ultimo sueldo/pension mensual ' con espacio al
    # final. El saneado de los opcionales lo recortaba y dejaba de coincidir, asi que
    # `_buscar_sueldo` devolvia None EN SILENCIO: informe sin comparacion y sin motivo.
    df = pd.DataFrame({"Cargo ": ["CONTADOR"], "Ultimo sueldo/pension mensual ": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"columna_cargo": "Cargo",
                           "columna_sueldo": "ultimo sueldo/pension mensual"})
    assert r.status_code == 202, r.text
    d = cliente.get(f"/informes/{r.json()['id']}").json()
    assert len(d["por_puesto"]) == 1, "la comparacion tiene que haberse hecho"
    assert d["detalle"][0]["sueldo_actual"] == 1500.0


def test_una_columna_de_sueldo_inventada_da_400_en_vez_de_ignorarse(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"columna_sueldo": "no_existe"})
    assert r.status_code == 400 and "no_existe" in r.json()["detail"]


def test_el_JSON_trae_las_columnas_del_cliente_por_defecto(cliente):
    # El front necesita el NOMBRE para decir a quien subirle el sueldo, la ANTIGUEDAD
    # para explicar por que cobra lo que cobra, y el SEXO para el analisis de brecha.
    # Que `sexo` viaje NO contradice que nunca sea variable del modelo: no entra en
    # ningun calculo, sale para poder MEDIR la brecha (D-011).
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"],
                       "Nombres": ["Ana"], "Sexo": ["F"],
                       "Fecha de primer ingreso": ["01/01/2015"]})
    tid = cliente.post("/informes",
                       files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    f = cliente.get(f"/informes/{tid}").json()["detalle"][0]
    assert f["Nombres"] == "Ana" and f["Sexo"] == "F"
    assert f["Fecha de primer ingreso"]
    # y lo del modelo va primero, para que la fila se lea de un vistazo
    assert list(f)[:3] == ["fila", "cargo", "estado"]


def test_se_puede_recortar_a_solo_los_numeros(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"],
                       "Centro de costos": ["Admin"], "Nombres": ["Ana"]})
    tid = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                       data={"columnas_originales": "false",
                             "columnas_extra": "centro de costos"}).json()["id"]
    d = cliente.get(f"/informes/{tid}").json()
    f = d["detalle"][0]
    assert f["Centro de costos"] == "Admin", "la pedida si"
    assert "Nombres" not in f, "las demas no"
    assert "Nombres" in d["meta"]["columnas_omitidas"]


def test_una_columna_extra_inventada_da_400(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"columnas_originales": "false",
                           "columnas_extra": "no_existe"})
    assert r.status_code == 400 and "no_existe" in r.json()["detail"]


def test_la_antiguedad_viaja_calculada_y_en_tramos(cliente):
    # El front la necesita para el filtro de ANTIGUEDAD y para explicar por que alguien
    # cobra lo que cobra. La plantilla no la trae: hay que calcularla de las fechas.
    df = pd.DataFrame({"cargo": ["CONTADOR", "CONTADOR"], "sueldo": ["1500", "1400"],
                       "Fecha de primer ingreso": ["01/01/2010", "01/01/2024"],
                       "Fecha de salida 1": ["01/01/2015", None],
                       "Fecha de reingreso 1": ["01/01/2020", None]})
    tid = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                       data={"anio": 2025}).json()["id"]
    d = cliente.get(f"/informes/{tid}").json()
    a, b = d["detalle"][0], d["detalle"][1]
    assert abs(a["antiguedad_anios"] - 11.0) < 0.1, "no cuenta los 5 anios fuera"
    assert a["antiguedad_tramo"] == "10 a 20"
    assert b["antiguedad_tramo"] == "1 a 3"
    assert d["meta"]["unidades"]["antiguedad_anios"]["unidad"] == "anios"


def test_sin_fechas_la_antiguedad_es_null_y_no_cero(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    tid = cliente.post("/informes",
                       files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    f = cliente.get(f"/informes/{tid}").json()["detalle"][0]
    assert f["antiguedad_anios"] is None and f["antiguedad_tramo"] is None


def test_las_tarjetas_de_cabecera(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR", "CONTADOR", "VENDEDOR"],
                       "sueldo": ["1500", "1400", "800"]})
    tid = cliente.post("/informes",
                       files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    m = cliente.get(f"/informes/{tid}").json()["mercado"]
    assert m["cargos_del_cliente"] == 2
    assert m["cargos_con_datos_en_la_base"] == 2
    # 14 personas por cargo en la base sintetica, y NO se cuenta CONTADOR dos veces
    assert m["trabajadores_analizados"] == 28
    assert m["empresas_analizadas"] == 28


def test_las_empresas_se_cuentan_SIN_DUPLICAR(cliente):
    # Es la tarjeta mas visible del informe. La base sintetica usa empresas distintas
    # por cargo (E0*, E1*, E2*), asi que la union son 42 y no 14.
    df = pd.DataFrame({"cargo": ["CONTADOR", "VENDEDOR", "GUARDIA"],
                       "sueldo": ["1500", "800", "600"]})
    tid = cliente.post("/informes",
                       files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    m = cliente.get(f"/informes/{tid}").json()["mercado"]
    assert m["empresas_analizadas"] == 42


def test_el_mismo_cargo_dos_veces_no_infla_el_conteo(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"] * 5, "sueldo": ["1500"] * 5})
    tid = cliente.post("/informes",
                       files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    m = cliente.get(f"/informes/{tid}").json()["mercado"]
    assert m["empresas_analizadas"] == 14 and m["trabajadores_analizados"] == 14


def test_la_industria_solo_llega_a_seccion(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    sin = cliente.get(f"/informes/"
                      f"{cliente.post('/informes', files={'archivo': ('n.xlsx', _xlsx(df))}).json()['id']}"
                      ).json()
    assert sin["industria"] is None, "sin rubro no hay tarjeta de industria"
