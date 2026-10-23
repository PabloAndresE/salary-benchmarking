"""T-016: baseline estandar. JobBERT-v3 (TechWolf, multilingue) para recuperar sinonimos (protocolo de T-001) y el
«mapeo estandar» a la taxonomia ESCO en espanol (registro, T-016).

    CUDA_VISIBLE_DEVICES=N PYTHONPATH=.libs_tesis .venv/bin/python research/tesis/t16_jobbert.py

Necesita salidas/t16_esco_es.parquet (las 2.942 ocupaciones de la API oficial de ESCO, en espanol).
SALIDA: salidas/t16_jobbert.txt
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import torch

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
SAL = AQUI / "salidas"
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(RAIZ / "src"))
import t01_recuperacion_qwen as t01  # noqa: E402

MODELO = pathlib.Path("/root/salary-benchmarking/modelos/jobbert-v3")
SEM = 20261023


def cargar_jobbert():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(str(MODELO), device="cuda" if torch.cuda.is_available() else "cpu")


def embeber(m, textos, lote=256):
    """Rama «anchor» (titulos), como indica la ficha del modelo; normalizado."""
    from sentence_transformers.util import batch_to_device
    orden = np.argsort([len(t) for t in textos])
    out = np.zeros((len(textos), m.get_sentence_embedding_dimension()), dtype=np.float32)
    with torch.no_grad():
        for i in range(0, len(textos), lote):
            ii = orden[i:i + lote]
            f = batch_to_device(m.tokenize([textos[j] for j in ii]), m.device)
            f["text_keys"] = ["anchor"]
            e = m.forward(f)["sentence_embedding"].float()
            out[ii] = torch.nn.functional.normalize(e, dim=-1).cpu().numpy()
    return out


def parte_a(m, out):
    celdas, grupo, _ = t01.cargar_base()
    idx = {c: i for i, c in enumerate(celdas)}
    q = t01.oro(idx, grupo)
    q["grupo_propio"] = [int(grupo[idx[c]]) for c in q["consulta"]]
    D = embeber(m, [c.title() for c in celdas])         # titulo con mayusculas iniciales, como texto natural
    np.save(SAL / "t16_emb_jobbert.npy", D.astype(np.float16))
    r_j = t01.ranking(D[[idx[c] for c in q["consulta"]]], D, grupo, q)
    prev = pd.read_parquet(SAL / "t01_rangos.parquet")
    assert list(prev["consulta"]) == list(q["consulta"]), "el oro no coincide con el de T-001"
    res = {"Vertex": prev["V"].to_numpy(), "Qwen titulo": prev["Q-t"].to_numpy(),
           "Qwen titulo+desc": prev["Q-d"].to_numpy(), "JobBERT-v3": r_j}
    out.append("PARTE A · recuperacion de sinonimos (protocolo T-001): {:,} consultas, {} pares".format(
        len(q), q["par"].nunique()))
    for k, r in res.items():
        out.append("  {:<17} r@1 {:.1%}  r@10 {:.1%}  MRR {:.3f}".format(k, (r <= 1).mean(), (r <= 10).mean(),
                                                                      (1 / r).mean()))
    rng = np.random.default_rng(SEM)
    pares = q["par"].unique()
    for ref in ("Qwen titulo+desc", "Vertex"):
        bs = []
        for _ in range(2000):
            s = np.isin(q["par"].to_numpy(), rng.choice(pares, len(pares)))
            bs.append((r_j[s] <= 10).mean() - (res[ref][s] <= 10).mean())
        d0 = (r_j <= 10).mean() - (res[ref] <= 10).mean()
        lo, hi = np.percentile(bs, [2.5, 97.5])
        out.append("  JobBERT - {}: {:+.1f} pts [{:+.1f}, {:+.1f}] -> {}".format(
            ref, 100 * d0, 100 * lo, 100 * hi, "MEJOR" if lo > 0 else ("PEOR" if hi < 0 else "no se distingue")))
    return D, celdas


def esco(m):
    e = pd.read_parquet(SAL / "t16_esco_es.parquet")
    textos, dueno = [], []
    for k, (pref, alt) in enumerate(zip(e["preferido"], e["alternativos"])):
        nombres = {p.strip() for p in str(pref).split("/") if p.strip()} | {a.strip() for a in json.loads(alt) if a.strip()}
        for n in nombres:
            textos.append(n[:1].upper() + n[1:])
            dueno.append(k)
    return e, embeber(m, textos), np.array(dueno)


def mapear(T, E, dueno):
    """Ocupacion ESCO de cada titulo: la de su nombre mas parecido (similitud maxima)."""
    s = T @ E.T
    j = s.argmax(1)
    return dueno[j], s.max(1)


def parte_b(m, D, celdas, out):
    e9 = __import__("importlib").import_module("t09_etapa1")
    e, E, dueno = esco(m)
    _, smax = mapear(D, E, dueno)
    out += ["", "PARTE B · mapeo estandar a ESCO ({:,} ocupaciones, {:,} nombres en espanol)".format(len(e), len(E)),
            "  cobertura: similitud con la ocupacion mas cercana, titulos de la base: mediana {:.2f}; >= 0,8 {:.0%}; "
            ">= 0,9 {:.0%}".format(np.median(smax), (smax >= 0.8).mean(), (smax >= 0.9).mean())]
    from benchmarking.producto.juez import cargar as cargar_juez
    jueces = {k: cargar_juez(v) for k, v in e9.MODELOS.items()}
    rng = np.random.default_rng(SEM + 1)
    for nom, d in e9.conjuntos().items():
        y = d["y"].to_numpy()
        ta, tb = embeber(m, [t.title() for t in d["a"]]), embeber(m, [t.title() for t in d["b"]])
        oa, _ = mapear(ta, E, dueno)
        ob, _ = mapear(tb, E, dueno)
        pred = {"ESCO (JobBERT)": (oa == ob).astype(int)}
        for k, j in jueces.items():
            pred["cross-encoder " + ("del producto" if k == "v3" else "reentrenado")] = (
                j.P(list(zip(d["a"], d["b"]))) >= 0.5).astype(int)
        bal = lambda p, ii: 0.5 * ((p[ii][y[ii] == 1] == 1).mean() + (p[ii][y[ii] == 0] == 0).mean())  # noqa: E731
        todos = np.arange(len(y))
        out.append("  {} (n={}, si {}):".format(nom, len(y), int(y.sum())))
        for k, p in pred.items():
            out.append("    {:<28} exactitud balanceada {:.3f}  (si juntos {:.1%}, no separados {:.1%})".format(
                k, bal(p, todos), (p[y == 1] == 1).mean(), (p[y == 0] == 0).mean()))
        i1, i0 = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
        for ref in ("cross-encoder reentrenado", "cross-encoder del producto"):
            bs = [bal(pred["ESCO (JobBERT)"], ii) - bal(pred[ref], ii)
                  for ii in (np.concatenate([rng.choice(i1, len(i1)), rng.choice(i0, len(i0))]) for _ in range(2000))]
            d0 = bal(pred["ESCO (JobBERT)"], todos) - bal(pred[ref], todos)
            lo, hi = np.percentile(bs, [2.5, 97.5])
            out.append("    ESCO - {}: {:+.3f} [{:+.3f}, {:+.3f}] -> {}".format(
                ref, d0, lo, hi, "ESCO MEJOR" if lo > 0 else ("ESCO PEOR" if hi < 0 else "no se distingue")))


def main():
    m = cargar_jobbert()
    out = ["T-016 · baseline estandar: JobBERT-v3 (TechWolf) y mapeo a ESCO en espanol", ""]
    D, celdas = parte_a(m, out)
    parte_b(m, D, celdas, out)
    (SAL / "t16_jobbert.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
