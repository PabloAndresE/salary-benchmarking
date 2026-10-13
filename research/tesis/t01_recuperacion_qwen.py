"""T-001: busqueda semantica, Qwen3-Embedding-8B frente a Vertex (ver docs/registro_decisiones.md, T-001).

Oro: pares de sinonimos aprobados por el autor (rondas 1-2) en grupos distintos + pares `si` de la validacion a mano.
Cada par en las dos direcciones; acierto = cualquier titulo del grupo del otro; el grupo de la consulta se excluye.
Ranking por GRUPO (puntaje del grupo = maximo coseno de sus titulos). recall@1/5/10 y MRR, IC por bootstrap de pares.

    CUDA_VISIBLE_DEVICES=1 ../../.venv/bin/python t01_recuperacion_qwen.py

SALIDAS: salidas/t01_emb_qwen_titulo.npy, t01_emb_qwen_desc.npy (cache), salidas/t01_recuperacion.txt
"""
import json
import pathlib
import time

import numpy as np
import pandas as pd
import torch

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
SAL = AQUI / "salidas"
MODELO = RAIZ / "modelos" / "qwen3-embedding-8b"
TAREA = ("Dado un titulo de cargo escrito en una nomina de una empresa de Ecuador, recupera el cargo equivalente "
         "del catalogo salarial")


def cargar_base():
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    return celdas, np.asarray(b["grupo"]), np.asarray(b["Z"], dtype=np.float32)


def descripciones(celdas):
    d = pd.read_csv(RAIZ / "research/experimentos/e2_nivel/salidas/46_descripciones.csv")
    out = {}
    for t, r in zip(d["titulo"].astype(str), d["respuesta"].astype(str)):
        try:
            x = json.loads(r).get("descripcion", "").strip()
        except ValueError:
            x = ""
        if x:
            out[t] = x
    return [("{}: {}".format(c, out[c]) if c in out else c) for c in celdas], sum(c in out for c in celdas)


def oro(idx, grupo):
    pares = pd.read_csv(RAIZ / "src/benchmarking/producto/datos/sinonimos_v2/sinonimos.csv")
    p = [(a, b, "sinonimos") for a, b in zip(pares["titulo_a"], pares["titulo_b"])]
    v = pd.read_csv(RAIZ / "research/experimentos/e2_nivel/salidas/52_validacion_para_juzgar.csv", encoding="utf-8-sig")
    p += [(a, b, "validacion") for a, b, s in zip(v["a"], v["b"], v["mismo"]) if str(s).strip().lower() == "si"]
    q = []
    for k, (a, b, f) in enumerate(p):
        a, b = str(a).strip().upper(), str(b).strip().upper()
        if a in idx and b in idx and grupo[idx[a]] != grupo[idx[b]]:
            q += [(k, a, int(grupo[idx[b]]), f), (k, b, int(grupo[idx[a]]), f)]
    return pd.DataFrame(q, columns=["par", "consulta", "grupo_oro", "fuente"])


class Qwen:
    def __init__(self):
        from transformers import AutoModel, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(MODELO, padding_side="left")
        self.m = AutoModel.from_pretrained(MODELO, torch_dtype=torch.bfloat16).cuda().eval()

    @torch.no_grad()
    def __call__(self, textos, lote=256, largo=96):
        out = []
        for i in range(0, len(textos), lote):
            x = self.tok(textos[i:i + lote], padding=True, truncation=True, max_length=largo, return_tensors="pt").to("cuda")
            h = self.m(**x).last_hidden_state[:, -1]           # ultimo token (relleno a la izquierda)
            out.append(torch.nn.functional.normalize(h.float(), dim=-1).cpu().numpy().astype(np.float16))
        return np.vstack(out)


def ranking(Qv, D, grupo, q):
    """Rango del grupo de oro (1 = primero) entre grupos, excluyendo el grupo propio de la consulta."""
    Dg = torch.tensor(D, device="cuda", dtype=torch.float16)
    g = torch.tensor(grupo, device="cuda", dtype=torch.long)
    ng = int(grupo.max()) + 1
    rangos = []
    for i in range(0, len(Qv), 256):
        s = (torch.tensor(Qv[i:i + 256], device="cuda", dtype=torch.float16) @ Dg.T).float()
        gm = torch.full((s.shape[0], ng), -9.0, device="cuda").scatter_reduce(1, g.expand(s.shape[0], -1), s, "amax")
        for r, (_, fila) in enumerate(q.iloc[i:i + 256].iterrows()):
            gm[r, fila["grupo_propio"]] = -9.0
            rangos.append(int((gm[r] > gm[r, fila["grupo_oro"]]).sum().item()) + 1)
    return np.array(rangos)


