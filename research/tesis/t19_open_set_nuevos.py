"""T-019: open set con muchos mas cargos nuevos, quitando de la base la familia entera de equivalentes (registro, T-019).

    CUDA_VISIBLE_DEVICES=N .venv/bin/python research/tesis/t19_open_set_nuevos.py armar
    CUDA_VISIBLE_DEVICES=a,b /root/salary-benchmarking/.venv-llm/bin/python research/tesis/t19_open_set_nuevos.py etiquetar
    .venv/bin/python research/tesis/t19_open_set_nuevos.py medir

SALIDAS: salidas/t19_decisiones.parquet, t19_pool.parquet, t19_qwen.parquet (fuera del repo), t19_open_set.txt
"""
import importlib.util
import pathlib
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
SAL = AQUI / "salidas"
SEM = 20261023
UMBRAL = {"A": 0.90, "B": 0.93, "C": 0.96, "Cfijo": 0.5, "D": 0.70}      # los elegidos en calibra en T-010b
SISTEMAS = ("A", "B", "C", "Cfijo", "D")
NOMBRE = {"A": "Qwen + cross-encoder reentrenado", "B": "Qwen + cross-encoder del producto",
          "C": "Vertex + cross-encoder del producto", "Cfijo": "producto hoy (Vertex >= 0,90, P >= 0,5)",
          "D": "solo coseno de Qwen"}


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def juicios():
    g = [pd.read_parquet(SAL / "t10b_qwen.parquet")]
    if (SAL / "t19_qwen.parquet").exists():
        g.append(pd.read_parquet(SAL / "t19_qwen.parquet"))
    g = pd.concat(g)
    return {(a, b): s for a, b, s in zip(g["q"], g["e"], g["si"])}


def clase_t10b():
    t = pd.read_parquet(SAL / "t10b_decisiones.parquet")
    g = pd.read_parquet(SAL / "t10b_qwen.parquet")
    pool = g.groupby("q").agg(alguno=("si", lambda s: bool((s == 1).any())),
                              todos_no=("si", lambda s: bool((s == 0).all())))
    t["clase"] = t["q"].map(lambda q: "con equivalente" if pool.loc[q, "alguno"] else
                            ("nueva" if pool.loc[q, "todos_no"] else "fuera"))
    return t, g


def armar():
    t10 = cargar("t10", AQUI / "t10_open_set.py")
    sys.path.insert(0, str(RAIZ / "src"))
    from benchmarking.producto.juez import cargar as cargar_juez
    e43 = cargar("e43", E2 / "43_perdida_vertex.py")
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    tit = np.array([str(c) for c in b["celdas"]], dtype=object)
    idx = {t: i for i, t in enumerate(tit)}
    grupo = np.asarray(b["grupo"]).astype(int)
    t, g = clase_t10b()
    t = t[t["clase"] == "con equivalente"].reset_index(drop=True)
    familia = g[g["si"] == 1].groupby("q")["e"].apply(lambda s: {int(grupo[idx[x]]) for x in s})
    filas = np.array([idx[q] for q in t["q"]])
    norm = lambda X: (X / np.linalg.norm(X, axis=1, keepdims=True)).astype(np.float32)  # noqa: E731
    Qd = norm(np.load(SAL / "t01_emb_qwen_desc.npy").astype(np.float32))
    Qc = norm(np.load(SAL / "t02_emb_qwen_consulta.npy").astype(np.float32))
    Zv = norm(np.asarray(b["Z"], dtype=np.float32))
    rq, rv = t10.ranking(Qc, Qd, filas, k=800), t10.ranking(Zv, Zv, filas, k=800)
    dec, quitados = [], []
    for k, (q, parte) in enumerate(zip(t["q"], t["parte"])):
        fuera = {int(grupo[idx[q]])} | familia.get(q, set())
        quitados.append(len(fuera))
        cq = t10.candidatos(rq[0][k], rq[1][k], fuera, q, tit, grupo, e43.bloqueado)
        cv = t10.candidatos(rv[0][k], rv[1][k], fuera, q, tit, grupo, e43.bloqueado)
        dec.append(dict(q=q, parte=parte, cq=cq, cv=cv, cf=[c for c in cv if c[2] >= 0.90]))
    for nom, ruta in t10.JUECES.items():
        j = cargar_juez(ruta)
        pares = sorted({(d["q"], str(tit[c[0]])) for d in dec for c in d["cq"] + d["cv"]})
        P = dict(zip(pares, j.P(pares)))
        for d in dec:
            for cl in ("cq", "cv", "cf"):
                d["P_{}_{}".format(nom, cl)] = [P[(d["q"], str(tit[c[0]]))] for c in d[cl]]
    ya = set(juicios())
    out, pool = [], set()
    for d in dec:
        f = {"q": d["q"], "parte": d["parte"]}
        for sis, cand, punt in (("A", d["cq"], d["P_reentrenado_cq"]), ("B", d["cq"], d["P_producto_cq"]),
                                ("C", d["cv"], d["P_producto_cv"]), ("Cfijo", d["cf"], d["P_producto_cf"]),
                                ("D", d["cq"], [c[2] for c in d["cq"]])):
            if cand:
                m = int(np.argmax(punt))
                f["e_" + sis], f["s_" + sis] = str(tit[cand[m][0]]), float(punt[m])
                pool.add((d["q"], f["e_" + sis]))
            else:
                f["e_" + sis], f["s_" + sis] = "", -np.inf
        for c in d["cq"][:3] + d["cv"][:3]:
            pool.add((d["q"], str(tit[c[0]])))
        out.append(f)
    pd.DataFrame(out).to_parquet(SAL / "t19_decisiones.parquet", index=False)
    nuevos = sorted(p for p in pool if p not in ya)
    pd.DataFrame(nuevos, columns=["q", "e"]).to_parquet(SAL / "t19_pool.parquet", index=False)
    print("consultas {:,}; grupos quitados por consulta: mediana {:.0f}, max {}; pares del pool {:,} (nuevos {:,})".format(
        len(out), np.median(quitados), max(quitados), len(pool), len(nuevos)))


