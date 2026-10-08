"""D-058: capa 0 v2, limpieza. Para cada titulo sucio de `base_v22`, su titulo limpio de destino (sin sueldos).

    ../../../.venv/bin/python 71_limpieza.py

SALIDA: salidas/71_limpieza.parquet (titulo, destino, regla)
"""
import collections
import pathlib
import re
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.capa0 import compatibles  # noqa: E402
from benchmarking.producto.nivel import nivel_rubrica, seniority_lexica  # noqa: E402

# sin A, E ni O: sueltas al final son letras de grado (`ANALYST A`), no conectores
CONECTORES = {"DE", "DEL", "Y", "LA", "LAS", "LOS", "EL", "EN", "PARA", "CON", "AL", "POR", "/", "-", "&"}
LARGOS = {40, 50, 60, 64}


def limpio(t):
    return re.sub(r"\s+", " ", t).strip(" -/,.")


def candado(a, b):
    na, nb = nivel_rubrica(a), nivel_rubrica(b)
    return bool((na and nb and na != nb) or seniority_lexica(a) != seniority_lexica(b) or not compatibles(a, b))


def main():
    b = np.load(RAIZ / "demo" / "base_v22.npz", allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    grupo = dict(zip(celdas, b["grupo"].astype(int)))
    per = dict(zip(celdas, b["personas"].astype(float)))
    existe = set(celdas)
    cuenta = collections.Counter(w for t in celdas for w in set(re.findall(r"[A-Z]+", t)))
    vocab = {w for w, n in cuenta.items() if n >= 20}
    orden = sorted(celdas)                          # para buscar prefijos
    import bisect
    filas = []

    def destino_prefijo(t):
        i = bisect.bisect_left(orden, t)
        gs = {}
        while i < len(orden) and orden[i].startswith(t):
            if orden[i] != t:
                gs.setdefault(grupo[orden[i]], []).append(orden[i])
            i += 1
            if len(gs) > 1:
                return None
        if len(gs) == 1:
            ms = list(gs.values())[0]
            return max(ms, key=lambda x: per[x])
        return None

    for t in celdas:
        cand = []
        # A (i): conectores finales
        ws = t.split()
        k = len(ws)
        while k > 1 and ws[k - 1] in CONECTORES:
            k -= 1
        if k < len(ws):
            cand.append((limpio(" ".join(ws[:k])), "A_conector"))
        # A (ii): cortado por largo, o terminado en conector
        if len(t) in LARGOS or k < len(ws):
            d = destino_prefijo(t)
            if d:
                cand.append((d, "A_cortado"))
        # B: codigos numericos y prefijos de lista
        tb = re.sub(r"^\s*\d+\s*[-.)/:]\s*", "", t)
        tb = re.sub(r"^\s*\d{2,}\s+", "", tb)
        tb = re.sub(r"(?<![A-Z])\d{2,}(?![A-Z])", " ", tb)
        tb = limpio(tb)
        if tb != t and tb:
            cand.append((tb, "B_codigo"))
        # C: siglas sueltas raras
        wc = [w for w in t.split() if not (re.fullmatch(r"[A-Z]{1,4}\.?", w) and w.strip(".") not in vocab
                                           and w.strip(".") not in CONECTORES)]
        tc = limpio(" ".join(wc))
        if tc != t and tc:
            cand.append((tc, "C_sigla"))
        for d, regla in cand:
            if d.split()[-1] in CONECTORES:         # el destino no puede ser otro titulo cortado
                continue
            if d in existe and grupo[d] != grupo[t] and not candado(t, d):
                filas.append((t, d, regla))
                break
    d = pd.DataFrame(filas, columns=["titulo", "destino", "regla"])
    d["personas"] = d["titulo"].map(per)
    d.to_parquet(SAL / "71_limpieza.parquet", index=False)
    print(d.groupby("regla").agg(titulos=("titulo", "size"), personas=("personas", "sum")).to_string())
    for r_, g in d.groupby("regla"):
        print(r_, g.sample(min(8, len(g)), random_state=1)[["titulo", "destino"]].values.tolist())


if __name__ == "__main__":
    main()
