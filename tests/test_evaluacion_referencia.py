import numpy as np
import pandas as pd
from benchmarking.evaluacion.referencia import (
    componentes_varianza, pesos_empresa, cuantil_ponderado, predecir, aplicar_abstencion)


def _m(filas):
    return pd.DataFrame(filas, columns=["empresa_ruc", "celda", "y"])


def _pred(train, test, **kw):
    p = predecir(train, test, "celda", **kw)
    return p.assign(y_ref=aplicar_abstencion(p))


# --- componentes de varianza -------------------------------------------------

def test_componentes_recuperan_las_varianzas_conocidas():
    # Se construye con tau=0,4 y sigma=0,2 y se comprueba que el estimador de momentos
    # los recupera. Si esto falla, TODOS los pesos estan mal y no lo veriamos en ningun
    # otro test: los pesos solo se notan en el tercer decimal del resultado final.
    rng = np.random.default_rng(7)
    filas = []
    for c in range(6):
        for f in range(40):
            a = rng.normal(0, 0.4)
            for _ in range(12):
                filas.append((f"E{c}_{f}", f"c{c}", 2.0 + a + rng.normal(0, 0.2)))
    tau2, sigma2 = componentes_varianza(_m(filas), "celda")
    assert abs(np.sqrt(tau2) - 0.4) < 0.06, f"tau={np.sqrt(tau2):.3f}"
    assert abs(np.sqrt(sigma2) - 0.2) < 0.02, f"sigma={np.sqrt(sigma2):.3f}"


def test_sin_efecto_empresa_tau2_es_cero():
    rng = np.random.default_rng(3)
    filas = [(f"E{f}", "c", float(rng.normal(0, 0.3))) for f in range(50) for _ in range(10)]
    tau2, sigma2 = componentes_varianza(_m(filas), "celda")
    assert tau2 < 0.01 and abs(np.sqrt(sigma2) - 0.3) < 0.03


# --- pesos -------------------------------------------------------------------

def test_los_pesos_interpolan_entre_las_dos_posturas():
    # n grande -> todas pesan igual (una empresa, un voto).
    w = pesos_empresa([1000, 3000], tau2=0.16, sigma2=0.04)
    assert abs(w[0] / w[1] - 1.0) < 0.01
    # tau2 -> 0 -> el peso es proporcional a n (una persona, un voto).
    w = pesos_empresa([1, 10], tau2=1e-12, sigma2=0.04)
    assert abs(w[1] / w[0] - 10.0) < 0.01


def test_el_ratio_de_pesos_esta_acotado():
    # ESTE es el punto de D-011: una empresa de 3.000 no puede pesar 3.000 veces mas que
    # una de 1. La cota es 1 + sigma2/tau2, aqui 1 + 0.04/0.16 = 1,25.
    tau2, sigma2 = 0.16, 0.04
    w = pesos_empresa([1, 3000], tau2, sigma2)
    assert w[1] / w[0] <= 1.0 + sigma2 / tau2 + 1e-9
    assert w[1] / w[0] > 1.0                      # pero sigue premiando a la mas precisa


# --- cuantil ponderado -------------------------------------------------------

def test_con_pesos_iguales_es_la_mediana():
    for v in ([1., 2., 3., 4., 5.], [1., 2., 3., 4.]):
        assert abs(cuantil_ponderado(v, np.ones(len(v))) - float(np.median(v))) < 1e-9


def test_el_peso_desplaza_el_cuantil():
    v = [1.0, 10.0]
    assert cuantil_ponderado(v, [1.0, 99.0]) > 9.0
    assert cuantil_ponderado(v, [99.0, 1.0]) < 2.0


def test_cuantil_ponderado_ignora_pesos_nulos_y_nan():
    assert abs(cuantil_ponderado([1., 5., np.nan], [1., 1., 1.]) - 3.0) < 1e-9
    assert abs(cuantil_ponderado([1., 5., 99.], [1., 1., 0.]) - 3.0) < 1e-9
    assert np.isnan(cuantil_ponderado([], []))


# --- prediccion --------------------------------------------------------------

def test_excluye_la_propia_empresa():
    # El efecto empresa explica ~39% de la varianza: usar a los companeros seria acertar
    # por la razon equivocada.
    train = _m([("E1", "c", 10.0)] * 3 + [(f"E{i}", "c", 1.0) for i in range(2, 8)])
    out = _pred(train, _m([("E1", "c", 10.0)]))
    assert abs(out["y_ref"].iloc[0] - 1.0) < 1e-9


def test_una_empresa_grande_no_define_el_mercado():
    # La correccion 1 de D-009 SIGUE vigente con los pesos nuevos: E1 aporta 100 personas
    # a 5.0 y las otras seis una a 1.0. Su peso es como mucho 1+sigma2/tau2 veces mayor.
    #
    # Se desactiva el suelo de dominancia a proposito: con 100 de 106 personas E1 tiene el
    # 94% y el suelo abstendria ANTES de que la ponderacion entre en juego. Aqui se prueba
    # el estimador; el suelo tiene su propio test.
    train = _m([("E1", "c", 5.0)] * 100 + [(f"E{i}", "c", 1.0) for i in range(2, 8)])
    p = predecir(train, _m([("E9", "c", 1.0)]), "celda")
    y = aplicar_abstencion(p, share_max=1.01)
    assert abs(y.iloc[0] - 1.0) < 0.2, "un empleador grande no es el mercado"
    assert p["n_empresas_donantes"].iloc[0] == 7


