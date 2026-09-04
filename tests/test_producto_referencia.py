import numpy as np
import pandas as pd
import pytest
from benchmarking.producto.base_referencia import BaseReferencia


def _sbu(anio):
    return 470.0


def _marco(filas):
    return pd.DataFrame(filas, columns=["empresa_ruc", "cargo_norm", "y"])


def _base(filas, emb):
    return BaseReferencia.construir(_marco(filas), emb, _sbu)


@pytest.fixture
def caso():
    """Tres familias bien separadas en el espacio de texto, con pagos distintos."""
    rng = np.random.default_rng(3)
    filas, emb = [], {}
    centros = {"BODEGA": np.array([1., 0., 0.]), "VENTAS": np.array([0., 1., 0.]),
               "SISTEMAS": np.array([0., 0., 1.])}
    paga = {"BODEGA": 0.2, "VENTAS": 0.8, "SISTEMAS": 1.4}
    for fam, c in centros.items():
        for v in range(6):
            etq = f"{fam} {v}"
            emb[etq] = c + rng.normal(0, 0.02, 3)
            for e in range(8):
                filas += [(f"E{fam}{v}{e}", etq, paga[fam] + rng.normal(0, .05))
                          for _ in range(4)]
    return filas, emb, centros


def test_un_titulo_conocido_usa_sus_propios_datos(caso):
    filas, emb, _ = caso
    b = _base(filas, emb)
    r = b.referenciar(["BODEGA 0"], emb).iloc[0]
    assert r["base"] == "datos directos" and r["confianza"] == "ALTA"
    assert abs(r["referencia_log"] - 0.2) < 0.1


def test_un_titulo_NUEVO_se_coloca_por_analogia(caso):
    filas, emb, centros = caso
    b = _base(filas, emb)
    emb2 = dict(emb)
    emb2["BODEGUERO NOCTURNO"] = centros["BODEGA"] + np.array([0.01, 0.0, 0.0])
    r = b.referenciar(["BODEGUERO NOCTURNO"], emb2).iloc[0]
    assert r["base"] == "por analogia"
    assert abs(r["referencia_log"] - 0.2) < 0.15, "debe caer con su familia, no en el medio"


def test_un_vecino_lejano_no_gana_por_tener_mas_datos(caso):
    # EL caso OPERADOR DE PARQUEADERO: un vecino casi identico pero con pocos datos debe
    # pesar mas que uno lejano con muchisimos. Con `similitud x precision` perdia.
    filas, emb, centros = caso
    gemelo = centros["BODEGA"] + np.array([0.001, 0.0, 0.0])
    emb = dict(emb)
    emb["BODEGA GEMELA"] = gemelo
    filas = list(filas) + [(f"EG{e}", "BODEGA GEMELA", 0.2) for e in range(3) for _ in range(2)]
    # y una familia enorme y lejana que paga muy distinto
    for v in range(3):
        etq = f"VENTAS MASIVO {v}"
        emb[etq] = centros["VENTAS"] + np.random.default_rng(v).normal(0, .01, 3)
        filas += [(f"EM{v}{e}", etq, 0.8) for e in range(60) for _ in range(6)]
    b = _base(filas, emb)
    emb["BODEGUERO X"] = gemelo + np.array([0.0005, 0.0, 0.0])
    r = b.referenciar(["BODEGUERO X"], emb).iloc[0]
    assert abs(r["referencia_log"] - 0.2) < 0.2, f"se fue a {r['referencia_log']:.3f}"


def test_sin_vecindario_real_la_confianza_cae(caso):
    # EL caso LOTERO: el embedding se agarra a cualquier cosa. El intervalo debe
    # dispararse y la confianza bajar, no dar un numero con cara de seguro.
    filas, emb, _ = caso
    b = _base(filas, emb)
    emb2 = dict(emb)
    emb2["LOTERO"] = np.array([0.58, 0.58, 0.58])       # lejos de las tres familias
    lejos = b.referenciar(["LOTERO"], emb2).iloc[0]
    cerca = b.referenciar(["BODEGA 0"], emb2).iloc[0]
    assert lejos["confianza"] == "BAJA"
    assert lejos["sd"] > cerca["sd"], "el intervalo debe ensancharse cuando no hay base"


def test_responde_siempre(caso):
    filas, emb, _ = caso
    b = _base(filas, emb)
    emb2 = dict(emb)
    emb2["CUALQUIER COSA RARA"] = np.array([0.3, -0.5, 0.8])
    out = b.referenciar(["BODEGA 0", "CUALQUIER COSA RARA"], emb2)
    assert out["referencia_log"].notna().all(), "decision de producto: se responde siempre"
    assert set(out["confianza"]) <= {"ALTA", "MEDIA", "BAJA"}