def medidas(r):
    return {"r@1": (r <= 1).mean(), "r@5": (r <= 5).mean(), "r@10": (r <= 10).mean(), "mrr": (1.0 / r).mean()}


def main():
    t0 = time.time()
    celdas, grupo, Zv = cargar_base()
    idx = {c: i for i, c in enumerate(celdas)}
    q = oro(idx, grupo)
    q["grupo_propio"] = [int(grupo[idx[c]]) for c in q["consulta"]]
    docs_d, n_desc = descripciones(celdas)
    out = ["T-001 · BUSQUEDA: Qwen3-Embedding-8B frente a Vertex",
           "consultas {:,} ({} pares; {}); titulos en el indice {:,}; con descripcion {:,}".format(
               len(q), q["par"].nunique(), q["fuente"].value_counts().to_dict(), len(celdas), n_desc)]
    Zv = Zv / np.linalg.norm(Zv, axis=1, keepdims=True)
    res = {"V": ranking(Zv[[idx[c] for c in q["consulta"]]], Zv, grupo, q)}
    m = Qwen()
    costos = {}
    for nom, docs in (("Q-t", celdas), ("Q-d", docs_d)):
        cache = SAL / "t01_emb_qwen_{}.npy".format("titulo" if nom == "Q-t" else "desc")
        t1 = time.time()
        if cache.exists():
            D = np.load(cache)
        else:
            D = m(docs, largo=32 if nom == "Q-t" else 128)
            np.save(cache, D)
        costos[nom] = time.time() - t1
        t1 = time.time()
        Qv = m(["Instruct: {}\nQuery:{}".format(TAREA, c) for c in q["consulta"]], largo=64)
        costos[nom + " consultas"] = (time.time() - t1) / len(q)
        res[nom] = ranking(Qv, D, grupo, q)
    rng = np.random.default_rng(1)
    pares = q["par"].unique()
    for nom, r in res.items():
        md = medidas(r)
        out.append("   {:<4} r@1 {:.1%}  r@5 {:.1%}  r@10 {:.1%}  MRR {:.3f}".format(nom, md["r@1"], md["r@5"], md["r@10"], md["mrr"]))
    for nom in ("Q-t", "Q-d"):
        dif = []
        for _ in range(1000):
            s = np.isin(q["par"].to_numpy(), rng.choice(pares, len(pares)))
            dif.append((res[nom][s] <= 10).mean() - (res["V"][s] <= 10).mean())
        dd = (res[nom] <= 10).mean() - (res["V"] <= 10).mean()
        lo, hi = np.percentile(dif, [2.5, 97.5])
        out.append("   {} - V, recall@10: {:+.1f} pts [{:+.1f}, {:+.1f}]".format(nom, 100 * dd, 100 * lo, 100 * hi))
    for f, x in q.groupby("fuente"):
        out.append("   por fuente {:<10} ".format(f) + "  ".join("{} r@10 {:.1%}".format(n, (res[n][x.index] <= 10).mean()) for n in res))
    out.append("costo: embeber la base Q-t {:.0f} s, Q-d {:.0f} s; por consulta {:.1f} ms; memoria GPU pico {:.1f} GB; total {:.0f} s".format(
        costos["Q-t"], costos["Q-d"], 1000 * costos["Q-d consultas"], torch.cuda.max_memory_allocated() / 1e9, time.time() - t0))
    mejor = max(("Q-t", "Q-d"), key=lambda n: (res[n] <= 10).mean())
    (SAL / "t01_recuperacion.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    pd.DataFrame({"consulta": q["consulta"], "fuente": q["fuente"], **{n: r for n, r in res.items()}}).to_parquet(SAL / "t01_rangos.parquet")
    print("\n".join(out))
    print("mejor Qwen:", mejor)


if __name__ == "__main__":
    main()
