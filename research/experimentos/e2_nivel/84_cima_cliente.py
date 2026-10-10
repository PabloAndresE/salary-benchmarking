"""D-078: la banda del GG con estructura solo para clientes con otros cargos de nivel 5 (con las salidas de `prima`
y `cima`). IC por bootstrap de empresas (1.000).

    ../../../.venv/bin/python 84_cima_cliente.py

SALIDA: salidas/84_cima_cliente.txt
"""
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
SUF = "_50_clusters_confiable_cargos_venv.parquet"


def ic(x, n=1000, semilla=78):
    rng = np.random.default_rng(semilla)
    b = [rng.choice(x, len(x)).mean() for _ in range(n)]
    return float(np.mean(x)), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def main():
    b = np.load(RAIZ / "demo" / "base_v28.npz", allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    g = b["grupo"]
    gg = g[celdas.index("GERENTE GENERAL")]
    tit_gg = {c for c, x in zip(celdas, g) if x == gg}
    p = pd.read_parquet(SAL / ("54_prima" + SUF))
    c = pd.read_parquet(SAL / ("54_cima" + SUF))[["empresa", "cargo", "pinball"]].rename(columns={"pinball": "pc"})
    d = p.merge(c, on=["empresa", "cargo"])
    d["es_gg"] = d["cargo"].isin(tit_gg)
    estructura = set(d.loc[(~d["es_gg"]) & (d["nivel"] == 5), "empresa"])
    x = d[d["es_gg"]].groupby("empresa").agg(p0=("pinball", "mean"), p1=("pc", "mean")).reset_index()
    x["con"] = x["empresa"].isin(estructura)
    rng = np.random.default_rng(79)
    azar = set(rng.choice(x["empresa"], int(x["con"].sum()), replace=False))
    x["plac"] = np.where(x["empresa"].isin(azar), x["p1"], x["p0"])
    x["var"] = np.where(x["con"], x["p1"], x["p0"])
    out = ["84 · GG SEGUN LA ESTRUCTURA DEL CLIENTE (D-078)",
           "empresas apartadas con voto GG: {}; con estructura (otro nivel 5): {}".format(len(x), int(x["con"].sum()))]
    for nom, xx in (("CON estructura", x[x["con"]]), ("sin estructura", x[~x["con"]])):
        m, lo, hi = ic((xx["p1"] - xx["p0"]).to_numpy())
        out.append("   {:<15} banda con estructura - banda de siempre: {:+.4f} [{:+.4f}, {:+.4f}] (n={})".format(nom, m, lo, hi, len(xx)))
    xc = x[x["con"]]
    m, lo, hi = ic((xc["var"] - xc["plac"]).to_numpy())
    out.append("   variante - placebo (empresas con estructura): {:+.4f} [{:+.4f}, {:+.4f}]".format(m, lo, hi))
    m0, l0, h0 = ic((xc["p1"] - xc["p0"]).to_numpy())
    ok = h0 < 0 and hi < 0
    out.append("CRITERIO (mejora con estructura y frente al placebo): {}".format("CUMPLE" if ok else "NO CUMPLE"))
    (SAL / "84_cima_cliente.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
