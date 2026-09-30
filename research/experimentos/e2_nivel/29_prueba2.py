"""`prueba 2`: 400 pares nuevos, el examen del cross-encoder v2. D-038.

POR QUE HACE FALTA. `prueba` se abrio una vez para H1 (D-036). Todo lo que se mida despues
sobre ella es exploratorio: la v2 se disena mirando el analisis de errores y con una rubrica
(v5) escrita despues de H1. Para que "la v2 le gana a la v1" signifique algo, hace falta un
examen que nadie haya mirado. Se arma y se juzga ANTES de entrenar la v2.

EL MISMO MARCO QUE `20` (y que `13e`), para que sea comparable: pares entre grupos distintos
de `base_v15` con coseno 0,90-1,01, del censo de `16`; estratos bajo (0,90-0,93), banda
(0,93-0,97, en cuatro tramos) y alto (>= 0,97). Cupos de `20`: bajo 60, banda el resto, alto
lo que quede (se agoto en `20`).

LO QUE SE EXCLUYE:
    1. cualquier par que toque un grupo de la plata (`16`): la v1 y la v2 se entrenan con esos
       cargos;
    2. los pares ya juzgados: `13e` (400), `13a` (48) y `20` (400), por par de grupos (y por
       titulo para `13a`, cuyos grupos se leen del propio censo);
    3. los que la capa 0 fusiona por el grado (`mismo_salvo_grado`, D-037): nunca llegan al
       juez (Enmienda 5 de D-036).
El lote de entrenamiento de la zona dificil (siguiente paso de D-038) excluira los GRUPOS de
`prueba 2`.

SE JUZGA A CIEGAS CON LA RUBRICA v5, en 8 lotes de 50, sin `sim`, estrato ni tramo.

Usa el Python del sistema (necesita `pyarrow` para el censo; el `.venv` del cross no lo trae).

SALIDAS (con titulos; se versionan con -f)
    29_prueba2_pares.csv        metadatos: grupos, sim, estrato, tramo. NO se abre antes de juzgar
    29_prueba2_para_juzgar.csv  n, lote, comun, raro, emp_comun, emp_raro, mismo, nota
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.nivel import mismo_salvo_grado  # noqa: E402

CENSO = SAL / "16_censo.parquet"
PLATA = SAL / "16_pares_10000.csv"
ORO_400 = SAL / "13e_pares_400.csv"
ORO_48 = SAL / "13_para_juzgar.csv"
NUEVOS_400 = SAL / "20_pares_400.csv"
META = SAL / "29_prueba2_pares.csv"
JUZGAR = SAL / "29_prueba2_para_juzgar.csv"
SEM = 20261003
POR_LOTE = 50
TOTAL = 400
CUPO = {"bajo": 60, "alto": 60}                 # la banda se lleva el resto
TRAMOS_BANDA = np.linspace(0.93, 0.97, 5)


def leer(p):
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig")


def main():
    if JUZGAR.exists():
        p = pd.read_csv(JUZGAR, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                        keep_default_na=False)
        if (p["mismo"].str.strip() != "").any():
            raise SystemExit("{} ya tiene juicios; no se sobrescribe.".format(JUZGAR.name))

    c = pd.read_parquet(CENSO)
    print("censo de `16`: {:,} pares".format(len(c)))

    plata = leer(PLATA)
    g_plata = set(plata["g_comun"]) | set(plata["g_raro"])
    c = c[~c["g_comun"].isin(g_plata) & ~c["g_raro"].isin(g_plata)]
    print("  sin grupos de la plata: {:,}".format(len(c)))

    ya = set()
    for f in (ORO_400, NUEVOS_400):
        m = leer(f)
        ya |= {frozenset(x) for x in zip(m["g_comun"], m["g_raro"])}
    titulo_grupo = dict(zip(c["comun"], c["g_comun"])) | dict(zip(c["raro"], c["g_raro"]))
    v = leer(ORO_48)
    v.columns = [x.strip() for x in v.columns]
    t48 = set(v["comun"].astype(str)) | set(v["raro"].astype(str))
    for a, b in zip(v["comun"].astype(str), v["raro"].astype(str)):
        if a in titulo_grupo and b in titulo_grupo:
            ya.add(frozenset((titulo_grupo[a], titulo_grupo[b])))
    c = c[[frozenset(x) not in ya for x in zip(c["g_comun"], c["g_raro"])]]
    c = c[~(c["comun"].isin(t48) & c["raro"].isin(t48))]
    print("  sin pares ya juzgados (13e, 13a, 20): {:,}".format(len(c)))

    capa0 = np.array([mismo_salvo_grado(a, b) for a, b in zip(c["comun"], c["raro"])])
    c = c[~capa0].copy()
    print("  sin los que la capa 0 fusiona por el grado: {:,} (fuera {:,})".format(
        len(c), int(capa0.sum())))

    c["estrato"] = pd.cut(c["sim"], [0.90, 0.93, 0.97, 1.01],
                          labels=["bajo", "banda", "alto"], include_lowest=True)
    disp = c["estrato"].value_counts().to_dict()
    print("  disponibles por estrato:", {k: disp.get(k, 0) for k in ("bajo", "banda", "alto")})

    alto = c[c["estrato"] == "alto"]
    n_alto = min(len(alto), CUPO["alto"])
    n_bajo = CUPO["bajo"]
    n_banda = TOTAL - n_alto - n_bajo
    print("\n  cupos: bajo {}, banda {}, alto {} (el alto se agoto en `20`)".format(
        n_bajo, n_banda, n_alto))

    trozos = [alto.sample(n_alto, random_state=SEM).assign(tramo=""),
              c[c["estrato"] == "bajo"].sample(n_bajo, random_state=SEM).assign(tramo="")]
    banda = c[c["estrato"] == "banda"].copy()
    banda["tramo"] = pd.cut(banda["sim"], TRAMOS_BANDA, include_lowest=True).astype(str)
    # Reparto igual entre los cuatro tramos; lo que un tramo no llena pasa a los demas (la
    # regla de `16` y `20`). El tramo alto de la banda tambien se agoto en `20`, asi que
    # `prueba 2` queda con coseno algo mas bajo que `prueba`: la comparacion v2 / v1 es sobre
    # los mismos pares y no se sesga, pero se declara.
    grupos = [gr for _, gr in banda.groupby("tramo", observed=True)]
    cupo = [0] * len(grupos)
    falta = n_banda
    abiertos = list(range(len(grupos)))
    while falta and abiertos:
        por, resto = divmod(falta, len(abiertos))
        for j, k in enumerate(list(abiertos)):
            quiero = por + (1 if j < resto else 0)
            dar = min(quiero, len(grupos[k]) - cupo[k])
            cupo[k] += dar
            falta -= dar
            if cupo[k] == len(grupos[k]):
                abiertos.remove(k)
    if falta:
        raise SystemExit("la banda no alcanza: faltan {} pares".format(falta))
    for gr, q in zip(grupos, cupo):
        trozos.append(gr.sample(q, random_state=SEM))

    m = pd.concat(trozos, ignore_index=True)
    assert len(m) == TOTAL, len(m)
    assert m[["g_comun", "g_raro"]].apply(frozenset, axis=1).nunique() == TOTAL
    m["particion"] = "prueba2"
    m["origen"] = "29"
    m = m.sample(frac=1.0, random_state=SEM + 1).reset_index(drop=True)
    m.insert(0, "n", range(1, len(m) + 1))
    m["lote"] = (m["n"] - 1) // POR_LOTE + 1

    m.to_csv(META, index=False, encoding="utf-8-sig", sep=";")
    j = m[["n", "lote", "comun", "raro", "emp_comun", "emp_raro"]].copy()
    j["mismo"] = ""
    j["nota"] = ""
    j.to_csv(JUZGAR, index=False, encoding="utf-8-sig", sep=";")

    print("\n  muestra: {} pares".format(len(m)))
    print("  por estrato:", dict(m["estrato"].value_counts().sort_index()))
    print("  banda por tramo:", dict(m.loc[m["estrato"] == "banda", "tramo"]
                                     .value_counts().sort_index()))
    print("  grupos distintos: {:,}".format(len(set(m["g_comun"]) | set(m["g_raro"]))))
    print("\n  para juzgar -> {}   (rubrica v5, a ciegas)".format(JUZGAR.name))
    print("  metadatos   -> {}   (NO abrir antes de juzgar)".format(META.name))


if __name__ == "__main__":
    main()
