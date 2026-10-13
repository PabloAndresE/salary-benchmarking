"""T-009, etapa 1 (reconocer): el cross-encoder v9 frente a la v3, con juicios humanos.

    .venv/bin/python research/tesis/t09_etapa1.py

- lejos: los 100 pares de `52` (juicio ciego del autor, rubrica v7)
- cerca: `prueba` (13e y 20) y `prueba 2` (29), juicio humano
AUC de P(mismo) y diferencia v9 - v3 con IC 95 % por bootstrap estratificado de pares (2.000 replicas).
SALIDA: salidas/t09_etapa1.txt
"""
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.juez import cargar  # noqa: E402

MODELOS = {"v3": E2 / "salidas/22_modelos_v3/elegido", "v9": E2 / "salidas/t09_modelos/elegido"}


def leer(f):
    return pd.read_csv(E2 / "salidas" / f, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                       keep_default_na=False)


def conjuntos():
    v = leer("52_validacion_para_juzgar.csv")
    lejos = pd.DataFrame({"a": v["a"], "b": v["b"], "y": v["mismo"].str.strip().str.lower()})
    cerca = []
    for pares, juicio in (("13e_pares_400.csv", "13e_para_juzgar.csv"), ("20_pares_400.csv", "20_para_juzgar.csv"),
                          ("29_prueba2_pares.csv", "29_prueba2_para_juzgar.csv")):
        p, j = leer(pares), leer(juicio)
        n = set(p.loc[p["particion"].isin(["prueba", "prueba2"]), "n"])
        j = j[j["n"].isin(n)]
        cerca.append(pd.DataFrame({"a": j["comun"], "b": j["raro"], "y": j["mismo"].str.strip().str.lower()}))
    cerca = pd.concat(cerca, ignore_index=True)
    out = {}
    for nom, d in (("lejos (52, autor ciego)", lejos), ("cerca (prueba + prueba 2)", cerca)):
        d = d[d["y"].isin(["si", "no"])].reset_index(drop=True)
        d["y"] = (d["y"] == "si").astype(int)
        out[nom] = d
    return out


def auc(y, p):
    from sklearn.metrics import roc_auc_score
    return roc_auc_score(y, p)


def main():
    conj = conjuntos()
    P = {}
    for m, ruta in MODELOS.items():
        j = cargar(ruta)
        assert j is not None, ruta
        for nom, d in conj.items():
            P[(m, nom)] = np.asarray(j.P(list(zip(d["a"], d["b"]))), dtype=float)
    rng = np.random.default_rng(20261013)
    out = ["T-009 etapa 1 · AUC de P(mismo), cross-encoder v9 (reentrenado) frente a v3 (producto)"]
    for nom, d in conj.items():
        y = d["y"].to_numpy()
        a3, a9 = auc(y, P[("v3", nom)]), auc(y, P[("v9", nom)])
        i1, i0 = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
        bs = []
        for _ in range(2000):
            k = np.concatenate([rng.choice(i1, len(i1)), rng.choice(i0, len(i0))])
            bs.append(auc(y[k], P[("v9", nom)][k]) - auc(y[k], P[("v3", nom)][k]))
        lo, hi = np.percentile(bs, [2.5, 97.5])
        acc = {m: ((P[(m, nom)] >= 0.5).astype(int) == y).mean() for m in MODELOS}
        out.append("  {:<26} n={:>4} (si {:>3})  AUC v3 {:.4f}  v9 {:.4f}  v9-v3 {:+.4f} [{:+.4f}, {:+.4f}]  "
                   "acierto con P>=0,5: v3 {:.1%}  v9 {:.1%}".format(nom, len(y), int(y.sum()), a3, a9, a9 - a3, lo, hi,
                                                                     acc["v3"], acc["v9"]))
    (AQUI / "salidas" / "t09_etapa1.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
