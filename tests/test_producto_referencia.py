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


def test_la_banda_no_incluye_la_dispersion_DENTRO_de_la_empresa():
    # La banda dice "la mitad de las EMPRESAS paga entre X e Y", asi que `sigma` no entra:
    # que dos personas de la misma nomina cobren muy distinto no mueve el nivel de esa
    # empresa. Aqui las 12 empresas tienen la MISMA mediana y una dispersion interna
    # enorme; la banda tiene que salir estrecha.
    emb = {"PUESTO": np.array([1.0, 0.0, 0.0]), "OTRO": np.array([0.0, 1.0, 0.0])}
    filas = [(f"E{e}", "PUESTO", v) for e in range(12) for v in (0.0, .1, .2, .3, .4)]
    filas += [(f"O{e}", "OTRO", 1.0) for e in range(4)]
    r = _base(filas, emb).referenciar(["PUESTO"], emb).iloc[0]
    assert r["base"] == "datos directos"
    # sigma dentro de empresa es ~0.15; si entrara en la banda, el ancho seria >10%
    assert r["ancho_rel"] < 0.02, f"la banda se contamino de sigma: {r['ancho_rel']}"
    assert r["p25_log"] <= r["referencia_log"] <= r["p75_log"]


def test_el_intervalo_del_modelo_nunca_baja_del_suelo_del_cargo(caso):
    # En la rama de modelo —sin empresas de sobra para cuantiles empiricos— el intervalo
    # no puede prometer mas precision que la dispersion real del cargo entre empresas.
    filas, emb, centros = caso
    filas = list(filas)
    emb = dict(emb)
    emb["PUESTO FLACO"] = centros["BODEGA"] + 0.4 * centros["SISTEMAS"]
    filas += [(f"EFL{e}", "PUESTO FLACO", 0.2 + 0.1 * e) for e in range(5)]
    b = _base(filas, emb)
    i = b.idx["PUESTO FLACO"]
    assert b.emp[i] < 10, "debe caer en la rama de modelo, no en cuantiles empiricos"
    r = b.referenciar(["PUESTO FLACO"], emb).iloc[0]
    assert r["sd"] >= np.sqrt(b.tau2_c[i]) - 1e-9


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
    # 3 empresas pero con gente dentro: el suelo de personas rechaza las celdas de 3-4
    # personas, y aqui lo que se quiere contrastar es POCAS EMPRESAS, no poca gente.
    # Y las tres pagan distinto, para que su mercado sea comparable al de la gorda.
    for e, base in enumerate((0.10, 0.20, 0.32)):
        filas += [(f"EF{e}", "BODEGA FLACA", base + 0.01 * k) for k in range(4)]
    b = _base(filas, emb)

    gorda = b.referenciar(["BODEGA 0"], emb).iloc[0]
    flaca = b.referenciar(["BODEGA FLACA"], emb).iloc[0]
    assert gorda["base"] == flaca["base"] == "datos directos"
    # Lo que separa a las dos es la INCERTIDUMBRE DEL CENTRO, no el ancho de la banda: el
    # ancho dice cuanto varia el mercado —que puede ser estrecho con pocos datos— y la
    # incertidumbre dice cuanto puede moverse la referencia. Ver D-017.
    assert flaca["incert_centro"] > gorda["incert_centro"], "menos empresas, centro peor"
    assert gorda["confianza"] == "ALTA"


def test_un_mercado_ruidoso_no_degrada_la_confianza_por_si_solo(caso):
    # La confianza mide lo bien que se conoce el CENTRO, no lo ancho que es el mercado.
    # Si el cargo se dispersa mas, la banda se ensancha —eso es informacion, y se
    # entrega— pero la referencia no se vuelve menos fiable por ello.
    filas, emb, _ = caso
    b = _base(filas, emb)
    antes = b.referenciar(["BODEGA 0"], emb).iloc[0]
    # la dispersion del CARGO es la que manda ahora, no la global
    i = b.idx["BODEGA 0"]
    b.tau2_c = b.tau2_c.copy()
    b.tau2_c[i] = 0.5
    b.bandas = b.bandas.copy()
    b.bandas[i] = np.nan          # sin banda empirica, se ve el efecto del modelo
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


