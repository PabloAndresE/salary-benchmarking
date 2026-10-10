"""D-068 (b): umbral de «cargo no reconocido».

tau = percentil 2 de `similitud` entre los votos apartados que van por analogia en `tam_A`. Se cuenta cuantos de
la lista de control de basura (fijada en el registro) quedan bajo tau, con la base v26 y Vertex, como la API; y,
entre los votos apartados bajo tau, su pinball frente al resto.

    GRPC_DNS_RESOLVER=native ../../../.venv/bin/python 79_no_reconocido.py

SALIDA: salidas/79_no_reconocido.txt
"""
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.evaluacion import embeddings  # noqa: E402
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402
from benchmarking.producto.juez import cargar as cargar_juez  # noqa: E402

BASURA = ["ASDFGH QWERTY", "XXXXX", "AAAA BBBB", "123456", "LOREM IPSUM", "TEST", "PRUEBA PRUEBA", "NINGUNO", "N/A",
          "HOLA MUNDO", "ASTRONAUTA", "DOMADOR DE LEONES", "MAGO", "UNICORNIO", "PIRATA", "VAMPIRO", "SUPERHEROE",
          "DRAGON", "ZZZZ", "QWERTYUIOP", "MESA", "SILLA", "PERRO", "GATO", "PIZZA", "FUTBOL", "BANANA", "CIELO AZUL",
          "JKLÑ", "????"]


def main():
    d = pd.read_parquet(SAL / "54_tam_A_50_clusters_confiable_cargos_venv.parquet")
    an = d[d["base"] == "por analogia"]
    tau = float(np.percentile(an.drop_duplicates("cargo")["similitud"], 2))
    bajo = an["similitud"] < tau
    s = cargar_settings()
    b = BaseReferencia.cargar(RAIZ / "demo" / "base_v26.npz", s.get_sbu)
    b.juez = cargar_juez(RAIZ / "modelos" / "juez_v3")
    b.juez_vecinos = True
    b.nivel_por_grupo()
    b.candado_nivel = True
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
    emb = {c: b.Z[i] for i, c in enumerate(b.celdas)}
    nuevos = [t for t in BASURA if t not in emb]
    emb.update(dict(zip(nuevos, embeddings.embeber(nuevos, cli, s.vertex_embedding_model))))
    r = b.referenciar(BASURA, emb).set_index("cargo")
    rech = (r["base"] == "por analogia") & (r["similitud"] < tau)
    out = ["79 · NO RECONOCIDO (D-068 b)",
           "tau = percentil 2 de similitud (titulos apartados por analogia, tam_A): {:.3f}".format(tau),
           "votos apartados por analogia bajo tau: {:,} de {:,} ({:.1%}); pinball medio bajo tau {:.4f} vs resto {:.4f}".format(
               int(bajo.sum()), len(an), bajo.mean(), an.loc[bajo, "pinball"].mean(), an.loc[~bajo, "pinball"].mean()),
           "basura rechazada: {} de {} ({:.0%})".format(int(rech.sum()), len(BASURA), rech.mean()),
           "CRITERIO (>= 80 % de la lista): {}".format("CUMPLE" if rech.mean() >= 0.8 else "NO CUMPLE"), ""]
    for t in BASURA:
        out.append("   {:<20} {:<16} similitud {:.3f} {}".format(t, r.loc[t, "base"], r.loc[t, "similitud"],
                                                                 "RECHAZADO" if rech[t] else ""))
    (SAL / "79_no_reconocido.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
