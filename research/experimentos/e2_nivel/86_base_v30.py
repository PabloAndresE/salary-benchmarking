"""La base v30 = la v28 con D-080: niveles 4-5 sin los votos de dueno (gerente contratado) y el efecto de tamano
propio de cada cargo (D-079) estimado sin ellos. Con todas las empresas y el nivel por grupo, como en la medicion.

    ../../../.venv/bin/python 86_base_v30.py
"""
import importlib.util
import pathlib
import sys

import numpy as np

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402

spec = importlib.util.spec_from_file_location("e41", AQUI / "41_base_v16.py")
e41 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e41)
marco = e41.cargar_marco()
b = BaseReferencia.cargar(RAIZ / "demo" / "base_v28.npz", e41._Ajustes.get_sbu)
nivel_original = np.array(b.nivel, copy=True)
b.nivel_por_grupo()
res, limpio = b.sin_duenos(marco)
print("sin duenos:", res)
print("tamano:", b.estandarizar_tamano(limpio, por_cargo=True)["delta"])
b.nivel = nivel_original                      # la base guarda el nivel de siempre; la API arma el de grupo al cargar
b.guardar(RAIZ / "demo" / "base_v30.npz")
print("base_v30 lista")
