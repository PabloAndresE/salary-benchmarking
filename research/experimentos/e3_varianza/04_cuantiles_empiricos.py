"""Cuantiles empiricos contra banda normal: .cual describe mejor el mercado?

`02` midio que `tau` por celda arregla la parte de la mala calibracion que DEPENDE DEL
CARGO (recorrido entre quintiles 54,7 -> 23,4 puntos, CRPS -8,6%) y deja intacto un sesgo
global: todas las variantes dan bandas demasiado anchas, 66-69% de cobertura donde deberia
haber 50%.

`03` enseno por que, en dolares. `AUXILIAR DE LIMPIEZA` tiene p25=$475, p50=$475,
p75=$485: la mitad de la gente esta en UN SOLO VALOR. Eso no es una campana, es un pico, y
ninguna normal lo describe con ningun ancho. `GERENTE GENERAL` es lo contrario: p05=$500,
p95=$13.712, cola larguisima. El problema no es el ANCHO de la banda, es la FORMA.

POR ESO SE DESCARTA RECALIBRAR EL MULTIPLICADOR. Un `0,6745` ajustado con los datos
arreglaria la media y seguiria fallando en los dos extremos, porque un solo numero no
puede describir un pico y una cola larga a la vez.

LA ALTERNATIVA. Donde hay empresas de sobra, no hace falta modelo: se reportan los
CUANTILES EMPIRICOS de la celda. No supone forma ninguna. Se ponderan por empresa —cada
empresa aporta su peso `w_f` repartido entre su gente— porque si no, una nomina de 400
contadores define el mercado, que es el mismo problema que el voto ya resuelve para el
centro.

Por debajo del umbral se cae al modelo con `tau_c`/`sigma_c`, que es donde el trabajo de
`01` y `02` sigue haciendo falta. Y toda la rama por analogia sigue siendo modelo.

QUE SE MIDE
  - cobertura del 50% y del 80%: el objetivo es 50,0% y 80,0%, ni mas ni menos
  - perdida pinball en q=0,25 y q=0,75: regla de puntuacion PROPIA para cuantiles. Es lo
    correcto aqui porque lo que se entrega SON cuantiles; el CRPS normal no aplica a una
    prediccion empirica.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import pathlib
import sys
from importlib import import_module

import numpy as np
import pandas as pd
from google.cloud import bigquery

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
_c = import_module("02_calibracion_por_celda")     # reutiliza el estimador, no lo copia

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import (_cuantil_por_grupo, componentes_varianza,
                                                sigma2_por_celda)

SEM = 20260805
MIN_EMPRESAS = 3
Z = {0.10: -1.2816, 0.25: -0.6745, 0.75: 0.6745, 0.90: 1.2816}
CUANTILES = (0.10, 0.25, 0.75, 0.90)
UMBRALES_EMP = (10, 20)
CASOS = ["AUXILIAR DE LIMPIEZA", "GUARDIA DE SEGURIDAD", "TRABAJADOR AGRICOLA", "CHOFER",
         "ASISTENTE CONTABLE", "VENDEDOR", "JEFE DE BODEGA", "CONTADOR", "GERENTE GENERAL"]


def cuantiles_empiricos(cod, y, peso, n_celdas, qs):
    """Cuantil ponderado por celda, para varios `q`. Devuelve dict q -> array por celda."""
    o = np.lexsort((y, cod))                    # celda ascendente, y ascendente dentro
    c, v, w = cod[o], y[o], peso[o]
    vis = np.unique(c)
    cc = np.searchsorted(vis, c)
    out = {}
    for q in qs:
        r = np.full(n_celdas, np.nan)
        r[vis] = _cuantil_por_grupo(cc, v, w, len(vis), q=q)
        out[q] = r
    return out


def pinball(y, pred, q):
    d = y - pred
    return float(np.mean(np.maximum(q * d, (q - 1.0) * d)))


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train.empresa_ruc.isin(val)]
    ts = train[train.empresa_ruc.isin(val)]
    print(f"construir {len(tr):,} filas / {tr.empresa_ruc.nunique():,} empresas   "
          f"evaluar {len(ts):,} / {ts.empresa_ruc.nunique():,}")

    celdas = sorted(set(tr.cargo_norm.astype(str)) | set(ts.cargo_norm.astype(str)))
    idx = {c: i for i, c in enumerate(celdas)}
    n_c = len(celdas)
    cod_tr = tr.cargo_norm.astype(str).map(idx).to_numpy()
    cod_ts = ts.cargo_norm.astype(str).map(idx).to_numpy()
    y_tr = pd.to_numeric(tr["y"], errors="coerce").to_numpy(float)
    y_ts = pd.to_numeric(ts["y"], errors="coerce").to_numpy(float)
    ce_tr = pd.factorize(tr.empresa_ruc)[0]

    tau2_g, sigma2_g = componentes_varianza(tr, "cargo_norm")
    s2_serie, _ = sigma2_por_celda(tr, "cargo_norm", sigma2_global=sigma2_g)
    s2c = np.full(n_c, float(sigma2_g))
    for k, v_ in s2_serie.items():
        i = idx.get(str(k))
        if i is not None and np.isfinite(v_):
            s2c[i] = float(v_)
    MSB, _, n0, F_anova, _ = _c.anova_por_celda(cod_tr, ce_tr, y_tr, n_c)
    t2c, _ = _c.tau2_por_celda(MSB, s2c, n0, F_anova, tau2_g)
    print(f"global tau={np.sqrt(tau2_g):.4f} sigma={np.sqrt(sigma2_g):.4f}")

    # centro y pesos, con la variante por celda (la mejor de `02`)
    m, W, F = _c.referencia(cod_tr, ce_tr, y_tr, t2c, s2c, n_c)
    directo = F >= MIN_EMPRESAS

    # peso de cada PERSONA: el de su empresa repartido entre su gente. Sin esto, una
    # nomina de 400 contadores define sola los cuantiles del cargo.
    dpar = pd.DataFrame({"c": cod_tr, "e": ce_tr, "y": y_tr}).dropna(subset=["y"])
    tam = dpar.groupby(["c", "e"])["y"].transform("size").to_numpy(float)
    n_f = dpar.groupby(["c", "e"])["y"].transform("size").to_numpy(float)
    w_emp = 1.0 / (t2c[dpar["c"].to_numpy(int)] + s2c[dpar["c"].to_numpy(int)] / n_f)
    peso_persona = w_emp / tam
    emp_q = cuantiles_empiricos(dpar["c"].to_numpy(int), dpar["y"].to_numpy(float),
                                peso_persona, n_c, CUANTILES)

    # -- variantes --------------------------------------------------------------
    def normal(t2, s2):
        with np.errstate(divide="ignore"):
            sd = np.sqrt(t2 + s2 + np.where(W > 0, 1.0 / np.where(W > 0, W, 1), np.inf))
        return {q: m + Z[q] * sd for q in CUANTILES}

    unos = np.ones(n_c)
    VAR = {"A hoy (normal, glob)": normal(unos * tau2_g, unos * sigma2_g),
           "C normal, tau_c": normal(t2c, s2c)}
    for u in UMBRALES_EMP:
        usa = F >= u
        VAR[f"D empirico F>={u}"] = {q: np.where(usa, emp_q[q], VAR["C normal, tau_c"][q])
                                     for q in CUANTILES}
        print(f"  empirico se usa en {int((usa & directo).sum()):,} celdas "
              f"({float(usa[cod_ts].mean()):.1%} de la gente a evaluar)")

    sel = directo[cod_ts] & np.isfinite(y_ts) & np.isfinite(m[cod_ts])
    cc, yy = cod_ts[sel], y_ts[sel]
    print(f"\nevaluando sobre {sel.sum():,} personas en celdas directas")

    print("\n" + "=" * 82)
    print("CALIBRACION. Objetivo: 50,0% y 80,0%.  Pinball mas bajo es mejor")
    print("=" * 82)
    print(f"  {'variante':<24} {'cob 50%':>8} {'cob 80%':>8} {'pin.25':>8} {'pin.75':>8} "
          f"{'banda':>8}")
    res = {}
    for nom, Q in VAR.items():
        lo, hi = Q[0.25][cc], Q[0.75][cc]
        lo8, hi8 = Q[0.10][cc], Q[0.90][cc]
        res[nom] = dict(cob50=float(((yy >= lo) & (yy <= hi)).mean()),
                        cob80=float(((yy >= lo8) & (yy <= hi8)).mean()),
                        p25=pinball(yy, lo, 0.25), p75=pinball(yy, hi, 0.75),
                        ancho=float(np.mean(np.exp((hi - lo) / 2) - 1)), lo=lo, hi=hi)
        r = res[nom]
        print(f"  {nom:<24} {r['cob50']:>7.1%} {r['cob80']:>7.1%} {r['p25']:>8.4f} "
              f"{r['p75']:>8.4f} {r['ancho']:>7.1%}")

    print("\n" + "=" * 82)
    print("POR QUINTIL DE DISPERSION DEL CARGO")
    print("=" * 82)
    disp = np.sqrt(t2c + s2c)[cc]
    q5 = np.quantile(disp, [0, .2, .4, .6, .8, 1.0])
    print(f"  {'quintil':<9} {'personas':>9}   " + "  ".join(f"{n[:14]:>14}" for n in VAR))
    for k in range(5):
        selq = ((disp >= q5[k]) & (disp <= q5[k + 1]) if k == 4
                else (disp >= q5[k]) & (disp < q5[k + 1]))
        cols = [f"{float(((yy[selq] >= r['lo'][selq]) & (yy[selq] <= r['hi'][selq])).mean()):>14.1%}"
                for r in res.values()]
        print(f"  Q{k+1:<8} {int(selq.sum()):>9,}   " + "  ".join(cols))

    print("\n" + "=" * 82)
    print("CARGOS CONCRETOS: cobertura del 50% central")
    print("=" * 82)
    print(f"  {'cargo':<24} {'pers':>6} {'F':>5}   " + "  ".join(f"{n[:14]:>14}" for n in VAR))
    for cg in CASOS:
        i = idx.get(cg)
        if i is None:
            continue
        selc = cc == i
        if selc.sum() < 30:
            continue
        cols = [f"{float(((yy[selc] >= r['lo'][selc]) & (yy[selc] <= r['hi'][selc])).mean()):>14.1%}"
                for r in res.values()]
        print(f"  {cg[:23]:<24} {int(selc.sum()):>6} {int(F[i]):>5}   " + "  ".join(cols))

    print("\n" + "=" * 82)
    print("LA BANDA EN DOLARES (SBU 2025), cargos concretos")
    print("=" * 82)
    sbu = float(s.get_sbu(2025))
    for cg in CASOS:
        i = idx.get(cg)
        if i is None or F[i] < MIN_EMPRESAS:
            continue
        real_lo = np.quantile(y_ts[cod_ts == i], 0.25) if (cod_ts == i).sum() > 30 else np.nan
        real_hi = np.quantile(y_ts[cod_ts == i], 0.75) if (cod_ts == i).sum() > 30 else np.nan
        print(f"\n  {cg}")
        if np.isfinite(real_lo):
            print(f"    {'REAL (evaluacion)':<24} ${np.exp(real_lo)*sbu:>8,.0f} — "
                  f"${np.exp(real_hi)*sbu:>8,.0f}")
        for nom, Q in VAR.items():
            print(f"    {nom:<24} ${np.exp(Q[0.25][i])*sbu:>8,.0f} — "
                  f"${np.exp(Q[0.75][i])*sbu:>8,.0f}")


if __name__ == "__main__":
    main()
