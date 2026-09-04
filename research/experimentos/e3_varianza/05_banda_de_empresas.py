"""La banda habla de EMPRESAS. Con esa definicion, .cual es el mejor estimador y umbral?

DECISION DE PRODUCTO tomada tras `04`: la banda dice *"la mitad de las EMPRESAS paga entre
X e Y"*, no *"la mitad de las PERSONAS cobra entre X e Y"*. Es la definicion coherente con
el centro, que ya es la mediana de los votos por empresa, y es la pregunta que le importa
a un cliente que decide su politica salarial.

ESO CAMBIA DOS COSAS, Y LA SEGUNDA NO ES COSMETICA.

  1. LA EVALUACION. Se mide contra empresas apartadas, no contra personas. Antes, una
     cadena con 400 vendedores metia 400 observaciones y definia sola el resultado del
     cargo; eso es lo que hacia fallar a `VENDEDOR` en `04`.

  2. `sigma` SALE DE LA BANDA. El nivel de una empresa es `mu + u_f`, con varianza `tau^2`.
     `sigma^2` es la dispersion DENTRO de la empresa: separa a dos contadores de la misma
     nomina, no mueve el nivel de la empresa. Meterla ensancha la banda por una variacion
     que la pregunta no incluye. La banda de empresas es `tau_c^2 + 1/W`, sin `sigma^2`.

QUE SE COMPARA
  A  hoy:          normal, tau y sigma GLOBALES              (lo que entrega el producto)
  B  tau_c:        normal, tau por celda y SIN sigma
  D5..D20         cuantiles empiricos de los VOTOS por empresa, ponderados por w_f,
                   con distintos umbrales de empresas; por debajo del umbral cae a B

METRICA QUE DECIDE: pinball en q=0,25 y q=0,75 sobre los votos de las empresas apartadas.
Regla de puntuacion propia para cuantiles, que es lo que se entrega.

UN CUIDADO AL LEER LA COBERTURA. El voto observado de una empresa apartada trae su propio
ruido `sigma^2/n_f`: una empresa con un solo contador "vota" el sueldo de esa persona. La
banda predice el NIVEL de la empresa, no su voto ruidoso, asi que se reporta tambien
restringiendo a empresas con 3+ personas en el cargo, donde el voto ya es buen proxy.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import pathlib
import sys
from importlib import import_module

import numpy as np
import pandas as pd
from google.cloud import bigquery

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
_c = import_module("02_calibracion_por_celda")

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import (_cuantil_por_grupo, componentes_varianza,
                                                sigma2_por_celda)

SEM = 20260805
MIN_EMPRESAS = 3
Z = {0.10: -1.2816, 0.25: -0.6745, 0.75: 0.6745, 0.90: 1.2816}
CUANTILES = (0.10, 0.25, 0.75, 0.90)
UMBRALES = (5, 10, 15, 20, 30)
CASOS = ["AUXILIAR DE LIMPIEZA", "GUARDIA DE SEGURIDAD", "TRABAJADOR AGRICOLA", "CHOFER",
         "ASISTENTE CONTABLE", "VENDEDOR", "JEFE DE BODEGA", "CONTADOR", "GERENTE GENERAL"]


def votos(df, cod, tau2_c, sigma2_c):
    """Un voto por (celda, empresa): mediana, tamano y peso inverso-varianza."""
    d = pd.DataFrame({"c": cod, "e": df.empresa_ruc.to_numpy(),
                      "y": pd.to_numeric(df["y"], errors="coerce").to_numpy(float)})
    v = d.dropna(subset=["y"]).groupby(["c", "e"], sort=False)["y"] \
         .agg(voto="median", n="size").reset_index()
    c = v["c"].to_numpy(int)
    v["w"] = 1.0 / (tau2_c[c] + sigma2_c[c] / v["n"].to_numpy(float))
    return v


def cuantiles_de_votos(v, n_celdas, qs):
    """Cuantil ponderado de los VOTOS de cada celda. Una empresa, una observacion."""
    v = v.sort_values(["c", "voto"], kind="mergesort")
    c = v["c"].to_numpy(int)
    val = v["voto"].to_numpy(float)
    w = v["w"].to_numpy(float)
    vis = np.unique(c)
    cc = np.searchsorted(vis, c)
    out = {}
    for q in qs:
        r = np.full(n_celdas, np.nan)
        r[vis] = _cuantil_por_grupo(cc, val, w, len(vis), q=q)
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

    celdas = sorted(set(tr.cargo_norm.astype(str)) | set(ts.cargo_norm.astype(str)))
    idx = {c: i for i, c in enumerate(celdas)}
    n_c = len(celdas)
    cod_tr = tr.cargo_norm.astype(str).map(idx).to_numpy()
    cod_ts = ts.cargo_norm.astype(str).map(idx).to_numpy()
    y_tr = pd.to_numeric(tr["y"], errors="coerce").to_numpy(float)
    ce_tr = pd.factorize(tr.empresa_ruc)[0]

    tau2_g, sigma2_g = componentes_varianza(tr, "cargo_norm")
    s2_serie, _ = sigma2_por_celda(tr, "cargo_norm", sigma2_global=sigma2_g)
    s2c = np.full(n_c, float(sigma2_g))
    for k, v_ in s2_serie.items():
        i = idx.get(str(k))
        if i is not None and np.isfinite(v_):
            s2c[i] = float(v_)
    MSB, _, n0, F_an, _ = _c.anova_por_celda(cod_tr, ce_tr, y_tr, n_c)
    t2c, _ = _c.tau2_por_celda(MSB, s2c, n0, F_an, tau2_g)
    print(f"global tau={np.sqrt(tau2_g):.4f} sigma={np.sqrt(sigma2_g):.4f}")

    v_tr = votos(tr, cod_tr, t2c, s2c)
    m, W, F = _c.referencia(cod_tr, ce_tr, y_tr, t2c, s2c, n_c)
    emp_q = cuantiles_de_votos(v_tr, n_c, CUANTILES)

    # -- lo que se evalua: los votos de las empresas APARTADAS -----------------
    v_ts = votos(ts, cod_ts, t2c, s2c)
    v_ts = v_ts[(F[v_ts["c"].to_numpy(int)] >= MIN_EMPRESAS)
                & np.isfinite(m[v_ts["c"].to_numpy(int)])]
    cc = v_ts["c"].to_numpy(int)
    yy = v_ts["voto"].to_numpy(float)
    nn = v_ts["n"].to_numpy(float)
    print(f"evaluando {len(v_ts):,} votos de empresa en {len(np.unique(cc)):,} celdas "
          f"({int((nn >= 3).sum()):,} con 3+ personas)")

    def normal(t2, s2):
        with np.errstate(divide="ignore"):
            sd = np.sqrt(t2 + s2 + np.where(W > 0, 1.0 / np.where(W > 0, W, 1), np.inf))
        return {q: m + Z[q] * sd for q in CUANTILES}

    unos = np.ones(n_c)
    VAR = {"A hoy (norm, glob, +sig)": normal(unos * tau2_g, unos * sigma2_g),
           "B norm, tau_c, sin sigma": normal(t2c, np.zeros(n_c))}
    B = VAR["B norm, tau_c, sin sigma"]
    for u in UMBRALES:
        usa = F >= u
        VAR[f"D empirico F>={u}"] = {q: np.where(usa, emp_q[q], B[q]) for q in CUANTILES}

    print("\n" + "=" * 88)
    print("SOBRE VOTOS DE EMPRESA. Objetivo cobertura 50,0% y 80,0%; pinball menor mejor")
    print("=" * 88)
    print(f"  {'variante':<26} {'cob50':>7} {'cob80':>7} {'pin.25':>8} {'pin.75':>8} "
          f"{'pin.med':>8} {'cob50 n>=3':>11} {'% celdas':>9}")
    res, mejor = {}, None
    for nom, Q in VAR.items():
        lo, hi = Q[0.25][cc], Q[0.75][cc]
        lo8, hi8 = Q[0.10][cc], Q[0.90][cc]
        dentro = (yy >= lo) & (yy <= hi)
        p25, p75 = pinball(yy, lo, 0.25), pinball(yy, hi, 0.75)
        u = nom.split(">=")[-1] if ">=" in nom else None
        cob_lim = float(dentro[nn >= 3].mean()) if (nn >= 3).any() else float("nan")
        pct = (float((F >= int(u))[cc].mean()) if u else 0.0)
        res[nom] = dict(lo=lo, hi=hi, dentro=dentro, pin=(p25 + p75) / 2)
        print(f"  {nom:<26} {dentro.mean():>6.1%} "
              f"{float(((yy >= lo8) & (yy <= hi8)).mean()):>6.1%} {p25:>8.4f} {p75:>8.4f} "
              f"{(p25+p75)/2:>8.4f} {cob_lim:>10.1%} {pct:>8.1%}")
        if mejor is None or (p25 + p75) / 2 < res[mejor]["pin"]:
            mejor = nom
    print(f"\n  MEJOR PINBALL: {mejor}")

    print("\n" + "=" * 88)
    print("POR QUINTIL DE DISPERSION DEL CARGO")
    print("=" * 88)
    disp = np.sqrt(t2c)[cc]
    q5 = np.quantile(disp, [0, .2, .4, .6, .8, 1.0])
    print(f"  {'quintil':<9} {'votos':>8}   " + "  ".join(f"{n[:16]:>16}" for n in VAR))
    for k in range(5):
        sq = ((disp >= q5[k]) & (disp <= q5[k + 1]) if k == 4
              else (disp >= q5[k]) & (disp < q5[k + 1]))
        print(f"  Q{k+1:<8} {int(sq.sum()):>8,}   "
              + "  ".join(f"{float(r['dentro'][sq].mean()):>16.1%}" for r in res.values()))

    print("\n" + "=" * 88)
    print("CARGOS CONCRETOS: cobertura, y la banda en dolares (SBU 2025)")
    print("=" * 88)
    sbu = float(s.get_sbu(2025))
    for cg in CASOS:
        i = idx.get(cg)
        if i is None:
            continue
        sc = cc == i
        if sc.sum() < 20:
            continue
        print(f"\n  {cg}   ({int(sc.sum())} empresas apartadas, {int(F[i])} en la base)")
        print(f"    {'REAL (votos apartados)':<26} ${np.exp(np.quantile(yy[sc],.25))*sbu:>8,.0f}"
              f" — ${np.exp(np.quantile(yy[sc],.75))*sbu:>8,.0f}")
        for nom, Q in VAR.items():
            if ">=" in nom and nom != f"D empirico F>={UMBRALES[1]}":
                continue
            print(f"    {nom:<26} ${np.exp(Q[0.25][i])*sbu:>8,.0f} — "
                  f"${np.exp(Q[0.75][i])*sbu:>8,.0f}   cobertura "
                  f"{float(res[nom]['dentro'][sc].mean()):>6.1%}")


if __name__ == "__main__":
    main()
