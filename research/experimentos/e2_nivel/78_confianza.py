"""D-069: la confianza por el centro (regla vieja) frente a centro + ancho de la banda (regla nueva).

Con los votos apartados de `tam_A`: error del centro |voto - referencia| (mediana) por clase, IC en dos vias.
Regla nueva: ALTA si c = ALTA y p75/p25 <= 2,0; BAJA si c = BAJA o p75/p25 > 3,0; MEDIA el resto.

    ../../../.venv/bin/python 78_confianza.py

SALIDA: salidas/78_confianza.txt
"""
import importlib.util
import pathlib

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
spec = importlib.util.spec_from_file_location("e77", AQUI / "77_comparar_v2.py")
e77 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e77)


def regla_nueva(c, r):
    return np.where((c == "BAJA") | (r > 3.0), "BAJA", np.where((c == "ALTA") & (r <= 2.0), "ALTA", "MEDIA"))


def mediana_dos_vias(d, n=400, semilla=11):
    rng = np.random.default_rng(semilla)
    E, C = d["empresa"].unique(), d["cargo"].unique()
    ei = pd.Series(np.arange(len(E)), index=E)[d["empresa"]].to_numpy()
    ci = pd.Series(np.arange(len(C)), index=C)[d["cargo"]].to_numpy()
    x = d["err"].to_numpy(float)
    o = np.argsort(x)
    b = []
    for _ in range(n):
        w = (rng.multinomial(len(E), np.full(len(E), 1 / len(E)))[ei]
             * rng.multinomial(len(C), np.full(len(C), 1 / len(C)))[ci]).astype(float)[o]
        cw = np.cumsum(w)
        b.append(x[o][np.searchsorted(cw, cw[-1] / 2)])
    return float(np.median(x)), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def main():
    d = pd.read_parquet(SAL / "54_tam_A_50_clusters_confiable_cargos_venv.parquet")
    d = d[np.isfinite(d["referencia_log"])].copy()
    d["err"] = (d["voto"] - d["referencia_log"]).abs()
    d["r"] = np.exp(d["p75_log"] - d["p25_log"])
    d["nueva"] = regla_nueva(d["confianza"].to_numpy(), d["r"].to_numpy())
    out = ["78 · CONFIANZA (D-069): |voto - referencia| (mediana, en log; exp-1 en %) por clase, IC en dos vias",
           "votos: {:,}".format(len(d))]
    res = {}
    for regla in ("confianza", "nueva"):
        out.append("regla {}:".format("VIEJA (centro)" if regla == "confianza" else "NUEVA (centro + ancho)"))
        for cl in ("ALTA", "MEDIA", "BAJA"):
            x = d[d[regla] == cl]
            if len(x) < 20:
                out.append("   {:<6} n={}".format(cl, len(x)))
                continue
            m, lo, hi = mediana_dos_vias(x)
            res[(regla, cl)] = (m, lo, hi)
            out.append("   {:<6} n={:>6,} ({:.0%})  error {:.1f} % [{:.1f}, {:.1f}]  | p75/p25 mediano {:.2f}".format(
                cl, len(x), len(x) / len(d), 100 * (np.exp(m) - 1), 100 * (np.exp(lo) - 1), 100 * (np.exp(hi) - 1),
                x["r"].median()))
    a, me, ba = (res.get(("nueva", k)) for k in ("ALTA", "MEDIA", "BAJA"))
    va = res.get(("confianza", "ALTA"))
    c1 = all(x is not None for x in (a, me, ba)) and a[0] < me[0] < ba[0] and a[2] < ba[1]
    c2 = a is not None and va is not None and a[0] <= va[0]
    out.append("CRITERIO: 1) orden ALTA < MEDIA < BAJA sin solape ALTA/BAJA: {} · 2) error ALTA nueva <= vieja: {} -> {}".format(
        "si" if c1 else "no", "si" if c2 else "no", "CUMPLE" if c1 and c2 else "NO CUMPLE"))
    (SAL / "78_confianza.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
