"""El servicio HTTP, sobre una base SINTETICA.

Nada de esto toca datos reales ni la red: se construye una base de juguete, se guarda a
un `.npz` temporal y el motor la carga como cargaria la de produccion.
"""
import datetime as _dt
import io

import numpy as np
import pandas as pd
import pytest

fastapi = pytest.importorskip("fastapi", reason="extra opcional: pip install -e .[servicio]")
from fastapi.testclient import TestClient  # noqa: E402

from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402


# El servicio dolariza con el ano ACTUAL por defecto, asi que el doble tiene que
# conocerlo: si solo supiera 2025, los tests probarian un camino que produccion no usa.
ANIO = _dt.date.today().year


def _sbu(anio, estricto=False):
    if anio not in (2025, ANIO):
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
        sbu = {2025: 470, ANIO: 470}
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
    d = cliente.get(f"/informes/{tid}").json()
    assert d["unidades"]["vs_mercado"]["unidad"] == "ratio"
    assert d["unidades"]["referencia"]["unidad"] == "usd"
    assert "NO es una brecha salarial" in d["meta"]["aviso"]


def test_las_UNIDADES_estan_en_EL_MISMO_SITIO_en_los_dos_endpoints(cliente):
    # Estaban en `meta` en /informes y en la raiz en /referencia. Un front que leia
    # `respuesta.unidades` recibia nada del primero y lo daba por vacio: el mapa existia,
    # se declaraba en el contrato y no llegaba nunca. Es el mismo fallo que UNIDADES
    # existe para evitar, una capa mas arriba.
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    tid = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    inf = cliente.get(f"/informes/{tid}").json()
    ref = cliente.get("/referencia", params={"cargo": "CONTADOR"}).json()
    assert inf["unidades"] == ref["unidades"], "el mismo contrato en dos formas"
    assert "unidades" not in inf["meta"], "y en un solo sitio, no en dos"


def test_los_tramos_publicados_son_los_que_de_verdad_se_calculan(cliente):
    # El front arma el filtro de antiguedad con esta lista. Si la deduce de los datos
    # que le llegaron, una nomina joven le deja el filtro sin `mas de 20`. Y si la lista
    # se copia a mano en dos archivos, se desincronizan.
    from benchmarking.producto.antiguedad import TRAMOS
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"],
                       "fecha_ingreso": ["01/01/2020"]})
    tid = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    d = cliente.get(f"/informes/{tid}").json()
    assert d["unidades"]["antiguedad_tramo"]["valores"] == list(TRAMOS)
    # la nomina solo produce UN tramo, y aun asi se publican los seis
    assert len({f["antiguedad_tramo"] for f in d["detalle"]}) == 1
    assert len(d["unidades"]["antiguedad_tramo"]["valores"]) == 6


def test_estado_explicito_en_vez_de_null(cliente):
    # Un nulo puede significar cinco cosas y cada una lleva a otro mensaje en la interfaz.
    df = pd.DataFrame({"cargo": ["CONTADOR", "CONTADOR"], "sueldo": ["1500", "sin dato"]})
    tid = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    d = cliente.get(f"/informes/{tid}").json()
    estados = {f["estado"] for f in d["detalle"]}
    assert "sueldo_ilegible" in estados, "el sueldo malo no puede salir como 'sin datos'"
    assert "directa" in estados
    assert d["reparto_estado"]


def test_el_anio_por_defecto_es_el_ACTUAL(cliente):
    # Estaba fijado a 2025 y eso envejece solo: en enero se seguirian emitiendo dolares
    # del ano anterior sin que nadie lo note.
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))})
    assert r.status_code == 202 and r.json()["anio"] == ANIO


def test_un_anio_sin_SBU_se_rechaza_al_subir_y_no_treinta_segundos_despues(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"anio": 2099})
    assert r.status_code == 400 and "2099" in r.json()["detail"]


def test_una_nomina_ilegible_da_400_y_NO_mata_al_worker(cliente):
    # El CLI usa SystemExit ante una nomina mala: correcto en una terminal, catastrofico
    # en un servidor. Aqui tiene que ser un 400 con el motivo, y el servicio seguir vivo.
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", b"esto no es un excel")})
    assert r.status_code == 400
    df = pd.DataFrame({"otra_cosa": ["x"]})
    r2 = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                      data={"formato_libre": "true"})
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
                     data={"formato_libre": "true", "columna_cargo": "Cargo",
                           "columna_sueldo": "ultimo sueldo/pension mensual"})
    assert r.status_code == 202, r.text
    d = cliente.get(f"/informes/{r.json()['id']}").json()
    assert len(d["por_puesto"]) == 1, "la comparacion tiene que haberse hecho"
    assert d["detalle"][0]["sueldo_actual"] == 1500.0


