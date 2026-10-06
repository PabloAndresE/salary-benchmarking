"""La base v19 = la v18 con el nivel de Qwen v2 y su clasificador para la consulta (D-049), y, con
`--idioma`, los titulos en ingles en el grupo de su traduccion (D-050).

    ../../../.venv/bin/python 65_base_v19.py [--idioma]

SALIDAS: demo/base_v19.npz, salidas/65_base_v19.txt
"""
import argparse
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


def main(con_idioma):
    t0 = time.time()
    e41, e54 = cargar("e41", "41_base_v16.py"), cargar("e54", "54_pinball.py")
    marco = e41.cargar_marco()
    celdas = sorted(set(marco["cargo_norm"].astype(str)))
    b15 = np.load(RAIZ / "demo" / "base_v15.npz", allow_pickle=True)
    emb = e41.embeddings(celdas, b15)
    grupos = e54.grupos_de_clusters("50_clusters_confiable_cargos.parquet")
    unidos = 0
    if con_idioma:
        r = pd.read_parquet(SAL / "64_idioma_resueltos.parquet")
        for t, d in zip(r["titulo"], r["destino"]):
            if d and t in grupos and d in grupos and grupos[t] != grupos[d]:
                grupos[t] = grupos[d]
                unidos += 1
    q = pd.read_parquet(SAL / "60_niveles_qwen_v2.parquet")
    niveles = dict(zip(q["titulo"].astype(str), q["nivel"].astype(int)))
    b = BaseReferencia.construir(marco, emb, e41._Ajustes.get_sbu, umbral_fusion=None,
                                 capa0=c0mod.nueva("v1"), grupos=grupos, niveles=niveles)
    b.guardar(RAIZ / "demo" / "base_v19.npz")
    out = ["65 · BASE v19: nivel de Qwen v2 + clasificador de la consulta (D-049){}".format(
               "; titulos en ingles unidos a su traduccion (D-050): {:,}".format(unidos) if con_idioma else ""),
           "titulos {:,}; grupos {:,}; con nivel {:.1%}; clasificador: {}".format(
               len(b.celdas), len(set(np.asarray(b.grupo).tolist())), np.isfinite(b.nivel).mean(),
               "si" if b.clf_nivel is not None else "NO"),
           "({:.0f} s)".format(time.time() - t0)]
    (SAL / "65_base_v19.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--idioma", action="store_true")
    main(ap.parse_args().idioma)
