""".Predice `1/W` cuanto se mueve la referencia? Y .sirve mejor que la etiqueta de hoy?

La etiqueta de confianza de hoy compara el ancho de la banda contra el suelo del cargo. Eso
responde *"que tan ancho es el mercado"*, no *"que tan bien conozco su centro"*, y por eso
casi todo sale ALTA: en la rama directa el suelo es casi todo el ancho.

La alternativa es etiquetar por la incertidumbre del CENTRO, que en el modelo es todo lo
que NO es dispersion del mercado:

    directo      var_centro = 1/W
    por analogia var_centro = suma(peso^2/W) + suma(peso*dist) + penal_nivel

Antes de fijar umbrales hay que comprobar que ese numero predice algo. SE PUEDE MEDIR
DIRECTAMENTE: si `1/W` es la varianza de la referencia estimada, entonces al calcularla
sobre dos mitades disjuntas de empresas las dos referencias deben separarse

    E|m_A - m_B| ~ sqrt(2/pi) * sqrt(1/W_A + 1/W_B)

Si `1/W` esta bien calibrado, el cociente entre lo observado y lo predicho es ~1 en todos
los tramos. Si no predice nada, no correlaciona.

Y se compara contra la cantidad que usa la etiqueta HOY (`ancho/suelo`), que deberia
predecir mucho peor porque no es una medida de nuestra ignorancia.

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
from benchmarking.evaluacion.referencia import componentes_varianza, sigma2_por_celda

SEM = 20260805
MIN_EMPRESAS = 3
# La referencia se usa para decidir subidas de sueldo, que se mueven en escalones de ~5%.
# Un centro conocido a mejor que 5% es accionable; entre 5% y 15% hay que mirarlo dos
# veces; por encima de 15% la referencia no distingue "sube un 10%" de "baja un 10%".
CORTE_ALTA, CORTE_MEDIA = 0.05, 0.15


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(mk, splits.empresas_test(mk))

    celdas = sorted(set(train.cargo_norm.astype(str)))
    idx = {c: i for i, c in enumerate(celdas)}
    n_c = len(celdas)
    cod = train.cargo_norm.astype(str).map(idx).to_numpy()
    y = pd.to_numeric(train["y"], errors="coerce").to_numpy(float)
    ce = pd.factorize(train.empresa_ruc)[0]

    tau2_g, sigma2_g = componentes_varianza(train, "cargo_norm")
    s2s, _ = sigma2_por_celda(train, "cargo_norm", sigma2_global=sigma2_g)
    s2c = np.full(n_c, float(sigma2_g))
    for k, v in s2s.items():
        i = idx.get(str(k))
        if i is not None and np.isfinite(v):
            s2c[i] = float(v)
    MSB, _, n0, F_an, _ = _c.anova_por_celda(cod, ce, y, n_c)
    t2c, _ = _c.tau2_por_celda(MSB, s2c, n0, F_an, tau2_g)

    # -- cuanto etiqueta ALTA la regla de hoy, sobre TODAS las celdas directas ---
    # El argumento de por que es ~100% es algebraico (ver D-017), pero el numero hay que
    # poder reproducirlo: se cita en `mediciones.md` y en el registro.
    m_t, W_t, F_t = _c.referencia(cod, ce, y, t2c, s2c, n_c)
    dir_t = F_t >= MIN_EMPRESAS
    suelo_t = np.sqrt(t2c + s2c)
    anch0 = lambda sd: np.exp(0.6745 * sd) - 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        sd_t = np.sqrt(t2c + s2c + np.where(W_t > 0, 1.0 / np.where(W_t > 0, W_t, 1), np.inf))
        veces_t = anch0(sd_t) / anch0(suelo_t)
    print(f"\nREGLA DE HOY sobre las {int(dir_t.sum()):,} celdas con {MIN_EMPRESAS}+ "
          f"empresas:")
    print(f"  etiquetadas ALTA (<= 1,25x el suelo): "
          f"{float((veces_t[dir_t] <= 1.25).mean()):.2%}")
    tres = dir_t & (F_t == MIN_EMPRESAS)
    if tres.any():
        print(f"  y entre las que tienen exactamente {MIN_EMPRESAS} empresas "
              f"({int(tres.sum()):,}): {float((veces_t[tres] <= 1.25).mean()):.1%} ALTA")
    print(f"  veces el suelo: mediana {np.nanmedian(veces_t[dir_t]):.3f}  "
          f"p99 {np.nanquantile(veces_t[dir_t], 0.99):.3f}  "
          f"max {np.nanmax(veces_t[dir_t]):.3f}")

    # dos mitades disjuntas de EMPRESAS
    rng = np.random.default_rng(SEM)
    lado = rng.integers(0, 2, size=ce.max() + 1)[ce]
    res = {}
    for L in (0, 1):
        sel = lado == L
        res[L] = _c.referencia(cod[sel], pd.factorize(ce[sel])[0], y[sel], t2c, s2c, n_c)

    (mA, WA, FA), (mB, WB, FB) = res[0], res[1]
    ok = (FA >= MIN_EMPRESAS) & (FB >= MIN_EMPRESAS) & np.isfinite(mA) & np.isfinite(mB)
    print(f"{int(ok.sum()):,} celdas con {MIN_EMPRESAS}+ empresas en las DOS mitades")

    obs = np.abs(mA[ok] - mB[ok])
    pred = np.sqrt(1.0 / WA[ok] + 1.0 / WB[ok])          # sd de la diferencia
    esperado = np.sqrt(2.0 / np.pi) * pred               # E|N(0,s)| = s*sqrt(2/pi)

    print("\n" + "=" * 76)
    print("A. .PREDICE `1/W` CUANTO SE MUEVE LA REFERENCIA?")
    print("=" * 76)
    print(f"  correlacion  Pearson {np.corrcoef(pred, obs)[0,1]:+.3f}   "
          f"Spearman {pd.Series(pred).corr(pd.Series(obs), method='spearman'):+.3f}")
    print(f"\n  {'decil de 1/W':<14} {'celdas':>7} {'predicho':>10} {'observado':>10} "
          f"{'obs/pred':>9}")
    q = np.quantile(pred, np.linspace(0, 1, 11))
    for k in range(10):
        m_ = (pred >= q[k]) & (pred <= q[k + 1] if k == 9 else pred < q[k + 1])
        if m_.sum() < 20:
            continue
        print(f"  D{k+1:<13} {int(m_.sum()):>7,} {esperado[m_].mean():>10.4f} "
              f"{obs[m_].mean():>10.4f} {obs[m_].mean()/esperado[m_].mean():>9.2f}")
    print("\n  (calibrado perfecto = 1.00 en todos los deciles)")

    # -- comparacion con la cantidad que usa la etiqueta HOY --------------------
    suelo = np.sqrt(t2c + s2c)
    anch = lambda sd: np.exp(0.6745 * sd) - 1.0
    sd_hoy = np.sqrt(t2c + s2c + 1.0 / np.where(WA > 0, WA, np.nan))
    veces_hoy = anch(sd_hoy) / anch(suelo)
    print("\n" + "=" * 76)
    print("B. CONTRA LA CANTIDAD QUE USA LA ETIQUETA DE HOY")
    print("=" * 76)
    for nom, v in (("hoy  (ancho/suelo)", veces_hoy[ok]), ("nuevo (sqrt(1/W))", pred)):
        fin = np.isfinite(v)
        print(f"  {nom:<22} Spearman con el movimiento real: "
              f"{pd.Series(v[fin]).corr(pd.Series(obs[fin]), method='spearman'):+.3f}")

    # -- .separan las etiquetas? ------------------------------------------------
    print("\n" + "=" * 76)
    print("C. .SEPARAN LAS ETIQUETAS EL MOVIMIENTO REAL DE LA REFERENCIA?")
    print("=" * 76)
    centro = np.sqrt(1.0 / WA[ok])                       # lo que veria el producto
    pct = np.exp(centro) - 1.0
    et_nueva = np.where(pct <= CORTE_ALTA, "ALTA",
                        np.where(pct <= CORTE_MEDIA, "MEDIA", "BAJA"))
    et_hoy = np.where(veces_hoy[ok] <= 1.25, "ALTA",
                      np.where(veces_hoy[ok] <= 2.0, "MEDIA", "BAJA"))
    for nom, et in (("HOY", et_hoy), ("NUEVA (1/W)", et_nueva)):
        print(f"\n  {nom}")
        print(f"    {'etiqueta':<8} {'celdas':>8} {'%':>7} {'|mA-mB| medio':>15} "
              f"{'en dolares*':>13}")
        for e in ("ALTA", "MEDIA", "BAJA"):
            m_ = et == e
            if not m_.any():
                print(f"    {e:<8} {0:>8}")
                continue
            print(f"    {e:<8} {int(m_.sum()):>8,} {m_.mean():>6.1%} "
                  f"{obs[m_].mean():>15.4f} {np.exp(obs[m_].mean())-1:>12.1%}")
    print("\n  * cuanto se mueve la referencia al cambiar la muestra de empresas")
    print("    (una etiqueta util tiene que separar: ALTA << MEDIA << BAJA)")


if __name__ == "__main__":
    main()
