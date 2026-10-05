"""D-046: correlation clustering con la v3 sobre los grupos de la capa 0 de base_v16.

    candidatos                  la union de los 100 vecinos de B, 50 por descripcion y Gemini;
                                reutiliza los P ya puntuados en 47
    puntuar --parte K --de N    la v3 sobre los pares nuevos (una parte por GPU)
    agrupar                     union voraz con candados; la v3 puntua al vuelo los pares que falten

REGLA (D-046 §5): de la arista mas segura a la menos, dos clusters se juntan si la suma de log-odds
entre todos sus miembros es positiva, ningun par entre ellos tiene P < 0,1, ningun candado lo impide
(nivel de la rubrica, seniority, numero de grado: por cluster) y el cluster no pasa de 60 grupos.

SALIDAS (fuera del repo salvo el informe): salidas/50_candidatos.parquet, 50_puntajes_*.parquet,
50_clusters.parquet, 50_clustering.txt
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
from benchmarking.producto.nivel import nivel_rubrica, seniority_lexica  # noqa: E402

B = SAL / "48_bi_encoder_B3" / "semilla_1"
V3 = SAL / "22_modelos_v3" / "elegido"
K_B, K_DESC, TOPE = 100, 50, 60
# P minimo de TODOS los pares entre dos clusters: 0,1 en la primera corrida (regla de D-046 §5, con
# la suma de log-odds); 0,5 = enlace completo (enmienda a D-046), sin la suma (queda implicita)
P_MIN = {"suma": 0.1, "completo": 0.5, "confiable": 0.5}
# "confiable" (enmienda a D-046 tras D-047): ademas, TODOS los pares entre los dos clusters con coseno
# de Vertex >= 0,90, la poblacion en que la v3 se entreno y se evaluo
COS_CONFIABLE = 0.90
CAND = SAL / "50_candidatos.parquet"


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def candidatos():
    import torch
    from transformers import AutoTokenizer
    e43, e44, e47, e48 = (cargar("e43", "43_perdida_vertex.py"), cargar("e44", "44_bi_encoder_base.py"),
                          cargar("e47", "47_pares_bi_encoder.py"), cargar("e48", "48_entrenar_bi_encoder.py"))
    _, tit, _, _, c0, atomo_a_nodo = e47.nodos_y_capa0()
    n = len(tit)
    tok = AutoTokenizer.from_pretrained(B)
    m = e48.Codificador(B).cuda()
    Zb = e48.codificar(m, tok, list(tit)).cpu().numpy()
    del m
    torch.cuda.empty_cache()
    np.save(SAL / "50_B_titulos.npy", Zb)
    desc = pd.read_csv(SAL / "46_descripciones.csv", keep_default_na=False)
    dtxt = {int(k): json.loads(r)["descripcion"].strip() for k, r in zip(desc["nodo"], desc["respuesta"])}
    con = np.array([k for k in range(n) if dtxt.get(k)])
    Zd = np.zeros((n, Zb.shape[1]), dtype=np.float32)
    Zd[con] = e44.embeber(str(e47.E5), [dtxt[k] for k in con], "media", "query: ", "cuda")
    filas = []
    for i, r in zip(range(n), e47.topk(Zb, np.arange(n), K_B)):
        filas += [(min(i, int(j)), max(i, int(j)), "B") for j in r]
    for i, r in zip(con, e47.topk(Zd, con, K_DESC + 1)):
        filas += [(min(int(i), int(j)), max(int(i), int(j)), "descripcion") for j in r
                  if int(j) != int(i) and dtxt.get(int(j))][:K_DESC]
    prop = pd.read_csv(SAL / "46_propuestas.csv", keep_default_na=False)
    for i, r in zip(prop["nodo"].astype(int), prop["respuesta"]):
        for a in {c0.atomo(t) for t in json.loads(r)["titulos"]}:
            j = atomo_a_nodo.get(a)
            if j is not None and j != i:
                filas.append((min(i, j), max(i, j), "gemini"))
    d = pd.DataFrame(filas, columns=["i", "j", "fuente"])
    d = d.groupby(["i", "j"])["fuente"].agg(lambda s: "|".join(sorted(set(s)))).reset_index()
    viejos = pd.read_parquet(SAL / "47_pares.parquet", columns=["i", "j", "P", "bloqueado"])
    d = d.merge(viejos, on=["i", "j"], how="left")
    falta = d["bloqueado"].isna()
    d.loc[falta, "bloqueado"] = [e43.bloqueado(tit[i], tit[j]) for i, j in zip(d.loc[falta, "i"], d.loc[falta, "j"])]
    d["bloqueado"] = d["bloqueado"].astype(bool)
    d["a"], d["b"] = tit[d["i"]], tit[d["j"]]
    d.to_parquet(CAND, index=False)
    print("candidatos: {:,} pares ({:,} ya puntuados en 47; faltan {:,}, de ellos bloqueados {:,})".format(
        len(d), int(d["P"].notna().sum()), int(d["P"].isna().sum()),
        int((d["P"].isna() & d["bloqueado"]).sum())))
    print(d["fuente"].str.split("|").explode().value_counts().to_string())


def puntuar(parte, de):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoTokenizer
    e22, e31 = cargar("e22", "22_entrenar_cross.py"), cargar("e31", "31_h4_prueba2.py")
    d = pd.read_parquet(CAND)
    d = d[d["P"].isna() & ~d["bloqueado"]].iloc[parte::de]
    tok = AutoTokenizer.from_pretrained(RAIZ / "modelos" / "mdeberta-xnli")
    inf = json.loads((V3 / "info.json").read_text(encoding="utf-8"))
    m = e22.construir(V3, False, "cuda")
    t0 = time.time()
    ab, ba = e22.puntuar(m, tok, d["a"].tolist(), d["b"].tolist(), "cuda", contextlib.nullcontext, lote=512)
    P = e31.calibrada(e22.puntaje(inf["modo"], ab, ba), inf["temperatura"])
    pd.DataFrame({"i": d["i"].to_numpy(), "j": d["j"].to_numpy(), "P": P}).to_parquet(
        SAL / "50_puntajes_{}de{}.parquet".format(parte, de), index=False)
    print("parte {}/{}: {:,} pares en {:.0f} s".format(parte, de, len(d), time.time() - t0))


class Juez:
    """El juez al vuelo, con cache: los pares entre clusters que ninguna fuente propuso."""

    def __init__(self, tit, cache, ruta=V3):
        from transformers import AutoTokenizer
        self.e22, self.e31 = cargar("e22", "22_entrenar_cross.py"), cargar("e31", "31_h4_prueba2.py")
        self.tok = AutoTokenizer.from_pretrained(RAIZ / "modelos" / "mdeberta-xnli")
        self.inf = json.loads((ruta / "info.json").read_text(encoding="utf-8"))
        self.m = self.e22.construir(ruta, False, "cuda")
        self.tit, self.cache, self.nuevos = tit, cache, 0

    def P(self, pares):
        falta = [p for p in pares if p not in self.cache]
        if falta:
            ab, ba = self.e22.puntuar(self.m, self.tok, [self.tit[i] for i, _ in falta],
                                      [self.tit[j] for _, j in falta], "cuda", contextlib.nullcontext,
                                      lote=512)
            for p, v in zip(falta, self.e31.calibrada(self.e22.puntaje(self.inf["modo"], ab, ba),
                                                      self.inf["temperatura"])):
                self.cache[p] = float(v)
            self.nuevos += len(falta)
        return np.array([self.cache[p] for p in pares])


def es_cargo(n):
    """D-047: los nodos que Gemini no pudo describir (basura de planilla, areas, productos) no son
    cargos y quedan solos en el clustering."""
    desc = pd.read_csv(SAL / "46_descripciones.csv", keep_default_na=False)
    m = np.zeros(n, bool)
    for k, r in zip(desc["nodo"], desc["respuesta"]):
        m[int(k)] = bool(json.loads(r)["descripcion"].strip())
    return m


def agrupar(de, regla="completo", solo_cargos=False):
    p_min = P_MIN[regla]
    sufijo = "" if regla == "suma" else "_" + regla
    _, tit, Zv, _, _, _ = cargar("e47", "47_pares_bi_encoder.py").nodos_y_capa0()
    n = len(tit)
    d = pd.read_parquet(CAND)
    p = pd.concat([pd.read_parquet(SAL / "50_puntajes_{}de{}.parquet".format(k, de)) for k in range(de)])
    d = d.merge(p.rename(columns={"P": "P2"}), on=["i", "j"], how="left")
    d["P"] = d["P"].fillna(d["P2"])
    cache = {(int(i), int(j)): float(v) for i, j, v in zip(d["i"], d["j"], d["P"]) if v == v}
    vuelo = SAL / "50_cache_vuelo.parquet"            # lo que la v3 puntuo al vuelo en corridas previas
    if vuelo.exists():
        c = pd.read_parquet(vuelo)
        cache.update({(int(i), int(j)): float(v) for i, j, v in zip(c["i"], c["j"], c["P"])})
    n_previo = len(cache)
    juez = Juez(tit, cache)
    niv = [nivel_rubrica(t) for t in tit]
    sen = [seniority_lexica(t) for t in tit]
    gra = [c0mod.grado_numerico(t) for t in tit]
    miembros = {k: [k] for k in range(n)}
    de_ = np.arange(n)
    c_niv = {k: ({niv[k]} if niv[k] else set()) for k in range(n)}
    c_sen = {k: {sen[k]} for k in range(n)}
    c_gra = {k: gra[k] for k in range(n)}
    aristas = d[(d["P"] >= 0.5) & ~d["bloqueado"]].sort_values("P", ascending=False)
    if regla == "confiable":
        cv = np.einsum("ij,ij->i", Zv[aristas["i"].to_numpy()], Zv[aristas["j"].to_numpy()])
        aristas = aristas[cv >= COS_CONFIABLE]
    if solo_cargos:
        ok = es_cargo(n)
        aristas = aristas[ok[aristas["i"].to_numpy()] & ok[aristas["j"].to_numpy()]]
        sufijo += "_cargos"
    motivo = {"unidos": 0, "mismo cluster": 0, "candado": 0, "tope": 0, "par con P < minimo": 0,
              "suma de log-odds <= 0": 0}
    t0 = time.time()
    for k, (i, j) in enumerate(zip(aristas["i"].to_numpy(), aristas["j"].to_numpy())):
        if k % 100_000 == 0:
            print("   {:,} de {:,} aristas; {:,} uniones; {:,} pares nuevos de la v3 ({:.0f} s)".format(
                k, len(aristas), motivo["unidos"], juez.nuevos, time.time() - t0), flush=True)
        A, Bc = int(de_[i]), int(de_[j])
        if A == Bc:
            motivo["mismo cluster"] += 1
            continue
        if len(c_niv[A] | c_niv[Bc]) > 1 or c_sen[A] != c_sen[Bc] or (
                c_gra[A] and c_gra[Bc] and c_gra[A] != c_gra[Bc]):
            motivo["candado"] += 1
            continue
        mA, mB = miembros[A], miembros[Bc]
        if len(mA) + len(mB) > TOPE:
            motivo["tope"] += 1
            continue
        if regla == "confiable" and float((Zv[mA] @ Zv[mB].T).min()) < COS_CONFIABLE:
            motivo["par con coseno < 0,90"] = motivo.get("par con coseno < 0,90", 0) + 1
            continue
        pares = [(min(x, y), max(x, y)) for x in mA for y in mB]
        # atajo sin cambiar la regla: si un par YA puntuado tiene P < 0,1, la union esta rechazada
        # y no hace falta pedirle a la v3 los que faltan
        conocidos = [cache[q] for q in pares if q in cache]
        if conocidos and min(conocidos) < p_min:
            motivo["par con P < minimo"] += 1
            continue
        P = np.clip(juez.P(pares), 1e-4, 1 - 1e-4)
        if P.min() < p_min:
            motivo["par con P < minimo"] += 1
            continue
        if regla == "suma" and np.log(P / (1 - P)).sum() <= 0:
            motivo["suma de log-odds <= 0"] += 1
            continue
        # se une B en A
        miembros[A] = mA + mB
        del miembros[Bc]
        de_[mB] = A
        c_niv[A] |= c_niv.pop(Bc)
        c_sen.pop(Bc)
        c_gra[A] = c_gra[A] | c_gra.pop(Bc)
        motivo["unidos"] += 1
    pd.DataFrame({"nodo": np.arange(n), "titulo": tit, "cluster": de_}).to_parquet(
        SAL / "50_clusters{}.parquet".format(sufijo), index=False)
    if len(cache) > n_previo:
        claves = list(cache)[n_previo:]
        nuevo = pd.DataFrame({"i": [a for a, _ in claves], "j": [b for _, b in claves],
                              "P": [cache[q] for q in claves]})
        if vuelo.exists():
            nuevo = pd.concat([pd.read_parquet(vuelo), nuevo])
        nuevo.to_parquet(vuelo, index=False)
    tam = pd.Series(de_).value_counts()
    out = ["50 · CORRELATION CLUSTERING CON LA v3 (D-046), regla {} (P minimo {})".format(regla, p_min),
           "candidatos {:,}; aristas P >= 0,5 sin candado recorridas {:,}".format(len(d), len(aristas)),
           "resultado de cada arista: " + json.dumps(motivo, ensure_ascii=False),
           "pares nuevos que la v3 puntuo al vuelo: {:,}".format(juez.nuevos),
           "clusters: {:,} (de {:,} grupos de la capa 0); grupos en clusters de 2+: {:,}; el mayor {} grupos".format(
               len(tam), n, int(tam[tam > 1].sum()), int(tam.iloc[0])),
           "tamanos: " + json.dumps(tam.value_counts().sort_index().head(12).to_dict())]
    grandes = tam.index[:8]
    for c in grandes:
        out.append("   {:>3} | {}".format(int(tam[c]), " ; ".join(sorted(str(tit[x]) for x in miembros[int(c)])[:12])))
    (SAL / "50_clustering{}.txt".format(sufijo)).write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("etapa", choices=["candidatos", "puntuar", "agrupar"])
    ap.add_argument("--parte", type=int, default=0)
    ap.add_argument("--de", type=int, default=3)
    ap.add_argument("--regla", default="completo", choices=list(P_MIN))
    ap.add_argument("--solo-cargos", action="store_true", help="D-047: los no-cargos quedan solos")
    a = ap.parse_args()
    {"candidatos": candidatos, "puntuar": lambda: puntuar(a.parte, a.de),
     "agrupar": lambda: agrupar(a.de, a.regla, a.solo_cargos)}[a.etapa]()
