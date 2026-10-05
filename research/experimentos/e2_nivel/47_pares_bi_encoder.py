"""D-045 §3-§4: los pares para entrenar y evaluar el bi-encoder, y la separacion por componentes.

Tres etapas, con todo en disco (salidas/47_*, fuera del repo: llevan titulos de clientes):

    candidatos   anclas y pares de las cinco fuentes; no usa la v3
    puntuar --parte K --de N   la v3 (fp32, la de su calibracion) sobre una parte de los pares;
                 se lanzan N partes en paralelo, una por GPU
    separar      junta las partes, aplica candados, arma las componentes conectadas y reparte
                 entrenamiento / validacion / evaluacion

ANCLAS: 20.000 nodos de base_v16 sorteados sin reposicion con peso por personas, mas los 5.000 de
las propuestas de Gemini (detalle de implementacion registrado en D-045).
FUENTES (D-045 §3): a) 100 vecinos por titulo con e5-base, Vertex y TF-IDF; b) propuestas de Gemini
que existen en la base (por la capa 0); c) 50 vecinos por descripcion (e5-base); d) 20 lejanos por
ancla, rango 100-1.000 de e5 y de Vertex (10 y 10, al azar).
SEPARACION (D-045 §4 y su enmienda): comunidades de Louvain sobre aristas P >= 0,9 sin candado
(las componentes conectadas daban una gigante); 80 / 20 por comunidad, semilla fija; los cinco casos conocidos, forzados a
evaluacion; validacion = 10 % de las componentes de entrenamiento.
"""
import argparse
import contextlib
import importlib.util
import json
import os
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto import capa0 as c0mod  # noqa: E402

V3 = SAL / "22_modelos_v3" / "elegido"
E5 = RAIZ / "modelos" / "e5-base"
SEM = 20261005
N_ANCLAS, K_CERCA, K_DESC, N_LEJOS = 20_000, 100, 50, 10
CASOS = [("CHOFER", "CONDUCTOR"), ("VENDEDOR", "ASESOR COMERCIAL"), ("MENSAJERO", "MOTORIZADO"),
         ("GUARDIA", "AGENTE DE SEGURIDAD"),
         ("JEFE DE TALENTO HUMANO", "JEFE DE RECURSOS HUMANOS")]
