"""Estabilidad de una particion: test-retest real y ARI entre submuestras.

Es la regla con la que se eligen la granularidad (k) y la familia de clustering, y la
razon de que exista es anti-circularidad: **ninguna de las dos se elige por acierto
salarial** (D-005 Enmienda 1, elementos 1 y 2). Si k se eligiera por MAE, el modelo
estaria ajustado a la misma cantidad que despues se usa para juzgarlo.

Dos medidas distintas, y la primera es mas fuerte de lo que suele reconocerse:

- `retest_entre_anios` compara la celda asignada a la MISMA persona en dos anios. Es una
  re-medicion REAL, no simulada: hay 478.522 personas presentes en 2024 y 2025. Ninguna
  simulacion de bootstrap sostiene lo que sostiene eso.
- `ari_submuestras` mide si el metodo reproduce la misma particion al reentrenarlo sobre
  otra mitad de las EMPRESAS. Responde a "esto es estructura o es ruido".
"""
import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

SEMILLA = 20260805


def retest_entre_anios(df, col_celda, col_persona="id_hash", col_anio="anio_valoracion"):
    """Acuerdo de la celda asignada a la MISMA persona en dos anios distintos.

    Es el *test-retest* clasico de psicometria. El nombre NO empieza por `test_` a
    proposito: pytest recoge como test cualquier funcion asi llamada que aparezca en el
    espacio de nombres de un modulo de tests, y una funcion de produccion importada alli
    se colaria en la suite. Costo un error de coleccion antes de descubrirlo.

    Re-medicion real, no simulada. Solo entran las personas presentes en ambos anios.

    Se reporta `acuerdo` (fraccion que cae en la misma celda) y `kappa`, que descuenta el
    acuerdo por azar: con pocas celdas grandes, coincidir es facil sin que la particion
    sea estable, y el acuerdo crudo lo esconderia.
    """
    d = df[[col_persona, col_anio, col_celda]].dropna()
    pares = (d.sort_values(col_anio).groupby(col_persona)[col_celda]
              .agg(lambda v: (v.iloc[0], v.iloc[-1])))
    pares = pares[d.groupby(col_persona)[col_anio].nunique() >= 2]
    if pares.empty:
        return {"n_personas_repetidas": 0, "acuerdo": float("nan"), "kappa": float("nan")}

    a = np.array([p[0] for p in pares], dtype=object)
    b = np.array([p[-1] for p in pares], dtype=object)
    observado = float((a == b).mean())

    # acuerdo esperado por azar, dadas las frecuencias marginales de cada anio
    fa = pd.Series(a).value_counts(normalize=True)
    fb = pd.Series(b).value_counts(normalize=True)
    esperado = float((fa * fb.reindex(fa.index).fillna(0.0)).sum())
    kappa = (observado - esperado) / (1 - esperado) if esperado < 1 else float("nan")
    return {"n_personas_repetidas": int(len(pares)), "acuerdo": observado,
            "kappa": float(kappa)}


def ari_submuestras(df, asignador, n=20, frac=0.5, semilla=SEMILLA,
                    col_empresa="empresa_ruc"):
    """Reproducibilidad de la particion entre submuestras DE EMPRESAS.

    Es la regla con la que se elige la granularidad y la familia (D-005): nunca por
    acierto salarial.

    Las submuestras son de empresas y no de filas por la misma razon que el split: la
    fila no es la unidad independiente. Se comparan solo las personas que caen en ambas
    submuestras, que es donde las dos asignaciones son comparables.
    """
    rng = np.random.default_rng(int(semilla))
    empresas = np.array(sorted(df[col_empresa].unique()))
    tam = max(1, int(len(empresas) * frac))
    aris = []
    for _ in range(int(n)):
        a = set(rng.choice(empresas, tam, replace=False))
        b = set(rng.choice(empresas, tam, replace=False))
        da, db = df[df[col_empresa].isin(a)], df[df[col_empresa].isin(b)]
        comun = da.index.intersection(db.index)
        if len(comun) < 2:
            continue
        aris.append(adjusted_rand_score(asignador(da).reindex(comun).astype(str),
                                        asignador(db).reindex(comun).astype(str)))
    if not aris:
        return {"ari_medio": float("nan"), "ari_min": float("nan"), "n_comparaciones": 0}
    return {"ari_medio": float(np.mean(aris)), "ari_min": float(np.min(aris)),
            "n_comparaciones": len(aris)}