def test_la_confianza_baja_cuando_hay_MENOS_empresas_aunque_el_mercado_sea_igual():
    # Lo que la regla vieja NO podia distinguir. Dos cargos con la misma dispersion de
    # mercado y muy distinto respaldo: 40 empresas contra 4. La banda de los dos es
    # parecida —el mercado es igual de ancho— pero la referencia del segundo esta mucho
    # peor determinada, y la etiqueta tiene que decirlo.
    rng = np.random.default_rng(7)
    emb = {"MUCHAS": np.array([1.0, 0.0, 0.0]), "POCAS": np.array([0.0, 1.0, 0.0])}
    # el efecto de empresa lo comparten los empleados de esa empresa, y cada celda tiene
    # gente de sobra: lo que se contrasta es el NUMERO DE EMPRESAS, no el de personas
    filas = []
    for e in range(40):
        u = rng.normal(0, .30)
        filas += [(f"EM{e}", "MUCHAS", 0.5 + u + rng.normal(0, .02)) for _ in range(3)]
    for e in range(4):
        u = rng.normal(0, .30)
        filas += [(f"EP{e}", "POCAS", 0.5 + u + rng.normal(0, .02)) for _ in range(3)]
    b = _base(filas, emb)
    r = b.referenciar(["MUCHAS", "POCAS"], emb).set_index("cargo")
    assert r.loc["MUCHAS", "base"] == r.loc["POCAS", "base"] == "datos directos"
    assert r.loc["MUCHAS", "incert_centro"] < r.loc["POCAS", "incert_centro"] / 2
    assert r.loc["MUCHAS", "confianza"] == "ALTA"
    assert r.loc["POCAS", "confianza"] in ("MEDIA", "BAJA")


def test_la_confianza_no_depende_del_ancho_del_mercado():
    # Dos cargos con el MISMO numero de empresas y dispersiones muy distintas. El ancho
    # de banda tiene que separarlos; la etiqueta NO, porque el centro de los dos esta
    # igual de bien determinado. Con la regla vieja esto se confundia.
    rng = np.random.default_rng(11)
    emb = {"ESTRECHO": np.array([1.0, 0.0, 0.0]), "ANCHO": np.array([0.0, 1.0, 0.0])}
    filas = [(f"EE{e}", "ESTRECHO", 0.5 + rng.normal(0, .02)) for e in range(30)]
    filas += [(f"EA{e}", "ANCHO", 0.5 + rng.normal(0, .60)) for e in range(30)]
    # relleno: el encogimiento empirico-bayesiano de `tau_c` necesita 3+ celdas para
    # estimar la varianza ENTRE celdas. Con dos cae al global y el test no mide lo suyo.
    for k in range(4):
        etq = f"RELLENO {k}"
        emb[etq] = np.array([0.0, 0.0, 1.0]) + rng.normal(0, .05, 3)
        filas += [(f"ER{k}{e}", etq, 1.0 + rng.normal(0, .1 * (k + 1)), )
                  for e in range(20)]
    r = _base(filas, emb).referenciar(["ESTRECHO", "ANCHO"], emb).set_index("cargo")
    assert r.loc["ANCHO", "ancho_rel"] > 5 * r.loc["ESTRECHO", "ancho_rel"], "la banda si"
    assert r.loc["ESTRECHO", "confianza"] == "ALTA", "el centro se conoce bien"