def test_convierte_a_dolares_con_el_sbu_del_anio(caso):
    filas, emb, _ = caso
    r = _base(filas, emb).referenciar(["VENTAS 0"], emb, anio=2025).iloc[0]
    assert abs(r["referencia"] - np.exp(r["referencia_log"]) * 470) < 0.02
    assert r["p25"] < r["referencia"] < r["p75"]


def test_el_intervalo_nunca_baja_del_ruido_irreducible(caso):
    # tau + sigma son irreducibles bajo comparacion entre empresas: el intervalo no puede
    # prometer mas precision de la que existe, por muchos donantes que haya.
    filas, emb, _ = caso
    b = _base(filas, emb)
    r = b.referenciar(["BODEGA 0"], emb).iloc[0]
    assert r["sd"] >= np.sqrt(b.tau2 + b.sigma2) - 1e-9


def test_la_confianza_sale_del_intervalo_y_no_del_conteo(caso):
    # `SCRUM MASTER` con 14 empresas salia igual de ALTA que `CONTADOR` con 823. Lo
    # que importa es cuanto se puede mover el numero, no cuantas empresas hay.
    filas, emb, centros = caso
    filas = list(filas)
    emb = dict(emb)
    # Tiene que ser un puesto DISTINTO, no una grafia mas: por debajo del umbral de
    # fusion. Si se la pone pegada al centro de la familia, la fusion la absorbe —con
    # razon— y las dos celdas comparten estadisticos, que es justo lo contrario de lo
    # que este test quiere contrastar.
    emb["BODEGA FLACA"] = centros["BODEGA"] + 0.4 * centros["SISTEMAS"]
    filas += [(f"EF{e}", "BODEGA FLACA", 0.2) for e in range(3)]
    b = _base(filas, emb)

    gorda = b.referenciar(["BODEGA 0"], emb).iloc[0]
    flaca = b.referenciar(["BODEGA FLACA"], emb).iloc[0]
    assert gorda["base"] == flaca["base"] == "datos directos"
    assert flaca["ancho_rel"] > gorda["ancho_rel"], "menos datos, intervalo mas ancho"
    assert gorda["confianza"] == "ALTA"


def test_un_mercado_ruidoso_no_degrada_la_confianza_por_si_solo(caso):
    # El corte es relativo al SUELO IRREDUCIBLE, no un porcentaje fijo. Si todo el
    # mercado es disperso, una celda que ya esta en el suelo sigue siendo lo mejor
    # posible: no tiene sentido llamarla BAJA cuando no existe nada mejor.
    filas, emb, _ = caso
    b = _base(filas, emb)
    antes = b.referenciar(["BODEGA 0"], emb).iloc[0]
    b.tau2 = 0.5
    despues = b.referenciar(["BODEGA 0"], emb).iloc[0]
    assert despues["ancho_rel"] > antes["ancho_rel"]
    assert despues["confianza"] == "ALTA"


def test_la_base_se_guarda_y_se_carga_igual(tmp_path, caso):
    filas, emb, _ = caso
    b = _base(filas, emb)
    ruta = tmp_path / "base.npz"
    b.guardar(ruta)
    b2 = BaseReferencia.cargar(ruta, _sbu)
    a = b.referenciar(["BODEGA 0", "VENTAS 1"], emb)
    c = b2.referenciar(["BODEGA 0", "VENTAS 1"], emb)
    pd.testing.assert_frame_equal(a, c)


def _caso_jerarquico(sin=()):
    """Tres areas con cinco escalones cada una, y el embedding del area ENMASCARADA.

    Reproduce el caso diagnosticado: `SUPERVISOR DE CAJA` se promediaba con `AUXILIAR
    DE CAJA` porque el embedding es ciego a la jerarquia. Aqui todos los rangos de un
    area comparten vector y solo el lexico los distingue.

    Cada empresa tiene gente de VARIOS escalones a proposito: `efecto_nivel` centra
    dentro de empresa —el empleador es el 81% del ruido—, asi que con una persona por
    empresa el residuo es cero y el efecto no se puede estimar.
    """
    paga = {"AUXILIAR": 0.0, "TECNICO": 0.3, "SUPERVISOR": 0.6, "JEFE": 1.0,
            "GERENTE": 1.5}
    areas = {"CAJA": (0.0, [0.11, 1.0, 0.0]), "BODEGA": (0.2, [0.55, 1.0, 0.0]),
             "PLANTA": (0.4, [0.90, 1.0, 0.0])}
    filas, emb = [], {}
    for area, (base, vec) in areas.items():
        for rango, extra in paga.items():
            etq = f"{rango} DE {area}"
            emb[etq] = np.array(vec, dtype=float)
            if etq in sin:
                continue
            for e in range(8):
                # la misma empresa emplea a todos los escalones de esa area
                filas.append((f"E{area}{e}", etq, base + extra))
    return filas, emb


