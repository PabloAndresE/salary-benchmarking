"""T-022: oro humano a ciegas con dos anotadores (registro, T-022).

    .venv/bin/python research/tesis/t22_oro_humano.py armar      hojas ciegas para los dos anotadores + la llave
    .venv/bin/python research/tesis/t22_oro_humano.py medir      kappa, juez LLM frente al oro, precision, nuevas

Las hojas se llenan en la columna `mismo` (si / no) y, si hace falta, `nota` (duda). Los desacuerdos resueltos
conversando van en t22_resolucion.csv (n_par, mismo).
SALIDAS (fuera del repo): salidas/t22_anotador_1.csv, t22_anotador_2.csv, t22_llave.parquet; t22_oro.txt
"""
import io
import os
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
SEM = 20261028
N_E1, N_E2, N_E3 = 75, 80, {"si": 30, "no": 30, "incoherente": 20}


def juicios():
    g = pd.concat([pd.read_parquet(SAL / f)[["q", "e", "si"]] for f in
                   ("t10b_qwen.parquet", "t12_etiquetas.parquet", "t19_qwen.parquet", "t20_qwen.parquet")
                   if (SAL / f).exists()])
    return {(a, b): s for a, b, s in zip(g["q"], g["e"], g["si"])}


def nuevas_t19(J):
    t = pd.read_parquet(SAL / "t19_decisiones.parquet")
    p = pd.read_parquet(SAL / "t19_pool.parquet")
    pares = {}
    for q, e in zip(p["q"], p["e"]):
        pares.setdefault(q, set()).add(e)
    for c in [c for c in t.columns if c.startswith("e_")]:
        for q, e in zip(t["q"], t[c]):
            if e:
                pares.setdefault(q, set()).add(e)
    def nueva(q):
        v = [J.get((q, e), np.nan) for e in pares.get(q, ())]
        return bool(v) and all(x == 0 for x in v)
    return t[t["q"].map(nueva)]


def armar():
    rng = np.random.default_rng(SEM)
    J = juicios()
    t = pd.read_parquet(SAL / "t10b_decisiones.parquet")
    g = pd.read_parquet(SAL / "t10b_qwen.parquet")
    filas = []
    for sis, rec in (("propuesto", t["s_A"] >= 0.90), ("producto", t["s_Cfijo"] >= 0.5)):
        e = "e_A" if sis == "propuesto" else "e_Cfijo"
        d = t[rec & (t[e] != "")]
        for k in rng.choice(len(d), N_E1, replace=False):
            filas.append(("E1_" + sis, d["q"].iloc[k], d[e].iloc[k]))
    todos_no = g.groupby("q")["si"].apply(lambda s: bool((s == 0).all()))
    nv = pd.concat([t[t["q"].map(todos_no)][["q", "e_A"]], nuevas_t19(J)[["q", "e_A"]]]).drop_duplicates("q")
    nv = nv[nv["e_A"] != ""]
    for k in rng.choice(len(nv), min(N_E2, len(nv)), replace=False):
        filas.append(("E2_nueva", nv["q"].iloc[k], nv["e_A"].iloc[k]))
    g["clase_llm"] = np.where(~g["coherente"], "incoherente", np.where(g["si"] == 1, "si", "no"))
    for c, n in N_E3.items():
        d = g[g["clase_llm"] == c]
        for k in rng.choice(len(d), n, replace=False):
            filas.append(("E3_" + c, d["q"].iloc[k], d["e"].iloc[k]))
    m = pd.DataFrame(filas, columns=["estrato", "q", "e"])
    llave = m.groupby(["q", "e"])["estrato"].apply(lambda s: "+".join(sorted(set(s)))).reset_index()
    llave = llave.sample(frac=1.0, random_state=SEM).reset_index(drop=True)
    llave["n_par"] = np.arange(1, len(llave) + 1)
    llave["llm"] = [J.get((q, e), np.nan) for q, e in zip(llave["q"], llave["e"])]
    for a in (1, 2):
        r = np.random.default_rng(SEM + a)
        orden = r.permutation(len(llave))
        gira = r.random(len(llave)) < 0.5
        h = pd.DataFrame({"n_par": llave["n_par"].to_numpy()[orden],
                          "a": np.where(gira, llave["e"], llave["q"])[orden],
                          "b": np.where(gira, llave["q"], llave["e"])[orden]})
        h.insert(0, "n_ciego", np.arange(1, len(h) + 1))
        llave["n_ciego_{}".format(a)] = h.set_index("n_par").loc[llave["n_par"], "n_ciego"].to_numpy()
        h[["n_ciego", "a", "b"]].assign(mismo="", nota="").to_csv(
            SAL / "t22_anotador_{}.csv".format(a), index=False, encoding="utf-8-sig")
    llave.to_parquet(SAL / "t22_llave.parquet", index=False)
    for f in ("t22_anotador_1.csv", "t22_anotador_2.csv", "t22_llave.parquet"):
        os.chmod(SAL / f, 0o600)
    print("pares unicos {:,}; por estrato: {}".format(len(llave), m["estrato"].value_counts().to_dict()))


