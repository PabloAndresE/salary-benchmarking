import numpy as np, pandas as pd
from google.cloud import bigquery
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits

SEM = 20260805
COMP = ["pct_fijo", "pct_comisiones", "pct_extras", "pct_otros"]

s = cargar_settings(); cl = bigquery.Client(project=s.bq_project)
m = datos.marco_evaluable(datos.agregar_objetivo(
    datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
train, _ = splits.partir(m, splits.empresas_test(m))
d = train[train["tiene_composicion"]].dropna(subset=COMP + ["y"]).copy()
d = d.groupby("cargo_norm").filter(lambda g: len(g) >= 30).reset_index(drop=True)

y = d["y"].to_numpy(float)
d["r1"] = y - d.groupby("empresa_ruc")["y"].transform("mean")
d["r2"] = (d["r1"] - d.groupby("cargo_norm")["r1"].transform("mean")).astype(float)
print(f"filas {len(d):,}  etiquetas {d.cargo_norm.nunique():,}  "
      f"var(r2)={d.r2.var():.4f}  sd={np.sqrt(d.r2.var()):.3f}")

rng = np.random.default_rng(SEM)
d["placebo"] = rng.normal(0, 1, len(d))
grupos = d["empresa_ruc"].to_numpy()
r2 = d["r2"].to_numpy(float)

def r2_cv(cols, etiqueta):
    """R2 FUERA DE MUESTRA, en CV agrupada por empresa. Un R2 en muestra con un GBM
    siempre sale bien y no dice nada."""
    X = d[cols].to_numpy(float)
    pred = np.zeros(len(d))
    for i_tr, i_va in GroupKFold(n_splits=4).split(X, groups=grupos):
        mo = HistGradientBoostingRegressor(random_state=SEM, max_iter=150)
        mo.fit(X[i_tr], r2[i_tr]); pred[i_va] = mo.predict(X[i_va])
    ss_res = float(((r2 - pred) ** 2).sum()); ss_tot = float(((r2 - r2.mean()) ** 2).sum())
    r2_oos = 1 - ss_res / ss_tot
    print(f"  {etiqueta:34s} R2 fuera de muestra = {r2_oos:+.4f}"
          f"   -> reduce la sd un {1-np.sqrt(max(1-r2_oos,0)):.2%}")
    return r2_oos

print("\n=== RELACION CONTINUA con r2 (lo que ni empresa ni CARGO explican) ===")
r2_cv(["placebo"], "PLACEBO (ruido puro)")
r2_cv(COMP, "composicion (4 proporciones)")
r2_cv(["antiguedad_total"], "antiguedad")
r2_cv(COMP + ["antiguedad_total"], "composicion + antiguedad")

print("\n=== SOLO EN LAS 50 ETIQUETAS MAS DISPERSAS ===")
tam = d.groupby("cargo_norm")["y"].agg(["size", "std"])
rotas = set(tam[tam["size"] >= 50].sort_values("std", ascending=False).head(50).index)
sub = d[d.cargo_norm.isin(rotas)].reset_index(drop=True)
gs, rs = sub["empresa_ruc"].to_numpy(), sub["r2"].to_numpy(float)
print(f"filas {len(sub):,}  var(r2)={rs.var():.4f}")
for cols, et in ((["placebo"], "PLACEBO"), (COMP, "composicion"),
                 (["antiguedad_total"], "antiguedad")):
    X = sub[cols].to_numpy(float); pred = np.zeros(len(sub))
    for i_tr, i_va in GroupKFold(n_splits=4).split(X, groups=gs):
        mo = HistGradientBoostingRegressor(random_state=SEM, max_iter=150)
        mo.fit(X[i_tr], rs[i_tr]); pred[i_va] = mo.predict(X[i_va])
    v = 1 - float(((rs-pred)**2).sum())/float(((rs-rs.mean())**2).sum())
    print(f"  {et:34s} R2 fuera de muestra = {v:+.4f}"
          f"   -> reduce la sd un {1-np.sqrt(max(1-v,0)):.2%}")
