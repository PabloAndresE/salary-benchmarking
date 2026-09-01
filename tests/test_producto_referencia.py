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
    emb["BODEGA FLACA"] = centros["BODEGA"] + np.array([0.015, 0., 0.])
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
