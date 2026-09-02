""".Se puede recuperar el nivel jerarquico del texto del cargo?

D-012 midio que los embeddings son ciegos a la jerarquia y D-013 que el nivel vale 2,11x
en pago. Este script comprueba si un clasificador puede recuperarlo, y sobre todo si lo
recupera para los titulos que NO llevan la palabra de rango escrita — que son la mitad de
las etiquetas y el caso que importa.

TRES EVALUACIONES, de menos a mas exigente:

  A. ACIERTO sobre etiquetas retenidas que SI llevan rango.
     Es la mas facil y la menos informativa: en parte el modelo solo lee la palabra de
     vuelta. Sirve como control de sanidad y para ver si los errores son de un escalon o
     salvajes.

  B. LA ESCALERA SALARIAL sobre los titulos SIN rango.
     La prueba de verdad. El modelo no ve salarios en ningun momento; si su nivel predicho
     ordena el salario de forma monotona en textos donde nadie escribio el rango, encontro
     jerarquia real. Con placebo al lado.

  C. .APORTA SOBRE EL TEXTO SOLO?
     El nivel podria estar ya implicito en el embedding de forma utilizable. Se compara
     ordenar por nivel predicho contra ordenar por la primera componente del embedding.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import confusion_matrix

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.nivel import (ClasificadorNivel, escalera_salarial, etiquetar)

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))
    print(f"train: {len(train):,} filas, {train.cargo_norm.nunique():,} etiquetas")

    etiquetas = sorted(set(train.cargo_norm.astype(str)))
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print("embebiendo...")
    X = embeddings.embeber(etiquetas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    X = X / np.linalg.norm(X, axis=1, keepdims=True)
    pos = {e: i for i, e in enumerate(etiquetas)}

    niv = etiquetar(etiquetas)
    con = niv.notna().to_numpy()
    personas = train.cargo_norm.map(niv).notna().mean()
    print(f"\netiquetas con palabra de rango: {con.mean():.1%}   "
          f"personas cubiertas: {personas:.1%}")
    print(pd.Series(niv[con].astype(int)).value_counts().sort_index()
            .rename("etiquetas por nivel").to_string())

    # ---- A. acierto sobre etiquetas retenidas CON rango ---------------------
    idx = np.flatnonzero(con)
    rng = np.random.default_rng(SEM)
    rng.shuffle(idx)
    corte = int(0.75 * len(idx))
    tr_i, ts_i = idx[:corte], idx[corte:]
    y_tr = niv.iloc[tr_i].astype(int).to_numpy()
    y_ts = niv.iloc[ts_i].astype(int).to_numpy()

    clf = ClasificadorNivel().entrenar(X[tr_i], y_tr)
    pred = clf.predecir(X[ts_i])
    acierto = float((pred == y_ts).mean())
    a_uno = float((np.abs(pred - y_ts) <= 1).mean())
    mayoria = float((y_ts == pd.Series(y_tr).mode()[0]).mean())
    print("\n" + "=" * 72)
    print("A. ACIERTO sobre etiquetas retenidas que SI llevan rango")
    print("=" * 72)
    print(f"  exacto        {acierto:.1%}")
    print(f"  +-1 escalon   {a_uno:.1%}")
    print(f"  clase mayoritaria (baseline trivial)  {mayoria:.1%}")
    print("\n  matriz de confusion (filas = verdadero, columnas = predicho):")
    cm = confusion_matrix(y_ts, pred, labels=[1, 2, 3, 4, 5])
    print(pd.DataFrame(cm, index=[f"v{k}" for k in range(1, 6)],
                       columns=[f"p{k}" for k in range(1, 6)]).to_string())

    # ---- B. la escalera sobre los titulos SIN rango -------------------------
    clf_todo = ClasificadorNivel().entrenar(X[idx], niv.iloc[idx].astype(int).to_numpy())
    sin = np.flatnonzero(~con)
    nivel_pred = clf_todo.predecir(X[sin])
    esperado = clf_todo.nivel_esperado(X[sin])
    mapa = dict(zip([etiquetas[i] for i in sin], nivel_pred))

    d = train[train.cargo_norm.map(niv).isna()].copy()
    d["nivel_pred"] = d.cargo_norm.map(mapa)
    d["placebo"] = np.random.default_rng(7).permutation(d["nivel_pred"].to_numpy())
    print("\n" + "=" * 72)
    print("B. LA ESCALERA SALARIAL sobre titulos SIN palabra de rango")
    print("=" * 72)
    print(f"  {len(d):,} personas, {d.cargo_norm.nunique():,} etiquetas, "
          f"y el modelo NUNCA vio un salario")
    for nombre, col in (("nivel predicho", "nivel_pred"), ("PLACEBO", "placebo")):
        g, rec, mono = escalera_salarial(d[col], d["y"])
        print(f"\n  {nombre}:")
        for k, r in g.iterrows():
            print(f"    nivel {int(k)}   mediana {r['median']:>7.3f}   "
                  f"{int(r['size']):>7,} personas")
        print(f"    recorrido nivel bajo -> alto: {rec:.2f}x   "
              f"{'MONOTONA' if mono else 'no monotona'}")

    # y sobre las que SI llevan rango, para comparar la escalera conocida
    con_rango = train[train.cargo_norm.map(niv).notna()].copy()
    con_rango["nivel"] = con_rango.cargo_norm.map(niv)
    g, rec, mono = escalera_salarial(con_rango["nivel"], con_rango["y"])
    print(f"\n  (referencia: la escalera de las etiquetas que SI llevan rango, "
          f"{rec:.2f}x, {'monotona' if mono else 'no monotona'})")

    # ---- C. .aporta sobre el texto solo? ------------------------------------
    print("\n" + "=" * 72)
    print("C. .APORTA SOBRE EL EMBEDDING CRUDO?")
    print("=" * 72)
    from sklearn.decomposition import PCA
    pc1 = PCA(n_components=1, random_state=SEM).fit_transform(X[sin]).ravel()
    bandas = pd.qcut(pc1, 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
    d["pc1"] = d.cargo_norm.map(dict(zip([etiquetas[i] for i in sin], bandas)))
    g2, rec2, mono2 = escalera_salarial(d["pc1"].astype(float), d["y"])
    print(f"  ordenando por la 1a componente del embedding: {rec2:.2f}x   "
          f"{'monotona' if mono2 else 'NO monotona'}")
    print("  (si el embedding crudo ya ordenara el salario, el clasificador sobraria)")

    print("\n" + "=" * 72)
    print("LECTURA")
    print("=" * 72)
    print("  A alto y errores de un escalon: el nivel es recuperable del texto.")
    print("  B monotona y con recorrido apreciable frente al placebo: lo recupera TAMBIEN")
    print("    donde nadie lo escribio, que es lo que hace falta para el producto.")
    print("  C plano: la senal no estaba disponible en el embedding crudo.")


if __name__ == "__main__":
    main()
