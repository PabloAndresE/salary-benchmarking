import numpy as np
import pandas as pd
from benchmarking.evaluacion.metricas import (
    augrc, crps_normal, curva_coste, curva_riesgo, error_y_cobertura, ic_diferencia,
    omega2_intra_empresa, por_subgrupo, replicas_bootstrap)
from benchmarking.evaluacion.referencia import predecir
from benchmarking.evaluacion.splits import empresas_test, partir


def _test(y, emp=None, **extra):
    n = len(y)
    d = {"y": y, "empresa_ruc": emp if emp is not None else [f"E{i}" for i in range(n)]}
    d.update(extra)
    return pd.DataFrame(d)


def _caso():
    """Marco HETEROSCEDASTICO: la celda c paga con dispersion sigma_c, de 0,05 a 0,60.

    Dos razones para construirlo asi, y la segunda costo un fallo real:

    1. Las celdas tienen entre 3 y 49 empresas donantes, para que el termino de error de
       estimacion varie.
    2. **La dispersion real varia 12x entre celdas.** Un marco homocedastico —la version
       anterior de este helper— no puede probar la abstencion: si todas las celdas tienen
       la misma varianza, no hay nada que ordenar y cualquier orden puntua igual. Con el
       marco homocedastico el test de AUGRC comparaba dos ordenaciones aleatorias entre si
       y pasaba o fallaba por azar.
    """
    rng = np.random.default_rng(7)
    f_tr, f_ts = [], []
    for c in range(24):
        nivel = rng.normal(0, .4)
        s_c = 0.05 + 0.55 * (c / 23)
        for f in range(3 + 2 * c):
            a = rng.normal(0, .25)
            f_tr += [(f"T{c}_{f}", f"c{c}", nivel + a + rng.normal(0, s_c)) for _ in range(4)]
        for f in range(3):
            a = rng.normal(0, .25)
            f_ts += [(f"S{c}_{f}", f"c{c}", nivel + a + rng.normal(0, s_c)) for _ in range(4)]
    cols = ["empresa_ruc", "celda", "y"]
    tr = pd.DataFrame(f_tr, columns=cols)
    ts = pd.DataFrame(f_ts, columns=cols)
    return tr, ts, predecir(tr, ts, "celda")


# --- error, sesgo, MAE intra --------------------------------------------------

def test_las_abstenciones_no_cuentan_como_error():
    # Si contaran, un metodo que se calla saldria peor que uno que responde mal.
    r = error_y_cobertura(_test([1.0, 2.0, 3.0]), pd.Series([1.1, np.nan, np.nan]))
    assert abs(r["mae"] - 0.1) < 1e-9 and abs(r["cobertura"] - 1 / 3) < 1e-9
    assert r["n_evaluadas"] == 1 and r["n_total"] == 3


def test_el_sesgo_con_signo_detecta_descalibracion():
    # MAE identico, sesgo opuesto: sin esta columna los dos casos son indistinguibles.
    alto = error_y_cobertura(_test([0.0, 0.0]), pd.Series([0.5, 0.5]))
    mixto = error_y_cobertura(_test([0.0, 0.0]), pd.Series([0.5, -0.5]))
    assert abs(alto["mae"] - mixto["mae"]) < 1e-9
    assert abs(alto["sesgo"] + 0.5) < 1e-9 and abs(mixto["sesgo"]) < 1e-9


def test_mae_intra_descuenta_el_efecto_empresa():
    # Los cuatro de E1 fallan por +2 exactamente: es nivel de empresa, no de particion, y
    # ningun metodo puede predecirlo bajo leave-company-out.
    t = _test([2.0] * 4, emp=["E1"] * 4)
    r = error_y_cobertura(t, pd.Series([0.0] * 4))
    assert abs(r["mae"] - 2.0) < 1e-9
    assert r["mae_intra"] < 1e-9, "el desplazamiento comun de la empresa debe descontarse"


def test_mae_intra_conserva_el_error_que_si_es_del_metodo():
    t = _test([1.0, -1.0], emp=["E1", "E1"])
    r = error_y_cobertura(t, pd.Series([0.0, 0.0]))
    assert abs(r["mae_intra"] - 1.0) < 1e-9


def test_cobertura_cero_no_revienta():
    r = error_y_cobertura(_test([1.0, 2.0]), pd.Series([np.nan] * 2))
    assert r["cobertura"] == 0.0 and np.isnan(r["mae"])


# --- CRPS ---------------------------------------------------------------------

def test_crps_se_reduce_al_error_absoluto_cuando_no_hay_incertidumbre():
    # G&R 2007 4.2. Es lo que garantiza que adoptar CRPS no rompe el pre-registro.
    assert abs(float(crps_normal(3.0, 1.0, 1e-8)) - 2.0) < 1e-4