def test_el_nivel_separa_lo_que_el_embedding_confunde():
    # EL caso del README: mismo area, embeddings identicos, y aun asi las referencias
    # deben ordenarse por escalon. Sin el ajuste por nivel todos saldrian iguales.
    filas, emb = _caso_jerarquico()
    b = _base(filas, emb)
    r = b.referenciar(["AUXILIAR DE CAJA", "SUPERVISOR DE CAJA", "GERENTE DE CAJA"], emb)
    v = r.set_index("cargo")["referencia_log"]
    assert v["AUXILIAR DE CAJA"] < v["SUPERVISOR DE CAJA"] < v["GERENTE DE CAJA"]


def test_un_titulo_nuevo_hereda_el_nivel_de_su_palabra_de_rango():
    # `JEFE DE CAJA` no existe en la base, pero `JEFE` si es una palabra de rango: debe
    # colocarse por encima de los auxiliares de su area, no en el promedio.
    filas, emb = _caso_jerarquico()
    filas, emb = _caso_jerarquico(sin=("JEFE DE CAJA",))
    b = _base(filas, emb)
    r = b.referenciar(["JEFE DE CAJA", "AUXILIAR DE CAJA"], emb).set_index("cargo")
    assert r.loc["JEFE DE CAJA", "referencia_log"] > r.loc["AUXILIAR DE CAJA", "referencia_log"]


def test_sin_palabra_de_rango_el_intervalo_paga_la_ignorancia():
    # Un titulo sin rango no se puede ajustar por nivel, y eso NO se disimula: se cobra
    # en el intervalo. Es la diferencia entre "no lo se" y fingir que si.
    filas, emb = _caso_jerarquico()
    emb = dict(emb)
    emb["ENCARGADO DE CAJA"] = emb["AUXILIAR DE CAJA"]
    b = _base(filas, emb)
    r = b.referenciar(["ENCARGADO DE CAJA", "AUXILIAR DE CAJA"], emb).set_index("cargo")
    assert b.var_nivel > 0
    assert r.loc["ENCARGADO DE CAJA", "sd"] > r.loc["AUXILIAR DE CAJA", "sd"]


def test_el_castigo_por_nivel_desconocido_sale_del_vecindario():
    # Un puesto sin palabra de rango cuyo vecindario es HOMOGENEO en escalon no merece el
    # mismo castigo que uno cuyo vecindario va de auxiliar a gerente. Antes los dos
    # pagaban la dispersion global, o sea el caso peor.
    filas, emb = _caso_jerarquico()
    emb = dict(emb)
    # vecindario homogeneo: pegado a los auxiliares de CAJA
    emb["ENCARGADO X"] = emb["AUXILIAR DE CAJA"]
    b = _base(filas, emb)
    # y uno cuyo vecindario mezcla escalones: en medio de todo
    todos = np.mean([emb[f"{r} DE CAJA"] for r in
                     ("AUXILIAR", "TECNICO", "SUPERVISOR", "JEFE", "GERENTE")], axis=0)
    emb["ENCARGADO Y"] = todos
    b2 = _base(filas, emb)
    homogeneo = b2.referenciar(["ENCARGADO X"], emb).iloc[0]
    mezclado = b2.referenciar(["ENCARGADO Y"], emb).iloc[0]
    assert homogeneo["base"] == mezclado["base"] == "por analogia"
    assert homogeneo["sd"] <= mezclado["sd"] + 1e-9


# --- fusion de cuasi-duplicados -------------------------------------------------

def _caso_grafias(n_empresas=2):
    """El mismo puesto tecleado de dos formas, lejos de todo lo demas.

    Reproduce `ASISTENTE / AYUDANTE / AUXILIAR ADMINISTRATIVO` contra
    `ASISTENTE/AYUDANTE/AUXILIAR ADMINISTRATIVO`: vector identico, celdas separadas, y
    cada una demasiado delgada para contestar sola.
    """
    filas, emb = [], {}
    emb["ANALISTA DE RIESGO DE CREDITO"] = np.array([1.0, 0.0, 0.0])
    emb["ANALISTA DE RIESGO CREDITICIO"] = np.array([1.0, 0.0, 0.0])
    emb["MENSAJERO"] = np.array([0.0, 1.0, 0.0])
    for i, etq in enumerate(["ANALISTA DE RIESGO DE CREDITO",
                             "ANALISTA DE RIESGO CREDITICIO"]):
        for e in range(n_empresas):
            filas += [(f"EA{i}{e}", etq, 1.0 + 0.01 * j) for j in range(4)]
    for e in range(9):
        filas += [(f"EM{e}", "MENSAJERO", 0.1 + 0.01 * j) for j in range(4)]
    return filas, emb


