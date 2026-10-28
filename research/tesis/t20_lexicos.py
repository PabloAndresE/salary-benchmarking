"""T-020: baselines lexicos (TF-IDF de caracteres, BM25, coincidencia aproximada) en la recuperacion de T-001 y en el
open set de T-010b (registro, T-020).

    PYTHONPATH=.libs_tesis .venv/bin/python research/tesis/t20_lexicos.py recuperacion
    CUDA_VISIBLE_DEVICES=N PYTHONPATH=.libs_tesis .venv/bin/python research/tesis/t20_lexicos.py armar
    CUDA_VISIBLE_DEVICES=a,b /root/salary-benchmarking/.venv-llm/bin/python research/tesis/t20_lexicos.py etiquetar
    .venv/bin/python research/tesis/t20_lexicos.py medir

SALIDAS: salidas/t20_recuperacion.txt, t20_rangos.parquet, t20_elegido.json, t20_decisiones.parquet, t20_pool.parquet,
t20_qwen.parquet (fuera del repo), t20_open_set.txt
"""
import importlib.util
import json
import pathlib
import re
import shutil
import sys
import tempfile
import unicodedata

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
SAL = AQUI / "salidas"
SEM = 20261028
METODOS = ("TF-IDF caracteres", "BM25", "coincidencia aproximada")
UMBRALES_L = tuple(np.round(np.arange(0.30, 0.981, 0.02), 2))
K_TOP = 800


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def normal(t):
    t = unicodedata.normalize("NFKD", str(t).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


class Lexico:
    """Puntajes de un metodo lexico entre consultas y los titulos de la base, por bloques (filas = consultas)."""

    def __init__(self, metodo, docs):
        self.metodo, self.docs = metodo, [normal(d) for d in docs]
        if metodo == "TF-IDF caracteres":
            from sklearn.feature_extraction.text import TfidfVectorizer
            self.v = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=False, dtype=np.float32)
            self.D = self.v.fit_transform(self.docs)
        elif metodo == "BM25":
            from sklearn.feature_extraction.text import CountVectorizer
            self.v = CountVectorizer(token_pattern=r"(?u)\b\w+\b", lowercase=False, dtype=np.float32)
            tf = self.v.fit_transform(self.docs).tocsr()
            n, df = tf.shape[0], np.bincount(tf.indices, minlength=tf.shape[1])
            idf = np.log((n - df + 0.5) / (df + 0.5) + 1.0).astype(np.float32)
            dl = np.asarray(tf.sum(1)).ravel()
            k1, b = 1.2, 0.75
            norma = np.repeat(k1 * (1 - b + b * dl / dl.mean()), np.diff(tf.indptr))
            tf.data = idf[tf.indices] * tf.data * (k1 + 1) / (tf.data + norma)
            self.D = tf

    def __call__(self, consultas, bloque=512):
        qn = [normal(q) for q in consultas]
        for i in range(0, len(qn), bloque):
            q = qn[i:i + bloque]
            if self.metodo == "coincidencia aproximada":
                from rapidfuzz import fuzz, process
                yield i, process.cdist(q, self.docs, scorer=fuzz.token_set_ratio, workers=-1, dtype=np.float32) / 100.0
            else:
                Q = self.v.transform(q)
                if self.metodo == "BM25":
                    Q.data[:] = 1.0
                yield i, (Q @ self.D.T).toarray().astype(np.float32)


