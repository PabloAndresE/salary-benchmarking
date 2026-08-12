import numpy as np
import pandas as pd
from benchmarking.evaluacion.estabilidad import ari_submuestras, retest_entre_anios


def _panel(filas):
    return pd.DataFrame(filas, columns=["id_hash", "anio_valoracion", "celda"])


# --- test-retest ---------------------------------------------------------------

def test_retest_perfecto_da_uno():
    # 478.522 personas aparecen en 2024 y 2025: dos mediciones REALES de la misma
    # persona, mas fuertes que cualquier ARI de bootstrap simulado.
    r = retest_entre_anios(_panel([("a", 2024, "x"), ("a", 2025, "x"),
                            ("b", 2024, "y"), ("b", 2025, "y")]), "celda")
    assert r["n_personas_repetidas"] == 2 and r["acuerdo"] == 1.0


def test_retest_detecta_desacuerdo():
    r = retest_entre_anios(_panel([("a", 2024, "x"), ("a", 2025, "z"),
                            ("b", 2024, "y"), ("b", 2025, "y")]), "celda")
    assert r["acuerdo"] == 0.5


def test_retest_ignora_a_quien_solo_aparece_una_vez():
    r = retest_entre_anios(_panel([("a", 2024, "x"), ("a", 2025, "x"), ("c", 2025, "q")]),
                    "celda")
    assert r["n_personas_repetidas"] == 1


def test_kappa_descuenta_el_acuerdo_por_azar():
    # Con una sola celda TODOS coinciden y el acuerdo crudo vale 1, pero la particion no
    # informa nada. Kappa lo delata. Importa: con k=50 sobre celdas desiguales, coincidir
    # es facil sin que la particion sea estable.
    todos_iguales = _panel([(f"p{i}", a, "unica") for i in range(50) for a in (2024, 2025)])
    r = retest_entre_anios(todos_iguales, "celda")
    assert r["acuerdo"] == 1.0 and np.isnan(r["kappa"])


def test_kappa_es_menor_que_el_acuerdo_cuando_hay_celdas_desiguales():
    rng = np.random.default_rng(0)
    filas = []
    for i in range(400):
        # 80% cae en la celda grande: coincidir por azar es muy probable
        c1 = "grande" if rng.random() < 0.8 else f"chica{rng.integers(5)}"
        c2 = c1 if rng.random() < 0.7 else ("grande" if rng.random() < 0.8
                                            else f"chica{rng.integers(5)}")
        filas += [(f"p{i}", 2024, c1), (f"p{i}", 2025, c2)]
    r = retest_entre_anios(_panel(filas), "celda")
    assert r["kappa"] < r["acuerdo"] - 0.1


# --- ARI entre submuestras -----------------------------------------------------

def test_ari_alto_para_un_asignador_estable():
    from sintetico import generar
    df = generar(n_empresas=40, personas_por_empresa=10)
    assert ari_submuestras(df, lambda d: d["rol_verdadero"], n=5)["ari_medio"] > 0.95


def test_ari_bajo_para_un_asignador_aleatorio():
    from sintetico import generar
    df = generar(n_empresas=40, personas_por_empresa=10)
    c = {"i": 0}

    def inestable(d):
        c["i"] += 1
        return pd.Series(
            np.random.default_rng(c["i"]).integers(0, 3, len(d)).astype(str), index=d.index)

    assert ari_submuestras(df, inestable, n=5)["ari_medio"] < 0.2


def test_ari_remuestrea_empresas_no_filas():
    # Si remuestreara filas, dos submuestras compartirian companeros de la misma empresa
    # y el ARI saldria alto por parentesco, no por estructura.
    from sintetico import generar
    df = generar(n_empresas=30, personas_por_empresa=10)
    vistas = []

    def espia(d):
        vistas.append(set(d["empresa_ruc"]))
        return d["rol_verdadero"]

    ari_submuestras(df, espia, n=2, frac=0.5)
    assert all(len(v) <= 16 for v in vistas), "cada submuestra debe traer media empresa"
    assert all(len(v) >= 10 for v in vistas)


def test_ari_reporta_cuantas_comparaciones_hizo():
    from sintetico import generar
    df = generar(n_empresas=20, personas_por_empresa=8)
    r = ari_submuestras(df, lambda d: d["rol_verdadero"], n=7)
    assert r["n_comparaciones"] == 7 and r["ari_min"] <= r["ari_medio"]


def test_ari_determinista():
    from sintetico import generar
    df = generar(n_empresas=20, personas_por_empresa=8)
    a = ari_submuestras(df, lambda d: d["rol_verdadero"], n=4, semilla=3)
    b = ari_submuestras(df, lambda d: d["rol_verdadero"], n=4, semilla=3)
    assert a == b
