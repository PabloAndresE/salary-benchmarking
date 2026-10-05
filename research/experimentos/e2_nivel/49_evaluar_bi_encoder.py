"""D-045 §5: evaluar el bi-encoder afinado, en el lado `evalua` (escrito antes de ver resultados).

Verdad: pares de `47_pares.parquet` con los dos nodos en `evalua`, P de la v3 >= 0,5 y sin candado.
Modelos: Vertex, e5-base sin entrenar y e5-base afinado (la semilla elegida en `48`). Los dos e5 se
codifican con la MISMA funcion de `48` (prefijo, promedio, largo 32, bf16).

    principal   recall@100 (buscando sobre los 58.051 nodos); IC 95 % por bootstrap de comunidades
                (10.000). SE ADOPTA si (i) afinado - sin entrenar tiene el IC entero sobre cero y
                (ii) el limite inferior del IC de afinado - Vertex no baja de -1 punto.
    control     el mismo recall@100 solo en pares con los dos nodos SIN vecino P >= 0,9 en
    de fuga     entrenamiento (enmienda a D-045 §4).
    secundaria  precision@25: de los 25 vecinos de 2.000 nodos de `evalua` (con peso por personas),
                fraccion que la v3 dice `si` (sin candado).
    casos       rango del nodo del otro titulo entre los vecinos, para los cinco casos conocidos.
    descriptivo recall@100 por fuente del par, y recall@25.

    CUDA_VISIBLE_DEVICES=0 .venv/bin/python 49_evaluar_bi_encoder.py

SALIDA: salidas/49_evaluar_bi_encoder.txt
"""
import argparse
import contextlib
import importlib.util
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import torch

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
V3 = SAL / "22_modelos_v3" / "elegido"
SEM, B = 20261005, 10_000


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def vecinos(Z, filas, k):
    T = torch.from_numpy(Z).cuda()
    out = np.empty((len(filas), k), dtype=np.int64)
    for a in range(0, len(filas), 2048):
        ix = torch.from_numpy(np.asarray(filas[a:a + 2048])).cuda()
        s = T[ix] @ T.T
        s[torch.arange(len(ix)), ix] = -2
        out[a:a + 2048] = s.topk(k, dim=1).indices.cpu().numpy()
    return out


def rango(Z, i, j):
    s = Z @ Z[i]
    s[i] = -2
    return int((s > s[j]).sum()) + 1


