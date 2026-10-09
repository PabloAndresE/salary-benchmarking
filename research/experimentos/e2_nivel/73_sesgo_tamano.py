"""D-063: el sesgo del centro por tamano de empresa, la primaria declarada.

Por variante del `54` (tam_A, tam_B, tam_C, tam_C0, tam_C_placebo): mediana de `voto - referencia` (en %) por
segmento, en los niveles 4-5 y en todos, y su recorrido (maximo - minimo). IC del recorrido por bootstrap de
empresas (el de `54`: 400 replicas).

    ../../../.venv/bin/python 73_sesgo_tamano.py

SALIDA: salidas/73_sesgo_tamano.txt
"""
import pathlib

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
SUF = "_50_clusters_confiable_cargos_venv.parquet"
SEGS = ("MICROEMPRESA", "PEQUENA", "MEDIANA", "GRANDE")


def sesgos(d):
    return {s: float(np.median(d.loc[d["segmento"] == s, "e"])) for s in SEGS if (d["segmento"] == s).sum() >= 30}


def recorrido(x):
    return float(np.exp(max(x.values())) - np.exp(min(x.values()))) if x else np.nan


def main():
    out = ["73 · SESGO DEL CENTRO POR TAMANO (D-063): mediana de voto - referencia, en %; recorrido = max - min"]
    rng = np.random.default_rng(11)
    for v in ("tam_A", "tam_B", "tam_C", "tam_C0", "tam_C_placebo"):
        f = SAL / ("54_" + v + SUF)
        if not f.exists():
            out.append("   {:<14} (falta)".format(v))
            continue
        d = pd.read_parquet(f)
        d = d[d["segmento"].isin(SEGS) & np.isfinite(d["referencia_log"])].copy()
        d["e"] = d["voto"] - d["referencia_log"]
        for nombre, dd in (("niveles 4-5", d[d["nivel"].isin([4.0, 5.0])]), ("todos", d)):
            s = sesgos(dd)
            emp = dd["empresa"].unique()
            reps = []
            for _ in range(400):
                b = rng.choice(emp, len(emp))
                bb = dd.set_index("empresa").loc[b].reset_index()
                reps.append(recorrido(sesgos(bb)))
            lo, hi = np.nanpercentile(reps, [2.5, 97.5])
            out.append("   {:<14} {:<12} {}  recorrido {:.1f} [{:.1f}, {:.1f}] pts  ({:,} votos)".format(
                v, nombre, "  ".join("{} {:+.1f}%".format(k[:3], 100 * (np.exp(x) - 1)) for k, x in s.items()),
                100 * recorrido(s), 100 * lo, 100 * hi, len(dd)))
    (SAL / "73_sesgo_tamano.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
