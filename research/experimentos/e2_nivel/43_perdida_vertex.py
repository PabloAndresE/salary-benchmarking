"""D-043: ¿cuanto pierde Vertex como buscador de candidatos? Diagnostico antes del clustering.

Registrado antes de medir (D-043, commit b2a25af). Los pares salen de un buscador que NO usa
Vertex (TF-IDF de n-gramas de caracteres), los juzga el cross-encoder v3, y se cuenta cuantos `si`
no propondria Vertex (25 vecinos y un piso de coseno).

    .venv/bin/python 43_perdida_vertex.py            mide y escribe la auditoria ciega
    .venv/bin/python 43_perdida_vertex.py corregir   aplica la auditoria del autor y decide

SALIDAS: salidas/43_perdida_vertex.txt, 43_pares.csv, 43_auditoria_para_juzgar.csv (ciega:
n_ciego, a, b, mismo, nota) y 43_auditoria_mapa.csv (n_ciego -> par, tramo, P de la v3).
"""
import contextlib
import importlib.util
import json
import os
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto import capa0 as c0mod  # noqa: E402
from benchmarking.producto.nivel import nivel_rubrica, seniority_lexica  # noqa: E402

V16 = RAIZ / "demo" / "base_v16.npz"
V3 = SAL / "22_modelos_v3" / "elegido"
N_MUESTRA, K, SEM = 2000, 25, 20261003
PISOS = (0.80, 0.85, 0.90)
UMBRAL_PERDIDA = 0.05
N_AUD_SI, N_AUD_NO = 100, 50
TRAMOS = ("fuera de los 25 vecinos", "coseno < 0,80", "0,80 - 0,85", "0,85 - 0,90")


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def nodos():
    """Un representante por grupo de base_v16: la celda que ya es su atomo, o la mas corta."""
    b = np.load(V16, allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    c0 = c0mod.Capa0.de_json(str(b["capa0_json"]), celdas)
    grupo = b["grupo"].astype(int)
    rep = {}
    for i, (c, g) in enumerate(zip(celdas, grupo)):
        clave = (c != c0.atomo(c), len(c), c)
        if g not in rep or clave < rep[g][0]:
            rep[g] = (clave, i)
    ix = np.array(sorted(i for _, i in rep.values()))
    Z = b["Z"][ix].astype(np.float32)
    Z /= np.linalg.norm(Z, axis=1, keepdims=True)
    return (np.array(celdas, dtype=object)[ix], Z, b["personas"][ix].astype(float))


def vecinos_vertex(Z, k):
    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    T = torch.from_numpy(Z).to(dev)
    vec = np.empty((len(Z), k), dtype=np.int64)
    for a in range(0, len(Z), 4096):
        s = T[a:a + 4096] @ T.T
        s[torch.arange(s.shape[0]), torch.arange(a, a + s.shape[0])] = -2
        vec[a:a + 4096] = s.topk(k, dim=1).indices.cpu().numpy()
    return vec


def bloqueado(a, b):
    na, nb = nivel_rubrica(a), nivel_rubrica(b)
    if na and nb and na != nb:
        return True
    if seniority_lexica(a) != seniority_lexica(b):
        return True
    return not c0mod.compatibles(a, b)


def tramo(r):
    if not r["en_vecinos"]:
        return TRAMOS[0]
    if r["coseno"] < 0.80:
        return TRAMOS[1]
    if r["coseno"] < 0.85:
        return TRAMOS[2]
    return TRAMOS[3]


def medir():
    from sklearn.feature_extraction.text import TfidfVectorizer
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    from transformers import AutoTokenizer
    e22 = cargar("e22", "22_entrenar_cross.py")
    e31 = cargar("e31", "31_h4_prueba2.py")

    tit, Z, per = nodos()
    n = len(tit)
    rng = np.random.default_rng(SEM)
    muestra = rng.choice(n, N_MUESTRA, replace=False, p=per / per.sum())

    # buscador independiente: TF-IDF de 3-gramas de caracteres dentro de palabra
    X = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 3)).fit_transform(tit)
    S = (X[muestra] @ X.T).toarray()
    S[np.arange(N_MUESTRA), muestra] = -1
    tf = np.argsort(-S, axis=1)[:, :K]

    vec = vecinos_vertex(Z, K)
    en_v = [set(v) for v in vec]
    filas, vistos = [], set()
    for f, i in enumerate(muestra):
        for j in tf[f]:
            j = int(j)
            par = (min(i, j), max(i, j))
            if par in vistos or S[f, j] <= 0:
                continue
            vistos.add(par)
            filas.append({"i": int(i), "j": j, "a": tit[i], "b": tit[j],
                          "tfidf": float(S[f, j]), "coseno": float(Z[i] @ Z[j]),
                          "en_vecinos": j in en_v[i] or int(i) in en_v[j],
                          "personas": per[i]})
    d = pd.DataFrame(filas)
    d["bloqueado"] = [bloqueado(a, b) for a, b in zip(d["a"], d["b"])]

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    base = RAIZ / "modelos" / "mdeberta-xnli"
    e22.verificar_modelo(base)
    tok = AutoTokenizer.from_pretrained(base)
    inf = json.loads((V3 / "info.json").read_text(encoding="utf-8"))
    m = e22.construir(V3, False, dev)
    ab, ba = e22.puntuar(m, tok, d["a"].tolist(), d["b"].tolist(), dev, contextlib.nullcontext)
    d["P"] = e31.calibrada(e22.puntaje(inf["modo"], ab, ba), inf["temperatura"])
    d["tramo"] = d.apply(tramo, axis=1)
    d.to_csv(SAL / "43_pares.csv", index=False, encoding="utf-8")

    # --- la auditoria ciega -----------------------------------------------------------
    si = d[(d["P"] >= 0.5) & ~d["bloqueado"]]
    perd90 = si[~(si["en_vecinos"] & (si["coseno"] >= 0.90))]
    cuota = (perd90["tramo"].value_counts() / len(perd90) * N_AUD_SI).round().astype(int)
    partes = [perd90[perd90["tramo"] == t].sample(min(c, (perd90["tramo"] == t).sum()),
                                                  random_state=SEM)
              for t, c in cuota.items()]
    noes = d[(d["P"] < 0.5) & ~d["bloqueado"]].sample(N_AUD_NO, random_state=SEM)
    aud = pd.concat(partes + [noes.assign(tramo="v3 dijo no")]).sample(frac=1, random_state=SEM)
    aud = aud.reset_index(drop=True)
    aud["n_ciego"] = np.arange(1, len(aud) + 1)
    # el orden dentro del par tambien al azar, para no delatar cual es el sorteado
    gira = rng.random(len(aud)) < 0.5
    aud["A"] = np.where(gira, aud["b"], aud["a"])
    aud["B"] = np.where(gira, aud["a"], aud["b"])
    aud[["n_ciego", "A", "B"]].assign(mismo="", nota="").rename(
        columns={"A": "a", "B": "b"}).to_csv(SAL / "43_auditoria_para_juzgar.csv",
                                             index=False, encoding="utf-8-sig")
    aud[["n_ciego", "i", "j", "a", "b", "tramo", "P", "coseno", "personas"]].to_csv(
        SAL / "43_auditoria_mapa.csv", index=False, encoding="utf-8")
    informe(d, None)