CAND = SAL / "47_candidatos.parquet"


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def nodos_y_capa0():
    e43 = cargar("e43", "43_perdida_vertex.py")
    tit, Zv, per = e43.nodos()
    b = np.load(RAIZ / "demo" / "base_v16.npz", allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    c0 = c0mod.Capa0.de_json(str(b["capa0_json"]), celdas)
    # atomo -> nodo: el grupo de base_v16 al que pertenece cualquier celda con ese atomo
    grupo = dict(zip(celdas, b["grupo"].astype(int)))
    nodo_de_grupo = {grupo[str(t)]: k for k, t in enumerate(tit)}
    atomo_a_nodo = {}
    for c in celdas:
        atomo_a_nodo.setdefault(c0.atomo(c), nodo_de_grupo[grupo[c]])
    return e43, tit, Zv, per, c0, atomo_a_nodo


def topk(Z, filas, k, desde=0):
    import torch
    T = torch.from_numpy(Z).cuda()
    out = np.empty((len(filas), k - desde), dtype=np.int64)
    for a in range(0, len(filas), 2048):
        ix = torch.from_numpy(np.asarray(filas[a:a + 2048])).cuda()
        s = T[ix] @ T.T
        s[torch.arange(len(ix)), ix] = -2
        out[a:a + 2048] = s.topk(k, dim=1).indices[:, desde:].cpu().numpy()
    return out


def candidatos():
    from sklearn.feature_extraction.text import TfidfVectorizer
    e44 = cargar("e44", "44_bi_encoder_base.py")
    e43, tit, Zv, per, c0, atomo_a_nodo = nodos_y_capa0()
    n = len(tit)
    rng = np.random.default_rng(SEM)
    prop = pd.read_csv(SAL / "46_propuestas.csv", keep_default_na=False)
    desc = pd.read_csv(SAL / "46_descripciones.csv", keep_default_na=False)
    anclas = set(rng.choice(n, N_ANCLAS, replace=False, p=per / per.sum()).tolist())
    anclas |= set(prop["nodo"].astype(int))
    anclas = np.array(sorted(anclas))
    print("anclas: {:,}".format(len(anclas)), flush=True)

    Ze = e44.embeber(str(E5), list(tit), "media", "query: ", "cuda")
    np.save(SAL / "47_e5_titulos.npy", Ze)
    dtxt = {int(k): json.loads(r)["descripcion"].strip() for k, r in zip(desc["nodo"], desc["respuesta"])}
    con_desc = np.array([k for k in range(n) if dtxt.get(k)])
    Zd_parcial = e44.embeber(str(E5), [dtxt[k] for k in con_desc], "media", "query: ", "cuda")
    Zd = np.zeros_like(Ze)
    Zd[con_desc] = Zd_parcial

    filas = []

    def agrega(i, js, fuente):
        for j in js:
            j = int(j)
            if j != i:
                filas.append((min(i, j), max(i, j), fuente))

    for nombre, Z in (("e5", Ze), ("vertex", Zv)):
        cerca = topk(Z, anclas, K_CERCA)
        lejos = topk(Z, anclas, 1000, desde=K_CERCA)
        for f, i in enumerate(anclas):
            agrega(int(i), cerca[f], "cerca_" + nombre)
            agrega(int(i), rng.choice(lejos[f], N_LEJOS, replace=False), "lejos_" + nombre)
        print("   {} listo".format(nombre), flush=True)
    X = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 3)).fit_transform(tit)
    for a in range(0, len(anclas), 2000):
        bloque = anclas[a:a + 2000]
        S = (X[bloque] @ X.T).toarray()
        S[np.arange(len(bloque)), bloque] = -1
        for f, i in enumerate(bloque):
            agrega(int(i), np.argsort(-S[f])[:K_CERCA], "cerca_tfidf")
    print("   tfidf listo", flush=True)
    anc_desc = np.array([i for i in anclas if dtxt.get(int(i))])
    vd = topk(Zd, anc_desc, K_DESC + 1)
    for f, i in enumerate(anc_desc):
        agrega(int(i), [j for j in vd[f] if dtxt.get(int(j))][:K_DESC], "descripcion")
    print("   descripciones listo", flush=True)
    n_prop = 0
    for i, r in zip(prop["nodo"].astype(int), prop["respuesta"]):
        js = {atomo_a_nodo[a] for a in (c0.atomo(t) for t in json.loads(r)["titulos"])
              if a in atomo_a_nodo}
        agrega(int(i), js, "gemini")
        n_prop += len(js)
    print("   propuestas de Gemini en la base: {:,}".format(n_prop), flush=True)

    d = pd.DataFrame(filas, columns=["i", "j", "fuente"])
    d = d.groupby(["i", "j"])["fuente"].agg(lambda s: "|".join(sorted(set(s)))).reset_index()
    d["a"], d["b"] = tit[d["i"]], tit[d["j"]]
    d["cos_vertex"] = np.einsum("ij,ij->i", Zv[d["i"]], Zv[d["j"]])
    d["cos_e5"] = np.einsum("ij,ij->i", Ze[d["i"]], Ze[d["j"]])
    d["bloqueado"] = [e43.bloqueado(a, b) for a, b in zip(d["a"], d["b"])]
    d.to_parquet(CAND, index=False)
    print("pares unicos: {:,}  (bloqueados por candado {:,})".format(len(d), int(d["bloqueado"].sum())))
    print(d["fuente"].str.split("|").explode().value_counts().to_string())


