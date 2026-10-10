"""Protocolo v2 (2026-10-10): variante frente al producto y frente a su placebo.

Votos: la UNION de los votos donde actuan la variante o su placebo. IC 95 % por bootstrap en dos vias (empresa x
cargo, pesos multinomiales, media por voto), 400 replicas; tambien la media por empresa. Variante - placebo pareado.

    ../../../.venv/bin/python 77_comparar_v2.py REF VARIANTE PLACEBO [--producto]   (--producto: criterio de no
    inferioridad, extremo superior < +0,001)

SALIDA: se agrega a salidas/77_comparar_v2.txt
"""
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
SUF = "_50_clusters_confiable_cargos_venv.parquet"
MARGEN = 0.001


def leer(v):
    return pd.read_parquet(SAL / ("54_" + v + SUF))[["empresa", "cargo", "pinball"]]


def dos_vias(d, col, n=400, semilla=11):
    rng = np.random.default_rng(semilla)
    E, C = d["empresa"].unique(), d["cargo"].unique()
    ei = pd.Series(np.arange(len(E)), index=E)[d["empresa"]].to_numpy()
    ci = pd.Series(np.arange(len(C)), index=C)[d["cargo"]].to_numpy()
    x = d[col].to_numpy(float)
    b = []
    for _ in range(n):
        w = rng.multinomial(len(E), np.full(len(E), 1 / len(E)))[ei] * rng.multinomial(len(C), np.full(len(C), 1 / len(C)))[ci]
        b.append((w * x).sum() / max(w.sum(), 1))
    return float(x.mean()), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def main(ref, var, pla, producto):
    d = leer(ref).merge(leer(var), on=["empresa", "cargo"], suffixes=("", "_v")).merge(
        leer(pla).rename(columns={"pinball": "pinball_p"}), on=["empresa", "cargo"])
    d["dv"], d["dp"] = d["pinball_v"] - d["pinball"], d["pinball_p"] - d["pinball"]
    d["vp"] = d["pinball_v"] - d["pinball_p"]
    u = d[(d["dv"].abs() > 1e-6) | (d["dp"].abs() > 1e-6)]
    out = ["{} frente a {} (placebo {}): union {:,} votos, {:,} empresas, {:,} cargos".format(
        var, ref, pla, len(u), u["empresa"].nunique(), u["cargo"].nunique())]
    if len(u) == 0:
        out.append("   no actua")
    else:
        for nom, col in (("variante - producto", "dv"), ("placebo - producto", "dp"), ("variante - placebo", "vp")):
            m, lo, hi = dos_vias(u, col)
            emp = u.groupby("empresa")[col].mean().mean()
            out.append("   {:<20} {:+.5f} [{:+.5f}, {:+.5f}] (dos vias)  | media por empresa {:+.5f}".format(nom, m, lo, hi, emp))
        m, lo, hi = dos_vias(u, "dv")
        mp, lop, hip = dos_vias(u, "vp")
        if producto:
            ok = hi < MARGEN
            out.append("   CRITERIO (regla de producto, no inferior: extremo < +{}): {}".format(MARGEN, "CUMPLE" if ok else "NO CUMPLE"))
        else:
            ok = hi < 0 and hip < 0
            out.append("   CRITERIO (precision: frente al producto y al placebo, IC bajo 0): {}".format("CUMPLE" if ok else "NO CUMPLE"))
    with open(SAL / "77_comparar_v2.txt", "a", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    main(a[0], a[1], a[2], "--producto" in sys.argv)
