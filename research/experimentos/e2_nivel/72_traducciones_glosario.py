"""Las traducciones (con el glosario vigente) de todos los titulos en ingles de la base, embebidas con Vertex.

`64_emb_traducciones.npz` se hizo antes del glosario: las traducciones de hoy no estan todas ahi. D-062 busca cada
titulo en ingles por su traduccion, asi que el pinball y la base necesitan su embedding. Reusa los de la 64 y los de
la base; embebe solo lo que falta.

    GRPC_DNS_RESOLVER=native ../../../.venv/bin/python 72_traducciones_glosario.py

SALIDA: salidas/72_emb_traducciones.npz (textos, X). Solo titulos de cargo traducidos: sin sueldos.
"""
import pathlib
import sys

import numpy as np

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.evaluacion import embeddings  # noqa: E402
from benchmarking.producto import idioma  # noqa: E402


def main():
    b = np.load(RAIZ / "demo" / "base_v25.npz", allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    ing = [c for c in celdas if idioma.es_ingles(c)]
    tr = idioma.cargar(RAIZ / "modelos" / "opus-mt-en-es")
    trad = tr.traducir(ing)
    textos = sorted({x for x in trad.values() if x})
    conocidos = {c: z for c, z in zip(celdas, b["Z"])}
    e64 = np.load(SAL / "64_emb_traducciones.npz", allow_pickle=True)
    conocidos.update({str(x): z for x, z in zip(e64["textos"], e64["X"])})
    falta = [x for x in textos if x not in conocidos]
    print("{} titulos en ingles, {} traducciones distintas, {} por embeber".format(len(ing), len(textos), len(falta)),
          flush=True)
    if falta:
        s = cargar_settings()
        cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
        conocidos.update(dict(zip(falta, embeddings.embeber(falta, cli, s.vertex_embedding_model))))
    X = np.vstack([np.asarray(conocidos[x], dtype=np.float32) for x in textos])
    np.savez_compressed(SAL / "72_emb_traducciones.npz", textos=np.array(textos, dtype=object), X=X)
    print("listo: salidas/72_emb_traducciones.npz", flush=True)


if __name__ == "__main__":
    main()
