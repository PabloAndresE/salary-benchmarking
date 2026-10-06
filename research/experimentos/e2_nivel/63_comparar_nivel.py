"""D-049 d: pinball de las variantes de nivel frente al producto de hoy (`juez_vecinos`, la tabla).

Pareado por (empresa, cargo), IC por bootstrap de empresas (el de `54`). En todos los votos y
donde la variante cambia la banda.

    ../../../.venv/bin/python 63_comparar_nivel.py nivel_v1 nivel_v1_placebo [...]
"""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
spec = importlib.util.spec_from_file_location("e54", AQUI / "54_pinball.py")
e54 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e54)
SUF = "_50_clusters_confiable_cargos_venv.parquet"


def leer(v):
    return pd.read_parquet(SAL / ("54_" + v + SUF))[["empresa", "cargo", "pinball", "base"]]


REF = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--ref=")), "juez_vecinos")
ref = leer(REF)
out = ["63 · NIVEL (D-049 d): diferencia de pinball frente a {}; negativo = mejor".format(REF)]
for v in [a for a in sys.argv[1:] if not a.startswith("--ref=")]:
    d = ref.merge(leer(v), on=["empresa", "cargo"], suffixes=("_0", "_1"))
    d["dif"] = d["pinball_1"] - d["pinball_0"]
    rng = np.random.default_rng(11)
    m, lo, hi = e54.ic(d["dif"].to_numpy(), d["empresa"].to_numpy(), rng)
    a = d[d["dif"].abs() > 1e-6]          # mas chico es ruido de redondeo (1e-11)
    ma, la, ha = e54.ic(a["dif"].to_numpy(), a["empresa"].to_numpy(), rng)
    veredicto = "EMPEORA" if la > 0 else ("MEJORA" if ha < 0 else "no se distingue")
    out.append("   {:<20} todos {:+.5f} [{:+.5f}, {:+.5f}] | donde actua ({:,} votos, {:.1%}) {:+.5f} [{:+.5f}, {:+.5f}] {}".format(
        v, m, lo, hi, len(a), len(a) / len(d), ma, la, ha, veredicto))
(SAL / "63_comparar_nivel.txt").open("a", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out))
