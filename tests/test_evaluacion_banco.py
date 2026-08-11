"""Prueba de aceptacion: el banco debe ordenar bien particiones de calidad conocida,
y debe declarar cuanta degradacion es capaz de detectar.

Un instrumento que nadie verifico no sirve para verificar nada. **Si algun test falla
aqui, esta mal el BANCO (Tareas 3-9), no el test.**
"""
import numpy as np
import pandas as pd
import pytest
from sintetico import generar
from benchmarking.evaluacion.metricas import (
    error_y_cobertura, ic_diferencia, replicas_bootstrap)
from benchmarking.evaluacion.particiones import aleatoria, oraculo_salarial
from benchmarking.evaluacion.referencia import aplicar_abstencion, predecir
from benchmarking.evaluacion.splits import empresas_test, partir


@pytest.fixture(scope="module")
def marco():
    df = generar(n_empresas=60, personas_por_empresa=20, n_roles=3)
    df["y"] = np.log(df["sueldo"] / 470)
    return df


def _r(df, col):
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    return error_y_cobertura(ts, aplicar_abstencion(predecir(tr, ts, col)))


def _degradar(serie, x, semilla=0):
    """Reasigna al azar una fraccion x de las etiquetas, conservando el reparto."""
    rng = np.random.default_rng(semilla)
    v = serie.astype(str).to_numpy().copy()
    n = int(round(x * len(v)))
    if n:
        i = rng.choice(len(v), n, replace=False)
        v[i] = rng.permutation(v[i])
    return pd.Series(v, index=serie.index)


# --- ordena bien lo que ya sabemos ordenar -----------------------------------

def test_la_particion_verdadera_gana_a_la_aleatoria(marco):
    m = marco.assign(azar=aleatoria(marco, k=3))
    assert _r(m, "rol_verdadero")["mae"] < _r(m, "azar")["mae"]


def test_la_particion_deliberadamente_mala_pierde(marco):
    m = marco.assign(tonta=marco["id_hash"].str[-1])
    assert _r(m, "rol_verdadero")["mae"] < _r(m, "tonta")["mae"]


def test_una_celda_por_persona_no_gana(marco):
    # La trampa que hundio a la Balanza 1: partir de mas debe COSTAR.
    assert _r(marco.assign(cada_uno=marco["id_hash"]), "cada_uno")["cobertura"] == 0.0


def test_la_abstencion_cuenta_en_cobertura_y_no_en_error(marco):
    r = _r(marco, "rol_verdadero")
    assert 0.0 < r["cobertura"] <= 1.0 and not np.isnan(r["mae"])


def test_una_empresa_dominante_no_secuestra_la_referencia():
    # Correccion 1 de D-009 extremo a extremo, ahora con pesos inverso-varianza: una
    # empresa con mucha mas gente y nivel salarial atipico no mueve la referencia del
    # resto.
    df = generar(n_empresas=30, personas_por_empresa=10, desiguales=True)
    df["y"] = np.log(df["sueldo"] / 470)
    grande = df["empresa_ruc"].value_counts().idxmax()
    df.loc[df["empresa_ruc"] == grande, "y"] += 3.0
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    ts = ts[ts["empresa_ruc"] != grande]
    r = error_y_cobertura(ts, aplicar_abstencion(predecir(tr, ts, "rol_verdadero")))
    assert r["mae"] < 0.6, "la empresa atipica no debe arrastrar la referencia del resto"


def test_la_escalera_queda_en_el_orden_esperado(marco):
    # aleatoria > verdadera > oraculo. El ORACULO GANA, y eso es correcto: agrupa por la
    # propia `y` de la persona, y nada puede ganarle a una particion construida desde el
    # objetivo. Por eso es bandera roja y no rival — si el arquetipo se le acerca, derivo
    # a bandas salariales.
    tr, ts = partir(marco, empresas_test(marco, frac=0.25))

    def mae(col_tr, col_ts):
        t = tr.assign(_c=col_tr.astype(str).to_numpy())
        s = ts.assign(_c=col_ts.astype(str).to_numpy())
        return error_y_cobertura(s, aplicar_abstencion(predecir(t, s, "_c")))["mae"]

    azar = mae(aleatoria(tr, 3), aleatoria(ts, 3))
    verdadera = mae(tr["rol_verdadero"], ts["rol_verdadero"])
    oraculo = mae(oraculo_salarial(tr, tr, 3), oraculo_salarial(tr, ts, 3))
    assert oraculo < verdadera < azar, f"{oraculo:.4f} / {verdadera:.4f} / {azar:.4f}"


