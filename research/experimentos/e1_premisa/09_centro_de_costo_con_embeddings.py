"""SOBREVIVE EL CENTRO DE COSTO SI SE LEE POR SIGNIFICADO?

En `08` el centro de costo dio R2 = -0,1232: PEOR que no predecir nada. La lectura fue que
es vocabulario privado de cada empresa —`CC-402`, `BODEGA 3`— que no transfiere.

Pero esa medicion uso TF-IDF de CARACTERES, que sobre codigos internos es inutil por
construccion: `BODEGA 3` y `ALMACEN CENTRAL` no comparten un solo n-grama. Es el mismo error
que enterró la senal al concatenar el centro al cargo en `07`.

Aqui se lee por SIGNIFICADO, con embeddings. Es la ultima medicion que puede rescatar la
tesis de la ocupacion latente: si el centro de costo transfiere entre empresas, hay una
segunda vista con contenido ocupacional de verdad. Si tampoco transfiere, se cierra la
linea.

El trabajo con Vertex se corto una vez por tiempo, asi que este script:
  - embebe SOLO los centros de costo unicos (no las filas)
  - informa progreso por lote
  - cachea en disco de forma incremental, para que una segunda corrida reanude
"""
import argparse
import time

import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.decomposition import PCA, TruncatedSVD
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import GroupKFold

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits

SEM = 20260805
COMP = ["pct_fijo", "pct_comisiones", "pct_extras", "pct_otros"]
CACHE = "research/experimentos/e1_premisa/emb_centro.npz"


def embeber_con_progreso(textos, cliente, modelo, cache, lote=200, cada=10):
    """Como `embeddings.embeber` pero informando y volcando el cache cada N lotes."""
    # las vacias no se envian: Vertex responde 400 y tumba el lote entero
    unicos = sorted({str(t) for t in textos if str(t).strip()})
    pend = [t for t in unicos if cache.leer((modelo, embeddings.TAREA, t)) is None]
    print(f"  unicos: {len(unicos):,}   ya en cache: {len(unicos)-len(pend):,}   "
          f"por embeber: {len(pend):,}", flush=True)
    t0 = time.time()
    for i in range(0, len(pend), lote):
        trozo = pend[i:i + lote]
        for t, emb in zip(trozo, cliente.get_embeddings(trozo)):
            cache.guardar((modelo, embeddings.TAREA, t), np.asarray(emb.values, float))
        if (i // lote) % cada == 0:
            hechos = min(i + lote, len(pend))
            vel = hechos / max(time.time() - t0, 1e-9)
            print(f"    {hechos:,}/{len(pend):,}  ({vel:.0f}/s, "
                  f"faltan ~{(len(pend)-hechos)/max(vel,1e-9)/60:.1f} min)", flush=True)
            cache.volcar()
    cache.volcar()
    vec = {t: np.asarray(cache.leer((modelo, embeddings.TAREA, t)), float) for t in unicos}
    dim = len(next(iter(vec.values()))) if vec else 1
    return np.vstack([vec.get(str(t).strip() and str(t), np.zeros(dim))
                      if str(t).strip() else np.zeros(dim) for t in textos])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", type=int, default=150000)
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))
    d = train[train["tiene_composicion"]].dropna(subset=COMP + ["y"]).copy()

    rng = np.random.default_rng(SEM)
    emp = np.array(sorted(d.empresa_ruc.unique())); rng.shuffle(emp)
    acum, elegidas = 0, []
    for e in emp:
        n = int((d.empresa_ruc == e).sum())
        if acum + n > args.muestra:
            break
        elegidas.append(e); acum += n
    d = d[d.empresa_ruc.isin(elegidas)].reset_index(drop=True)
    d["centro"] = d["centro_de_costo"].fillna("").astype(str).str.strip().str.upper()
    print(f"muestra {len(d):,} personas / {d.empresa_ruc.nunique():,} empresas")
    print(f"centros de costo unicos: {d.centro.nunique():,}   "
          f"vacios: {(d.centro == '').mean():.1%}")

    d["r"] = d["y"] - d.groupby("empresa_ruc")["y"].transform("mean")
    y = d["r"].to_numpy(float)
    g = d["empresa_ruc"].to_numpy()

    def r2(X, et):
        X = np.asarray(X, float); pred = np.zeros(len(y))
        for a, b in GroupKFold(n_splits=4).split(X, groups=g):
            mo = HistGradientBoostingRegressor(random_state=SEM, max_iter=200)
            mo.fit(X[a], y[a]); pred[b] = mo.predict(X[b])
        v = 1 - float(((y - pred) ** 2).sum()) / float(((y - y.mean()) ** 2).sum())
        print(f"  {et:52s} R2 = {v:+.4f}", flush=True)
        return v

    print("\nembebiendo centros de costo...", flush=True)
    cache = embeddings.CacheArchivo(CACHE)
    cliente = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                        s.vertex_location)
    E = embeber_con_progreso(d["centro"].tolist(), cliente,
                             s.vertex_embedding_model, cache)
    Ek = PCA(n_components=32, random_state=SEM).fit_transform(E)

    tf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=5,
                         max_features=60000)
    Xc = TruncatedSVD(64, random_state=SEM).fit_transform(
        tf.fit_transform(d["cargo_norm"].astype(str)))
    ant = d[["antiguedad_total"]].fillna(d.antiguedad_total.median()).to_numpy(float)
    sin_texto = np.hstack([d[COMP].to_numpy(float), ant])

    print("\n" + "=" * 78)
    print("TRANSFIERE EL CENTRO DE COSTO ENTRE EMPRESAS?")
    print("=" * 78)
    r_cargo = r2(Xc, "cargo (TF-IDF), referencia")
    r_cen_e = r2(Ek, "CENTRO DE COSTO por SIGNIFICADO (embeddings)")
    print("  centro de costo por CARACTERES (medido en 08)          R2 = -0.1232")
    r_sin = r2(sin_texto, "sin texto (composicion + antiguedad)")
    r_alt = r2(np.hstack([Ek, sin_texto]), "TODO MENOS EL CARGO (centro + sin texto)")
    r_todo = r2(np.hstack([Xc, Ek, sin_texto]), "TODAS LAS VISTAS")

    print("\n" + "=" * 78)
    print("LECTURA")
    print("=" * 78)
    if r_cen_e > 0.02:
        print(f"  El centro de costo SI transfiere leido por significado: "
              f"{r_cen_e:+.4f} frente a -0,1232 por caracteres.")
        print(f"  Alcanza el {r_cen_e/r_cargo:.0%} del cargo, y las vistas sin cargo juntas "
              f"llegan a {r_alt/r_cargo:.0%}.")
        print("  -> hay una segunda vista con contenido ocupacional. La tesis latente vive.")
    else:
        print(f"  El centro de costo NO transfiere ni leido por significado ({r_cen_e:+.4f}).")
        print("  -> no es vocabulario mal representado: es informacion privada de cada")
        print("     empresa. Se cierra la linea de la ocupacion latente con estos datos.")
    print(f"\n  lo que TODO anade sobre el cargo solo: {r_todo - r_cargo:+.4f}")


if __name__ == "__main__":
    main()