def leer(a):
    txt = (SAL / "t22_anotador_{}.csv".format(a)).read_text(encoding="utf-8-sig")
    sep = ";" if txt.splitlines()[0].count(";") > txt.splitlines()[0].count(",") else ","
    h = pd.read_csv(io.StringIO(txt), sep=sep, dtype=str, keep_default_na=False)
    h["mismo"] = h["mismo"].str.strip().str.lower().map({"si": 1.0, "sí": 1.0, "no": 0.0})
    return dict(zip(h["n_ciego"].astype(int), h["mismo"]))


def kappa(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    po = (x == y).mean()
    pe = x.mean() * y.mean() + (1 - x.mean()) * (1 - y.mean())
    return (po - pe) / (1 - pe) if pe < 1 else np.nan


def ic(f, n, rng, b=2000):
    v = [f(rng.integers(0, n, n)) for _ in range(b)]
    return np.nanpercentile(v, [2.5, 97.5])


def medir():
    ll = pd.read_parquet(SAL / "t22_llave.parquet")
    h1, h2 = leer(1), leer(2)
    ll["a1"] = ll["n_ciego_1"].map(h1)
    ll["a2"] = ll["n_ciego_2"].map(h2)
    rng = np.random.default_rng(SEM + 9)
    out = ["T-022 · oro humano a ciegas ({:,} pares)".format(len(ll))]
    d = ll.dropna(subset=["a1", "a2"]).reset_index(drop=True)
    out.append("respondidos por los dos: {:,}; sin respuesta: {:,}".format(len(d), len(ll) - len(d)))
    k = kappa(d["a1"], d["a2"])
    lo, hi = ic(lambda i: kappa(d["a1"].to_numpy()[i], d["a2"].to_numpy()[i]), len(d), rng)
    out.append("1. acuerdo entre anotadores: {:.1%}; kappa {:.3f} [{:.3f}, {:.3f}] -> {}".format(
        (d["a1"] == d["a2"]).mean(), k, lo, hi, "aceptable" if k >= 0.60 else "BAJO 0,60"))
    d["oro"] = np.where(d["a1"] == d["a2"], d["a1"], np.nan)
    res = SAL / "t22_resolucion.csv"
    if res.exists():
        r = pd.read_csv(res, dtype=str)
        r = dict(zip(r["n_par"].astype(int), r["mismo"].str.strip().str.lower().map({"si": 1.0, "sí": 1.0, "no": 0.0})))
        d["oro"] = d["oro"].fillna(d["n_par"].map(r))
    out.append("   desacuerdos {:,}; resueltos {:,}".format(int((d["a1"] != d["a2"]).sum()),
                                                           int(((d["a1"] != d["a2"]) & d["oro"].notna()).sum())))
    o = d.dropna(subset=["oro"]).reset_index(drop=True)
    c = o.dropna(subset=["llm"]).reset_index(drop=True)
    k = kappa(c["llm"], c["oro"])
    lo, hi = ic(lambda i: kappa(c["llm"].to_numpy()[i], c["oro"].to_numpy()[i]), len(c), rng)
    out.append("2. juez LLM (Qwen3.5-122B) frente al oro, {:,} pares coherentes: exactitud {:.1%}; kappa {:.3f} "
               "[{:.3f}, {:.3f}] -> {}".format(len(c), (c["llm"] == c["oro"]).mean(), k, lo, hi,
                                              "se sostiene" if k >= 0.60 else "NO se sostiene"))
    prec = {}
    for s in ("propuesto", "producto"):
        prec[s] = o[o["estrato"].str.contains("E1_" + s)]["oro"].to_numpy()
        out.append("3. precision del reconocimiento, {}: {:.1%} (n = {})".format(s, prec[s].mean(), len(prec[s])))
    a, b = prec["propuesto"], prec["producto"]
    bs = [a[rng.integers(0, len(a), len(a))].mean() - b[rng.integers(0, len(b), len(b))].mean() for _ in range(2000)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    out.append("   propuesto - producto: {:+.1%} [{:+.1%}, {:+.1%}] -> {}".format(
        a.mean() - b.mean(), lo, hi, "PROPUESTO MEJOR" if lo > 0 else ("PROPUESTO PEOR" if hi < 0 else "no se distingue")))
    n = o[o["estrato"].str.contains("E2_nueva")]["oro"].to_numpy()
    out.append("4. cargos nuevos confirmados (el humano dice no al candidato mas probable): {:.1%} de {}".format(
        (n == 0).mean(), len(n)))
    for e in ("E3_si", "E3_no", "E3_incoherente"):
        x = o[o["estrato"].str.contains(e)]["oro"].to_numpy()
        out.append("   {}: el oro dice si en {:.0%} (n = {})".format(e, x.mean(), len(x)))
    (SAL / "t22_oro.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    {"armar": armar, "medir": medir}[sys.argv[1]]()