def test_dos_grafias_del_mismo_puesto_votan_juntas():
    # Por separado cada grafia tiene 2 empresas y no llega al suelo; fusionadas son 4 y
    # se contestan con datos propios. Es la ganancia medida: 57,7% -> 64,1% de cobertura.
    filas, emb = _caso_grafias()
    con = _base(filas, emb).referenciar(list(emb), emb).set_index("cargo")
    sin = BaseReferencia.construir(_marco(filas), emb, _sbu, umbral_fusion=None)
    sin = sin.referenciar(list(emb), emb).set_index("cargo")

    assert sin.loc["ANALISTA DE RIESGO CREDITICIO", "base"] == "por analogia"
    assert con.loc["ANALISTA DE RIESGO CREDITICIO", "base"] == "datos directos"
    assert con.loc["ANALISTA DE RIESGO CREDITICIO", "empresas"] == 4
    # y las dos grafias dan exactamente la misma respuesta, que es el punto
    assert (con.loc["ANALISTA DE RIESGO CREDITICIO", "referencia_log"]
            == con.loc["ANALISTA DE RIESGO DE CREDITO", "referencia_log"])


def test_sin_fusionar_el_informe_cuenta_mensajeros_como_evidencia():
    # Sin fusion la respuesta NO se rompe —la hermana de grafia ya la rescataba por
    # analogia a distancia cero, y el numero sale igual—; lo que se rompe es lo que el
    # informe declara. `empresas` sumaba todo el vecindario, mensajeros incluidos, y el
    # cliente leia 11 empresas de respaldo donde solo hay 4 de su puesto.
    filas, emb = _caso_grafias()
    sin = BaseReferencia.construir(_marco(filas), emb, _sbu, umbral_fusion=None)
    r = sin.referenciar(["ANALISTA DE RIESGO CREDITICIO"], emb).iloc[0]
    con = _base(filas, emb).referenciar(["ANALISTA DE RIESGO CREDITICIO"], emb).iloc[0]
    assert r["base"] == "por analogia" and con["base"] == "datos directos"
    assert r["empresas"] > con["empresas"] == 4, "la fusion declara el respaldo real"


def test_la_fusion_no_cuela_una_celda_por_debajo_del_suelo():
    # EL riesgo de la fusion. Si el grupo entero sigue sin llegar a MIN_EMPRESAS, su
    # mediana no puede reaparecer disfrazada de "vecino a distancia cero": el suelo es
    # de confidencialidad, no de gusto. La respuesta debe venir de FUERA del grupo.
    filas, emb = _caso_grafias(n_empresas=1)          # 1 + 1 = 2 empresas, bajo el suelo
    b = _base(filas, emb)
    r = b.referenciar(["ANALISTA DE RIESGO CREDITICIO"], emb).iloc[0]
    assert r["base"] == "por analogia"
    # su propio grupo paga 1,0 y el unico vecino disponible paga 0,1: si la referencia
    # saliera cerca de 1,0 es que se filtro por la puerta de atras
    assert abs(r["referencia_log"] - 0.1) < abs(r["referencia_log"] - 1.0)


def test_el_escalon_impide_fusionar_puestos_de_distinto_rango():
    # `AUXILIAR DE CAJA` y `GERENTE DE CAJA` comparten vector exacto en este caso, y aun
    # asi no pueden acabar en la misma celda: el candado de nivel lo prohibe.
    filas, emb = _caso_jerarquico()
    b = _base(filas, emb)
    assert b.grupo[b.idx["AUXILIAR DE CAJA"]] != b.grupo[b.idx["GERENTE DE CAJA"]]
    r = b.referenciar(["AUXILIAR DE CAJA", "GERENTE DE CAJA"], emb).set_index("cargo")
    assert (r.loc["AUXILIAR DE CAJA", "referencia_log"]
            < r.loc["GERENTE DE CAJA", "referencia_log"])


def test_el_enlace_completo_no_encadena():
    # El defecto que se midio: union-find junta A con C si existe la cadena A~B~C aunque
    # A y C no se parezcan. Tres puntos en fila, cada uno cerca del siguiente y lejos del
    # tercero, no pueden acabar en un solo grupo.
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.25, 0.0])
    c = np.array([1.0, 0.52, 0.0])
    emb = {"PUESTO A": a, "PUESTO B": b, "PUESTO C": c}
    filas = [(f"E{n}{e}", n, 0.5) for n in emb for e in range(4)]
    base = _base(filas, emb)
    g = {n: int(base.grupo[base.idx[n]]) for n in emb}
    cos = lambda u, v: float(u @ v / (np.linalg.norm(u) * np.linalg.norm(v)))
    assert cos(a, b) > 0.95 and cos(b, c) > 0.95, "la cadena existe"
    assert cos(a, c) < 0.95, "y los extremos no se parecen"
    assert g["PUESTO A"] != g["PUESTO C"], "el enlace completo no debe encadenar"
