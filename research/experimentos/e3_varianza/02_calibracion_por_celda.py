""".Contiene la banda p25-p75 al 50% de la gente? Con tau y sigma globales, y por celda.

`01` midio que `tau` varia 8x entre cargos y que la variacion es REAL (test-retest entre
mitades de empresas: r = 0,78). Eso demuestra que el PARAMETRO no es constante. No
demuestra que usarlo por celda MEJORE nada: son dos afirmaciones distintas y esta es la
segunda.

LA PRUEBA QUE DECIDE ES LA CALIBRACION, no el error. La banda que se le entrega al
cliente es el intervalo intercuartil: por definicion deberia contener al 50% de la gente
de ese puesto. Si `tau` varia 8x y se usa uno solo, es IMPOSIBLE que la banda este
calibrada a la vez para gerentes y para auxiliares — una de las dos tiene que estar mal.
Aqui se mide cual, y cuanto.

Se mide ademas el CRPS, que es una regla de puntuacion PROPIA: premia a la vez acertar el
centro y declarar bien la incertidumbre, y no se puede mejorar exagerando el intervalo.
El MAE se reporta pero no decide nada aqui: el centro casi no cambia entre variantes.

TRES VARIANTES

  A. tau global,  sigma global    <- lo que hace el producto hoy
  B. tau global,  sigma por celda <- lo que ya midio D-011 Enmienda 1, a medio aplicar
  C. tau por celda, sigma por celda

El encogimiento de `tau` copia el de `sigma2_por_celda`, sin parametros libres: se encoge
`log tau2_c` hacia el global con peso `V/(V + 2/df)`. La df efectiva es `F-1` porque bajo
el modelo el cuadrado medio ENTRE empresas se distribuye como chi2 con `F-1` grados, igual
que el de dentro. Es una aproximacion —`tau2` es una DIFERENCIA de cuadrados medios, no un
cuadrado medio— y por eso se exige un minimo de empresas antes de estimar nada.

SOLO SOBRE CELDAS DIRECTAS (>=3 empresas). La rama por analogia anade el castigo de
distancia semantica, que es otra historia y contaminaria la lectura.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.metricas import crps_normal
from benchmarking.evaluacion.referencia import (_cuantil_por_grupo, componentes_varianza,
                                                sigma2_por_celda)

SEM = 20260805
MIN_EMPRESAS = 3
MIN_F_TAU = 8              # por debajo, `tau_c` es ruido y se usa el global
Z50, Z80 = 0.6745, 1.2816
CASOS = ["AUXILIAR DE LIMPIEZA", "GUARDIA DE SEGURIDAD", "TRABAJADOR AGRICOLA", "CHOFER",
         "ASISTENTE CONTABLE", "VENDEDOR", "JEFE DE BODEGA", "CONTADOR", "GERENTE GENERAL"]


def anova_por_celda(cod_celda, cod_emp, y, n_celdas):
    """(MSB, sigma2, n0, F, N) por celda. Los ingredientes del ANOVA de un factor."""
    par = cod_celda.astype(np.int64) * (cod_emp.max() + 1) + cod_emp
    uni, pcod = np.unique(par, return_inverse=True)
    n_f = np.bincount(pcod)
    s_f = np.bincount(pcod, weights=y)
    q_f = np.bincount(pcod, weights=y * y)
    cel = (uni // (cod_emp.max() + 1)).astype(np.int64)

    SSW = np.bincount(cel, weights=q_f - s_f ** 2 / n_f, minlength=n_celdas)
    N = np.bincount(cel, weights=n_f.astype(float), minlength=n_celdas)
    F = np.bincount(cel, minlength=n_celdas).astype(float)
    S = np.bincount(cel, weights=s_f, minlength=n_celdas)
    Q = np.bincount(cel, weights=s_f ** 2 / n_f, minlength=n_celdas)
    N2 = np.bincount(cel, weights=n_f ** 2.0, minlength=n_celdas)
    with np.errstate(invalid="ignore", divide="ignore"):
        MSB = np.where(F > 1, (Q - S ** 2 / N) / (F - 1), np.nan)
        sigma2 = np.where(N > F, SSW / (N - F), np.nan)
        n0 = np.where(F > 1, (N - N2 / N) / (F - 1), np.nan)
    return MSB, sigma2, n0, F, N


def tau2_por_celda(MSB, sigma2_c, n0, F, tau2_global, min_f=MIN_F_TAU):
    """`tau2_c` encogido hacia el global. Mismo empirical Bayes que `sigma2_por_celda`.

    Se estima solo donde hay `min_f` empresas o mas; el resto se queda en el global. Los
    ceros por truncamiento (`MSB < sigma2`, que pasa por ruido cuando la dispersion real
    es baja) se llevan al percentil 1 de los positivos antes de tomar logaritmos: un cero
    exacto no tiene logaritmo y descartarlos sesgaria la muestra hacia arriba.
    """
    out = np.full(len(F), float(tau2_global))
    with np.errstate(invalid="ignore", divide="ignore"):
        crudo = np.where(n0 > 0, (MSB - sigma2_c) / n0, np.nan)
    ok = (F >= min_f) & np.isfinite(crudo) & np.isfinite(sigma2_c)
    if ok.sum() < 3:
        return out, ok
    pos = crudo[ok & (crudo > 0)]
    if len(pos) < 3:
        return out, ok
    piso = float(np.quantile(pos, 0.01))
    v = np.maximum(crudo[ok], piso)

    L = np.log(v)
    var_muestreo = 2.0 / (F[ok] - 1.0)
    V = max(0.0, float(L.var(ddof=1)) - float(var_muestreo.mean()))
    w = V / (V + var_muestreo) if V > 0 else np.zeros_like(var_muestreo)
    out[ok] = np.exp(w * L + (1.0 - w) * float(L.mean()))
    return out, ok


def referencia(cod_tr, emp_tr, y_tr, tau2_c, sigma2_c, n_celdas):
    """(m, W, n_emp) por celda con los pesos inverso-varianza de esa variante."""
    d = pd.DataFrame({"c": cod_tr, "e": emp_tr, "y": y_tr}).dropna(subset=["y"])
    v = d.groupby(["c", "e"], sort=False)["y"].agg(voto="median", n="size").reset_index()
    c = v["c"].to_numpy(int)
    v["w"] = 1.0 / (tau2_c[c] + sigma2_c[c] / v["n"].to_numpy(float))
    v = v.sort_values(["c", "voto"], kind="mergesort")
    c = v["c"].to_numpy(int)
    m = np.full(n_celdas, np.nan)
    vis = np.unique(c)
    m[vis] = _cuantil_por_grupo(np.searchsorted(vis, c), v["voto"].to_numpy(float),
                                v["w"].to_numpy(float), len(vis))
    W = np.bincount(c, weights=v["w"].to_numpy(float), minlength=n_celdas)
    F = np.bincount(c, minlength=n_celdas).astype(float)
    return m, W, F


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
    print(f"construir: {len(tr):,} filas / {tr.empresa_ruc.nunique():,} empresas")
    print(f"evaluar:   {len(ts):,} filas / {ts.empresa_ruc.nunique():,} empresas")

    celdas = sorted(set(tr.cargo_norm.astype(str)) | set(ts.cargo_norm.astype(str)))
    idx = {c: i for i, c in enumerate(celdas)}
    n_c = len(celdas)
    cod_tr = tr.cargo_norm.astype(str).map(idx).to_numpy()
    cod_ts = ts.cargo_norm.astype(str).map(idx).to_numpy()
    y_tr = pd.to_numeric(tr["y"], errors="coerce").to_numpy(float)
    y_ts = pd.to_numeric(ts["y"], errors="coerce").to_numpy(float)
    ce_tr = pd.factorize(tr.empresa_ruc)[0]

    tau2_g, sigma2_g = componentes_varianza(tr, "cargo_norm")
    print(f"\nglobal: tau={np.sqrt(tau2_g):.4f}  sigma={np.sqrt(sigma2_g):.4f}")

    s2_serie, _ = sigma2_por_celda(tr, "cargo_norm", sigma2_global=sigma2_g)
    s2c = np.full(n_c, float(sigma2_g))
    for k, val_ in s2_serie.items():
        i = idx.get(str(k))
        if i is not None and np.isfinite(val_):
            s2c[i] = float(val_)

    MSB, sig_anova, n0, F, N = anova_por_celda(cod_tr, ce_tr, y_tr, n_c)
    t2c, estimadas = tau2_por_celda(MSB, s2c, n0, F, tau2_g)
    print(f"tau por celda estimado en {int(estimadas.sum()):,} celdas de {n_c:,} "
          f"(>= {MIN_F_TAU} empresas)")
    with np.errstate(invalid="ignore"):
        tt = np.sqrt(t2c[estimadas])
    print(f"  tau_c encogido: p05={np.nanquantile(tt,.05):.3f} "
          f"p50={np.nanquantile(tt,.50):.3f} p95={np.nanquantile(tt,.95):.3f}")

    unos = np.ones(n_c)
    VAR = {"A hoy (tau glob, sig glob)": (unos * tau2_g, unos * sigma2_g),
           "B (tau glob, sig celda)":    (unos * tau2_g, s2c),
           "C (tau celda, sig celda)":   (t2c, s2c)}

    filas = {}
    for nom, (t2, s2) in VAR.items():
        m, W, Femp = referencia(cod_tr, ce_tr, y_tr, t2, s2, n_c)
        directo = Femp >= MIN_EMPRESAS
        sel = directo[cod_ts] & np.isfinite(y_ts) & np.isfinite(m[cod_ts])
        c = cod_ts[sel]
        mu, yy = m[c], y_ts[sel]
        with np.errstate(divide="ignore"):
            sd = np.sqrt(t2[c] + s2[c] + 1.0 / W[c])
        e = np.abs(yy - mu)
        filas[nom] = dict(
            n=int(sel.sum()),
            cob50=float((e <= Z50 * sd).mean()),
            cob80=float((e <= Z80 * sd).mean()),
            mae=float(e.mean()),
            crps=float(np.mean(crps_normal(yy, mu, sd))),
            ancho=float(np.mean(np.exp(Z50 * sd) - 1.0)),
            sel=sel, c=c, mu=mu, yy=yy, sd=sd)

    print("\n" + "=" * 78)
    print("CALIBRACION GLOBAL. La banda p25-p75 deberia contener al 50% de la gente")
    print("=" * 78)
    print(f"  {'variante':<28} {'n':>9} {'cob 50%':>9} {'cob 80%':>9} {'CRPS':>8} "
          f"{'MAE':>8} {'banda':>8}")
    for nom, r in filas.items():
        print(f"  {nom:<28} {r['n']:>9,} {r['cob50']:>8.1%} {r['cob80']:>8.1%} "
              f"{r['crps']:>8.4f} {r['mae']:>8.4f} {r['ancho']:>7.1%}")
    print("\n  objetivo: cob 50% = 50,0%   cob 80% = 80,0%   CRPS mas bajo es mejor")

    print("\n" + "=" * 78)
    print("DONDE SE ROMPE: calibracion por quintil de dispersion real del cargo")
    print("=" * 78)
    ref = filas["C (tau celda, sig celda)"]
    disp = np.sqrt(t2c + s2c)
    q = np.quantile(disp[ref["c"]], [0, .2, .4, .6, .8, 1.0])
    print(f"  {'quintil':<10} {'banda real':>11} {'personas':>9}   "
          + "  ".join(f'{n.split()[0]:>7}' for n in VAR))
    for k in range(5):
        lo, hi = q[k], q[k + 1]
        et = f"Q{k+1}"
        linea = []
        for nom, r in filas.items():
            d2 = np.sqrt(t2c + s2c)[r["c"]]
            sel = (d2 >= lo) & (d2 <= hi) if k == 4 else (d2 >= lo) & (d2 < hi)
            e = np.abs(r["yy"] - r["mu"])
            linea.append(f"{float((e[sel] <= Z50*r['sd'][sel]).mean()):>7.1%}")
        d2 = np.sqrt(t2c + s2c)[ref["c"]]
        selr = (d2 >= lo) & (d2 <= hi) if k == 4 else (d2 >= lo) & (d2 < hi)
        print(f"  {et:<10} ±{np.exp(Z50*np.median(d2[selr]))-1:>9.1%} {int(selr.sum()):>9,}   "
              + "  ".join(linea))

    print("\n" + "=" * 78)
    print("CARGOS CONCRETOS: .contiene la banda al 50%?")
    print("=" * 78)
    print(f"  {'cargo':<24} {'pers':>6} {'tau_c':>7} " +
          "  ".join(f'{n.split()[0]:>16}' for n in VAR))
    for cg in CASOS:
        i = idx.get(cg)
        if i is None:
            continue
        col = []
        for nom, r in filas.items():
            sel = r["c"] == i
            if sel.sum() < 30:
                col.append(f"{'-':>16}")
                continue
            e = np.abs(r["yy"][sel] - r["mu"][sel])
            cob = float((e <= Z50 * r["sd"][sel]).mean())
            an = float(np.mean(np.exp(Z50 * r["sd"][sel]) - 1))
            col.append(f"{cob:>7.1%} ±{an:>6.1%}")
        n_p = int((ref["c"] == i).sum())
        print(f"  {cg[:23]:<24} {n_p:>6} {np.sqrt(t2c[i]):>7.3f} " + "  ".join(col))
    print("\n  (cobertura por encima del 50% = banda demasiado ANCHA, se subestima la")
    print("   precision; por debajo = banda demasiado ESTRECHA, se promete de mas)")


if __name__ == "__main__":
    main()
