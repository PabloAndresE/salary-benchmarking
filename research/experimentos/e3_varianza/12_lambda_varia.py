""".Varia `lambda` entre cargos, como varian `tau` y `sigma`?

EL MODELO tiene tres parametros y dos ya se comprobaron:

    tau    dispersion de pago ENTRE empresas    -> varia 8,3x, test-retest r = 0,78  (`01`)
    sigma  dispersion DENTRO de la empresa      -> varia, test-retest r = 0,48       (`01`)
    lambda cuanto pago hay por unidad de        -> UN SOLO ESCALAR para 65.081 cargos
           distancia semantica

`lambda` es el tercero y nadie lo ha mirado. Entra en el peso de cada vecino:

    var_j = 1/W_j + lambda * (1 - sim_j)

o sea que decide cuanto se castiga a un vecino por no ser exactamente el mismo puesto. Con
un solo numero, 0,03 de distancia coseno cuesta lo mismo en ingenieria que en limpieza — y
no hay razon para que sea asi. Hay ademas indicio de que es sensible: `e2_nivel/04` midio
1,90 en crudo contra 2,71 enmascarado.

COMO SE MIDE, igual que `tau` en `01`: se parten las empresas en dos mitades al azar, se
estima `lambda_c` por celda en cada mitad por separado y se correlacionan. Si el parametro
fuese comun y lo que se ve fuera ruido de estimacion, las dos mitades NO correlacionarian.

`lambda_c` sale de la misma regresion por el origen que usa el producto, restringida a los
vecinos de esa celda:

    d2_j = (m_c - m_j)^2 - (1/W_c + 1/W_j)      lo que sobra tras descontar el ruido
    x_j  = 1 - sim_j
    lambda_c = suma(x_j * d2_j) / suma(x_j^2)

Se reporta ademas por ESCALON lexico, que es la particion interpretable: si el patron sigue
al escalon como lo sigue `tau`, la conclusion es la misma y encaja con D-013.

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
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.evaluacion.referencia import componentes_varianza, sigma2_por_celda
from benchmarking.producto.base_referencia import VECINOS, _lambda_semantica, _vecinos
from benchmarking.producto.nivel import nivel_lexico

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
MIN_EMPRESAS = 3
MIN_VECINOS = 8          # vecinos utiles por celda; por debajo `lambda_c` es ruido puro


def lambda_por_celda(m, W, vec, sim):
    """`lambda_c` por celda, con la misma regresion por el origen que usa el producto."""
    n = len(m)
    j = vec
    x = 1.0 - sim
    with np.errstate(invalid="ignore", divide="ignore"):
        d2 = (m[:, None] - m[j]) ** 2 - (1.0 / W[:, None] + 1.0 / W[j])
    ok = (np.isfinite(m)[:, None] & np.isfinite(m[j]) & (W[:, None] > 0) & (W[j] > 0)
          & (sim < 0.9999) & np.isfinite(d2))
    xx = np.where(ok, x, 0.0)
    dd = np.where(ok, d2, 0.0)
    num = (xx * dd).sum(axis=1)
    den = (xx * xx).sum(axis=1)
    cuenta = ok.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        lam = np.where(den > 0, num / den, np.nan)
    return np.where(cuenta >= MIN_VECINOS, lam, np.nan), cuenta


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    mk = mk.copy()
    mk["cargo_norm"] = mk.cargo_norm.astype(str)
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    print(f"train {len(train):,} filas / {train.empresa_ruc.nunique():,} empresas")

    celdas = sorted(set(train.cargo_norm))
    idx = {c: i for i, c in enumerate(celdas)}
    n_c = len(celdas)
    cod = train.cargo_norm.map(idx).to_numpy()
    y = pd.to_numeric(train["y"], errors="coerce").to_numpy(float)
    ce = pd.factorize(train.empresa_ruc)[0]

    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print(f"embebiendo {n_c:,} titulos...")
    Z = embeddings.embeber(celdas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    Z = Z / np.linalg.norm(Z, axis=1, keepdims=True)
    print("buscando vecinos...")
    vec, sim = _vecinos(Z, Z, VECINOS, excluir_propio=True)
    niv = np.array([nivel_lexico(c) or np.nan for c in celdas], dtype=float)

    tau2, sigma2 = componentes_varianza(train, "cargo_norm")
    s2s, _ = sigma2_por_celda(train, "cargo_norm", sigma2_global=sigma2)
    s2c = np.full(n_c, float(sigma2))
    for k, v in s2s.items():
        i = idx.get(str(k))
        if i is not None and np.isfinite(v):
            s2c[i] = float(v)
    MSB, _, n0, F_an, _ = _c.anova_por_celda(cod, ce, y, n_c)
    t2c, _ = _c.tau2_por_celda(MSB, s2c, n0, F_an, tau2)

    m_all, W_all, F_all = _c.referencia(cod, ce, y, t2c, s2c, n_c)
    lam_g = _lambda_semantica(m_all, W_all, vec, sim)
    print(f"\nlambda GLOBAL (lo que usa el producto hoy): {lam_g:.3f}")

    lam_all, cuenta = lambda_por_celda(m_all, W_all, vec, sim)
    util = np.isfinite(lam_all) & (F_all >= MIN_EMPRESAS)
    print(f"celdas con lambda_c estimable: {int(util.sum()):,} de {n_c:,}")
    print("\n" + "=" * 78)
    print("A. .VARIA `lambda` ENTRE CARGOS?")
    print("=" * 78)
    for q in (0.05, 0.25, 0.50, 0.75, 0.95):
        print(f"  p{int(q*100):02d}  {np.nanquantile(lam_all[util], q):>8.3f}")
    pos = lam_all[util]
    print(f"  negativos: {float((pos < 0).mean()):.1%}   (ruido: la distancia no puede "
          f"reducir la diferencia)")

    # -- B. .es real o es ruido? test-retest -----------------------------------
    rng = np.random.default_rng(SEM)
    lado = rng.integers(0, 2, size=ce.max() + 1)[ce]
    res = {}
    for L in (0, 1):
        sel = lado == L
        mL, WL, FL = _c.referencia(cod[sel], pd.factorize(ce[sel])[0], y[sel],
                                   t2c, s2c, n_c)
        lamL, cL = lambda_por_celda(mL, WL, vec, sim)
        res[L] = (lamL, FL, cL)
    okr = (np.isfinite(res[0][0]) & np.isfinite(res[1][0])
           & (res[0][1] >= MIN_EMPRESAS) & (res[1][1] >= MIN_EMPRESAS))
    print("\n" + "=" * 78)
    print("B. .ES REAL O ES RUIDO? (test-retest entre mitades de empresas)")
    print("=" * 78)
    a, b = res[0][0][okr], res[1][0][okr]
    print(f"  celdas comparables: {int(okr.sum()):,}")
    print(f"  lambda   Pearson {np.corrcoef(a, b)[0,1]:+.3f}   "
          f"Spearman {pd.Series(a).corr(pd.Series(b), method='spearman'):+.3f}")
    print("\n  (referencia: tau dio +0,780 y sigma +0,484 con el mismo diseno.")
    print("   Si lambda sale cerca de 0, el escalar global esta justificado.)")

    # -- C. por escalon lexico, que es la particion interpretable ---------------
    print("\n" + "=" * 78)
    print("C. POR ESCALON LEXICO")
    print("=" * 78)
    print(f"  {'nivel':<8} {'celdas':>8} {'lambda mediana':>16} {'p25':>9} {'p75':>9}")
    for k in (1, 2, 3, 4, 5):
        sel = util & (niv == k)
        if sel.sum() < 30:
            continue
        v = lam_all[sel]
        print(f"  {k:<8} {int(sel.sum()):>8,} {np.nanmedian(v):>16.3f} "
              f"{np.nanquantile(v,.25):>9.3f} {np.nanquantile(v,.75):>9.3f}")
    sel = util & ~np.isfinite(niv)
    if sel.sum() >= 30:
        print(f"  {'sin rango':<8} {int(sel.sum()):>8,} "
              f"{np.nanmedian(lam_all[sel]):>16.3f} "
              f"{np.nanquantile(lam_all[sel],.25):>9.3f} "
              f"{np.nanquantile(lam_all[sel],.75):>9.3f}")

    # -- D. .cuanto cambiaria el castigo de distancia? --------------------------
    print("\n" + "=" * 78)
    print("D. QUE SIGNIFICA EN EL PRODUCTO")
    print("=" * 78)
    print("  El castigo a un vecino es `lambda * (1 - sim)`. Para un vecino a sim 0,95:")
    for et, v in (("global (hoy)", lam_g),
                  ("p25 de los cargos", float(np.nanquantile(lam_all[util], .25))),
                  ("p75 de los cargos", float(np.nanquantile(lam_all[util], .75)))):
        d = max(v, 0.0) * 0.05
        print(f"    {et:<20} lambda {v:>7.3f}  ->  castigo {d:.4f}  "
              f"(sd equivalente {np.sqrt(d):.3f})")


if __name__ == "__main__":
    main()
