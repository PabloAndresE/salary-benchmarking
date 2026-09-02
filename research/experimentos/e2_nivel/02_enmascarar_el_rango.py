"""Enmascarar el rango: .arregla la transferencia?

`01` midio que entrenar sobre el titulo COMPLETO da 98,9% de acierto y NO transfiere: al
llegarle un titulo sin rango el clasificador vuelca el 58% de la gente al nivel 1 y la
escalera salarial sale no monotona (1,48x). Aprendio a leer la palabra, no la jerarquia.

Aqui se entrena sobre el titulo ENMASCARADO:

    AUXILIAR DE BODEGA  ->  PUESTO DE BODEGA  ->  nivel 1
    JEFE DE BODEGA      ->  PUESTO DE BODEGA  ->  nivel 4

El atajo desaparece. La etiqueta queda ruidosa a proposito —el mismo texto es a veces 1 y
a veces 4— y eso es correcto: lo que se aprende es P(nivel | resto del titulo), que es la
pregunta real cuando nadie escribio el rango.

SE COMPARAN LAS DOS VERSIONES en la unica prueba que importa: la escalera salarial sobre
los titulos SIN rango, contra su placebo. El modelo no ve salarios en ninguna etapa.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.nivel import (ClasificadorNivel, enmascarar,
                                         escalera_salarial, etiquetar)

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"


def evaluar(nombre, clf, X_pred, etiquetas_sin, train, niv):
    """La escalera salarial que produce este clasificador sobre los titulos sin rango."""
    pred = clf.predecir(X_pred)
    mapa = dict(zip(etiquetas_sin, pred))
    d = train[train.cargo_norm.map(niv).isna()].copy()
    d["nivel"] = d.cargo_norm.map(mapa)
    g, rec, mono = escalera_salarial(d["nivel"], d["y"])
    reparto = d["nivel"].value_counts(normalize=True).sort_index()
    print(f"\n{nombre}")
    for k, r in g.iterrows():
        marca = "  <-- se acumula aqui" if reparto.get(k, 0) > 0.45 else ""
        print(f"    nivel {int(k)}   mediana {r['median']:>7.3f}   "
              f"{int(r['size']):>7,} personas ({reparto.get(k, 0):>5.1%}){marca}")
    print(f"    recorrido {rec:.2f}x   {'MONOTONA' if mono else 'no monotona'}")
    return rec, mono


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))
    etiquetas = sorted(set(train.cargo_norm.astype(str)))
    niv = etiquetar(etiquetas)
    con = niv.notna().to_numpy()
    print(f"train {len(train):,} filas, {len(etiquetas):,} etiquetas, "
          f"{con.mean():.1%} con rango")

    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)

    # dos espacios de texto: el crudo y el enmascarado
    mascarado = [enmascarar(e) for e in etiquetas]
    print(f"titulos enmascarados distintos: {len(set(mascarado)):,} "
          f"(de {len(etiquetas):,} originales)")
    print("embebiendo crudos...")
    X = embeddings.embeber(etiquetas, cli, s.vertex_embedding_model, cache=cache)
    print("embebiendo enmascarados...")
    Xm = embeddings.embeber(mascarado, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    X = X / np.linalg.norm(X, axis=1, keepdims=True)
    Xm = Xm / np.linalg.norm(Xm, axis=1, keepdims=True)

    idx = np.flatnonzero(con)
    sin = np.flatnonzero(~con)
    y_tr = niv.iloc[idx].astype(int).to_numpy()
    etiquetas_sin = [etiquetas[i] for i in sin]

    print("\n" + "=" * 74)
    print("LA ESCALERA SALARIAL SOBRE TITULOS SIN RANGO")
    print(f"({len(sin):,} etiquetas, y el modelo nunca vio un salario)")
    print("=" * 74)

    # sin enmascarar: la version de `01`
    clf_crudo = ClasificadorNivel().entrenar(X[idx], y_tr)
    r1, m1 = evaluar("A. entrenado sobre el titulo COMPLETO (la version de `01`)",
                     clf_crudo, X[sin], etiquetas_sin, train, niv)

    # enmascarado: se entrena en el espacio enmascarado y se predice en el mismo espacio.
    # Un titulo sin rango ya esta "enmascarado" por definicion, asi que no hay salto de
    # dominio entre entrenar y predecir — que era justo el problema de A.
    clf_masc = ClasificadorNivel().entrenar(Xm[idx], y_tr)
    r2, m2 = evaluar("B. entrenado sobre el titulo ENMASCARADO", clf_masc, Xm[sin],
                     etiquetas_sin, train, niv)

    # placebo comun
    d = train[train.cargo_norm.map(niv).isna()].copy()
    d["plac"] = np.random.default_rng(7).integers(1, 6, len(d))
    g, rp, mp = escalera_salarial(d["plac"], d["y"])
    print(f"\nC. PLACEBO   recorrido {rp:.2f}x   {'monotona' if mp else 'no monotona'}")

    # la escalera conocida, como referencia
    cr = train[train.cargo_norm.map(niv).notna()].copy()
    cr["nivel"] = cr.cargo_norm.map(niv)
    _, rr, mr = escalera_salarial(cr["nivel"], cr["y"])
    print(f"D. REFERENCIA (etiquetas que SI llevan rango)   {rr:.2f}x   "
          f"{'monotona' if mr else 'no monotona'}")

    print("\n" + "=" * 74)
    print("LECTURA")
    print("=" * 74)
    print(f"  completo   {r1:.2f}x  {'monotona' if m1 else 'NO monotona'}")
    print(f"  enmascarado{r2:>6.2f}x  {'monotona' if m2 else 'NO monotona'}")
    print(f"  placebo    {rp:.2f}x")
    print()
    if m2 and r2 > r1:
        print("  El enmascarado transfiere y el crudo no: la supervision debil funciona")
        print("  solo si se le quita al modelo la posibilidad de leer la respuesta.")
    elif r2 > r1:
        print("  Mejora pero sigue sin ordenar. El resto del titulo no basta para inferir")
        print("  el nivel, o el lexico de rango no es la supervision adecuada.")
    else:
        print("  No mejora. El nivel no es recuperable de los titulos que no lo declaran,")
        print("  al menos no con esta supervision y esta representacion.")


if __name__ == "__main__":
    main()
