"""La base v27 = la v26 con la prima del titulo en ingles encogida por nivel (D-067, n0 = 50 pares), estimada con
toda la base y la configuracion de la API (juez, nivel por grupo, traductor con glosario, candado de D-064).

    ../../../.venv/bin/python 80_base_v27.py

SALIDAS: demo/base_v27.npz, salidas/80_base_v27.txt
"""
import pathlib
import sys

import numpy as np

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.producto import idioma  # noqa: E402
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402
from benchmarking.producto.juez import cargar as cargar_juez  # noqa: E402


def main():
    s = cargar_settings()
    c = BaseReferencia.cargar(RAIZ / "demo" / "base_v26.npz", s.get_sbu)
    c.juez = cargar_juez(RAIZ / "modelos" / "juez_v3")
    c.juez_vecinos = True
    c.nivel_por_grupo()
    c.candado_nivel = True
    c.traductor = idioma.cargar(RAIZ / "modelos" / "opus-mt-en-es")
    c.candado_glosario = True
    emb = {x: c.Z[i] for i, x in enumerate(c.celdas)}
    for f in ("64_emb_traducciones.npz", "72_emb_traducciones.npz"):
        et = np.load(SAL / f, allow_pickle=True)
        emb.update({str(x): z for x, z in zip(et["textos"], et["X"])})
    r = c.estimar_prima_idioma(emb, encoger=50)
    b = BaseReferencia.cargar(RAIZ / "demo" / "base_v26.npz", s.get_sbu)
    b.idioma_prima = c.idioma_prima
    b.guardar(RAIZ / "demo" / "base_v27.npz")
    txt = "80 · BASE v27 = v26 + prima del ingles encogida (D-067)\n{}\n".format(r)
    (SAL / "80_base_v27.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
