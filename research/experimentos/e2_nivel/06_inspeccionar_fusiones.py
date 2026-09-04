"""Que esta fusionando de verdad? Inspeccion cualitativa de los grupos.

`05` midio que fusionar a >0,97 sale neutro en precision y da 4,6 puntos de cobertura
directa, y que a >0,95 EMPEORA un 5%. Este script mira los grupos concretos para entender
por que, y para poder defender o descartar el umbral con ejemplos y no solo con un IC.

Se imprimen tres cosas por umbral:

  - los grupos MAS GRANDES, que son los que mas gente mueven
  - los grupos con MAS DISPERSION de pago, que son donde la fusion hace dano
  - una muestra al azar, para no mirar solo los extremos

Un grupo es defendible si sus titulos son la misma cosa escrita distinto y pagan parecido.
Es un error si junta puestos distintos, y se nota en la dispersion.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import _vecinos
from benchmarking.producto.nivel import nivel_lexico

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
UMBRALES = (0.97, 0.95)


def agrupar(celdas, vec, sim, umbral, niveles):
    padre = list(range(len(celdas)))

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for i in range(len(celdas)):
        for j, sj in zip(vec[i], sim[i]):
            if sj < umbral:
                break
            ni, nj = niveles[i], niveles[int(j)]
            if np.isfinite(ni) and np.isfinite(nj) and ni != nj:
                continue
            ri, rj = raiz(i), raiz(int(j))
            if ri != rj:
                padre[ri] = rj
    return np.array([raiz(i) for i in range(len(celdas))])


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(mk, splits.empresas_test(mk))

    celdas = sorted(set(train.cargo_norm.astype(str)))
    idx = {c: i for i, c in enumerate(celdas)}
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    Z = embeddings.embeber(celdas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    Z = Z / np.linalg.norm(Z, axis=1, keepdims=True)
    niveles = np.array([nivel_lexico(c) or np.nan for c in celdas], dtype=float)

    print(f"{len(celdas):,} titulos. Buscando vecinos (una sola vez)...")
    vec, sim = _vecinos(Z, Z, 10, excluir_propio=True)

    # mediana de pago y personas por titulo
    g = train.groupby(train.cargo_norm.astype(str))["y"].agg(["median", "size"])
    med = g["median"].reindex(celdas).to_numpy()
    npers = g["size"].reindex(celdas).fillna(0).to_numpy()

    rng = np.random.default_rng(SEM)
    for u in UMBRALES:
        gr = agrupar(celdas, vec, sim, u, niveles)
        tam = pd.Series(gr).value_counts()
        multi = tam[tam > 1]
        print("\n" + "=" * 78)
        print(f"UMBRAL {u}   {len(multi):,} grupos con 2+ titulos, "
              f"{int(multi.sum()):,} titulos fusionados")
        print("=" * 78)

        def mostrar(titulo, claves):
            print(f"\n--- {titulo}")
            for k in claves:
                miembros = np.flatnonzero(gr == k)
                miembros = miembros[np.argsort(-npers[miembros])]
                disp = np.nanmax(med[miembros]) - np.nanmin(med[miembros])
                print(f"\n  grupo de {len(miembros)} titulos   "
                      f"dispersion de pago: {np.exp(disp):.2f}x")
                for i in miembros[:7]:
                    print(f"    {celdas[i][:52]:<54} {med[i]:>7.3f} "
                          f"{int(npers[i]):>7,} pers.")
                if len(miembros) > 7:
                    print(f"    ... y {len(miembros)-7} mas")

        mostrar("LOS MAS GRANDES (mas gente movida)", multi.head(3).index)

        # dispersion por grupo, solo los que mueven gente
        filas = []
        for k in multi.index:
            mi = np.flatnonzero(gr == k)
            if npers[mi].sum() < 200:
                continue
            v = med[mi][np.isfinite(med[mi])]
            if len(v) > 1:
                filas.append((k, float(np.nanmax(v) - np.nanmin(v)), int(npers[mi].sum())))
        f = pd.DataFrame(filas, columns=["k", "disp", "n"]).sort_values("disp",
                                                                       ascending=False)
        mostrar("LOS PEORES (mas dispersion de pago dentro del grupo)", f.head(3).k)
        mostrar("MUESTRA AL AZAR", rng.choice(multi.index, min(3, len(multi)),
                                              replace=False))

        if len(f):
            print(f"\n  dispersion mediana entre grupos con 200+ personas: "
                  f"{np.exp(f.disp.median()):.2f}x")


if __name__ == "__main__":
    main()
