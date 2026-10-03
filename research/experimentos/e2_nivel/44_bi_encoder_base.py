"""D-044: modelo base del bi-encoder, comparacion SIN entrenar contra Vertex.

Registrado antes de medir (D-044, commit 7a4eaf8). Verdad: los pares de `43_pares.csv` que la v3
dice `si` (P >= 0,5, sin candado). Para cada modelo, sobre los 58.051 nodos de base_v16:
    recall@100 (principal) y recall@25: fraccion de esos pares que queda entre los k vecinos mas
        cercanos de alguno de los dos; tambien ponderada por personas;
    precision@25: de los 25 vecinos de los 2.000 nodos de la muestra, fraccion que la v3 dice `si`.
Criterio: el abierto con mayor recall@100; si el IC 95 % de la diferencia con el siguiente toca
cero (bootstrap por nodo sorteado, 10.000), gana el mas chico.

    .venv/bin/python 44_bi_encoder_base.py

SALIDAS: salidas/44_bi_encoder_base.txt, 44_precision_pares.csv; modelos/<nombre>/ (pesos, fuera
del repo)
"""
import contextlib
import importlib.util
import json
import os
import pathlib
import sys
import time

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
MOD = RAIZ / "modelos"
V3 = SAL / "22_modelos_v3" / "elegido"
SEM, B = 20261003, 10_000
# nombre corto, repo, pooling, prefijo, parametros (millones, de la ficha)
MODELOS = [("e5-base", "intfloat/multilingual-e5-base", "media", "query: ", 278),
           ("e5-large", "intfloat/multilingual-e5-large", "media", "query: ", 560),
           ("bge-m3", "BAAI/bge-m3", "cls", "", 568),
           ("mpnet", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "media", "",
            278)]


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def bajar(repo, corto):
    from huggingface_hub import snapshot_download
    destino = MOD / corto
    snapshot_download(repo, local_dir=destino,
                      allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt",
                                      "sentencepiece*", "tokenizer*"],
                      ignore_patterns=["onnx/*", "openvino/*", "*/*"])
    from huggingface_hub import HfApi
    return HfApi().model_info(repo).sha


def embeber(ruta, textos, pooling, prefijo, dev, lote=512):
    import torch
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(ruta)
    m = AutoModel.from_pretrained(ruta, torch_dtype=torch.float16).to(dev).eval()
    out = []
    with torch.no_grad():
        for a in range(0, len(textos), lote):
            t = tok([prefijo + x for x in textos[a:a + lote]], padding=True, truncation=True,
                    max_length=64, return_tensors="pt").to(dev)
            h = m(**t).last_hidden_state.float()
            if pooling == "cls":
                v = h[:, 0]
            else:
                msk = t["attention_mask"].unsqueeze(-1).float()
                v = (h * msk).sum(1) / msk.sum(1)
            out.append(torch.nn.functional.normalize(v, dim=-1).cpu().numpy())
    del m
    torch.cuda.empty_cache()
    return np.vstack(out).astype(np.float32)


def recall(vec, i, j):
    ev = [set(v) for v in vec]
    return np.array([(b in ev[a]) or (a in ev[b]) for a, b in zip(i, j)])