def puntuar(parte, de):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoTokenizer
    e22 = cargar("e22", "22_entrenar_cross.py")
    e31 = cargar("e31", "31_h4_prueba2.py")
    d = pd.read_parquet(CAND, columns=["i", "j", "a", "b"])
    d = d.iloc[parte::de]
    tok = AutoTokenizer.from_pretrained(RAIZ / "modelos" / "mdeberta-xnli")
    inf = json.loads((V3 / "info.json").read_text(encoding="utf-8"))
    m = e22.construir(V3, False, "cuda")
    t0 = time.time()
    ab, ba = e22.puntuar(m, tok, d["a"].tolist(), d["b"].tolist(), "cuda",
                         contextlib.nullcontext, lote=512)
    P = e31.calibrada(e22.puntaje(inf["modo"], ab, ba), inf["temperatura"])
    pd.DataFrame({"i": d["i"].to_numpy(), "j": d["j"].to_numpy(), "P": P}).to_parquet(
        SAL / "47_puntajes_{}de{}.parquet".format(parte, de), index=False)
    print("parte {}/{}: {:,} pares en {:.0f} s".format(parte, de, len(d), time.time() - t0))


def separar(de):
    _, tit, _, _, c0, atomo_a_nodo = nodos_y_capa0()
    n = len(tit)
    d = pd.read_parquet(CAND)
    p = pd.concat([pd.read_parquet(SAL / "47_puntajes_{}de{}.parquet".format(k, de))
                   for k in range(de)])
    d = d.merge(p, on=["i", "j"], validate="one_to_one")

    def componentes(umbral):
        padre = np.arange(n)

        def raiz(x):
            while padre[x] != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x
        e = d[(d["P"] >= umbral) & ~d["bloqueado"]]
        for i, j in zip(e["i"], e["j"]):
            ri, rj = raiz(i), raiz(j)
            if ri != rj:
                padre[ri] = rj
        return np.array([raiz(x) for x in range(n)])

    out = []

    def p_(s=""):
        print(s, flush=True)
        out.append(s)

    p_("47 · PARES DEL BI-ENCODER Y SEPARACION POR COMUNIDADES (D-045, enmienda §4)")
    p_("pares puntuados: {:,}; bloqueados {:,}".format(len(d), int(d["bloqueado"].sum())))
    for umbral in (0.5, 0.8, 0.9):                      # lo registrado primero: el diagnostico
        tam = pd.Series(componentes(umbral)).value_counts()
        p_("   componentes conectadas, P >= {}: la mayor {:,} nodos ({:.1%})".format(
            umbral, int(tam.iloc[0]), tam.iloc[0] / n))
    import networkx as nx
    e = d[(d["P"] >= 0.9) & ~d["bloqueado"]]
    G = nx.Graph()
    G.add_nodes_from(range(n))
    G.add_weighted_edges_from(zip(e["i"], e["j"], e["P"]))
    com = nx.community.louvain_communities(G, weight="weight", resolution=1.0, seed=SEM)
    comp = np.empty(n, dtype=np.int64)
    for k, c in enumerate(com):
        comp[list(c)] = k
    tam = pd.Series(comp).value_counts()
    p_("   Louvain sobre aristas P >= 0,9: {:,} comunidades; la mayor {:,} nodos ({:.1%})".format(
        len(tam), int(tam.iloc[0]), tam.iloc[0] / n))

    casos = {}
    for a, b in CASOS:
        for t in (a, b):
            k = atomo_a_nodo.get(c0.atomo(t))
            casos[t] = k
            if k is None:
                p_("   AVISO: el caso conocido {} no esta en la base".format(t))
    forzadas = {comp[k] for k in casos.values() if k is not None}
    rng = np.random.default_rng(SEM)
    unicas = np.unique(comp)
    lado_c = dict(zip(unicas, np.where(rng.random(len(unicas)) < 0.8, "entrena", "evalua")))
    for c in forzadas:
        lado_c[c] = "evalua"
    ent = [c for c in unicas if lado_c[c] == "entrena"]
    for c in rng.choice(ent, int(0.1 * len(ent)), replace=False):
        lado_c[c] = "valida"
    lado = np.array([lado_c[c] for c in comp])
    d["comp_i"], d["comp_j"] = comp[d["i"]], comp[d["j"]]
    li, lj = lado[d["i"]], lado[d["j"]]
    d["lado"] = np.where(li == lj, li, "cruza")
    d.to_parquet(SAL / "47_pares.parquet", index=False)
    pd.DataFrame({"nodo": np.arange(n), "titulo": tit, "comp": comp, "lado": lado}).to_parquet(
        SAL / "47_nodos.parquet", index=False)

    p_("\nnodos por lado: " + json.dumps(pd.Series(lado).value_counts().to_dict()))
    p_("comunidades forzadas a evaluacion (casos conocidos): {}; nodos en ellas: {:,}".format(
        len(forzadas), int(np.isin(comp, list(forzadas)).sum())))
    ln = lado == "evalua"
    fuerte = e[["i", "j"]].to_numpy()
    con_vecino_ent = np.zeros(n, bool)
    np.logical_or.at(con_vecino_ent, fuerte[:, 0], np.isin(lado[fuerte[:, 1]], ["entrena", "valida"]))
    np.logical_or.at(con_vecino_ent, fuerte[:, 1], np.isin(lado[fuerte[:, 0]], ["entrena", "valida"]))
    p_("aristas P >= 0,9 cortadas: {:.1%}; nodos de evaluacion con vecino P >= 0,9 en entrenamiento:"
       " {:.1%}".format((lado[fuerte[:, 0]] != lado[fuerte[:, 1]]).mean(),
                        (con_vecino_ent & ln).sum() / ln.sum()))
    pd.DataFrame({"nodo": np.arange(n), "sin_fuga": ~con_vecino_ent}).to_parquet(
        SAL / "47_sin_fuga.parquet", index=False)
    p_("\npares por lado (P >= 0,5 sin candado = `si` de la v3):")
    si = (d["P"] >= 0.5) & ~d["bloqueado"]
    for l, g in d.groupby("lado"):
        p_("   {:<8} {:>9,} pares   si {:>8,}".format(l, len(g), int(si[g.index].sum())))
    p_("\n`si` de la v3 por fuente (P >= 0,5, sin candado):")
    f = d.assign(fuente=d["fuente"].str.split("|")).explode("fuente")
    for fu, g in f.groupby("fuente"):
        s = (g["P"] >= 0.5) & ~g["bloqueado"]
        p_("   {:<14} {:>9,} pares   si {:>8,} ({:.0%})   con P >= 0,9 y cos_vertex < 0,85: {:,}".format(
            fu, len(g), int(s.sum()), s.mean(),
            int(((g["P"] >= 0.9) & ~g["bloqueado"] & (g["cos_vertex"] < 0.85)).sum())))
    p_("\nlos casos conocidos (P de la v3 del par):")
    for a, b in CASOS:
        i, j = casos.get(a), casos.get(b)
        fila = d[(d["i"] == min(i, j)) & (d["j"] == max(i, j))] if None not in (i, j) else []
        p_("   {:<24} / {:<26} {}".format(a, b, "P {:.2f} ({})".format(
            fila["P"].iloc[0], fila["fuente"].iloc[0]) if len(fila) else "no es candidato"))
    (SAL / "47_pares_bi_encoder.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("etapa", choices=["candidatos", "puntuar", "separar"])
    ap.add_argument("--parte", type=int, default=0)
    ap.add_argument("--de", type=int, default=3)
    a = ap.parse_args()
    if a.etapa == "candidatos":
        candidatos()
    elif a.etapa == "puntuar":
        puntuar(a.parte, a.de)
    else:
        separar(a.de)
