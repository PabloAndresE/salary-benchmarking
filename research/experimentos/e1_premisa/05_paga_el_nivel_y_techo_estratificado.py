"""DOS MEDICIONES QUE DECIDEN LA FORMA DE LA TESIS (juez externo, 2026-08-12).

3. .PAGA EL NIVEL JERARQUICO?  Todo el valor incremental del proyecto frente a "normalizar
   texto y agrupar por embeddings" depende de esto, y nunca se midio. Se sabe que los
   embeddings son ciegos al rango; no se sabe si el rango predice el sueldo dentro del area
   y dentro de la empresa.

4. EL TECHO FUERA DE LA ZONA COMPRIMIDA. El 40,4% gana a menos del 5% del SBU: ahi la
   respuesta correcta es "el minimo" y cualquier metodo acierta. El techo del 10,9% es un
   promedio que incluye esa zona.
"""
import re
import numpy as np, pandas as pd
from google.cloud import bigquery
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import (componentes_varianza, sigma2_por_celda,
                                                tabla_votos)

RANGOS = {"AYUDANTE":1,"AUXILIAR":1,"OPERARIO":1,"OBRERO":1,"ASISTENTE":1,
          "TECNICO":2,"ANALISTA":2,"SUPERVISOR":3,"COORDINADOR":3,"ESPECIALISTA":3,
          "JEFE":4,"SUBGERENTE":4,"GERENTE":5,"DIRECTOR":5}
PAT = re.compile(rf"^({'|'.join(RANGOS)})\s+(?:DE\s+|DEL\s+)?(.+)$")
SEM = 20260805

def omega2(r, celda):
    d = pd.DataFrame({"r": np.asarray(r,float), "c": np.asarray(celda)}).dropna()
    k, n = d["c"].nunique(), len(d)
    if k < 2 or n <= k: return float("nan")
    gran = d["r"].mean(); g = d.groupby("c")["r"].agg(["mean","size"])
    sse = float((g["size"]*(g["mean"]-gran)**2).sum())
    sst = float(((d["r"]-gran)**2).sum()); msd = (sst-sse)/(n-k)
    return float((sse-(k-1)*msd)/(sst+msd)) if sst+msd>0 else float("nan")

s = cargar_settings(); cl = bigquery.Client(project=s.bq_project)
m = datos.marco_evaluable(datos.agregar_objetivo(
    datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024,2025)), s))
train, _ = splits.partir(m, splits.empresas_test(m))

# ============ 3. PAGA EL NIVEL? ============
print("="*70)
print("3. .PAGA EL NIVEL JERARQUICO, DENTRO DEL AREA Y DENTRO DE LA EMPRESA?")
print("="*70)
d = train.copy()
part = d["cargo_norm"].astype(str).str.upper().str.strip().str.extract(PAT)
d["rango"], d["area"] = part[0], part[1].str.strip()
con = d[d["rango"].notna()].copy()
print(f"personas con palabra de rango: {len(con):,} ({len(con)/len(d):.1%})")
print(f"areas distintas: {con.area.nunique():,}")

# solo areas donde hay AL MENOS DOS RANGOS distintos: si no, no hay contraste
areas_ok = con.groupby("area")["rango"].nunique()
areas_ok = set(areas_ok[areas_ok >= 2].index)
c2 = con[con.area.isin(areas_ok)].copy()
print(f"personas en areas con >=2 rangos: {len(c2):,}  areas: {c2.area.nunique():,}")

y = c2["y"].to_numpy(float)
c2["r1"] = y - c2.groupby("empresa_ruc")["y"].transform("mean")
c2["r2"] = c2["r1"] - c2.groupby("area")["r1"].transform("mean")   # quita el AREA
rng = np.random.default_rng(SEM)
c2["nivel"] = c2["rango"].map(RANGOS).astype(str)
c2["placebo_r"] = rng.permutation(c2["rango"].to_numpy())          # rango permutado
print(f"\nvar tras quitar empresa        = {c2.r1.var():.4f}")
print(f"var tras quitar empresa + AREA = {c2.r2.var():.4f}  (sd={np.sqrt(c2.r2.var()):.3f})")
print(f"\nomega2 sobre ese residuo:")
for nom, col in (("RANGO (14 categorias)","rango"), ("NIVEL (5 escalones)","nivel"),
                 ("PLACEBO rango permutado","placebo_r")):
    o = omega2(c2["r2"], c2[col])
    print(f"  {nom:26s} {o:+.4f}   -> reduce la sd un {1-np.sqrt(max(1-o,0)):.2%}")

print("\ndiferencia media de y por escalon (dentro de empresa y area):")
esc = c2.assign(niv=c2["rango"].map(RANGOS)).groupby("niv")["r2"].agg(["mean","size"])
for niv, fila in esc.iterrows():
    print(f"  nivel {niv}: {fila['mean']:+.4f}  (n={int(fila['size']):,})")
print(f"  -> recorrido de nivel 1 a 5: {esc['mean'].iloc[-1]-esc['mean'].iloc[0]:+.4f} en log")

# ============ 4. TECHO FUERA DE LA ZONA COMPRIMIDA ============
print("\n" + "="*70)
print("4. EL TECHO DEL 10,9% FUERA DE LA ZONA COMPRIMIDA POR EL SBU")
print("="*70)
for etiqueta, sub in (("TODO (referencia)", train),
                      ("y > 0,05", train[train.y > 0.05]),
                      ("y > 0,20", train[train.y > 0.20]),
                      ("y > 0,40", train[train.y > 0.40])):
    if len(sub) < 20000: continue
    tau2, sigma2 = componentes_varianza(sub, "cargo_norm")
    s2c, _ = sigma2_por_celda(sub, "cargo_norm", sigma2_global=sigma2)
    v = tabla_votos(sub, "cargo_norm", tau2=tau2, sigma2=sigma2, sigma2_celda=s2c)
    por = v.groupby("cargo_norm").agg(sw=("w","sum"), personas=("n","sum"), s2=("s2","first"))
    por["irr"] = tau2 + por["s2"]; por["est"] = 1.0/por["sw"]
    w = por["personas"]
    sd_act = float(np.sqrt(((por.irr+por.est)*w).sum()/w.sum()))
    sd_ide = float(np.sqrt((por.irr*w).sum()/w.sum()))
    print(f"{etiqueta:20s} n={len(sub):>8,}  sd actual={sd_act:.4f}  "
          f"sd ideal={sd_ide:.4f}  TECHO={1-sd_ide/sd_act:>5.1%}")
