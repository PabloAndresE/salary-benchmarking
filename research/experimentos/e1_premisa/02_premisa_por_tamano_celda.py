import sys
import numpy as np, pandas as pd
from google.cloud import bigquery
from sklearn.cluster import MiniBatchKMeans
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits

SEM = 20260805
COMP = ["pct_fijo", "pct_comisiones", "pct_extras", "pct_otros"]

def omega2(r, celda):
    d = pd.DataFrame({"r": np.asarray(r, float), "c": np.asarray(celda)}).dropna()
    k, n = d["c"].nunique(), len(d)
    if k < 2 or n <= k: return float("nan")
    gran = d["r"].mean(); g = d.groupby("c")["r"].agg(["mean", "size"])
    ss_e = float((g["size"] * (g["mean"] - gran) ** 2).sum())
    ss_t = float(((d["r"] - gran) ** 2).sum())
    ms_d = (ss_t - ss_e) / (n - k); den = ss_t + ms_d
    return float((ss_e - (k - 1) * ms_d) / den) if den > 0 else float("nan")

s = cargar_settings(); cl = bigquery.Client(project=s.bq_project)
m = datos.marco_evaluable(datos.agregar_objetivo(
    datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
train, _ = splits.partir(m, splits.empresas_test(m))
d0 = train[train["tiene_composicion"]].dropna(subset=COMP + ["y"]).copy()

for minimo in (1, 30, 100):
    d = d0.groupby("cargo_norm").filter(lambda g: len(g) >= minimo).copy()
    if len(d) < 1000: continue
    y = d["y"].to_numpy(float)
    d["r1"] = y - d.groupby("empresa_ruc")["y"].transform("mean")
    d["r2"] = d["r1"] - d.groupby("cargo_norm")["r1"].transform("mean")
    rng = np.random.default_rng(SEM)
    d["p_comp"] = MiniBatchKMeans(n_clusters=25, random_state=SEM,
                                  n_init=10).fit_predict(d[COMP].to_numpy(float)).astype(str)
    d["p_ant"] = pd.qcut(d["antiguedad_total"].fillna(-1).rank(method="first"), 25,
                         labels=False).astype(str)
    d["p_azar"] = rng.integers(0, 25, len(d)).astype(str)
    print(f"\n=== etiquetas con >= {minimo} personas ===")
    print(f"filas {len(d):,}  etiquetas {d.cargo_norm.nunique():,}  "
          f"personas/etiqueta mediana {d.groupby('cargo_norm').size().median():.0f}")
    print(f"var(y)={y.var():.4f}  tras empresa={d.r1.var():.4f}  "
          f"tras empresa+CARGO={d.r2.var():.4f} (sd={np.sqrt(d.r2.var()):.3f})")
    print(f"CARGO explica {1 - d.r2.var()/d.r1.var():.1%} del residuo tras empresa")
    for nom, col in (("composicion", "p_comp"), ("antiguedad", "p_ant"), ("PLACEBO", "p_azar")):
        o = omega2(d["r2"], d[col])
        print(f"  omega2 {nom:12s} = {o:+.4f}   -> reduce la sd un {1-np.sqrt(max(1-o,0)):.2%}")
