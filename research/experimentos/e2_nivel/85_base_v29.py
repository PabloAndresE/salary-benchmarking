"""La base v29 = la v28 con el efecto de tamano propio de cada cargo, encogido hacia el del nivel (D-079), estimado
con todas las empresas y el nivel por grupo (como en la medicion).

    ../../../.venv/bin/python 85_base_v29.py
"""
import importlib.util
import pathlib
import sys

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402

spec = importlib.util.spec_from_file_location("e41", AQUI / "41_base_v16.py")
e41 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e41)
marco = e41.cargar_marco()
c = BaseReferencia.cargar(RAIZ / "demo" / "base_v28.npz", e41._Ajustes.get_sbu)
c.nivel_por_grupo()
print(c.estandarizar_tamano(marco, por_cargo=True))
b = BaseReferencia.cargar(RAIZ / "demo" / "base_v28.npz", e41._Ajustes.get_sbu)
b.ajuste_tam, b.delta_tam, b.delta_tam_g = c.ajuste_tam, c.delta_tam, c.delta_tam_g
b.guardar(RAIZ / "demo" / "base_v29.npz")
print("base_v29 lista")
