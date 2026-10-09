"""La base v26 = la v25 con el tamano de empresa por nivel (D-063): `ajuste_tam` y `delta_tam`, estimados con TODAS
las empresas y el nivel por grupo (como en la medicion). Se aplican solo cuando se conoce el tamano del cliente.

    ../../../.venv/bin/python 74_base_v26.py

SALIDAS: demo/base_v26.npz, salidas/74_base_v26.txt
"""
import importlib.util
import pathlib
import sys

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402


def main():
    spec = importlib.util.spec_from_file_location("e41", AQUI / "41_base_v16.py")
    e41 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e41)
    marco = e41.cargar_marco()
    con_grupo = BaseReferencia.cargar(RAIZ / "demo" / "base_v25.npz", e41._Ajustes.get_sbu)
    con_grupo.nivel_por_grupo()
    r = con_grupo.estandarizar_tamano(marco)
    b = BaseReferencia.cargar(RAIZ / "demo" / "base_v25.npz", e41._Ajustes.get_sbu)
    b.ajuste_tam, b.delta_tam = con_grupo.ajuste_tam, con_grupo.delta_tam
    b.guardar(RAIZ / "demo" / "base_v26.npz")
    txt = "74 · BASE v26 = v25 + tamano por nivel (D-063)\n{}\n".format(r)
    (SAL / "74_base_v26.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
