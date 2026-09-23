"""El lote de 400 pares para juzgar a mano. El paso que desbloquea todo lo demas.

POR QUE 400. Medido en `13d`: con los 48 pares actuales, ningun arbitro se separa de
forma concluyente. Si las tasas observadas del cross fueran las verdaderas, la potencia
del diseno de 48 es del 17%. Con 400 sube al 92%:

    N= 48  17%     N=100  41%     N=200  63%     N=400  92%

Con 400 se consigue lo que hoy no hay: decidir entre arbitros, CALIBRAR un umbral sobre
datos que no se usaron para elegirlo, y --si se decide afinar-- tener con que entrenar.

TRES COSAS QUE ESTE LOTE ARREGLA DEL DE 48
==============================================================================

1. NO SE MUESTRA `sim`. El CSV de los 48 traia la columna con la similitud del coseno a
   la vista de quien juzga. Eso CONTAMINA: ver 0,96 empuja hacia el `si`, y luego esas
   mismas etiquetas se usan para evaluar al coseno. El juez queda anclado al modelo que
   se pretende medir. Aqui se ve el titulo y el respaldo, nada mas.

   Esto obliga a una nota sobre los 48: siguen siendo utiles pero estan levemente
   contaminados a favor del coseno, asi que su AUC de 0,601 es si acaso OPTIMISTA. No
   se descartan --se juzgaron con criterio y sirven de comprobacion-- pero el patron de
   oro de referencia pasa a ser este lote.

2. CENSO, NO MUESTRA. `13a` recorrio 6.000 grupos de los 50.296 y dejo dicho «para el
   experimento se ampliara». Aqui se recorren todos, asi que el marco de muestreo es
   completo y las proporciones por tramo son las de verdad.

3. HAY ANCLAS FUERA DE LA BANDA. Los 48 salieron todos de 0,93-0,97. Con solo esa
   franja no se puede calibrar un umbral --no hay nada por encima ni por debajo contra
   lo que fijarlo-- y ademas no se puede comprobar que el juez y los modelos se
   comportan sensatamente donde la respuesta es facil. Se anaden dos anclas.

ESTRATOS
------------------------------------------------------------------------------
    banda   0,93 - 0,97   280 pares    donde hace falta juicio. El grueso, y se
                                       subdivide en cuatro tramos de 70 para que el
                                       azar no la llene de la parte baja, que es la
                                       mas poblada
    alto    >= 0,97        60 pares    el producto YA los fusiona. Ancla superior
    bajo    0,90 - 0,93    60 pares    el producto NO los fusiona. Ancla inferior

PARTICION DECLARADA ANTES DE JUZGAR, y esto es lo importante
------------------------------------------------------------------------------
    calibra   200   para elegir arbitro y fijar umbral. Se mira cuanto haga falta
    prueba    200   SE TOCA UNA VEZ, con el umbral ya congelado

Sin esto, «el mejor corte posible» se elige viendo las respuestas y no significa nada
--que es justo lo que le paso a `13c`, donde el corte optimo de 0,003 se ajusto sobre
los mismos 48 que luego media--. La particion se asigna AQUI, antes de que exista una
sola etiqueta, y va en el fichero de metadatos, NO en el que se juzga: quien juzga no
debe saber en que mitad cae cada par.

EL PATRON DE ORO NO VE SUELDOS. La regla mas importante del proyecto. Si quien juzga
mira lo que paga cada lado, etiquetara como "el mismo puesto" a los que pagan parecido y
la agrupacion queda optimizada contra el sueldo por la puerta de atras. Se juzga leyendo
los dos titulos. El numero de empresas se da solo para saber cual es el lado comun, que
hace falta para reconocer una errata.

SALIDAS
    13e_pares_400.csv     metadatos completos: sim, estrato, particion, nivel. NO se
                          abre antes de juzgar
    13e_para_juzgar.csv   lo que se rellena: n, los dos titulos, el respaldo, `mismo`
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

BASE = "demo/base_v15.npz"
SAL = pathlib.Path("research/experimentos/e2_nivel/salidas")
YA_JUZGADOS = SAL / "13_para_juzgar.csv"
SEM = 20260924
PASO = 512

# estrato -> (limite inferior, limite superior, cuantos)
ESTRATOS = {
    "bajo":  (0.90, 0.93, 60),
    "banda": (0.93, 0.97, 280),
    "alto":  (0.97, 1.01, 60),
}
N_TRAMOS_BANDA = 4
POR_LOTE = 50               # para poder juzgar en tandas


def main():
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
    print("grupos (censo completo): {:,}".format(len(reps)))

    lo_global = min(a for a, _, _ in ESTRATOS.values())
    hi_global = max(b for _, b, _ in ESTRATOS.values())

    filas, vistos = [], set()
    for a in range(0, len(reps), PASO):
        sub = reps[a:a + PASO]
        S = Z[sub] @ Z.T
        for r, i in enumerate(sub):
            s = S[r]
            cand = np.flatnonzero((s >= lo_global) & (s < hi_global) & (g != g[i]))
            for j in cand:
                par = (int(g[i]), int(g[j]))
                par = par if par[0] < par[1] else (par[1], par[0])
                if par in vistos:
                    continue
                vistos.add(par)
                a_i, b_i = (i, int(j)) if emp[i] >= emp[j] else (int(j), i)
                na = None if not np.isfinite(niv[a_i]) else int(niv[a_i])
                nb = None if not np.isfinite(niv[b_i]) else int(niv[b_i])
                filas.append({
                    "g_comun": int(g[a_i]), "g_raro": int(g[b_i]),
                    "comun": cel[a_i], "raro": cel[b_i],
                    "sim": round(float(s[j]), 4),
                    "emp_comun": int(emp[a_i]), "emp_raro": int(emp[b_i]),
                    "per_comun": int(per[a_i]), "per_raro": int(per[b_i]),
                    "niv_comun": na, "niv_raro": nb,
                    "escalon_distinto": bool(na is not None and nb is not None
                                             and na != nb),
                })
        if (a // PASO) % 10 == 0:
            print("  {:,}/{:,} grupos, {:,} pares".format(a, len(reps), len(filas)),
                  flush=True)

    t = pd.DataFrame(filas)
    print("\npares en {:.2f}-{:.2f}: {:,}".format(lo_global, hi_global, len(t)))

    # FUERA LOS 48 YA JUZGADOS. Volver a preguntarlos no anade informacion y gasta
    # trabajo humano.
    # POR GRUPO Y NO POR TEXTO. Un mismo par de PUESTOS puede aparecer escrito con
    # grafias distintas segun cual de sus titulos se cruzo primero, asi que comparar
    # cadenas deja pasar repeticiones. Comparando ids de grupo la exclusion es exacta.
    if YA_JUZGADOS.exists():
        v = pd.read_csv(YA_JUZGADOS, sep=None, engine="python", encoding="utf-8-sig")
        v.columns = [c.strip() for c in v.columns]
        ix = {c: i for i, c in enumerate(cel)}
        fuera, sin_rastro = set(), 0
        for x, y in zip(v["comun"], v["raro"]):
            if str(x) in ix and str(y) in ix:
                fuera.add(frozenset((int(g[ix[str(x)]]), int(g[ix[str(y)]]))))
            else:
                sin_rastro += 1
        antes = len(t)
        t = t[[frozenset((a, b)) not in fuera
               for a, b in zip(t["g_comun"], t["g_raro"])]].reset_index(drop=True)
        print("  quitados por estar ya juzgados: {} (de {} pares en los 48)".format(
            antes - len(t), len(v)))
        if sin_rastro:
            print("  AVISO: {} de los 48 no se encuentran en la base actual".format(
                sin_rastro))

    t["estrato"] = pd.cut(t["sim"],
                          [ESTRATOS["bajo"][0], ESTRATOS["banda"][0],
                           ESTRATOS["alto"][0], ESTRATOS["alto"][1]],
                          labels=["bajo", "banda", "alto"], include_lowest=True)
    print("\n  poblacion por estrato (marco completo):")
    for k, n in t["estrato"].value_counts().sort_index().items():
        print("    {:<8} {:>8,}".format(str(k), n))

    rng = np.random.default_rng(SEM)
    trozos = []
    for nom, (lo, hi, cuantos) in ESTRATOS.items():
        sub = t[t["estrato"] == nom]
        if nom == "banda":
            # Cuatro tramos iguales: sin esto el azar la llena de la parte baja.
            sub = sub.copy()
            sub["tramo"] = pd.cut(sub["sim"], np.linspace(lo, hi, N_TRAMOS_BANDA + 1),
                                  include_lowest=True)
            por = cuantos // N_TRAMOS_BANDA
            for _, gr in sub.groupby("tramo", observed=True):
                trozos.append(gr.sample(min(len(gr), por), random_state=SEM))
        else:
            trozos.append(sub.sample(min(len(sub), cuantos), random_state=SEM))
    m = pd.concat(trozos).drop(columns=["tramo"], errors="ignore")

    # PARTICION ANTES DE JUZGAR, estratificada para que las dos mitades tengan la
    # misma composicion. Si se asignara despues, «el mejor corte» se elegiria viendo
    # las respuestas y no significaria nada.
    m = m.sample(frac=1.0, random_state=SEM).reset_index(drop=True)
    m["particion"] = ""
    for nom, gr in m.groupby("estrato", observed=True):
        idx = rng.permutation(gr.index.to_numpy())
        mitad = len(idx) // 2
        m.loc[idx[:mitad], "particion"] = "calibra"
        m.loc[idx[mitad:], "particion"] = "prueba"

    # ORDEN AL AZAR, con los estratos entremezclados: si fueran en bloques, el
    # cansancio del final caeria entero sobre un estrato.
    m = m.sample(frac=1.0, random_state=SEM + 1).reset_index(drop=True)
    m.insert(0, "n", range(1, len(m) + 1))
    m["lote"] = (m["n"] - 1) // POR_LOTE + 1

    SAL.mkdir(parents=True, exist_ok=True)
    m.to_csv(SAL / "13e_pares_400.csv", index=False, encoding="utf-8-sig", sep=";")

    # LO QUE VE QUIEN JUZGA. Sin `sim` --es el modelo que se esta midiendo-- y sin
    # `estrato` ni `particion`, que tampoco le incumben.
    j = m[["n", "lote", "comun", "raro", "emp_comun", "emp_raro"]].copy()
    j["mismo"] = ""
    j["nota"] = ""
    j.to_csv(SAL / "13e_para_juzgar.csv", index=False, encoding="utf-8-sig", sep=";")

    print("\n  muestra final: {} pares".format(len(m)))
    print("  por estrato  :", dict(m["estrato"].value_counts().sort_index()))
    print("  por particion:", dict(m["particion"].value_counts()))
    print("  lotes de {}  : {}".format(POR_LOTE, m["lote"].max()))
    print("\n  para juzgar -> {}".format(SAL / "13e_para_juzgar.csv"))
    print("  metadatos   -> {}   (NO abrir antes de juzgar)".format(
        SAL / "13e_pares_400.csv"))
    print("\n  rellena `mismo` con si / no / duda. No hay columna de sueldo, a")
    print("  proposito, y tampoco la similitud del modelo.")


if __name__ == "__main__":
    main()