def recuperacion():
    t01 = cargar("t01", AQUI / "t01_recuperacion_qwen.py")
    celdas, grupo, _ = t01.cargar_base()
    grupo = grupo.astype(int)
    idx = {c: i for i, c in enumerate(celdas)}
    q = t01.oro(idx, grupo)
    q["grupo_propio"] = [int(grupo[idx[c]]) for c in q["consulta"]]
    prev = pd.read_parquet(SAL / "t01_rangos.parquet")
    assert list(prev["consulta"]) == list(q["consulta"]), "el oro no coincide con el de T-001"
    orden = np.argsort(grupo, kind="stable")
    gord = grupo[orden]
    inicio = np.flatnonzero(np.r_[True, gord[1:] != gord[:-1]])
    gids = gord[inicio]
    col = {g: k for k, g in enumerate(gids)}
    res = {"Vertex": prev["V"].to_numpy(), "Qwen titulo+desc": prev["Q-d"].to_numpy()}
    for met in METODOS:
        lx = Lexico(met, celdas)
        r = np.zeros(len(q))
        for i, S in lx(list(q["consulta"])):
            G = np.maximum.reduceat(S[:, orden], inicio, axis=1)
            for k in range(len(S)):
                fila = q.iloc[i + k]
                G[k, col[fila["grupo_propio"]]] = -np.inf
                s = G[k, col[fila["grupo_oro"]]]
                r[i + k] = 1 + (G[k] > s).sum() + ((G[k] == s).sum() - 1) / 2       # empate al rango medio
        res[met] = r
    out = ["T-020 · PARTE A · recuperacion de sinonimos con metodos lexicos (protocolo T-001)",
           "consultas {:,} ({} pares); empates al rango medio".format(len(q), q["par"].nunique())]
    for k, r in res.items():
        out.append("  {:<24} r@1 {:.1%}  r@10 {:.1%}  MRR {:.3f}".format(k, (r <= 1).mean(), (r <= 10).mean(), (1 / r).mean()))
    rng = np.random.default_rng(SEM)
    pares = q["par"].unique()
    for met in METODOS:
        for ref in ("Vertex", "Qwen titulo+desc"):
            bs = []
            for _ in range(2000):
                s = np.isin(q["par"].to_numpy(), rng.choice(pares, len(pares)))
                bs.append((res[met][s] <= 10).mean() - (res[ref][s] <= 10).mean())
            d0 = (res[met] <= 10).mean() - (res[ref] <= 10).mean()
            lo, hi = np.percentile(bs, [2.5, 97.5])
            out.append("  {} - {}: {:+.1f} pts [{:+.1f}, {:+.1f}] -> {}".format(
                met, ref, 100 * d0, 100 * lo, 100 * hi, "MEJOR" if lo > 0 else ("PEOR" if hi < 0 else "no se distingue")))
    mejor = max(METODOS, key=lambda m: (res[m] <= 10).mean())
    out.append("metodo lexico para la parte B (mejor r@10): " + mejor)
    (SAL / "t20_elegido.json").write_text(json.dumps({"metodo": mejor}), encoding="utf-8")
    pd.DataFrame({"consulta": q["consulta"], **res}).to_parquet(SAL / "t20_rangos.parquet")
    (SAL / "t20_recuperacion.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


def juicios():
    g = [pd.read_parquet(SAL / f)[["q", "e", "si"]] for f in ("t10b_qwen.parquet", "t12_etiquetas.parquet",
                                                             "t19_qwen.parquet", "t20_qwen.parquet")
         if (SAL / f).exists()]
    g = pd.concat(g)
    return {(a, b): s for a, b, s in zip(g["q"], g["e"], g["si"])}


def armar():
    t10 = cargar("t10", AQUI / "t10_open_set.py")
    sys.path.insert(0, str(RAIZ / "src"))
    from benchmarking.producto.juez import cargar as cargar_juez
    e43 = cargar("e43", E2 / "43_perdida_vertex.py")
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    tit = np.array([str(c) for c in b["celdas"]], dtype=object)
    idx = {t: i for i, t in enumerate(tit)}
    grupo = np.asarray(b["grupo"]).astype(int)
    met = json.loads((SAL / "t20_elegido.json").read_text(encoding="utf-8"))["metodo"]
    t = pd.read_parquet(SAL / "t10b_decisiones.parquet")[["q", "parte", "e_A", "s_A"]]
    lx = Lexico(met, list(tit))
    cands = []
    for i, S in lx(list(t["q"])):
        top = np.argpartition(-S, K_TOP, axis=1)[:, :K_TOP]
        for k in range(len(S)):
            q = t["q"].iloc[i + k]
            o = top[k][np.argsort(-S[k, top[k]], kind="stable")]
            cands.append(t10.candidatos(o, S[k, o], {int(grupo[idx[q]])}, q, tit, grupo, e43.bloqueado))
    j = cargar_juez(t10.JUECES["reentrenado"])
    pares = sorted({(q, str(tit[c[0]])) for q, cs in zip(t["q"], cands) for c in cs})
    P = dict(zip(pares, j.P(pares)))
    out, pool = [], set()
    for q, parte, cs in zip(t["q"], t["parte"], cands):
        f = {"q": q, "parte": parte}
        for sis, punt in (("L", [c[2] for c in cs]), ("LCE", [P[(q, str(tit[c[0]]))] for c in cs])):
            if cs:
                m = int(np.argmax(punt))
                f["e_" + sis], f["s_" + sis] = str(tit[cs[m][0]]), float(punt[m])
                pool.add((q, f["e_" + sis]))
            else:
                f["e_" + sis], f["s_" + sis] = "", -np.inf
        out.append(f)
    d = pd.DataFrame(out).merge(pd.read_parquet(SAL / "t10b_decisiones.parquet")[["q", "e_A", "s_A"]], on="q")
    d.to_parquet(SAL / "t20_decisiones.parquet", index=False)
    ya = set(juicios())
    nuevos = sorted(p for p in pool if p not in ya)
    pd.DataFrame(nuevos, columns=["q", "e"]).to_parquet(SAL / "t20_pool.parquet", index=False)
    print("metodo {}; consultas {:,}; sin candidatos {:,}; pares elegidos {:,} (sin juicio {:,})".format(
        met, len(d), sum(not c for c in cands), len(pool), len(nuevos)))


def etiquetar():
    """Qwen3.5-122B sobre los pares elegidos sin juicio, como `t10b etiquetar_qwen`."""
    t10b = cargar("t10b", AQUI / "t10b_open_set.py")
    tmp = pathlib.Path(tempfile.mkdtemp(dir=SAL))
    shutil.copy(SAL / "t20_pool.parquet", tmp / "t10b_pool.parquet")
    t10b.SAL = tmp
    t10b.etiquetar_qwen()
    shutil.move(str(tmp / "t10b_qwen.parquet"), str(SAL / "t20_qwen.parquet"))
    shutil.rmtree(tmp, ignore_errors=True)


def medir():
    t10b = cargar("t10b", AQUI / "t10b_open_set.py")
    J = juicios()
    met = json.loads((SAL / "t20_elegido.json").read_text(encoding="utf-8"))["metodo"]
    t = pd.read_parquet(SAL / "t20_decisiones.parquet")
    g = pd.read_parquet(SAL / "t10b_qwen.parquet")
    pool = g.groupby("q").agg(alguno=("si", lambda s: bool((s == 1).any())),
                              todos_no=("si", lambda s: bool((s == 0).all())))
    t["clase"] = t["q"].map(lambda q: "con equivalente" if pool.loc[q, "alguno"] else
                            ("nueva" if pool.loc[q, "todos_no"] else "fuera"))
    t = t[t["clase"] != "fuera"].reset_index(drop=True)
    for s in ("A", "L", "LCE"):
        t["j_" + s] = [J.get((q, e), np.nan) if e else np.nan for q, e in zip(t["q"], t["e_" + s])]

    def aciertos(d, s, u):
        rec = d["s_" + s].to_numpy() >= u
        con = (d["clase"] == "con equivalente").to_numpy()
        j = d["j_" + s].to_numpy()
        ok = np.where(con, rec & (j == 1), ~rec).astype(float)
        ok[con & rec & np.isnan(j)] = np.nan
        return ok

    def bal(d, ok):
        con = (d["clase"] == "con equivalente").to_numpy()
        return 0.5 * (np.nanmean(ok[con]) + np.nanmean(ok[~con]))

    tc, tp = t[t["parte"] == "calibra"].reset_index(drop=True), t[t["parte"] == "prueba"].reset_index(drop=True)
    umb = {"A": 0.90}                                   # el de T-010b
    umb["L"] = max(UMBRALES_L, key=lambda u: bal(tc, aciertos(tc, "L", u)))
    umb["LCE"] = max(t10b.UMBRALES_P, key=lambda u: bal(tc, aciertos(tc, "LCE", u)))
    nombre = {"A": "Qwen + cross-encoder reentrenado (propuesto)", "L": "piso lexico: " + met,
              "LCE": met + " + cross-encoder reentrenado"}
    con = (tp["clase"] == "con equivalente").to_numpy()
    out = ["T-020 · PARTE B · open set con el buscador lexico ({}), protocolo T-010b".format(met),
           "umbrales (calibra): " + "; ".join("{} {}".format(k, v) for k, v in umb.items()),
           "nuevas de T-010b en las que el lexico encontro un par juzgado si: {}".format(
               int(((t["clase"] == "nueva") & ((t["j_L"] == 1) | (t["j_LCE"] == 1))).sum())),
           "", "PRUEBA ({} con equivalente, {} nuevas)".format(int(con.sum()), int((~con).sum()))]
    oks = {s: aciertos(tp, s, umb[s]) for s in umb}
    for s, ok in oks.items():
        out.append("  {:<4} {:<46} exactitud balanceada {:.4f}  con equivalente: reconoce bien {:.1%}  nuevas: "
                   "desconocido {:.1%}  (sin verdad {})".format(s, nombre[s], bal(tp, ok), np.nanmean(ok[con]),
                                                               np.nanmean(ok[~con]), int(np.isnan(ok).sum())))
    rng = np.random.default_rng(SEM + 1)
    for y in ("L", "LCE"):
        bs = []
        for _ in range(2000):
            ii = rng.integers(0, len(tp), len(tp))
            s_ = tp.iloc[ii].reset_index(drop=True)
            bs.append(bal(s_, oks["A"][ii]) - bal(s_, oks[y][ii]))
        d0 = bal(tp, oks["A"]) - bal(tp, oks[y])
        lo, hi = np.nanpercentile(bs, [2.5, 97.5])
        out.append("A - {}: {:+.4f} [{:+.4f}, {:+.4f}] -> {}".format(
            y, d0, lo, hi, "A MEJOR" if lo > 0 else ("A PEOR" if hi < 0 else "no se distingue")))
    (SAL / "t20_open_set.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    {"recuperacion": recuperacion, "armar": armar, "etiquetar": etiquetar, "medir": medir}[sys.argv[1]]()
