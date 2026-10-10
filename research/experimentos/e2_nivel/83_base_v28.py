"""La base v28 = la v27 con el clasificador «es un cargo» de D-075 (el medido: pesos, sesgo y umbral de `82`).

    ../../../.venv/bin/python 83_base_v28.py
"""
import pathlib
import sys

import numpy as np

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402

c = np.load(AQUI / "salidas" / "82_clasificador.npz")
b = BaseReferencia.cargar(RAIZ / "demo" / "base_v27.npz", cargar_settings().get_sbu)
b.clf_cargo = (c["W"], float(c["b"]), float(c["u"]))
b.guardar(RAIZ / "demo" / "base_v28.npz")
print("base_v28 con clasificador es-cargo, u = {:.4f}".format(float(c["u"])))