def informe(d, corr):
    out = []

    def p(s=""):
        print(s, flush=True)
        out.append(s)

    p("=" * 78)
    p("43 · ¿CUANTO PIERDE VERTEX COMO BUSCADOR DE CANDIDATOS? (D-043)")
    p("=" * 78)
    p("nodos de base_v16: muestra {:,} (con peso por personas); pares TF-IDF: {:,}; bloqueados "
      "por candado: {:,}".format(N_MUESTRA, len(d), int(d["bloqueado"].sum())))
    si = d[(d["P"] >= 0.5) & ~d["bloqueado"]]
    p("pares que la v3 dice `si` (P >= 0,5, sin candado): {:,} ({:.1%})".format(
        len(si), len(si) / len(d)))
    p("\nde esos, en que tramo de Vertex caen:")
    for t in TRAMOS:
        k = si["tramo"] == t
        p("   {:<26} {:>6,} pares ({:5.1%})   personas {:5.1%}".format(
            t, int(k.sum()), k.mean(), si.loc[k, "personas"].sum() / si["personas"].sum()))
    k = si["en_vecinos"] & (si["coseno"] >= 0.90)
    p("   {:<26} {:>6,} pares ({:5.1%})".format("propuesto con piso 0,90", int(k.sum()), k.mean()))

    p("\nPERDIDA DE VERTEX (fraccion de los `si` de la v3 que no propone)")
    p("   piso    por pares   por personas{}".format("   corregida por la auditoria"
                                                    if corr is not None else ""))
    elegido = None
    for piso in PISOS:
        perd = ~(si["en_vecinos"] & (si["coseno"] >= piso))
        fila = "   {:.2f}    {:7.1%}     {:7.1%}".format(
            piso, perd.mean(), si.loc[perd, "personas"].sum() / si["personas"].sum())
        if corr is not None:
            # los perdidos por tramo, cada uno por la fraccion de `si` que dio el autor
            n_real = sum(int((perd & (si["tramo"] == t)).sum()) * corr.get(t, np.nan)
                         for t in TRAMOS if (perd & (si["tramo"] == t)).any())
            # los propuestos se toman como reales: no se auditan (afectan igual a todos)
            tasa = n_real / (n_real + int((~perd).sum()))
            fila += "        {:7.1%}".format(tasa)
            if tasa < UMBRAL_PERDIDA:
                elegido = piso
        p(fila)
    if corr is not None:
        p("\nauditoria: fraccion de `si` del autor por tramo: " + ", ".join(
            "{} {:.0%}".format(t, v) for t, v in corr.items()))
        p("\n>>> CRITERIO D-043: {} <<<".format(
            "Vertex con piso {:.2f}; el bi-encoder queda como mejora posterior".format(elegido)
            if elegido is not None else "ningun piso pierde < 5 %: EL BI-ENCODER VA ANTES"))
    p("\nejemplos de `si` de la v3 que Vertex no propone (fuera de vecinos o coseno < 0,80):")
    ej = si[si["tramo"].isin(TRAMOS[:2])].sort_values("personas", ascending=False).head(15)
    for _, r in ej.iterrows():
        p("   {:<36} / {:<36} P {:.2f}  cos {:.3f}".format(r["a"][:36], r["b"][:36], r["P"],
                                                          r["coseno"]))
    nombre = "43_perdida_vertex.txt" if corr is None else "43_perdida_vertex_corregida.txt"
    (SAL / nombre).write_text("\n".join(out) + "\n", encoding="utf-8")


def corregir():
    d = pd.read_csv(SAL / "43_pares.csv")
    j = pd.read_csv(SAL / "43_auditoria_para_juzgar.csv", encoding="utf-8-sig", dtype=str,
                    keep_default_na=False, sep=None, engine="python")
    j["mismo"] = j["mismo"].str.strip().str.lower()
    if not j["mismo"].isin(["si", "no"]).all():
        raise SystemExit("ALTO: la auditoria esta incompleta ({} sin juzgar)".format(
            int((~j["mismo"].isin(["si", "no"])).sum())))
    m = pd.read_csv(SAL / "43_auditoria_mapa.csv")
    m = m.merge(j[["n_ciego", "mismo"]].astype({"n_ciego": int}), on="n_ciego")
    corr = {t: float((g["mismo"] == "si").mean()) for t, g in m.groupby("tramo")}
    informe(d, corr)


if __name__ == "__main__":
    corregir() if sys.argv[1:] == ["corregir"] else medir()