def test_el_oraculo_rompe_la_cota_teorica_y_la_particion_verdadera_no(marco):
    # Con el efecto empresa inobservable bajo leave-company-out, Var(error) >=
    # eta2_empresa * Var(y) para CUALQUIER metodo legitimo: en sd, el mejor posible llega
    # a raiz(eta2) veces el MAE aleatorio. Que el oraculo baje de ahi es la prueba formal
    # de que ve lo que no debe, y que la verdadera se quede por encima es la prueba de que
    # el banco no esta midiendo circularidad.
    tr, ts = partir(marco, empresas_test(marco, frac=0.25))
    y = np.log(marco["sueldo"])
    g = marco.assign(_y=y).groupby("empresa_ruc")["_y"].agg(["mean", "size"])
    eta2 = float((g["size"] * (g["mean"] - y.mean()) ** 2).sum() / ((y - y.mean()) ** 2).sum())

    def mae(col_tr, col_ts):
        t = tr.assign(_c=col_tr.astype(str).to_numpy())
        s = ts.assign(_c=col_ts.astype(str).to_numpy())
        return error_y_cobertura(s, aplicar_abstencion(predecir(t, s, "_c")))["mae"]

    azar = mae(aleatoria(tr, 3), aleatoria(ts, 3))
    cota = np.sqrt(eta2) * azar
    assert mae(tr["rol_verdadero"], ts["rol_verdadero"]) > cota, "cota violada sin trampa"
    assert mae(oraculo_salarial(tr, tr, 3), oraculo_salarial(tr, ts, 3)) < cota


# --- magnitud minima detectable ----------------------------------------------

def test_el_error_responde_de_forma_monotona_a_la_degradacion(marco):
    # Si el banco no distingue 0% de 50% de ruido, no distingue nada.
    maes = [_r(marco.assign(deg=_degradar(marco["rol_verdadero"], x)), "deg")["mae"]
            for x in (0.0, 0.10, 0.25, 0.50)]
    assert all(b >= a - 1e-9 for a, b in zip(maes, maes[1:])), maes
    assert maes[-1] > maes[0] * 1.05


def test_declara_su_magnitud_minima_detectable(marco, capsys):
    # ESTE test es el que se cita en el pre-registro. Fija la sensibilidad del
    # instrumento: a partir de que degradacion el IC pareado separa del cero. Un criterio
    # sin MDE no es un criterio — si el banco no distingue el 20% de ruido, un empate no
    # significa "iguales", significa "no medible".
    #
    # Se promedia sobre TRES semillas de degradacion. Con una sola, la degradacion
    # realizada es tan variable que el resultado sale no monotono —medido: 5% no, 10% si,
    # 20% no— y un MDE no monotono no se puede escribir en un pre-registro.
    tr, ts = partir(marco, empresas_test(marco, frac=0.25))
    filas = []
    for x in (0.0, 0.10, 0.25, 0.50):
        difs, detecta = [], 0
        for s in (1, 2, 3):
            p_tr = {"buena": tr["rol_verdadero"].astype(str),
                    "degradada": _degradar(tr["rol_verdadero"], x, semilla=s)}
            p_ts = {"buena": ts["rol_verdadero"].astype(str),
                    "degradada": _degradar(ts["rol_verdadero"], x, semilla=s)}
            d = ic_diferencia(replicas_bootstrap(tr, ts, p_tr, p_ts, n=60, semilla=2),
                              "buena", "degradada")
            difs.append(d["dif"])
            detecta += int(d["ic_alto"] < 0)
        filas.append((x, float(np.mean(difs)), detecta))

    with capsys.disabled():
        print("\n  MDE (degradacion, dif media, veces detectada de 3):")
        for x, dif, det in filas:
            print(f"    {x:>5.0%}  {dif:+.4f}  {det}/3")

    sin_ruido = filas[0]
    assert sin_ruido[2] == 0, "detecta diferencia donde no la hay: falso positivo"
    difs = [d for _, d, _ in filas]
    assert all(b <= a + 1e-3 for a, b in zip(difs, difs[1:])), f"no monotono: {difs}"
    assert filas[-1][2] == 3, f"no detecta un 50% de ruido: {filas}"