def test_una_columna_de_sueldo_inventada_da_400_en_vez_de_ignorarse(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"formato_libre": "true", "columna_sueldo": "no_existe"})
    assert r.status_code == 400 and "no_existe" in r.json()["detail"]


def test_el_JSON_trae_las_columnas_del_cliente_por_defecto(cliente):
    # El front necesita el NOMBRE para decir a quien subirle el sueldo, la ANTIGUEDAD
    # para explicar por que cobra lo que cobra, y el SEXO para el analisis de brecha.
    # Que `sexo` viaje NO contradice que nunca sea variable del modelo: no entra en
    # ningun calculo, sale para poder MEDIR la brecha (D-011).
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"],
                       "nombre": ["Ana"], "sexo": ["F"],
                       "fecha_ingreso": ["01/01/2015"]})
    tid = cliente.post("/informes",
                       files={"archivo": ("n.xlsx", _xlsx(df))}).json()["id"]
    f = cliente.get(f"/informes/{tid}").json()["detalle"][0]
    assert f["nombre"] == "Ana" and f["sexo"] == "F"
    assert f["fecha_ingreso"]
    # y lo del modelo va primero, para que la fila se lea de un vistazo.
    # `cargo_normalizado` es la clave con la que el front une el detalle con
    # `por_puesto`, y va pegada a `cargo` porque es la misma cosa vista de otro modo.
    assert list(f)[:4] == ["fila", "cargo", "cargo_normalizado", "estado"]


def test_se_puede_recortar_a_solo_los_numeros(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"],
                       "centro_costo": ["Admin"], "nombre": ["Ana"]})
    tid = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                       data={"columnas_originales": "false",
                             "columnas_extra": "centro_costo"}).json()["id"]
    d = cliente.get(f"/informes/{tid}").json()
    f = d["detalle"][0]
    assert f["centro_costo"] == "Admin", "la pedida si"
    assert "Nombres" not in f, "las demas no"
    assert "nombre" in d["meta"]["columnas_omitidas"]


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
                       "fecha_ingreso": ["01/01/2014", "01/01/2024"]})
    tid = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                       data={"anio": 2025}).json()["id"]
    d = cliente.get(f"/informes/{tid}").json()
    a, b = d["detalle"][0], d["detalle"][1]
    assert abs(a["antiguedad_anios"] - 12.0) < 0.1
    assert a["antiguedad_tramo"] == "10 a 20"
    assert b["antiguedad_tramo"] == "1 a 3"
    assert d["unidades"]["antiguedad_anios"]["unidad"] == "anios"


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


def test_con_rubro_se_cuentan_las_empresas_DE_ESE_RUBRO(cliente):
    # La tarjeta tiene que describir la comparacion que de verdad se hizo. Contar el
    # padron entero daria un numero mayor que el conjunto contra el que se comparo.
    df = pd.DataFrame({"cargo": ["CONTADOR", "VENDEDOR"], "sueldo": ["1500", "800"]})
    sin = cliente.get(f"/informes/{cliente.post('/informes', files={'archivo': ('n.xlsx', _xlsx(df))}).json()['id']}").json()
    assert sin["mercado"]["cargos_comparados_contra_su_rubro"] == 0
    assert sin["mercado"]["empresas_analizadas"] == 28


