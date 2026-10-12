"""La base v31 = la v30 con el techo de la cima en MICRO y PEQUENA (D-082), estimado con todas las empresas sin los
votos de dueno (D-080) y el nivel por grupo.

    ../../../.venv/bin/python 87_base_v31.py
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
b = BaseReferencia.cargar(RAIZ / "demo" / "base_v30.npz", e41._Ajustes.get_sbu)
nivel_original = np.array(b.nivel, copy=True)
b.nivel_por_grupo()
b.tamano_estandar = True
piso = 1.25
i = marco["cargo_norm"].astype(str).map(b.idx)
j = i.fillna(0).astype(int).to_numpy()
dueno = (i.notna().to_numpy() & np.isin(b.nivel[j], [4.0, 5.0]) & (np.exp(marco["y"].to_numpy(float)) < piso))
print("techo:", b.preparar_techo_cima(marco[~dueno]))
b.nivel = nivel_original
b.guardar(RAIZ / "demo" / "base_v31.npz")
print("base_v31 lista")
