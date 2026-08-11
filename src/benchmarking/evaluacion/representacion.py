"""Normalizacion de bloques heterogeneos por Analisis Factorial Multiple (MFA).

El problema: al concatenar bloques de tamanos distintos, la distancia euclidea suma una
diferencia por dimension, asi que un bloque de 768 columnas de texto domina a uno de 4 de
composicion aunque cada columna aporte poco. Normalizar a varianza unitaria no lo arregla:
dos bloques con la misma varianza total pero repartida de forma distinta influyen de forma
distinta sobre los primeros ejes, que son los que k-means y GMM usan.

MFA divide cada bloque por su **primer valor singular**, de modo que la direccion dominante
de cada uno mide 1. Es invariante al numero de dimensiones y a la escala, no tiene
parametros libres, y es citable (Escofier & Pages 1994; Abdi, Williams & Valentin 2013).

Sustituye al peso de bloque como hiperparametro (correccion 2 de D-009). Ese era el agujero
del pre-registro: el spec 3 principio 4 prohibia usar la metrica salarial para seleccionar
modelo, y el spec 7 afinaba el peso de bloque contra dispersion salarial en held-out. Sin
hiperparametro no hay nada que afinar, y la contradiccion desaparece en vez de vigilarse.
"""
import numpy as np
from sklearn.utils.extmath import randomized_svd

SEMILLA = 20260805


def primer_valor_singular(B, semilla=SEMILLA):
    """Primer valor singular de `B` ya centrado. 0 si el bloque es constante."""
    B = np.asarray(B, dtype=float)
    if B.size == 0 or not np.any(B):
        return 0.0
    if min(B.shape) == 1:                     # randomized_svd no aporta nada aqui
        return float(np.linalg.norm(B))
    return float(randomized_svd(B, n_components=1, random_state=int(semilla))[1][0])


def normalizar_mfa(bloques, semilla=SEMILLA):
    """Concatena los bloques, cada uno centrado y dividido por su primer valor singular.

    Un bloque constante se deja en cero en vez de dividirse: no aporta informacion y
    dividir por cero la fabricaria.
    """
    partes = []
    for B in bloques:
        Bc = np.asarray(B, dtype=float)
        if Bc.ndim == 1:
            Bc = Bc.reshape(-1, 1)
        Bc = Bc - Bc.mean(axis=0)
        s1 = primer_valor_singular(Bc, semilla)
        partes.append(Bc / s1 if s1 > 0 else Bc)
    return np.hstack(partes)
