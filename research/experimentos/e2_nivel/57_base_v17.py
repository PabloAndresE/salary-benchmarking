"""D-046: la base v17 = capa 0 v1 + clustering con la v3 en la zona confiable (sin sinonimos).

Mismos datos y vectores que la v15 y la v16 (`41`). Los grupos salen de
`50_clusters_confiable_cargos.parquet` (cada grupo de la capa 0 de base_v16 es un nodo) y se inyectan con
`construir(grupos=...)`. Informe: el mismo de `41`, frente a la v15.

    python3 57_base_v17.py         (Python del sistema: BigQuery)

SALIDAS: demo/base_v17.npz, salidas/57_base_v17.txt
"""
import importlib.util
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto import capa0 as c0mod  # noqa: E402
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    t0 = time.time()
    e41, e54 = cargar("e41", "41_base_v16.py"), cargar("e54", "54_pinball.py")
    marco = e41.cargar_marco()
    celdas = sorted(set(marco["cargo_norm"].astype(str)))
    per_t = marco.groupby(marco["cargo_norm"].astype(str))["id_hash"].nunique()
    b15 = np.load(RAIZ / "demo" / "base_v15.npz", allow_pickle=True)
    emb = e41.embeddings(celdas, b15)
    grupos = e54.grupos_de_clusters("50_clusters_confiable_cargos.parquet")
    b17 = BaseReferencia.construir(marco, emb, e41._Ajustes.get_sbu, umbral_fusion=None,
                                   capa0=c0mod.nueva("v1"), grupos=grupos)
    b17.guardar(RAIZ / "demo" / "base_v17.npz")
    c15 = [str(c) for c in b15["celdas"]]
    m15, m17 = e41.miembros(c15, b15["grupo"]), e41.miembros(b17.celdas, b17.grupo)
    comunes = [c for c in celdas if c in m15 and c in m17]
    cambia = [c for c in comunes if m15[c] != m17[c]]
    tot = int(per_t.sum())
    i15 = {c: i for i, c in enumerate(c15)}
    i17 = {c: i for i, c in enumerate(b17.celdas)}
    pct = np.expm1(np.array([np.asarray(b17.bandas, float)[i17[c]] - np.asarray(b15["bandas"], float)[i15[c]]
                             for c in cambia]))
    mueve = np.nanmax(np.abs(pct), axis=1) > 0.05
    out = ["57 · BASE v17: CAPA 0 v1 + CLUSTERING CON LA v3 EN LA ZONA CONFIABLE (D-046)",
           "titulos {:,}; grupos v15 {:,} -> v17 {:,}; el mayor de la v17: {} titulos".format(
               len(celdas), len(set(b15['grupo'].tolist())), len(set(np.asarray(b17.grupo).tolist())),
               int(pd.Series(np.asarray(b17.grupo)).value_counts().iloc[0])),
           "titulos que cambian de grupo frente a la v15: {:,} ({:.1%}); personas-titulo {:.1%}".format(
               len(cambia), len(cambia) / len(comunes), per_t[cambia].sum() / tot),
           "bandas de los que cambian (exp(dif) - 1), mediana del valor absoluto: " + ", ".join(
               "{} {:.1%}".format(n, np.nanmedian(np.abs(pct[:, k]))) for k, n in enumerate(("p10", "p25", "p50", "p75"))),
           "alguna banda se mueve > 5 %: {:,} titulos, {:.1%} de las personas-titulo".format(
               int(mueve.sum()), per_t[[c for c, x in zip(cambia, mueve) if x]].sum() / tot),
           "({:.0f} s)".format(time.time() - t0)]
    (SAL / "57_base_v17.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
