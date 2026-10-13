"""T-003 etapa 1: el nivel jerarquico dentro del texto embebido (documento y consulta), y los dos indicadores.

    CUDA_VISIBLE_DEVICES=1 ../../.venv/bin/python t03_nivel_qwen.py

SALIDAS: salidas/t03_emb_doc.npy, t03_emb_consulta.npy (orden de base_v31), salidas/t03_etapa1.txt
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import LogisticRegression

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(AQUI))
import t01_recuperacion_qwen as t01  # noqa: E402
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.producto.base_referencia import P_NIVEL_CLF, BaseReferencia  # noqa: E402

SAL = AQUI / "salidas"
NOMBRE = {1: "operativo o asistente", 2: "tecnico o analista", 3: "supervision o coordinacion", 4: "jefatura",
          5: "gerencia o direccion"}


def normal(X):
    X = np.asarray(X, np.float32)
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def nivel_cruzado(X, niv, grupo, folds=5, semilla=4):
    """Nivel predicho por el clasificador sobre X, con prediccion cruzada por grupos; NaN si P < P_NIVEL_CLF."""
    ok = np.isfinite(niv)
    gs = np.unique(grupo)
    asig = dict(zip(gs, np.random.default_rng(semilla).integers(0, folds, len(gs))))
    f = np.array([asig[g] for g in grupo])
    pred = np.full(len(niv), np.nan)
    for k in range(folds):
        tr, te = ok & (f != k), f == k
        clf = LogisticRegression(max_iter=2000, C=1.0).fit(X[tr], niv[tr].astype(int))
        p = clf.predict_proba(X[te])
        mejor = p.argmax(1)
        pred[te] = np.where(p.max(1) >= P_NIVEL_CLF, clf.classes_[mejor], np.nan)
    return pred


def main():
    b = BaseReferencia.cargar(RAIZ / "demo" / "base_v31.npz", cargar_settings().get_sbu)
    b.nivel_por_grupo()
    celdas = [str(c) for c in b.celdas]
    niv = np.asarray(b.nivel, float)
    grupo = np.asarray(b.grupo)
    d = pd.read_csv(RAIZ / "research/experimentos/e2_nivel/salidas/46_descripciones.csv")
    desc = {}
    for t, r in zip(d["titulo"].astype(str), d["respuesta"].astype(str)):
        try:
            x = json.loads(r).get("descripcion", "").strip()
        except ValueError:
            x = ""
        if x:
            desc[t] = x
    docs = []
    for c, n in zip(celdas, niv):
        s = "Cargo: {}.".format(c)
        if np.isfinite(n):
            s += " Nivel: {}.".format(NOMBRE[int(n)])
        if c in desc:
            s += " Descripcion: {}".format(desc[c])
        docs.append(s)
    Qc0 = normal(np.load(SAL / "t02_emb_qwen_consulta.npy"))
    pred = nivel_cruzado(Qc0, niv, grupo)
    acierto = (pred[np.isfinite(pred) & np.isfinite(niv)] == niv[np.isfinite(pred) & np.isfinite(niv)]).mean()
    consultas = [("{} (nivel estimado: {})".format(c, NOMBRE[int(p)]) if np.isfinite(p) else c) for c, p in zip(celdas, pred)]
    m = t01.Qwen()
    fd, fq = SAL / "t03_emb_doc.npy", SAL / "t03_emb_consulta.npy"
    D = np.load(fd) if fd.exists() else m(docs, largo=160)
    np.save(fd, D)
    Q = np.load(fq) if fq.exists() else m(["Instruct: {}\nQuery:{}".format(t01.TAREA, c) for c in consultas], largo=80)
    np.save(fq, Q)
    D, Q = normal(D), normal(Q)
    # indicador 1: vecinos top-10 (de otro grupo) con el mismo nivel; mismas 4.000 consultas que el diagnostico
    ok = np.isfinite(niv)
    rng = np.random.default_rng(3)
    gs = np.unique(grupo[ok])
    rng.choice(gs, len(gs) // 5, replace=False)          # mismo estado del generador que t03_diagnostico_nivel
    qi = rng.choice(np.flatnonzero(ok), 4000, replace=False)
    Dg = torch.tensor(D, device="cuda", dtype=torch.float16)
    g = torch.tensor(grupo, device="cuda")
    igual = []
    for i in range(0, len(qi), 500):
        ii = qi[i:i + 500]
        s = (torch.tensor(Q[ii], device="cuda", dtype=torch.float16) @ Dg.T).float()
        s[g[ii].unsqueeze(1) == g.unsqueeze(0)] = -9
        top = s.topk(10, dim=1).indices.cpu().numpy()
        igual.append(np.nanmean(niv[top] == niv[ii][:, None], axis=1))
    ind1 = float(np.concatenate(igual).mean())
    # indicador 2: recall@10 del oro de T-001
    idx = {c: i for i, c in enumerate(celdas)}
    q = t01.oro(idx, grupo)
    q["grupo_propio"] = [int(grupo[idx[c]]) for c in q["consulta"]]
    r = t01.ranking(Q[[idx[c] for c in q["consulta"]]].astype(np.float16), D.astype(np.float16), grupo, q)
    ind2 = float((r <= 10).mean())
    out = ["T-003 ETAPA 1 · nivel en el texto embebido",
           "nivel predicho para la consulta: {:.1%} de los titulos con prediccion segura; acierta {:.1%}".format(
               np.isfinite(pred).mean(), acierto),
           "indicador 1, vecinos top-10 con el mismo nivel: {:.1%} (Vertex 72,3 %; T-002 68,5 %) -> {}".format(
               ind1, "pasa" if ind1 > 0.723 else "NO pasa"),
           "indicador 2, recall@10 del oro de T-001: {:.1%} (minimo 21,2 %; Q-d 22,2 %) -> {}".format(
               ind2, "pasa" if ind2 >= 0.212 else "NO pasa"),
           "ETAPA 1: {}".format("PASA -> etapa 2 (pinball)" if ind1 > 0.723 and ind2 >= 0.212 else "NO PASA")]
    (SAL / "t03_etapa1.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