def main():
    e43 = cargar("e43", "43_perdida_vertex.py")
    e47 = cargar("e47", "47_pares_bi_encoder.py")
    e48 = cargar("e48", "48_entrenar_bi_encoder.py")
    from transformers import AutoTokenizer
    out = []

    def p(s=""):
        print(s, flush=True)
        out.append(s)

    tit, Zv, per = e43.nodos()
    nodos = pd.read_parquet(SAL / "47_nodos.parquet")
    sin_fuga = pd.read_parquet(SAL / "47_sin_fuga.parquet")["sin_fuga"].to_numpy()
    d = pd.read_parquet(SAL / "47_pares.parquet")
    lado = nodos["lado"].to_numpy()
    comp = nodos["comp"].to_numpy()
    # CORRECCION (2026-10-05): la verdad, solo de fuentes que no son los modelos comparados (por
    # letras o Gemini). Con los vecinos de e5 o de Vertex como verdad, cada uno acierta ~100 % de lo
    # que el mismo propuso y el afinado compite en desventaja.
    ev = d[(d["lado"] == "evalua") & (d["P"] >= 0.5) & ~d["bloqueado"]
           & d["fuente"].str.contains("cerca_tfidf|gemini")].reset_index(drop=True)

    ap = argparse.ArgumentParser()
    ap.add_argument("--afinados", default="48_bi_encoder",
                    help="carpetas de 48 separadas por coma; de cada una, la semilla elegida")
    a_ = ap.parse_args()
    modelos = [("e5 sin entrenar", e48.E5)]
    for carpeta in a_.afinados.split(","):
        res = json.loads((SAL / carpeta / "resultados.json").read_text(encoding="utf-8"))
        nombre = "af " + (res["hiper"].get("variante") or "original")
        modelos.append((nombre, SAL / carpeta / "semilla_{}".format(res["elegida"])))
    Z = {"Vertex": Zv}
    for nombre, ruta in modelos:
        tok = AutoTokenizer.from_pretrained(ruta)
        mod = e48.Codificador(ruta).cuda()
        Z[nombre] = e48.codificar(mod, tok, list(tit)).cpu().numpy()
        del mod
        torch.cuda.empty_cache()

    p("=" * 78)
    p("49 · EVALUACION DEL BI-ENCODER, lado `evalua` (verdad: pares por letras o de Gemini)")
    p("=" * 78)
    p("modelos: " + ", ".join("{} ({})".format(n_, pathlib.Path(r).name) for n_, r in modelos))
    p("pares `si` de la v3 en evalua: {:,} sobre {:,} nodos; sin fuga (los dos nodos): {:,}".format(
        len(ev), len(np.unique(ev[["i", "j"]])), int((sin_fuga[ev["i"]] & sin_fuga[ev["j"]]).sum())))

    nod = np.unique(ev[["i", "j"]].to_numpy())
    pos = {x: k for k, x in enumerate(nod)}
    acierto = {}
    for nombre, Zm in Z.items():
        v = vecinos(Zm, nod, 100)
        conj25 = [set(r[:25]) for r in v]
        conj100 = [set(r) for r in v]
        a, b = ev["i"].to_numpy(), ev["j"].to_numpy()
        acierto[nombre] = {
            25: np.array([(y in conj25[pos[x]]) or (x in conj25[pos[y]]) for x, y in zip(a, b)]),
            100: np.array([(y in conj100[pos[x]]) or (x in conj100[pos[y]]) for x, y in zip(a, b)])}

    w = per[ev["i"]]
    mf = sin_fuga[ev["i"]] & sin_fuga[ev["j"]]
    p("\n{:<16} {:>10} {:>11} {:>14} {:>14}".format(
        "modelo", "recall@25", "recall@100", "rec@100 pers", "rec@100 sin fuga"))
    for nombre in Z:
        a25, a100 = acierto[nombre][25], acierto[nombre][100]
        p("{:<16} {:>10.1%} {:>11.1%} {:>14.1%} {:>14.1%}".format(
            nombre, a25.mean(), a100.mean(), (a100 * w).sum() / w.sum(), a100[mf].mean()))

    rng = np.random.default_rng(SEM)
    cc = comp[ev["i"]]
    u, idx = np.unique(cc, return_inverse=True)

    def boot(x, y, mascara=None):
        m = np.ones(len(ev), bool) if mascara is None else mascara
        hx = np.bincount(idx[m], acierto[x][100][m], len(u))
        hy = np.bincount(idx[m], acierto[y][100][m], len(u))
        nn = np.bincount(idx[m], minlength=len(u)).astype(float)
        dd = np.empty(B)
        for k in range(B):
            r = rng.integers(0, len(u), len(u))
            dd[k] = (hx[r].sum() - hy[r].sum()) / nn[r].sum()
        dif = acierto[x][100][m].mean() - acierto[y][100][m].mean()
        return dif, *np.percentile(dd, [2.5, 97.5])

    p("\nCONTRASTES de recall@100 (IC 95 %, bootstrap por comunidad, {:,}; exploratorio)".format(B))
    for nombre in [n_ for n_ in Z if n_.startswith("af ")]:
        for base in ("e5 sin entrenar", "Vertex"):
            p("   {} - {:<16} {:+.1%} [{:+.1%}, {:+.1%}]   sin fuga {:+.1%} [{:+.1%}, {:+.1%}]".format(
                nombre, base, *boot(nombre, base), *boot(nombre, base, mf)))

    p("\nrecall@100 por fuente del par (descriptivo):")
    f = ev.assign(fuente=ev["fuente"].str.split("|")).explode("fuente")
    for fu, g in f.groupby("fuente"):
        ix = g.index.to_numpy()
        p("   {:<14} n={:>8,}   ".format(fu, len(ix)) + "   ".join(
            "{} {:.1%}".format(n_, acierto[n_][100][ix].mean()) for n_ in Z))

    # --- precision@25 ---------------------------------------------------------------------
    os_ev = np.flatnonzero(lado == "evalua")
    pe = per[os_ev] / per[os_ev].sum()
    muestra = np.random.default_rng(SEM).choice(os_ev, 2000, replace=False, p=pe)
    filas = []
    for nombre, Zm in Z.items():
        for x, r in zip(muestra, vecinos(Zm, muestra, 25)):
            for y in r:
                filas.append((nombre, min(x, y), max(x, y)))
    q = pd.DataFrame(filas, columns=["modelo", "i", "j"])
    q = q.merge(d[["i", "j", "P", "bloqueado"]], on=["i", "j"], how="left")
    falta = q[q["P"].isna()][["i", "j"]].drop_duplicates()
    if len(falta):
        e22 = cargar("e22", "22_entrenar_cross.py")
        e31 = cargar("e31", "31_h4_prueba2.py")
        tok = AutoTokenizer.from_pretrained(RAIZ / "modelos" / "mdeberta-xnli")
        inf = json.loads((V3 / "info.json").read_text(encoding="utf-8"))
        m = e22.construir(V3, False, "cuda")
        ab, ba = e22.puntuar(m, tok, list(tit[falta["i"]]), list(tit[falta["j"]]), "cuda",
                             contextlib.nullcontext, lote=512)
        falta = falta.assign(P2=e31.calibrada(e22.puntaje(inf["modo"], ab, ba), inf["temperatura"]),
                             bl2=[e43.bloqueado(a, b) for a, b in zip(tit[falta["i"]], tit[falta["j"]])])
        q = q.merge(falta, on=["i", "j"], how="left")
        q["P"] = q["P"].fillna(q["P2"])
        q["bloqueado"] = q["bloqueado"].fillna(q["bl2"]).astype(bool)
    p("\nprecision@25 (2.000 nodos de evalua; la v3 juzga los vecinos):")
    for nombre in Z:
        g = q[q["modelo"] == nombre]
        p("   {:<16} {:.1%}".format(nombre, ((g["P"] >= 0.5) & ~g["bloqueado"]).mean()))

    # --- los casos conocidos -----------------------------------------------------------
    _, _, _, _, c0, atomo_a_nodo = e47.nodos_y_capa0()
    p("\nCASOS CONOCIDOS: rango del otro titulo entre los vecinos (el menor de los dos sentidos)")
    p("   {:<46} ".format("") + "  ".join("{:>15}".format(n_) for n_ in Z))
    for a, b in e47.CASOS:
        i, j = atomo_a_nodo.get(c0.atomo(a)), atomo_a_nodo.get(c0.atomo(b))
        if i is None or j is None:
            p("   {} / {}: no esta en la base".format(a, b))
            continue
        p("   {:<46} ".format(a + " / " + b) + "  ".join(
            "{:>15,}".format(min(rango(Zm, i, j), rango(Zm, j, i))) for Zm in Z.values()))
    (SAL / "49_evaluar_bi_encoder.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
