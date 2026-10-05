"""D-045 §6: afinar e5-base destilando la v3. Solo lado `entrena`; la epoca se elige en `valida`.

DATOS (`47_pares.parquet`, `47_nodos.parquet`):
    positivos   P >= 0,8 sin candado si cos_vertex >= 0,85; P >= 0,9 si cos_vertex < 0,85 (la regla
                de la auditoria de D-045 §2: 89 % de acierto lejos).
    negativos   difiles: P <= 0,2, o bloqueados por un candado (nivel, seniority, grado); al azar: el
                resto del lote.
LOTES: 256 pares, NUNCA dos de la misma comunidad de Louvain (D-045 §4). En cada paso se sortean 256
comunidades distintas con probabilidad proporcional a sus positivos, y un positivo de cada una; a
cada ancla se le agrega, si tiene, un negativo dificil al azar. Una epoca = positivos / 256 pasos.
PERDIDA: MultipleNegativesRanking (escala 20): el ancla contra todos los positivos y negativos
dificiles del lote.
MODELO: e5-base (`modelos/e5-base`, revision d12875059715), prefijo `query: `, promedio de tokens,
normalizado; lr 2e-5, calentamiento 10 %, AdamW, bf16, hasta 3 epocas, semillas 1, 2 y 3.
SELECCION: recall@100 en `valida` (pares `si` de la v3 con los dos nodos en `valida`, buscando sobre
los 58.051 nodos) al final de cada epoca; se guarda la mejor de cada semilla, y se elige la semilla
con mejor valida. La evaluacion (lado `evalua`) es otro guion: `49`.

    CUDA_VISIBLE_DEVICES=0 .venv/bin/python 48_entrenar_bi_encoder.py

SALIDAS: salidas/48_bi_encoder/semilla_K/ (pesos, fuera del repo), 48_bi_encoder/resultados.json,
salidas/48_entrenar_bi_encoder.log
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import torch

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
E5 = RAIZ / "modelos" / "e5-base"
DESTINO = SAL / "48_bi_encoder"
LOTE, LR, EPOCAS, ESCALA, LARGO = 256, 2e-5, 3, 20.0, 32
SEMILLAS = (1, 2, 3)


def git(*c):
    return subprocess.run(["git", *c], cwd=RAIZ, capture_output=True, text=True).stdout.strip()


def datos():
    d = pd.read_parquet(SAL / "47_pares.parquet")
    nodos = pd.read_parquet(SAL / "47_nodos.parquet")
    pos = ~d["bloqueado"] & (((d["cos_vertex"] >= 0.85) & (d["P"] >= 0.8))
                             | ((d["cos_vertex"] < 0.85) & (d["P"] >= 0.9)))
    neg = d["bloqueado"] | (d["P"] <= 0.2)
    ent = d["lado"] == "entrena"
    P = d[ent & pos][["i", "j", "comp_i"]].reset_index(drop=True)
    N = d[ent & neg][["i", "j"]]
    duros = {}
    for i, j in zip(N["i"], N["j"]):
        duros.setdefault(int(i), []).append(int(j))
        duros.setdefault(int(j), []).append(int(i))
    # validacion SOLO con pares de fuentes que no son los modelos comparados (por letras o Gemini):
    # los vecinos de e5 o de Vertex como verdad favorecen a ese mismo modelo (49, 2026-10-05)
    indep = d["fuente"].str.contains("cerca_tfidf|gemini")
    va = d[(d["lado"] == "valida") & (d["P"] >= 0.5) & ~d["bloqueado"] & indep][["i", "j"]]
    # pares que la v3 ya confirmo: no pueden ser negativos dentro del lote
    sab = d[(d["P"] >= 0.5) & ~d["bloqueado"] & ent]
    conocidos = set(zip(sab["i"], sab["j"])) | set(zip(sab["j"], sab["i"]))
    return nodos["titulo"].tolist(), P, duros, va, conocidos


class Codificador(torch.nn.Module):
    def __init__(self, ruta):
        super().__init__()
        from transformers import AutoModel
        self.m = AutoModel.from_pretrained(ruta)

    def forward(self, t):
        h = self.m(**t).last_hidden_state
        msk = t["attention_mask"].unsqueeze(-1).to(h.dtype)
        return torch.nn.functional.normalize((h * msk).sum(1) / msk.sum(1), dim=-1)


def codificar(mod, tok, textos, lote=1024):
    mod.eval()
    out = []
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        for a in range(0, len(textos), lote):
            t = tok(["query: " + x for x in textos[a:a + lote]], padding=True, truncation=True,
                    max_length=LARGO, return_tensors="pt").to("cuda")
            out.append(mod(t).float())
    mod.train()
    return torch.cat(out)


def recall_valida(mod, tok, tit, va, k=100):
    Z = codificar(mod, tok, tit)
    nodos = np.unique(va[["i", "j"]].to_numpy())
    vec = {}
    for a in range(0, len(nodos), 2048):
        ix = torch.from_numpy(nodos[a:a + 2048]).cuda()
        s = Z[ix] @ Z.T
        s[torch.arange(len(ix)), ix] = -2
        for x, fila in zip(nodos[a:a + 2048], s.topk(k, dim=1).indices.cpu().numpy()):
            vec[int(x)] = set(fila.tolist())
    hit = [(j in vec[i]) or (i in vec[j]) for i, j in zip(va["i"], va["j"])]
    return float(np.mean(hit))


def una_semilla(sem, tit, P, duros, va, log, conocidos=None, lotes="comunidad", lr=LR,
                epocas=EPOCAS, destino=None):
    destino = destino or DESTINO
    from transformers import AutoTokenizer, get_linear_schedule_with_warmup
    torch.manual_seed(sem)
    rng = np.random.default_rng(sem)
    tok = AutoTokenizer.from_pretrained(E5)
    mod = Codificador(E5).cuda()
    por_comp = P.groupby("comp_i").indices
    comps = np.array(list(por_comp))
    peso = np.array([len(por_comp[c]) for c in comps], dtype=float)
    peso /= peso.sum()
    pasos = len(P) // LOTE
    opt = torch.optim.AdamW(mod.parameters(), lr=lr)
    sch = get_linear_schedule_with_warmup(opt, int(0.1 * pasos * epocas), pasos * epocas)
    mejor, hist = -1.0, []
    r0 = recall_valida(mod, tok, tit, va)
    log("semilla {}: recall@100 valida sin entrenar {:.4f}; {} pasos por epoca".format(sem, r0, pasos))
    for ep in range(1, epocas + 1):
        t0, perdidas = time.time(), []
        for _ in range(pasos):
            if lotes == "comunidad":
                cs = rng.choice(comps, min(LOTE, len(comps)), replace=False, p=peso)
                filas = P.iloc[[rng.choice(por_comp[c]) for c in cs]]
            else:
                filas = P.iloc[rng.choice(len(P), LOTE, replace=False)]
            gira = rng.random(len(filas)) < 0.5          # el ancla puede ser cualquiera de los dos
            anc = np.where(gira, filas["j"], filas["i"])
            posi = np.where(gira, filas["i"], filas["j"])
            negs = [int(rng.choice(duros[a])) for a in anc if a in duros]
            textos = [tit[x] for x in anc] + [tit[x] for x in posi] + [tit[x] for x in negs]
            t = tok(["query: " + x for x in textos], padding=True, truncation=True,
                    max_length=LARGO, return_tensors="pt").to("cuda")
            with torch.autocast("cuda", dtype=torch.bfloat16):
                e = mod(t).float()
            n = len(anc)
            s = e[:n] @ e[n:].T * ESCALA
            if conocidos is not None:
                # fuera de la diagonal: el mismo nodo o un par ya confirmado por la v3 no es negativo
                cand = list(posi) + negs
                malo = np.array([[(int(a) == int(c) or (int(a), int(c)) in conocidos) and k != q
                                  for q, c in enumerate(cand)] for k, a in enumerate(anc)])
                if malo.any():
                    s = s.masked_fill(torch.from_numpy(malo).cuda(), -1e4)
            perdida = torch.nn.functional.cross_entropy(s, torch.arange(n, device="cuda"))
            perdida.backward()
            torch.nn.utils.clip_grad_norm_(mod.parameters(), 1.0)
            opt.step()
            sch.step()
            opt.zero_grad()
            perdidas.append(float(perdida.detach()))
        r = recall_valida(mod, tok, tit, va)
        hist.append({"epoca": ep, "perdida": float(np.mean(perdidas)), "recall100_valida": r})
        log("   semilla {} epoca {}: perdida {:.4f}  recall@100 valida {:.4f}  ({:.0f} s)".format(
            sem, ep, np.mean(perdidas), r, time.time() - t0))
        if r > mejor:
            mejor = r
            ruta = destino / "semilla_{}".format(sem)
            mod.m.save_pretrained(ruta)
            tok.save_pretrained(ruta)
            (ruta / "info.json").write_text(json.dumps(
                {"semilla": sem, "epoca": ep, "recall100_valida": r, "prefijo": "query: ",
                 "pooling": "media", "largo": LARGO}, indent=2), encoding="utf-8")
    del mod
    torch.cuda.empty_cache()
    return {"semilla": sem, "recall100_valida_sin_entrenar": r0, "mejor": mejor, "historia": hist}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variante", default="", help="vacio = la corrida original")
    ap.add_argument("--lotes", default="comunidad", choices=["comunidad", "azar"])
    ap.add_argument("--lr", type=float, default=LR)
    ap.add_argument("--epocas", type=int, default=EPOCAS)
    ap.add_argument("--semillas", default="1,2,3")
    a = ap.parse_args()
    global DESTINO
    if a.variante:
        DESTINO = SAL / "48_bi_encoder_{}".format(a.variante)
    DESTINO.mkdir(parents=True, exist_ok=True)
    lineas = []

    def log(s):
        print(s, flush=True)
        lineas.append(s)
        (DESTINO / "entrenar.log").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    tit, P, duros, va, conocidos = datos()
    log("variante {!r}: lotes {}, lr {}, epocas {}".format(a.variante, a.lotes, a.lr, a.epocas))
    log("48 · BI-ENCODER e5-base DESTILADO DE LA v3 (D-045)")
    log("commit {} sin commitear {}".format(git("rev-parse", "HEAD")[:7],
                                           bool(git("status", "--porcelain"))))
    log("positivos (entrena) {:,} en {:,} comunidades; anclas con negativo dificil {:,}; pares "
        "`si` de valida {:,}".format(len(P), P["comp_i"].nunique(), len(duros), len(va)))
    res = [una_semilla(int(s), tit, P, duros, va, log,
                       conocidos=conocidos if a.lotes == "azar" else None, lotes=a.lotes, lr=a.lr,
                       epocas=a.epocas) for s in a.semillas.split(",")]
    elegida = max(res, key=lambda r: r["mejor"])
    log("ELEGIDA: semilla {} (recall@100 valida {:.4f})".format(elegida["semilla"], elegida["mejor"]))
    (DESTINO / "resultados.json").write_text(json.dumps(
        {"commit": git("rev-parse", "HEAD"), "sin_commitear": bool(git("status", "--porcelain")),
         "semillas": res, "elegida": elegida["semilla"],
         "hiper": {"lote": LOTE, "lr": a.lr, "epocas": a.epocas, "escala": ESCALA, "largo": LARGO,
                   "lotes": a.lotes, "variante": a.variante}},
        indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