def test_crps_premia_la_anchura_bien_calibrada():
    rng = np.random.default_rng(0)
    y = rng.normal(0, 1.0, 4000)
    bien = crps_normal(y, 0.0, 1.0).mean()
    estrecho = crps_normal(y, 0.0, 0.2).mean()
    ancho = crps_normal(y, 0.0, 5.0).mean()
    assert bien < estrecho and bien < ancho


# --- riesgo generalizado -------------------------------------------------------

def test_el_riesgo_generalizado_usa_denominador_N():
    # EL punto de Traub et al.: quien se abstiene siempre no obtiene riesgo cero, obtiene c.
    t = _test([1.0, 2.0, 3.0, 4.0])
    p = pd.DataFrame({"y_ref_bruto": [np.nan] * 4, "sd_pred": [np.nan] * 4,
                      "n_donantes": [0] * 4, "n_empresas_donantes": [0] * 4,
                      "share_max_empresa": [np.nan] * 4})
    c = curva_coste(t, p, costes=[0.5])
    assert abs(c["riesgo"].iloc[0] - 0.5) < 1e-9 and c["cobertura"].iloc[0] == 0.0


def test_la_curva_de_coste_va_del_silencio_al_MAE_completo():
    # La cobertura SI es monotona: es estructural, subir el coste de callarse solo puede
    # hacer que se hable mas.
    #
    # El riesgo NO es monotono exacto en muestra finita, y conviene saberlo antes de
    # dibujarlo: cuando una fila pasa de abstenerse (paga `c`) a responderse (paga
    # |err|), el riesgo BAJA si esa fila resulta acertar mejor que `c`. En esperanza es
    # creciente; en una realizacion tiene dientes de sierra. Lo garantizado son los
    # extremos — de casi cero (todo callado) al MAE completo (todo respondido).
    _, ts, p = _caso()
    c = curva_coste(ts, p, costes=np.linspace(0.05, 1.5, 12))
    assert c["cobertura"].is_monotonic_increasing
    assert c["riesgo"].iloc[0] < c["riesgo"].iloc[-1]
    assert abs(c["riesgo"].iloc[-1] - c["mae_aceptadas"].iloc[-1]) < 1e-9  # cobertura 1


def test_la_curva_de_riesgo_cubre_el_rango_de_cobertura():
    _, ts, p = _caso()
    c = curva_riesgo(ts, p, n_puntos=21)
    assert c["cobertura"].min() < 0.2 and c["cobertura"].max() > 0.8
    assert c["cobertura"].is_monotonic_increasing


def test_augrc_castiga_ordenar_la_confianza_al_azar():
    # Si la anchura predictiva no ordena los errores, abstenerse no ayuda y el area sube.
    # Este test solo tiene sentido sobre un marco heteroscedastico: ver `_caso`.
    _, ts, p = _caso()
    bueno = augrc(curva_riesgo(ts, p))
    peores = []
    for s in range(5):
        revuelto = p.copy()
        revuelto["sd_pred"] = np.random.default_rng(s).permutation(p["sd_pred"].to_numpy())
        peores.append(augrc(curva_riesgo(ts, revuelto)))
    assert bueno < min(peores), f"bueno={bueno:.4f} revueltos={np.round(peores, 4)}"


# --- subgrupos ------------------------------------------------------------------

def test_por_subgrupo_reporta_error_Y_cobertura():
    # Shah et al. 2022: bajar la cobertura puede empeorar el riesgo de un subgrupo aunque
    # el global mejore. Sin las dos columnas juntas, invisible.
    t = _test([1.0, 2.0, 3.0, 4.0], sexo=["F", "F", "M", "M"])
    r = por_subgrupo(t, pd.Series([1.0, np.nan, 3.5, 4.0]), "sexo", minimo=2)
    f = r.set_index("sexo")
    assert abs(f.loc["F", "cobertura"] - 0.5) < 1e-9
    assert abs(f.loc["M", "cobertura"] - 1.0) < 1e-9
    assert abs(f.loc["F", "mae"] - 0.0) < 1e-9 and abs(f.loc["M", "mae"] - 0.25) < 1e-9


# --- bootstrap pareado -----------------------------------------------------------

