"""Saca los pares que el umbral no puede decidir, y muestrea 50 para juzgar a mano.

POR QUE ESTA BANDA. Medido sobre `base_v15`, el 12,1% de los puestos tiene un
vecino por encima de 0,95 y aun asi no se fusiono —el 88% lo bloqueo el enlace
completo— y otro 24,2% se queda entre 0,93 y 0,95. Es la unica bolsa grande que
queda, y los umbrales NO la separan:

    0,955  SECRETARIO/A GENERAL       |  SECRETARIO GENERAL          <- el mismo
    0,953  GERENTE SUCURSAL GUAYAQUIL |  GERENTE DE LA SUCURSAL ...  <- el mismo
    0,956  GERENTE DE CREDITO         |  GERENTE DE CREDITO Y COB.   <- distintos
    0,958  FIELD SERVICE ENGINEER     |  SR. FIELD SERVICE ENGINEER  <- distintos

Y esta medido que bajar el umbral no ayuda: `completo >0,93` da -0,0005 con el IC
cruzando el cero. Por cada par que ganas, pierdes otro.

Hace falta JUICIO, no un numero. Antes de pedirselo a un modelo hace falta saber
contra que se compara, asi que este script produce dos cosas:

    13_pares_ambiguos.csv     todos los pares de la muestra, para el experimento
    13_para_juzgar.csv        50 al azar, con la columna `mismo` vacia

EL PATRON DE ORO NO VE SUELDOS. Es deliberado y es la regla mas importante del
proyecto: si quien juzga mira lo que paga cada lado, etiquetara como "el mismo
puesto" a los que pagan parecido, y entonces la agrupacion queda optimizada
contra el sueldo por la puerta de atras. Se juzga leyendo los dos titulos y nada
mas. Se da el numero de empresas solo para saber cual es el lado comun.

MUESTRA Y NO CENSO. Se recorren 6.000 grupos contra los 65.181 titulos; el censo
completo son 50.296 y tarda de mas para lo que hace falta aqui. Para el
experimento se ampliara.
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

BASE = "demo/base_v15.npz"
SAL = pathlib.Path("research/experimentos/e2_nivel/salidas")
N_GRUPOS = 6000
N_JUZGAR = 50
LO, HI = 0.93, 0.97
SEM = 20260923

d = np.load(BASE, allow_pickle=True)
cel = np.array([str(c) for c in d["celdas"]])
Z = d["Z"].astype(np.float32)
Z /= np.linalg.norm(Z, axis=1, keepdims=True)
g = d["grupo"].astype(np.int64)
emp, per, niv = d["emp"], d["personas"], d["nivel"]

# Un representante por grupo: el de mas empresas, desempatando por grafia corta.
rep = {}
for i in range(len(cel)):
    gi = int(g[i])
    if gi not in rep or (-emp[i], len(cel[i])) < (-emp[rep[gi]], len(cel[rep[gi]])):
        rep[gi] = i
reps = np.array(sorted(rep.values()))
print("grupos: %d" % len(reps))

rng = np.random.default_rng(SEM)
muestra = rng.choice(reps, size=min(N_GRUPOS, len(reps)), replace=False)

filas, vistos = [], set()
PASO = 200
for a in range(0, len(muestra), PASO):
    sub = muestra[a:a + PASO]
    S = Z[sub] @ Z.T
    for r, i in enumerate(sub):
        s = S[r].copy()
        s[g == g[i]] = -1.0
        for j in np.flatnonzero((s >= LO) & (s < HI)):
            par = (int(g[i]), int(g[j]))
            par = par if par[0] < par[1] else (par[1], par[0])
            if par in vistos:
                continue
            vistos.add(par)
            a_i, b_i = (i, int(j)) if emp[i] >= emp[j] else (int(j), i)
            na = None if not np.isfinite(niv[a_i]) else int(niv[a_i])
            nb = None if not np.isfinite(niv[b_i]) else int(niv[b_i])
            filas.append({
                "comun": cel[a_i], "raro": cel[b_i],
                "sim": round(float(s[j]), 4),
                "emp_comun": int(emp[a_i]), "emp_raro": int(emp[b_i]),
                "per_comun": int(per[a_i]), "per_raro": int(per[b_i]),
                "niv_comun": na, "niv_raro": nb,
                "escalon_distinto": bool(na is not None and nb is not None and na != nb),
            })
    if (a // PASO) % 5 == 0:
        print("  %d/%d grupos, %d pares" % (a, len(muestra), len(filas)), flush=True)

t = pd.DataFrame(filas).sort_values("sim", ascending=False).reset_index(drop=True)
SAL.mkdir(parents=True, exist_ok=True)
t.to_csv(SAL / "13_pares_ambiguos.csv", index=False, encoding="utf-8-sig")
print("\npares en la banda %.2f-%.2f: %d" % (LO, HI, len(t)))
print("  con escalon distinto (hoy los bloquea el candado): %d (%.0f%%)"
      % (t.escalon_distinto.sum(), 100 * t.escalon_distinto.mean()))
print("  con el lado raro bajo el suelo de 3 empresas     : %d (%.0f%%)"
      % ((t.emp_raro < 3).sum(), 100 * (t.emp_raro < 3).mean()))

# MUESTRA ESTRATIFICADA POR SIMILITUD. Sin estratificar, el azar la llena de la
# parte baja de la banda, que es la mas poblada, y el patron de oro no dice nada
# de donde se decide de verdad.
t["tramo"] = pd.cut(t["sim"], [LO, 0.94, 0.95, 0.96, HI], include_lowest=True)
juzgar = (t.groupby("tramo", observed=True, group_keys=False)
           .apply(lambda x: x.sample(min(len(x), N_JUZGAR // 4), random_state=SEM)))
juzgar = juzgar.sample(frac=1.0, random_state=SEM).head(N_JUZGAR)

# LO QUE VE QUIEN JUZGA: los dos titulos y el respaldo. NUNCA el sueldo.
salida = juzgar[["comun", "raro", "sim", "emp_comun", "emp_raro"]].copy()
salida.insert(0, "n", range(1, len(salida) + 1))
salida["mismo"] = ""           # si / no / duda
salida["nota"] = ""
salida.to_csv(SAL / "13_para_juzgar.csv", index=False, encoding="utf-8-sig")
print("\n%d pares para juzgar en %s" % (len(salida), SAL / "13_para_juzgar.csv"))
print("rellena `mismo` con si / no / duda. NO hay columna de sueldo, a proposito.")
