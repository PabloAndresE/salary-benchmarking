"""D-049: el clasificador pequeno de la consulta (regresion logistica embedding -> nivel de Qwen).

Se mide contra Qwen en titulos que no vio: particion por GRUPO de `base_v18` (80/20), para que
las grafias de un mismo puesto no queden a los dos lados. Ademas, los titulos SIN palabra de rango.

    ../../../.venv/bin/python 62_clasificador_nivel.py [--etiquetas 60_niveles_qwen_v2.parquet]

SALIDA: salidas/62_clasificador_nivel.txt
"""
import argparse
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.base_referencia import P_NIVEL_CLF, _entrenar_clf_nivel  # noqa: E402
from benchmarking.producto.nivel import nivel_rubrica  # noqa: E402


def main(archivo):
    b = np.load(RAIZ / "demo" / "base_v18.npz", allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    Z = b["Z"].astype(float)
    Z /= np.linalg.norm(Z, axis=1, keepdims=True)
    q = pd.read_parquet(SAL / archivo).set_index("titulo")["nivel"]
    niv = np.array([float(q.get(c, np.nan)) for c in celdas])
    niv[niv < 1] = np.nan
    grupo = b["grupo"].astype(int)
    rng = np.random.default_rng(20261006)
    gs = np.unique(grupo)
    prueba = np.isin(grupo, rng.choice(gs, len(gs) // 5, replace=False))
    tr = niv.copy()
    tr[prueba] = np.nan
    W, bb, k = _entrenar_clf_nivel(Z, tr)
    z = Z @ W.T + bb
    p = np.exp(z - z.max(1, keepdims=True))
    p /= p.sum(1, keepdims=True)
    pred, pmax = k[p.argmax(1)], p.max(1)
    per = b["personas"].astype(float)
    sin = np.array([nivel_rubrica(c) is None for c in celdas])
    out = ["62 · CLASIFICADOR DE NIVEL (embedding -> nivel de Qwen, {})".format(archivo)]
    for nombre, s in (("todos", prueba), ("sin palabra de rango", prueba & sin)):
        s = s & np.isfinite(niv)
        da = s & (pmax >= P_NIVEL_CLF)
        out.append("{:<22} n={:,}  acierto {:.1%} (por personas {:.1%}); |error| medio {:.2f}; da nivel en {:.1%},"
                   " y ahi acierta {:.1%}".format(
                       nombre, s.sum(), (pred[s] == niv[s]).mean(), np.average(pred[s] == niv[s], weights=per[s]),
                       np.abs(pred[s] - niv[s]).mean(), da.sum() / s.sum(), (pred[da] == niv[da]).mean()))
    out.append(pd.crosstab(pd.Series(niv[prueba & np.isfinite(niv)].astype(int), name="qwen"),
                           pd.Series(pred[prueba & np.isfinite(niv)], name="clasificador")).to_string())
    (SAL / "62_clasificador_nivel.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--etiquetas", default="60_niveles_qwen.parquet")
    main(ap.parse_args().etiquetas)