def test_una_celda_de_tres_personas_no_publica_su_mediana():
    # El suelo de EMPRESAS no dice nada de PERSONAS: tres empresas con una persona cada
    # una son tres personas, y la mediana de sus tres votos ES el sueldo de una de ellas.
    # Con `MIN_PERSONAS` esa celda pasa a contestarse por analogia.
    from benchmarking.producto.base_referencia import MIN_EMPRESAS, MIN_PERSONAS
    emb = {"RARO": np.array([1.0, 0.0, 0.0]), "VECINO": np.array([0.93, 0.37, 0.0])}
    # 3 empresas, 1 persona cada una: pasa el suelo de empresas, no el de personas
    filas = [(f"ER{e}", "RARO", 1.0 + 0.1 * e) for e in range(3)]
    filas += [(f"EV{e}", "VECINO", 0.5) for e in range(6) for _ in range(4)]
    b = _base(filas, emb)
    i = b.idx["RARO"]
    assert b.emp[i] >= MIN_EMPRESAS, "pasa el suelo de empresas"
    assert b.personas[i] < MIN_PERSONAS, "y no el de personas"
    r = b.referenciar(["RARO"], emb).iloc[0]
    assert r["base"] == "por analogia", "no puede publicar la mediana de 3 personas"
    # se sigue respondiendo: es la decision de producto
    assert np.isfinite(r["referencia_log"])


def test_el_suelo_de_personas_no_toca_las_celdas_con_gente():
    from benchmarking.producto.base_referencia import MIN_PERSONAS
    emb = {"GORDO": np.array([1.0, 0.0, 0.0]), "OTRO": np.array([0.0, 1.0, 0.0])}
    filas = [(f"EG{e}", "GORDO", 1.0 + 0.05 * k) for e in range(4) for k in range(5)]
    filas += [(f"EO{e}", "OTRO", 0.5) for e in range(4) for _ in range(5)]
    b = _base(filas, emb)
    i = b.idx["GORDO"]
    assert b.personas[i] >= MIN_PERSONAS
    assert b.referenciar(["GORDO"], emb).iloc[0]["base"] == "datos directos"


# --- D-018: correccion del centro por tamano de empresa -------------------------

def _caso_segmentado(n_por_seg=14):
    """Un cargo ALTO donde el tamano manda, y uno de BASE donde no.

    Reproduce el patron medido: en el nivel 5 la empresa pequena paga la mitad que la
    grande, y en el nivel 1 pagan lo mismo.
    """
    emb = {"GERENTE DE PLANTA": np.array([1.0, 0.0, 0.0]),
           "AUXILIAR DE PLANTA": np.array([0.0, 1.0, 0.0])}
    paga = {("GERENTE DE PLANTA", "GRANDE"): 2.0,
            ("GERENTE DE PLANTA", "PEQUEÑA"): 1.0,
            ("AUXILIAR DE PLANTA", "GRANDE"): 0.2,
            ("AUXILIAR DE PLANTA", "PEQUEÑA"): 0.2}
    filas = []
    for (cargo, seg), base in paga.items():
        for e in range(n_por_seg):
            filas += [(f"E{cargo[:3]}{seg[:2]}{e}", cargo, base + 0.01 * k, seg)
                      for k in range(4)]
    return pd.DataFrame(filas, columns=["empresa_ruc", "cargo_norm", "y", "segmento"]), emb


def test_el_tamano_corrige_el_centro_en_los_cargos_altos():
    from benchmarking.producto.base_referencia import NIVEL_MIN_SEGMENTAR
    from benchmarking.producto.nivel import nivel_lexico
    marco, emb = _caso_segmentado()
    b = BaseReferencia.construir(marco, emb, _sbu)
    assert nivel_lexico("GERENTE DE PLANTA") >= NIVEL_MIN_SEGMENTAR

    sin = b.referenciar(["GERENTE DE PLANTA"], emb).iloc[0]["referencia_log"]
    gr = b.referenciar(["GERENTE DE PLANTA"], emb, segmento="GRANDE").iloc[0]
    pq = b.referenciar(["GERENTE DE PLANTA"], emb, segmento="PEQUENA").iloc[0]

    assert pq["referencia_log"] < sin < gr["referencia_log"], "el centro se desplaza"
    # la banda se mueve con el centro, no se queda atras
    assert pq["p25_log"] < gr["p25_log"] and pq["p75_log"] < gr["p75_log"]
    # y la ANCHURA no cambia: se desplaza, no se reestima
    assert abs((gr["p75_log"] - gr["p25_log"]) - (pq["p75_log"] - pq["p25_log"])) < 1e-9