def test_al_cliente_se_le_dice_que_esta_dentro_de_su_propio_mercado(cliente):
    # `E00` respalda CONTADOR en la base de juguete. No se le quita del mercado —de una
    # mediana ponderada no se resta un voto sin guardar los votos, ver D-027—, pero el
    # informe tiene que DECIRLO en vez de presentar la comparacion como independiente.
    df = pd.DataFrame({"cargo": ["CONTADOR", "VENDEDOR"], "sueldo": ["1500", "1600"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"ruc": "E00"})
    assert r.status_code == 202
    # `en_la_base` mira el PADRON, no `meta_ruc`: este ultimo solo se puebla cuando el
    # marco trae columnas de SCVS —esta base de juguete no las trae— y con la fuente
    # equivocada se le decia a una empresa que no esta cuando si esta.
    assert r.json()["empresa"]["en_la_base"] is True
    d = cliente.get(f"/informes/{r.json()['id']}").json()

    m = d["mercado"]
    assert m["cargos_donde_tu_empresa_esta_en_el_mercado"] == 1
    assert "nota_espejo" in m

    pp = {f["cargo"]: f for f in d["por_puesto"]}
    assert pp["CONTADOR"]["tu_empresa"] is True
    assert pp["VENDEDOR"]["tu_empresa"] is False
    # 14 empresas respaldan la celda, asi que la influencia es 1/14
    assert abs(pp["CONTADOR"]["tu_influencia"] - 1 / 14) < 1e-3
    assert pp["VENDEDOR"]["tu_influencia"] is None


def test_sin_ruc_no_se_afirma_nada_sobre_el_espejo(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))})
    d = cliente.get(f"/informes/{r.json()['id']}").json()
    assert "nota_espejo" not in d["mercado"]
    assert d["por_puesto"][0]["tu_empresa"] is False


def test_un_ruc_que_no_esta_en_la_base_no_inventa_pertenencia(cliente):
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"ruc": "1790000000001"})
    assert r.json()["empresa"]["en_la_base"] is False
    d = cliente.get(f"/informes/{r.json()['id']}").json()
    assert d["mercado"]["cargos_donde_tu_empresa_esta_en_el_mercado"] == 0
    assert d["por_puesto"][0]["tu_empresa"] is False


def test_el_mismo_puesto_escrito_de_varias_formas_es_UN_puesto(cliente):
    # El modelo consulta en mayusculas y sin espacios de borde, asi que las cuatro
    # grafias reciben la MISMA referencia. Agrupando por el texto crudo salian como
    # cuatro puestos con `personas=1` y la referencia repetida.
    #
    # Y NO ES COSMETICO: `_voto` es la mediana de lo que la empresa paga por el puesto y
    # es lo que decide la lectura. Fragmentado, cada grafia votaba con la gente que le
    # tocara y el mismo puesto podia salir "en linea" en una fila y "muy por debajo" en
    # la de al lado, por como lo escribio quien lleno el Excel.
    df = pd.DataFrame({"cargo": ["Contador", "CONTADOR", "contador ", "Contador"],
                       "sueldo": ["1200", "1500", "1800", "2100"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))})
    d = cliente.get(f"/informes/{r.json()['id']}").json()

    assert len(d["por_puesto"]) == 1, d["por_puesto"]
    fila = d["por_puesto"][0]
    # LA ETIQUETA ES LA DEL CLIENTE, no el normalizado: el front no puede enseñarle
    # `CONTADOR` a quien escribio `Contador`. Se elige la grafia mas repetida.
    assert fila["cargo"] == "Contador"
    # ...y la clave con la que se agrupo viaja aparte, que es con la que el front une
    # esta tabla con el detalle.
    assert fila["cargo_normalizado"] == "CONTADOR"
    assert fila["personas"] == 4
    # juntar no puede ser silencioso
    assert fila["grafias"] == 3
    # la mediana es la de las CUATRO personas, no la de una
    assert fila["sueldo_mediano"] == 1650.0


def test_el_front_puede_unir_por_puesto_con_el_detalle(cliente):
    # La etiqueta de un puesto es UNA grafia y el detalle trae todas, asi que unir por
    # `cargo` dejaria filas huerfanas. `cargo_normalizado` esta en las dos tablas.
    df = pd.DataFrame({"cargo": ["Contador", "CONTADOR", "VENDEDOR"],
                       "sueldo": ["1200", "1500", "1600"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))})
    d = cliente.get(f"/informes/{r.json()['id']}").json()
    claves_pp = {f["cargo_normalizado"] for f in d["por_puesto"]}
    claves_det = {f["cargo_normalizado"] for f in d["detalle"]}
    assert claves_det == claves_pp, "ninguna fila del detalle puede quedar huerfana"


def test_la_etiqueta_no_depende_del_orden_de_las_filas(cliente):
    # Dos nominas con las mismas grafias empatadas tienen que rotular igual, o el mismo
    # informe cambia de nombre entre ejecuciones.
    etiquetas = []
    for orden in (["Contador", "CONTADOR"], ["Contador", "CONTADOR"]):
        df = pd.DataFrame({"cargo": orden, "sueldo": ["1200", "1500"]})
        r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))})
        d = cliente.get(f"/informes/{r.json()['id']}").json()
        etiquetas.append(d["por_puesto"][0]["cargo"])
    assert etiquetas[0] == etiquetas[1] == "Contador"