def _marco():
    from sintetico import generar
    df = generar(n_empresas=50, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    return partir(df, empresas_test(df, frac=0.25))


def _azar(df, k=3, semilla=5):
    # Inline y no `particiones.aleatoria`: ese modulo es la Tarea 9 y este es la 5. Un
    # test no debe adelantar una dependencia que todavia no existe.
    v = np.random.default_rng(semilla).integers(0, k, len(df)).astype(str)
    return pd.Series(v, index=df.index)


def _particiones(tr, ts):
    return ({"verdadera": tr["rol_verdadero"].astype(str), "azar": _azar(tr)},
            {"verdadera": ts["rol_verdadero"].astype(str), "azar": _azar(ts)})


def test_una_fila_por_replica_y_una_columna_por_metodo():
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    r = replicas_bootstrap(tr, ts, p_tr, p_ts, n=25, semilla=1)
    assert r.shape == (25, 2) and set(r.columns) == {"verdadera", "azar"}


def test_bootstrap_determinista():
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    a = replicas_bootstrap(tr, ts, p_tr, p_ts, n=15, semilla=3)
    b = replicas_bootstrap(tr, ts, p_tr, p_ts, n=15, semilla=3)
    pd.testing.assert_frame_equal(a, b)


def test_la_diferencia_pareada_es_mas_estrecha_que_dos_IC_marginales():
    # EL motivo del cambio. El error esta dominado por el efecto empresa, identico para
    # los dos metodos: se cancela en la diferencia y se paga entero en el contraste
    # marginal. Si esto falla, los numeros aleatorios comunes no se estan aplicando.
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    r = replicas_bootstrap(tr, ts, p_tr, p_ts, n=120, semilla=4)
    d = ic_diferencia(r, "verdadera", "azar")
    ancho_pareado = d["ic_alto"] - d["ic_bajo"]
    ancho_marginal = ((r["azar"].quantile(.975) - r["azar"].quantile(.025)) +
                      (r["verdadera"].quantile(.975) - r["verdadera"].quantile(.025)))
    assert ancho_pareado < ancho_marginal


def test_la_diferencia_detecta_a_la_particion_verdadera():
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    d = ic_diferencia(replicas_bootstrap(tr, ts, p_tr, p_ts, n=120, semilla=6),
                      "verdadera", "azar")
    assert d["dif"] < 0 and d["ic_alto"] < 0, "verdadera - azar: negativa y significativa"


def test_remuestrear_train_ensancha_el_intervalo():
    # El defecto 3b de D-011: tratar mu_c como fija cuando se estima con 3-5 empresas
    # subestima la varianza. La bandera existe para dejarlo demostrado, no para usarla.
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    con = replicas_bootstrap(tr, ts, p_tr, p_ts, n=80, semilla=8, remuestrear_train=True)
    sin = replicas_bootstrap(tr, ts, p_tr, p_ts, n=80, semilla=8, remuestrear_train=False)
    assert con["verdadera"].std() > sin["verdadera"].std()


# --- omega2 -----------------------------------------------------------------------

def test_omega2_premia_la_particion_verdadera():
    from sintetico import generar
    df = generar(n_empresas=30, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    df["azar"] = np.random.default_rng(0).integers(0, 3, len(df)).astype(str)
    assert omega2_intra_empresa(df, "rol_verdadero") > omega2_intra_empresa(df, "azar")


def test_omega2_es_indefinido_con_una_celda_por_persona():
    # k == n deja cero grados de libertad dentro de celda: omega2 NO esta definido, y
    # devolver un numero seria peor que devolver NaN. A esa particion la mata el banco por
    # cobertura (`test_una_celda_por_persona_no_gana`), no omega2.
    from sintetico import generar
    df = generar(n_empresas=20, personas_por_empresa=10)
    df["y"] = np.log(df["sueldo"] / 470)
    assert np.isnan(omega2_intra_empresa(df.assign(cada_uno=df["id_hash"]), "cada_uno"))


def test_omega2_penaliza_partir_de_mas():
    # Con celdas de 2 personas si esta definido, y debe salir peor que la verdad: omega2
    # descuenta los grados de libertad, que es la razon de usarlo y no eta2.
    from sintetico import generar
    df = generar(n_empresas=20, personas_por_empresa=10)
    df["y"] = np.log(df["sueldo"] / 470)
    df["de_dos"] = (np.arange(len(df)) // 2).astype(str)
    assert omega2_intra_empresa(df, "de_dos") < omega2_intra_empresa(df, "rol_verdadero")


def test_el_camino_rapido_del_bootstrap_da_LO_MISMO_que_predecir():
    # Guarda de la optimizacion. `_referencia_np` reimplementa en numpy lo que hace
    # `predecir_desde_votos`, porque en pandas el bootstrap costaba 10 horas. Una
    # optimizacion sin test de equivalencia es una reescritura a ciegas: si diverge,
    # los intervalos de confianza salen de un estimador distinto al que se reporta.
    from benchmarking.evaluacion.metricas import _compilar, _referencia_np
    from benchmarking.evaluacion.referencia import (
        tabla_votos, predecir_desde_votos, aplicar_abstencion)

    tr, ts, _ = _caso()
    votos = tabla_votos(tr, "celda")
    lento = aplicar_abstencion(
        predecir_desde_votos(votos, ts, "celda", loco=False), max_sd=0.9).to_numpy(float)

    c = _compilar(votos, ts, "celda")
    por_celda, _sd = _referencia_np(c, np.arange(len(c["voto"])), 0.9, 3, 0.80)
    rapido = np.where(c["cod_test"] >= 0, por_celda[np.clip(c["cod_test"], 0, c["k"] - 1)],
                      np.nan)

    assert np.allclose(lento, rapido, equal_nan=True, rtol=1e-10, atol=1e-12)
    assert np.isfinite(lento).any(), "el caso no prueba nada si todo son NaN"