def test_el_tamano_NO_toca_los_cargos_de_base():
    # El sesgo medido es plano en el nivel 1 (recorrido 10,1%), asi que segmentar ahi
    # moveria la referencia sin razon.
    marco, emb = _caso_segmentado()
    b = BaseReferencia.construir(marco, emb, _sbu)
    sin = b.referenciar(["AUXILIAR DE PLANTA"], emb).iloc[0]["referencia_log"]
    for seg in ("GRANDE", "PEQUENA"):
        r = b.referenciar(["AUXILIAR DE PLANTA"], emb, segmento=seg).iloc[0]
        assert abs(r["referencia_log"] - sin) < 1e-9, f"{seg} no deberia moverlo"


def test_sin_segmento_el_comportamiento_es_el_de_siempre():
    marco, emb = _caso_segmentado()
    b = BaseReferencia.construir(marco, emb, _sbu)
    a = b.referenciar(["GERENTE DE PLANTA"], emb)
    for vacio in (None, "", "NA", "  "):
        pd.testing.assert_frame_equal(a, b.referenciar(["GERENTE DE PLANTA"], emb,
                                                       segmento=vacio))


def test_un_segmento_con_pocas_empresas_no_mueve_nada():
    # Por debajo del minimo el desplazamiento seria ruido. Aqui MICROEMPRESA tiene 2.
    from benchmarking.producto.base_referencia import MIN_EMPRESAS_SEGMENTO
    marco, emb = _caso_segmentado()
    extra = pd.DataFrame(
        [(f"EMICRO{e}", "GERENTE DE PLANTA", 0.1 + 0.01 * k, "MICROEMPRESA")
         for e in range(2) for k in range(4)],
        columns=["empresa_ruc", "cargo_norm", "y", "segmento"])
    b = BaseReferencia.construir(pd.concat([marco, extra]), emb, _sbu)
    assert 2 < MIN_EMPRESAS_SEGMENTO
    sin = b.referenciar(["GERENTE DE PLANTA"], emb).iloc[0]["referencia_log"]
    mi = b.referenciar(["GERENTE DE PLANTA"], emb,
                       segmento="MICROEMPRESA").iloc[0]["referencia_log"]
    assert abs(mi - sin) < 1e-9, "2 empresas no bastan para desplazar la referencia"


# --------------------------------------------------------------------------
# BANDA POR RUBRO (D-023). Es una lente de PRODUCTO: esta medido que el sector no
# mejora la precision (D-022, indistinguible de placebo). Lo que estos tests fijan
# no es que acierte mas, sino que sea COHERENTE y que el coste sea visible.
# --------------------------------------------------------------------------

def _marco_rubro(filas):
    return pd.DataFrame(filas, columns=["empresa_ruc", "cargo_norm", "y", "ciiu_n1"])


def _dos_rubros(n=14, sep=1.0):
    """`CONTADOR` en dos rubros que pagan distinto, cada uno con respaldo de sobra."""
    filas = []
    for i in range(n):
        filas.append((f"A{i}", "CONTADOR", 1.0 + 0.01 * i, "C"))
        filas.append((f"B{i}", "CONTADOR", 1.0 + sep + 0.01 * i, "G"))
    # un cargo con rubro pero SIN respaldo suficiente: tiene que caer al global
    for i in range(4):
        filas.append((f"Z{i}", "BODEGUERO", 0.5 + 0.01 * i, "C"))
    return _marco_rubro(filas)


def _emb_rubro():
    return {"CONTADOR": np.array([1.0, 0.0]), "BODEGUERO": np.array([0.0, 1.0])}


def test_el_rubro_cambia_la_referencia_cuando_tiene_respaldo():
    b = BaseReferencia.construir(_dos_rubros(), _emb_rubro(), _sbu)
    emb = _emb_rubro()
    glob = b.referenciar(["CONTADOR"], emb).iloc[0]
    c = b.referenciar(["CONTADOR"], emb, rubro="C").iloc[0]
    g = b.referenciar(["CONTADOR"], emb, rubro="G").iloc[0]
    assert c["rubro"] == "C" and g["rubro"] == "G" and glob["rubro"] == ""
    assert c["referencia_log"] < glob["referencia_log"] < g["referencia_log"], (
        "el rubro barato debe quedar por debajo del global y el caro por encima")
    assert abs(g["referencia_log"] - c["referencia_log"] - 1.0) < 0.1