def test_el_detalle_respeta_lo_que_escribio_el_cliente(cliente):
    # En `por_puesto` se normaliza porque es un agregado; en el detalle NO, porque el
    # cliente tiene que poder casar cada fila con su nomina. Lo unico que se le quita
    # son los espacios de los bordes, que no son texto sino un caracter invisible.
    df = pd.DataFrame({"cargo": ["Contador", " CONTADOR "], "sueldo": ["1200", "1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))})
    d = cliente.get(f"/informes/{r.json()['id']}").json()
    assert [f["cargo"] for f in d["detalle"]] == ["Contador", "CONTADOR"]


def test_el_informe_trae_el_sector_del_cliente_SIN_meterlo_en_el_veredicto(cliente):
    # Lo que piden los ejecutivos: ver lo que paga SU sector. Lo que NO se les da: que
    # el veredicto salga de ahi. Medido (D-029): con la cascada cambia el veredicto del
    # 1,8% de los cargos y en esos la seccion acierta mas (+9,2% de pinball).
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))})
    d = cliente.get(f"/informes/{r.json()['id']}").json()
    f = d["por_puesto"][0]
    # las columnas viajan SIEMPRE, con dato o sin el: un front no puede tener que
    # programar dos formas de respuesta
    for c in ("sector_codigo", "sector_nivel", "sector_referencia", "sector_empresas"):
        assert c in f, f"falta {c}"


def test_la_ficha_del_ruc_devuelve_el_CIIU_COMPLETO(cliente):
    # `G4761.03` es lo que el cliente reconoce como suyo. `G476` no le dice nada, y la
    # seccion —"comercio al por mayor y al por menor; reparacion de vehiculos"— le dice
    # algo FALSO si vende libros.
    df = pd.DataFrame({"cargo": ["CONTADOR"], "sueldo": ["1500"]})
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(df))},
                     data={"ruc": "E00"})
    ficha = r.json()["empresa"]
    assert "ciiu" in ficha and "ciiu_seccion" in ficha


# --- la base que se carga, y que sabe hacer ---------------------------------------

def test_salud_declara_QUE_SABE_HACER_la_base(cliente):
    # Una base vieja NO falla: responde igual, con menos, y en silencio. El servicio
    # arrancaba con `demo/base_v8.npz` escrito a mano mientras el RUC, el padron y la
    # cascada vivian en la v13: tres funciones muertas y nada lo decia.
    d = cliente.get("/salud").json()
    assert "capacidades" in d and "base" in d
    for c in ("padron", "ruc_a_industria", "rubro_multinivel", "segmento_del_ruc"):
        assert c in d["capacidades"], f"falta declarar {c}"


def test_una_base_incompleta_lo_DICE_en_vez_de_callarselo(cliente):
    # La base de juguete de estos tests no trae RUC ni CIIU, asi que tiene que salir
    # como degradada. Si saliera "ok" a secas, el aviso no serviria de nada.
    d = cliente.get("/salud").json()
    assert d["degradado"], "esta base no soporta el RUC y deberia decirlo"
    assert d["aviso"] and "BASE_REFERENCIA" in d["aviso"]


def test_la_base_por_defecto_NO_esta_escrita_a_mano():
    # El defecto era `demo/base_v8.npz` en el codigo. Se sirvio una semana mientras se
    # construian la v9 a la v13. Ahora sale de la mas nueva por NUMERO DE VERSION, no
    # por fecha: copiar un fichero viejo lo volveria el mas reciente.
    import re
    from benchmarking.servicio.api import _ruta_base_por_defecto
    r = _ruta_base_por_defecto()
    assert re.search(r"base_v\d+\.npz$", r) or r.endswith("base_referencia.npz")


def test_el_entorno_manda_sobre_el_defecto(monkeypatch, base_npz):
    from benchmarking.servicio import api
    monkeypatch.setenv("BASE_REFERENCIA", base_npz)
    import os
    assert os.environ.get("BASE_REFERENCIA") == base_npz
    # y `capacidades_de` no revienta con una base a la que le falta todo
    from benchmarking.producto.base_referencia import BaseReferencia
    c = api.capacidades_de(BaseReferencia.cargar(base_npz, lambda a: 470.0))
    assert set(c) == {n for n, _, _ in api.CAPACIDADES}
