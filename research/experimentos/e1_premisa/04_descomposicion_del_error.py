"""Cuanto del error de CARGO es RUIDO IRREDUCIBLE y cuanto es MALA ESTIMACION.

Solo la segunda parte es recuperable agrupando distinto. Si es pequena, el arquetipo no
puede ganar por precision ni en las celdas flacas.
"""
import numpy as np, pandas as pd
from google.cloud import bigquery
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import (componentes_varianza, sigma2_por_celda,
                                                tabla_votos)

s = cargar_settings(); cl = bigquery.Client(project=s.bq_project)
m = datos.marco_evaluable(datos.agregar_objetivo(
    datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
train, _ = splits.partir(m, splits.empresas_test(m))
print(f"train: {len(train):,} filas, {train.empresa_ruc.nunique():,} empresas")

tau2, sigma2 = componentes_varianza(train, "cargo_norm")
s2c, _ = sigma2_por_celda(train, "cargo_norm", sigma2_global=sigma2)
print(f"\ntau (entre empresas) = {np.sqrt(tau2):.4f}")
print(f"sigma (intra empresa) = {np.sqrt(sigma2):.4f}")
print(f"ruido irreducible: sd = {np.sqrt(tau2+sigma2):.4f}")

v = tabla_votos(train, "cargo_norm", tau2=tau2, sigma2=sigma2, sigma2_celda=s2c)
por = v.groupby("cargo_norm").agg(suma_w=("w", "sum"), n_emp=("w", "size"),
                                  personas=("n", "sum"), s2=("s2", "first"))
por["irr"] = tau2 + por["s2"]
por["est"] = 1.0 / por["suma_w"]
por["sd_total"] = np.sqrt(por["irr"] + por["est"])
por["frac_est"] = por["est"] / (por["irr"] + por["est"])

# ponderado por PERSONAS, que es como se evalua
w = por["personas"]
print(f"\n=== DE DONDE VIENE EL ERROR DE CARGO (ponderado por personas) ===")
print(f"celdas: {len(por):,}")
print(f"sd predictiva media      = {(por.sd_total*w).sum()/w.sum():.4f}")
print(f"fraccion por MALA ESTIMACION = {(por.frac_est*w).sum()/w.sum():.1%}")

print("\n=== POR TAMANO DE CELDA ===")
cortes = [(1,2),(3,5),(6,20),(21,100),(101,10**9)]
print(f"{'empresas donantes':>20} {'celdas':>8} {'% personas':>11} "
      f"{'sd pred':>9} {'% error por estimacion':>24}")
for a,b in cortes:
    sel = por[(por.n_emp>=a) & (por.n_emp<=b)]
    if sel.empty: continue
    ws = sel["personas"]
    print(f"{f'{a}-{b}' if b<10**9 else f'{a}+':>20} {len(sel):>8,} "
          f"{ws.sum()/w.sum():>10.1%} "
          f"{(sel.sd_total*ws).sum()/ws.sum():>9.4f} "
          f"{(sel.frac_est*ws).sum()/ws.sum():>23.1%}")

# cuanto bajaria la sd si la estimacion fuera perfecta (celda infinita)
ideal = np.sqrt((por["irr"]*w).sum()/w.sum())
actual = (por.sd_total*w).sum()/w.sum()
print(f"\nsd si la referencia se estimara sin error = {ideal:.4f}")
print(f"sd actual de CARGO                        = {actual:.4f}")
print(f"-> TECHO de mejora por agrupar mejor      = {1-ideal/actual:.1%} del error")
