"""D-086: cortes de confianza por terciles de `incert_centro` en los votos apartados (mas la regla del ancho, D-069).

    ../../../.venv/bin/python 88_cortes_confianza.py VARIANTE

SALIDA: se agrega a salidas/88_cortes_confianza.txt
"""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
spec = importlib.util.spec_from_file_location("e78", AQUI / "78_confianza.py")
e78 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e78)


def main(var):
    d = pd.read_parquet(SAL / "54_{}_50_clusters_confiable_cargos_venv.parquet".format(var))
    d = d[np.isfinite(d["referencia_log"]) & np.isfinite(d["incert_centro"])].copy()
    d["err"] = (d["voto"] - d["referencia_log"]).abs()
    d["r"] = np.exp(d["p75_log"] - d["p25_log"])
    c1, c2 = np.quantile(d["incert_centro"], [1 / 3, 2 / 3])
    c = np.where(d["incert_centro"] <= c1, "ALTA", np.where(d["incert_centro"] <= c2, "MEDIA", "BAJA"))
    d["vieja"] = d["confianza"]
    d["nueva"] = e78.regla_nueva(c, d["r"].to_numpy())
    out = ["88 · CORTES DE CONFIANZA (D-086), {}: terciles de incert_centro = {:.3f} / {:.3f}".format(var, c1, c2)]
    res = {}
    for regla in ("vieja", "nueva"):
        out.append("regla {}:".format(regla))
        for cl in ("ALTA", "MEDIA", "BAJA"):
            x = d[d[regla] == cl]
            m, lo, hi = e78.mediana_dos_vias(x)
            res[(regla, cl)] = (m, lo, hi)
            out.append("   {:<6} n={:>6,} ({:.0%})  error {:.1f} % [{:.1f}, {:.1f}]  p75/p25 mediano {:.2f}".format(
                cl, len(x), len(x) / len(d), 100 * (np.exp(m) - 1), 100 * (np.exp(lo) - 1), 100 * (np.exp(hi) - 1),
                x["r"].median()))
    a, me, ba = (res[("nueva", k)] for k in ("ALTA", "MEDIA", "BAJA"))
    ok = a[0] < me[0] < ba[0] and a[2] < me[1] and me[2] < ba[1]
    out.append("CRITERIO (orden sin solape de vecinos): {}".format("CUMPLE" if ok else "NO CUMPLE"))
    with open(SAL / "88_cortes_confianza.txt", "a", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
