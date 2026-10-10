"""D-065: pinball de la limpieza de atipicos frente al producto sin tamano (`tam_A`).

Primaria: los votos apartados que NO son atipicos por la regla (columna `atipico` de la variante `atipicos`).
Secundaria: todos. IC por bootstrap de empresas (el de `54`); "donde actua" = la banda cambia.

    ../../../.venv/bin/python 75_atipicos.py

SALIDA: salidas/75_atipicos.txt
"""
import importlib.util
import pathlib

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
spec = importlib.util.spec_from_file_location("e54", AQUI / "54_pinball.py")
e54 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e54)
SUF = "_50_clusters_confiable_cargos_venv.parquet"


def main():
    ref = pd.read_parquet(SAL / ("54_tam_A" + SUF))[["empresa", "cargo", "pinball"]]
    marca = pd.read_parquet(SAL / ("54_atipicos" + SUF))[["empresa", "cargo", "atipico"]]
    out = ["75 · ATIPICOS (D-065): diferencia de pinball frente a tam_A; negativo = mejor",
           "votos apartados atipicos por la regla: {}".format(marca["atipico"].value_counts().to_dict())]
    for v in ("atipicos", "atipicos_placebo"):
        d = ref.merge(pd.read_parquet(SAL / ("54_" + v + SUF))[["empresa", "cargo", "pinball"]],
                      on=["empresa", "cargo"], suffixes=("_0", "_1")).merge(marca, on=["empresa", "cargo"])
        d["dif"] = d["pinball_1"] - d["pinball_0"]
        for nombre, dd in (("PRIMARIA (no atipicos)", d[d["atipico"] == ""]), ("secundaria (todos)", d)):
            rng = np.random.default_rng(11)
            a = dd[dd["dif"].abs() > 1e-6]
            m, lo, hi = e54.ic(a["dif"].to_numpy(), a["empresa"].to_numpy(), rng)
            mt, lt, ht = e54.ic(dd["dif"].to_numpy(), dd["empresa"].to_numpy(), rng)
            out.append("   {:<18} {:<24} todos {:+.5f} [{:+.5f}, {:+.5f}] | donde actua ({:,} votos) {:+.5f} [{:+.5f}, {:+.5f}] {}".format(
                v, nombre, mt, lt, ht, len(a), m, lo, hi,
                "EMPEORA" if lo > 0 else ("MEJORA" if hi < 0 else "no se distingue")))
    (SAL / "75_atipicos.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