def test_el_centro_del_rubro_cae_DENTRO_de_la_banda_del_rubro():
    # La incoherencia que este diseno existe para prohibir: publicar un centro global
    # dentro de una banda sectorial lo dejaria fuera de su propio p25-p75.
    b = BaseReferencia.construir(_dos_rubros(), _emb_rubro(), _sbu)
    for r in ("C", "G"):
        f = b.referenciar(["CONTADOR"], _emb_rubro(), rubro=r).iloc[0]
        assert f["p25_log"] <= f["referencia_log"] <= f["p75_log"], (
            f"rubro {r}: el centro cae fuera de su propia banda")
        assert f["p10_log"] <= f["p25_log"] <= f["p75_log"] <= f["p90_log"]


def test_el_cargo_sin_respaldo_en_su_rubro_cae_al_global_EL_SOLO():
    # El fallback es por CARGO, no por informe: `CONTADOR` tiene rubro y `BODEGUERO` no,
    # y los dos salen en la misma consulta.
    b = BaseReferencia.construir(_dos_rubros(), _emb_rubro(), _sbu)
    out = b.referenciar(["CONTADOR", "BODEGUERO"], _emb_rubro(),
                        rubro="C").set_index("cargo")
    assert out.loc["CONTADOR", "rubro"] == "C"
    assert out.loc["BODEGUERO", "rubro"] == "", "4 empresas no llegan al suelo"


def test_el_coste_del_rubro_es_visible_en_el_respaldo():
    # Es la mitad de la promesa: el cliente ve que su referencia sectorial sale de menos
    # empresas. Si el coste no se ve, la lente engana.
    b = BaseReferencia.construir(_dos_rubros(), _emb_rubro(), _sbu)
    emb = _emb_rubro()
    glob = b.referenciar(["CONTADOR"], emb).iloc[0]
    c = b.referenciar(["CONTADOR"], emb, rubro="C").iloc[0]
    assert c["empresas"] < glob["empresas"], "el rubro tiene menos empresas detras"
    assert c["incert_centro"] > glob["incert_centro"], (
        "menos empresas => 1/W mayor => el centro se conoce peor, y hay que decirlo")


def test_un_rubro_desconocido_avisa_y_sigue_en_global():
    b = BaseReferencia.construir(_dos_rubros(), _emb_rubro(), _sbu)
    with pytest.warns(UserWarning, match="sin datos suficientes"):
        f = b.referenciar(["CONTADOR"], _emb_rubro(), rubro="Q").iloc[0]
    assert f["rubro"] == "", "cae al mercado entero en vez de devolver nada"


def test_el_rubro_sobrevive_a_guardar_y_cargar(tmp_path):
    b = BaseReferencia.construir(_dos_rubros(), _emb_rubro(), _sbu)
    ruta = tmp_path / "b.npz"
    b.guardar(ruta)
    b2 = BaseReferencia.cargar(ruta, _sbu)
    a = b.referenciar(["CONTADOR"], _emb_rubro(), rubro="G").iloc[0]
    c = b2.referenciar(["CONTADOR"], _emb_rubro(), rubro="G").iloc[0]
    assert c["rubro"] == "G"
    assert abs(a["referencia_log"] - c["referencia_log"]) < 1e-9
    assert abs(a["p25_log"] - c["p25_log"]) < 1e-9


def test_sin_columna_de_rubro_la_base_se_construye_igual():
    # El marco de los tests viejos no trae `ciiu_n1`, y una base sin rubro tiene que
    # comportarse exactamente como antes.
    emb = _emb_rubro()
    filas = [(f"A{i}", "CONTADOR", 1.0 + 0.01 * i) for i in range(12)]
    b = BaseReferencia.construir(_marco(filas), emb, _sbu)
    assert b.rub == {} and b.rubros == []
    with pytest.warns(UserWarning, match="sin datos suficientes"):
        f = b.referenciar(["CONTADOR"], emb, rubro="C").iloc[0]
    assert f["rubro"] == ""
