"""La base v19 (con `--calibra`, la v20: D-051) = la v18 con el nivel de Qwen v2 y su clasificador para la consulta (D-049), y, con
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


def main(con_idioma, con_calibra=False, version="v2", con_e5=False, con_limpieza=False, con_coherencia=False,
         con_seniority=False):
    t0 = time.time()
    e41, e54 = cargar("e41", "41_base_v16.py"), cargar("e54", "54_pinball.py")
    marco = e41.cargar_marco()
    celdas = sorted(set(marco["cargo_norm"].astype(str)))
    b15 = np.load(RAIZ / "demo" / "base_v15.npz", allow_pickle=True)
    emb = e41.embeddings(celdas, b15)
    if con_e5:                           # D-057 (en medicion): los vectores del e5 ajustado
        b22 = np.load(RAIZ / "demo" / "base_v22.npz", allow_pickle=True)
        E = np.load(SAL / "e5B_base_v22.npy")
        e5 = {str(c): z for c, z in zip(b22["celdas"], E)}
        assert all(c in e5 for c in celdas), "faltan titulos en los vectores de e5"
        emb = {c: e5[c] for c in celdas}
    grupos = e54.grupos_de_clusters("50_clusters_confiable_cargos.parquet")
    unidos = 0
    if con_limpieza:                     # D-058: cortados y codigos al grupo de su titulo limpio (sin siglas)
        lim = pd.read_parquet(SAL / "71_limpieza.parquet")
        for t, d in zip(lim["titulo"], lim["destino"][lim["regla"] != "C_sigla"].reindex(lim.index)):
            if isinstance(d, str) and t in grupos and d in grupos and grupos[t] != grupos[d]:
                grupos[t] = grupos[d]
                unidos += 1
    if con_idioma:
        r = pd.read_parquet(SAL / "64_idioma_resueltos.parquet")
        for t, d in zip(r["titulo"], r["destino"]):
            if d and t in grupos and d in grupos and grupos[t] != grupos[d]:
                grupos[t] = grupos[d]
                unidos += 1
    q = pd.read_parquet(SAL / "60_niveles_qwen_{}.parquet".format(version))
    niveles = dict(zip(q["titulo"].astype(str), q["nivel"].astype(int)))
    b = BaseReferencia.construir(marco, emb, e41._Ajustes.get_sbu, umbral_fusion=None,
                                 capa0=c0mod.nueva("v1"), grupos=grupos, niveles=niveles)
    nombre = "base_v19.npz"
    if con_calibra:                      # D-051: k por particion interna de TODAS las empresas
        from benchmarking.producto.juez import cargar as cargar_juez
        juez = cargar_juez(RAIZ / "modelos" / "juez_v3")

        def preparar(base):
            base.juez, base.juez_vecinos = juez, True
            base.nivel_por_grupo()
            base.candado_nivel = True
            if con_e5:
                base.cos_juez = 0.8258
        b.escala_banda = e54.estimar_escala(marco, emb, dict(umbral_fusion=None, capa0=c0mod.nueva("v1"),
                                                                grupos=grupos, niveles=niveles),
                                            e41._Ajustes.get_sbu, preparar)
        nombre = ("base_v20.npz" if version == "v2" else "base_e5.npz" if con_e5
                  else "base_v23.npz" if con_limpieza else "base_v21.npz")
    if con_seniority:                    # D-060: el escalon de seniority en la analogia
        from benchmarking.producto.nivel import efecto_seniority
        b.efecto_sen = efecto_seniority(marco)
        print("seniority: {}".format(b.efecto_sen), flush=True)
        nombre = "base_v24.npz"
    if con_coherencia:                   # D-061: con la prima de dentro de la empresa (D-060) si la hay
        e_ = getattr(b, "efecto_sen", None)
        print("coherencia: {}".format(b.coherencia_seniority(
            prima={k: v for k, v in e_.items() if k in (1, -1)} if e_ else None)), flush=True)
        nombre = "base_v25.npz"
    b.guardar(RAIZ / "demo" / nombre)
    out = ["65 · BASE v19: nivel de Qwen v2 + clasificador de la consulta (D-049){}".format(
               "; titulos en ingles unidos a su traduccion (D-050): {:,}".format(unidos) if con_idioma else ""),
           "titulos {:,}; grupos {:,}; con nivel {:.1%}; clasificador: {}".format(
               len(b.celdas), len(set(np.asarray(b.grupo).tolist())), np.isfinite(b.nivel).mean(),
               "si" if b.clf_nivel is not None else "NO") + "; escala de banda: {}".format(b.escala_banda),
           "({:.0f} s)".format(time.time() - t0)]
    (SAL / "65_base_v19.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--idioma", action="store_true")
    ap.add_argument("--calibra", action="store_true", help="D-051: con la escala de banda -> base_v20")
    ap.add_argument("--nivel", choices=["v2", "v3"], default="v2", help="D-053: v3 -> base_v21")
    ap.add_argument("--e5", action="store_true", help="D-057 (en medicion): vectores de e5 -> base_e5")
    ap.add_argument("--limpieza", action="store_true", help="D-058: cortados y codigos -> base_v23")
    ap.add_argument("--coherencia", action="store_true", help="D-059: coherencia de seniority")
    ap.add_argument("--seniority", action="store_true", help="D-060: escalon de seniority -> base_v24")
    a = ap.parse_args()
    main(a.idioma, a.calibra, a.nivel, a.e5, a.limpieza, a.coherencia, a.seniority)