def etiquetar():
    """Qwen3.5-122B sobre los pares nuevos del pool, como `t10b etiquetar_qwen`."""
    t10b = cargar("t10b", AQUI / "t10b_open_set.py")
    tmp = pathlib.Path(tempfile.mkdtemp(dir=SAL))
    shutil.copy(SAL / "t19_pool.parquet", tmp / "t10b_pool.parquet")
    t10b.SAL = tmp
    t10b.etiquetar_qwen()
    shutil.move(str(tmp / "t10b_qwen.parquet"), str(SAL / "t19_qwen.parquet"))
    shutil.rmtree(tmp, ignore_errors=True)


def medir():
    J = juicios()
    t19 = pd.read_parquet(SAL / "t19_decisiones.parquet")
    pool19 = pd.read_parquet(SAL / "t19_pool.parquet")
    # clase de cada consulta de T-019: sus pares del pool (nuevos y ya juzgados)
    pares = {}
    for q, e in zip(pool19["q"], pool19["e"]):
        pares.setdefault(q, set()).add(e)
    for _, r in t19.iterrows():
        for s in SISTEMAS:
            if r["e_" + s]:
                pares.setdefault(r["q"], set()).add(r["e_" + s])
    def clase(q):
        v = [J.get((q, e), np.nan) for e in pares.get(q, ())]
        if any(x == 1 for x in v):
            return "con equivalente"
        if v and all(x == 0 for x in v):
            return "nueva"
        return "fuera"
    t19["clase"] = t19["q"].map(clase)
    nuevas = t19[t19["clase"] == "nueva"].reset_index(drop=True)
    t10, _ = clase_t10b()
    conoc = t10[(t10["clase"] == "con equivalente") & (t10["parte"] == "prueba")].reset_index(drop=True)
    nue10 = t10[(t10["clase"] == "nueva") & (t10["parte"] == "prueba")].reset_index(drop=True)

    def ok_conocido(d, s):
        rec = d["s_" + s].to_numpy() >= UMBRAL[s]
        j = np.array([J.get((q, e), np.nan) if e else np.nan for q, e in zip(d["q"], d["e_" + s])])
        ok = (rec & (j == 1)).astype(float)
        ok[rec & np.isnan(j)] = np.nan
        return ok

    def ok_nueva(d, s):
        return (d["s_" + s].to_numpy() < UMBRAL[s]).astype(float)

    out = ["T-019 · open set con mas cargos nuevos (familias de equivalentes quitadas de la base)",
           "consultas de T-019: {:,} -> nuevas {:,}, con otro equivalente {:,}, fuera {:,}".format(
               len(t19), (t19["clase"] == "nueva").sum(), (t19["clase"] == "con equivalente").sum(),
               (t19["clase"] == "fuera").sum()),
           "nuevas de T-019 que vienen de consultas de prueba: {:,}; nuevas de prueba en T-010b: {:,}".format(
               int((nuevas["parte"] == "prueba").sum()), len(nue10)),
           "umbrales fijos (los de T-010b): {}".format(UMBRAL), ""]
    rng = np.random.default_rng(SEM)
    ok_c = {s: ok_conocido(conoc, s) for s in SISTEMAS}
    for etiqueta, nv in (("todas las nuevas de T-019", nuevas),
                         ("solo nuevas de consultas de prueba", nuevas[nuevas["parte"] == "prueba"].reset_index(drop=True))):
        ok_n = {s: ok_nueva(nv, s) for s in SISTEMAS}
        out.append("{} (n = {:,}) + con equivalente de la prueba de T-010b (n = {:,})".format(etiqueta, len(nv), len(conoc)))
        for s in SISTEMAS:
            c, n = np.nanmean(ok_c[s]), ok_n[s].mean()
            out.append("  {:<6} {:<42} reconoce bien {:.1%}  desconocido en nuevas {:.1%}  balanceada {:.3f}".format(
                s, NOMBRE[s], c, n, (c + n) / 2))
        for x, y in (("A", "Cfijo"), ("A", "B")):
            bs = []
            for _ in range(2000):
                ic = rng.integers(0, len(conoc), len(conoc))
                inn = rng.integers(0, len(nv), len(nv))
                bx = 0.5 * (np.nanmean(ok_c[x][ic]) + ok_n[x][inn].mean())
                by = 0.5 * (np.nanmean(ok_c[y][ic]) + ok_n[y][inn].mean())
                bs.append(bx - by)
            d0 = 0.5 * (np.nanmean(ok_c[x]) + ok_n[x].mean()) - 0.5 * (np.nanmean(ok_c[y]) + ok_n[y].mean())
            lo, hi = np.nanpercentile(bs, [2.5, 97.5])
            out.append("  {} - {}: {:+.3f} [{:+.3f}, {:+.3f}] -> {}".format(
                x, y, d0, lo, hi, "A MEJOR" if lo > 0 else ("A PEOR" if hi < 0 else "no se distingue")))
        out.append("")
    (SAL / "t19_open_set.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    {"armar": armar, "etiquetar": etiquetar, "medir": medir}[sys.argv[1]]()
