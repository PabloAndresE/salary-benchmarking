"""D-068 (a): corrector de errores de tipeo del titulo, contra el vocabulario de la base.

Cada palabra que no esta en el vocabulario, con >= 5 letras, se reemplaza por la palabra del vocabulario a menor
distancia de Damerau-Levenshtein (transposiciones de adyacentes): <= 1 con 5-7 letras, <= 2 con >= 8. Solo si es
UNICA a esa distancia, o si la mas frecuente (por personas) tiene al menos el doble que la siguiente. Las palabras
de rango y las siglas de <= 4 letras no se tocan. Indice de borrados (al estilo SymSpell): sin librerias.
"""
import re
import zlib
from itertools import combinations

import numpy as np


def _borrados(w, k):
    out = {w}
    for d in range(1, k + 1):
        for pos in combinations(range(len(w)), d):
            out.add("".join(c for i, c in enumerate(w) if i not in pos))
    return out


def distancia(a, b):
    """Damerau-Levenshtein (alineamiento optimo de cadenas)."""
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            c = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


class Corrector:
    def __init__(self, titulos, pesos, protegidas=()):
        self.frec = {}
        for t, p in zip(titulos, pesos):
            for w in re.findall(r"[A-Z]+", str(t).upper()):
                self.frec[w] = self.frec.get(w, 0.0) + float(p)
        self.protegidas = set(protegidas)
        self.indice = {}
        for w in self.frec:
            if len(w) >= 3:
                for b in _borrados(w, 2):
                    self.indice.setdefault(b, set()).add(w)
        self.por_largo = {}
        for w in self.frec:
            self.por_largo.setdefault(len(w), []).append(w)

    def palabra(self, w):
        """La correccion de una palabra, o None."""
        if w in self.frec or len(w) < 5 or w in self.protegidas:
            return None
        k = 1 if len(w) < 8 else 2
        cand = set()
        for b in _borrados(w, k):
            cand |= self.indice.get(b, set())
        mejores = {}
        for c in cand:
            dd = distancia(w, c)
            if dd <= k:
                mejores.setdefault(dd, []).append(c)
        if not mejores:
            return None
        top = sorted(mejores[min(mejores)], key=lambda c: -self.frec[c])
        if len(top) == 1 or self.frec[top[0]] >= 2 * self.frec[top[1]]:
            return top[0]
        return None

    def titulo(self, t):
        """El titulo corregido, o None si no cambia."""
        t = str(t).upper()
        nuevo = re.sub(r"[A-Z]+", lambda m: self.palabra(m.group(0)) or m.group(0), t)
        return nuevo if nuevo != t else None

    def placebo(self, t):
        """Solo para medir: cada palabra que se corregiria va a una palabra del vocabulario AL AZAR del mismo
        largo (semilla estable por titulo)."""
        t = str(t).upper()
        rng = np.random.default_rng(zlib.crc32(t.encode()))

        def f(m):
            w = m.group(0)
            if self.palabra(w) is None:
                return w
            pool = self.por_largo.get(len(w)) or [w]
            return pool[int(rng.integers(len(pool)))]
        nuevo = re.sub(r"[A-Z]+", f, t)
        return nuevo if nuevo != t else None