def test_la_mediana_de_una_empresa_resume_a_sus_personas():
    train = _m([("E1", "c", 1.0), ("E1", "c", 3.0), ("E1", "c", 5.0)] +
               [(f"E{i}", "c", 100.0) for i in range(2, 7)])
    out = _pred(train, _m([("E9", "c", 0.0)]))
    assert out["y_ref"].iloc[0] > 50.0        # el voto de E1 es 3.0, y es 1 de 6


def test_mas_empresas_donantes_estrechan_la_predictiva():
    # La anchura predictiva es la perilla de confianza: tiene que MEJORAR con la evidencia.
    #
    # Los componentes se pasan FIJOS a las dos llamadas, que es como funciona de verdad:
    # tau2 y sigma2 se estiman una vez, globalmente, y se comparten entre celdas. Dejar
    # que cada conjunto estime los suyos compararia dos estimaciones ruidosas de la
    # varianza en vez del efecto de tener mas donantes — y con 4 empresas la estimacion
    # es tan mala que puede salir MENOR que con 60.
    rng = np.random.default_rng(11)
    pocas = _m([(f"E{i}", "c", float(rng.normal(2, .3))) for i in range(4) for _ in range(5)])
    muchas = _m([(f"E{i}", "c", float(rng.normal(2, .3))) for i in range(60) for _ in range(5)])
    t = _m([("EX", "c", 2.0)])
    comp = dict(tau2=0.02, sigma2=0.09)
    assert predecir(muchas, t, "celda", **comp)["sd_pred"].iloc[0] < \
           predecir(pocas, t, "celda", **comp)["sd_pred"].iloc[0]


def test_los_componentes_se_comparten_entre_celdas():
    # Corolario del test anterior, y la razon por la que `predecir` los acepta como
    # parametro: si cada celda estimara los suyos, `sd_pred` no seria comparable ENTRE
    # celdas, y la abstencion ordena precisamente comparando anchuras entre celdas.
    rng = np.random.default_rng(13)
    tr = _m([(f"E{i}", f"c{i % 3}", float(rng.normal(2, .3)))
             for i in range(30) for _ in range(6)])
    tau2, sigma2 = componentes_varianza(tr, "celda")
    t = _m([("EX", "c0", 2.0), ("EX", "c1", 2.0)])
    con_globales = predecir(tr, t, "celda", tau2=tau2, sigma2=sigma2)
    pd.testing.assert_frame_equal(con_globales, predecir(tr, t, "celda"))


def test_la_predictiva_no_baja_del_ruido_irreducible():
    # Ni con infinitos donantes: la empresa nueva y la persona nueva no se pueden predecir.
    rng = np.random.default_rng(5)
    tr = _m([(f"E{i}", "c", float(rng.normal(2, .3))) for i in range(400) for _ in range(8)])
    tau2, sigma2 = componentes_varianza(tr, "celda")
    sd = predecir(tr, _m([("EX", "c", 2.0)]), "celda")["sd_pred"].iloc[0]
    assert sd >= np.sqrt(tau2 + sigma2) - 1e-9


# --- abstencion --------------------------------------------------------------

def test_suelo_de_empresas():
    out = _pred(_m([("E2", "c", 1.0)] * 9 + [("E3", "c", 1.0)] * 9), _m([("E1", "c", 1.0)]))
    assert pd.isna(out["y_ref"].iloc[0]) and out["n_empresas_donantes"].iloc[0] == 2


def test_suelo_de_dominancia():
    # e>=3 NO impide que una empresa con el 95% de la gente domine. La regla de share si.
    train = _m([("E1", "c", 5.0)] * 95 + [("E2", "c", 1.0), ("E3", "c", 1.0)])
    out = _pred(train, _m([("E9", "c", 1.0)]))
    assert pd.isna(out["y_ref"].iloc[0])
    assert out["share_max_empresa"].iloc[0] > 0.8
    # sin el suelo de dominancia si responde
    p = predecir(train, _m([("E9", "c", 1.0)]), "celda")
    assert not pd.isna(aplicar_abstencion(p, share_max=1.01).iloc[0])


def test_umbral_de_anchura():
    rng = np.random.default_rng(2)
    tr = _m([(f"E{i}", "c", float(rng.normal(2, .3))) for i in range(20) for _ in range(6)])
    p = predecir(tr, _m([("EX", "c", 2.0)]), "celda")
    assert pd.isna(aplicar_abstencion(p, max_sd=0.01).iloc[0])
    assert not pd.isna(aplicar_abstencion(p, max_sd=99.0).iloc[0])


def test_se_abstiene_en_celda_no_vista():
    out = _pred(_m([(f"E{i}", "c", 1.0) for i in range(2, 12)]), _m([("E1", "otra", 1.0)]))
    assert pd.isna(out["y_ref"].iloc[0]) and out["n_donantes"].iloc[0] == 0


def test_una_celda_por_persona_no_predice_nada():
    # La trampa que la balanza debe castigar: partir de mas deja los cajones vacios.
    train = pd.DataFrame({"empresa_ruc": [f"E{i}" for i in range(20)],
                          "celda": [f"c{i}" for i in range(20)],
                          "y": np.linspace(0, 2, 20)})
    out = _pred(train, pd.DataFrame({"empresa_ruc": ["E0"], "celda": ["c0"], "y": [0.0]}))
    assert pd.isna(out["y_ref"].iloc[0])


def test_predecir_no_aplica_abstencion_por_su_cuenta():
    # Separacion de responsabilidades: la curva de la Tarea 5 barre el umbral sin
    # recalcular predecir. Si predecir filtrara, habria que llamarlo una vez por punto.
    out = predecir(_m([("E2", "c", 1.0), ("E3", "c", 1.0)]), _m([("E1", "c", 1.0)]), "celda")
    assert "y_ref" not in out.columns and not pd.isna(out["y_ref_bruto"].iloc[0])