def main():
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    import torch
    from transformers import AutoTokenizer
    e22 = cargar("e22", "22_entrenar_cross.py")
    e31 = cargar("e31", "31_h4_prueba2.py")
    e43 = cargar("e43", "43_perdida_vertex.py")
    dev = "cuda"
    t0 = time.time()
    out = []

    def p(s=""):
        print(s, flush=True)
        out.append(s)

    tit, Zv, per = e43.nodos()
    d = pd.read_csv(SAL / "43_pares.csv")
    si = d[(d["P"] >= 0.5) & ~d["bloqueado"]].reset_index(drop=True)
    muestra = np.array(sorted(set(d["i"])))
    vectores = {"Vertex": Zv}
    revision = {}
    for corto, repo, pooling, prefijo, _ in MODELOS:
        revision[corto] = bajar(repo, corto)
        vectores[corto] = embeber(str(MOD / corto), list(tit), pooling, prefijo, dev)
        print("   {} embebido ({:.0f} s)".format(corto, time.time() - t0), flush=True)

    p("=" * 78)
    p("44 · MODELO BASE DEL BI-ENCODER, SIN ENTRENAR (D-044)")
    p("=" * 78)
    p("nodos {:,}; pares `si` de la v3 (verdad): {:,} de {:,} nodos sorteados".format(
        len(tit), len(si), si["i"].nunique()))
    p("revisiones: " + ", ".join("{} {}".format(k, v[:12]) for k, v in revision.items()))

    acierto, prec_pares = {}, []
    for nombre, Z in vectores.items():
        v100 = e43.vecinos_vertex(Z, 100)
        acierto[nombre] = {k: recall(v100[:, :k], si["i"], si["j"]) for k in (25, 100)}
        for a in muestra:
            for b in v100[a, :25]:
                prec_pares.append((nombre, int(a), int(b)))

    # precision@25: la v3 juzga los vecinos propuestos (cada par una sola vez)
    pp = pd.DataFrame(prec_pares, columns=["modelo", "i", "j"])
    pp["a"], pp["b"] = tit[pp["i"]], tit[pp["j"]]
    unicos = pp[["a", "b"]].drop_duplicates().reset_index(drop=True)
    base = RAIZ / "modelos" / "mdeberta-xnli"
    tok = AutoTokenizer.from_pretrained(base)
    inf = json.loads((V3 / "info.json").read_text(encoding="utf-8"))
    m = e22.construir(V3, False, dev)
    ab, ba = e22.puntuar(m, tok, unicos["a"].tolist(), unicos["b"].tolist(), dev,
                         contextlib.nullcontext)
    unicos["P"] = e31.calibrada(e22.puntaje(inf["modo"], ab, ba), inf["temperatura"])
    unicos["bloqueado"] = [e43.bloqueado(a, b) for a, b in zip(unicos["a"], unicos["b"])]
    pp = pp.merge(unicos, on=["a", "b"])
    pp.to_csv(SAL / "44_precision_pares.csv", index=False, encoding="utf-8")

    w = si["personas"].to_numpy()
    p("\n{:<10} {:>10} {:>10} {:>12} {:>13}".format(
        "modelo", "recall@25", "recall@100", "rec@100 pers", "precision@25"))
    for nombre in vectores:
        a25, a100 = acierto[nombre][25], acierto[nombre][100]
        q = pp[pp["modelo"] == nombre]
        p("{:<10} {:>10.1%} {:>10.1%} {:>12.1%} {:>13.1%}".format(
            nombre, a25.mean(), a100.mean(), (a100 * w).sum() / w.sum(),
            ((q["P"] >= 0.5) & ~q["bloqueado"]).mean()))

    # --- criterio: bootstrap por nodo sorteado ---------------------------------------
    abiertos = sorted((n for n in vectores if n != "Vertex"),
                      key=lambda n: -acierto[n][100].mean())
    nodo = si["i"].to_numpy()
    u = np.unique(nodo)
    pos = {x: k for k, x in enumerate(u)}
    idx = np.array([pos[x] for x in nodo])
    rng = np.random.default_rng(SEM)

    def boot(a, b):
        ha = np.bincount(idx, acierto[a][100], len(u))
        hb = np.bincount(idx, acierto[b][100], len(u))
        nn = np.bincount(idx, minlength=len(u)).astype(float)
        dd = np.empty(B)
        for k in range(B):
            r = rng.integers(0, len(u), len(u))
            dd[k] = ha[r].sum() / nn[r].sum() - hb[r].sum() / nn[r].sum()
        return acierto[a][100].mean() - acierto[b][100].mean(), *np.percentile(dd, [2.5, 97.5])

    p("\nCONTRASTES de recall@100 (IC 95 %, bootstrap por nodo sorteado, {:,})".format(B))
    primero, segundo = abiertos[0], abiertos[1]
    d12, lo, hi = boot(primero, segundo)
    p("   {} - {:<9} {:+.1%}  [{:+.1%}, {:+.1%}]".format(primero, segundo, d12, lo, hi))
    for n in abiertos:
        dv, lo_v, hi_v = boot(n, "Vertex")
        p("   {} - Vertex {:+.1%}  [{:+.1%}, {:+.1%}]".format(n, dv, lo_v, hi_v))
    tam = {c: prm for c, _, _, _, prm in MODELOS}
    if lo > 0:
        elegido = primero
        razon = "mayor recall@100, con el IC sobre cero frente al segundo"
    else:
        empatados = [n for n in abiertos if n == primero or n == segundo]
        elegido = min(empatados, key=lambda n: tam[n])
        razon = "empate con IC que toca cero entre {} y {}: gana el mas chico".format(
            primero, segundo)
    p("\n>>> CRITERIO D-044: {} ({} M parametros). {} <<<".format(elegido, tam[elegido], razon))
    p("\n({:.0f} s)".format(time.time() - t0))
    (SAL / "44_bi_encoder_base.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
