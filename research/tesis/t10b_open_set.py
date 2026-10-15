"""T-010b: open set con la verdad juzgada par a par por GLM (registro, T-010b).

    CUDA_VISIBLE_DEVICES=0 .venv/bin/python research/tesis/t10b_open_set.py armar      candidatos, puntajes y pool
    .venv/bin/python research/tesis/t10b_open_set.py etiquetar                          GLM sobre el pool
    .venv/bin/python research/tesis/t10b_open_set.py medir

SALIDAS: salidas/t10b_decisiones.parquet, t10b_pool.parquet, t10b_glm.parquet (fuera del repo), t10b_open_set.txt
"""
import importlib.util
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
SAL = AQUI / "salidas"
SEM = 20261014
N_CONSULTAS = 1000
SISTEMAS = ("A", "B", "C", "Cfijo", "D")
UMBRALES_P = (0.5, 0.8, 0.9, 0.93, 0.95, 0.96, 0.97, 0.975, 0.98, 0.985, 0.99)
UMBRALES_COS = tuple(np.round(np.arange(0.60, 0.95, 0.02), 2))


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def armar():
    t10 = cargar("t10", AQUI / "t10_open_set.py")
    sys.path.insert(0, str(RAIZ / "src"))
    from benchmarking.producto.juez import cargar as cargar_juez
    e43, e52 = cargar("e43", E2 / "43_perdida_vertex.py"), cargar("e52", E2 / "52_validacion_glm.py")
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    tit = np.array([str(c) for c in b["celdas"]], dtype=object)
    grupo = np.asarray(b["grupo"]).astype(int)
    desc = pd.read_csv(E2 / "salidas" / "46_descripciones.csv", keep_default_na=False)
    con_desc = {t for t, r in zip(desc["titulo"].astype(str), desc["respuesta"])
                if json.loads(r).get("descripcion", "").strip()}
    vistos = set()
    for f in (E2 / "salidas/21_paquete_v6/plata.csv", E2 / "salidas/t09_paquete/plata.csv"):
        q = pd.read_csv(f, dtype=str, keep_default_na=False)
        vistos |= set(q["comun"]) | set(q["raro"])
    for f, a, c in (("13e_pares_400.csv", "comun", "raro"), ("20_pares_400.csv", "comun", "raro"),
                    ("29_prueba2_pares.csv", "comun", "raro")):
        d = e52.leer(E2 / "salidas" / f)
        vistos |= set(d[a]) | set(d[c])
    pos = [i for i, t in enumerate(tit) if t in con_desc and t not in vistos]
    filas = np.sort(np.random.default_rng(SEM).choice(pos, N_CONSULTAS, replace=False))
    norm = lambda X: (X / np.linalg.norm(X, axis=1, keepdims=True)).astype(np.float32)  # noqa: E731
    Qd = norm(np.load(SAL / "t01_emb_qwen_desc.npy").astype(np.float32))
    Qc = norm(np.load(SAL / "t02_emb_qwen_consulta.npy").astype(np.float32))
    Zv = norm(np.asarray(b["Z"], dtype=np.float32))
    rq, rv = t10.ranking(Qc, Qd, filas), t10.ranking(Zv, Zv, filas)
    dec = []
    for k, i in enumerate(filas):
        q, fuera = str(tit[i]), {int(grupo[i])}
        cq = t10.candidatos(rq[0][k], rq[1][k], fuera, q, tit, grupo, e43.bloqueado)
        cv = t10.candidatos(rv[0][k], rv[1][k], fuera, q, tit, grupo, e43.bloqueado)
        dec.append(dict(q=q, cq=cq, cv=cv, cf=[c for c in cv if c[2] >= 0.90]))
    for nom, ruta in t10.JUECES.items():
        j = cargar_juez(ruta)
        pares = sorted({(d["q"], str(tit[c[0]])) for d in dec for c in d["cq"] + d["cv"]})
        P = dict(zip(pares, j.P(pares)))
        for d in dec:
            for cl in ("cq", "cv", "cf"):
                d["P_{}_{}".format(nom, cl)] = [P[(d["q"], str(tit[c[0]]))] for c in d[cl]]
    out, pool = [], set()
    rng = np.random.default_rng(SEM + 2)
    for k, d in enumerate(dec):
        f = {"q": d["q"], "parte": "calibra" if rng.random() < 0.5 else "prueba"}
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
    pd.DataFrame(out).to_parquet(SAL / "t10b_decisiones.parquet", index=False)
    pd.DataFrame(sorted(pool), columns=["q", "e"]).to_parquet(SAL / "t10b_pool.parquet", index=False)
    print("consultas {:,}; pares en el pool {:,}".format(len(out), len(pool)))


def etiquetar():
    """GLM sobre el pool. Guarda cada respuesta al llegar (`t10b_glm_cache.jsonl`) y retoma desde ahi; las fallas de
    conexion no se guardan, para reintentarlas en la proxima corrida."""
    sys.modules["vllm"] = None
    e51 = cargar("e51", E2 / "51_etiquetador_local.py")
    p = pd.read_parquet(SAL / "t10b_pool.parquet")
    sis, sha = e51.sistema()
    url, nombre, _ = e51.API["glm-5.3-flash"]
    cache_f = SAL / "t10b_glm_cache.jsonl"
    hecho = {}
    if cache_f.exists():
        for linea in cache_f.read_text(encoding="utf-8").splitlines():
            r = json.loads(linea)
            hecho[(r["a"], r["b"])] = r["mismo"]
    filas = [(a, b) for x, y in zip(p["q"], p["e"]) for a, b in ((x, y), (y, x)) if (a, b) not in hecho]
    print("pendientes {:,} de {:,}".format(len(filas), 2 * len(p)), flush=True)
    import threading
    from concurrent.futures import ThreadPoolExecutor
    candado, n, t0 = threading.Lock(), [0], time.time()

    def uno(f):
        s = e51.pedir_api(url, nombre, sis, f[0], f[1], pensar=True)   # el servidor razona siempre (T-009)
        if str(s).startswith("ERROR"):
            return
        try:
            mismo = json.loads(s)["mismo"]
        except (ValueError, KeyError, TypeError):
            mismo = ""
        with candado:
            with open(cache_f, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"a": f[0], "b": f[1], "mismo": mismo}, ensure_ascii=False) + "\n")
            hecho[f] = mismo
            n[0] += 1
            if n[0] % 500 == 0:
                print("{:,} en {:.0f} min".format(n[0], (time.time() - t0) / 60), flush=True)
    with ThreadPoolExecutor(e51.CONCURRENCIA) as ex:
        list(ex.map(uno, filas))
    falta = sum(1 for x, y in zip(p["q"], p["e"]) for k in ((x, y), (y, x)) if k not in hecho)
    if falta:
        raise SystemExit("faltan {:,} respuestas (servidor caido?): volver a correr para retomar".format(falta))
    p["ab"] = [hecho[(x, y)] for x, y in zip(p["q"], p["e"])]
    p["ba"] = [hecho[(y, x)] for x, y in zip(p["q"], p["e"])]
    p["coherente"] = (p["ab"] == p["ba"]) & p["ab"].isin(["si", "no"])
    p["si"] = np.where(p["coherente"], (p["ab"] == "si").astype(float), np.nan)
    p["rubrica_sha"] = sha
    p.to_parquet(SAL / "t10b_glm.parquet", index=False)
    print("{:,} pares; coherentes {:.1%}; si {:.0%}".format(len(p), p["coherente"].mean(), p["si"].mean()))


def etiquetar_qwen():
    """Enmienda de T-010b: la verdad con Qwen3.5-122B local (vLLM, sin razonamiento, rubrica v7).
    CUDA_VISIBLE_DEVICES=1,3 /root/salary-benchmarking/.venv-llm/bin/python t10b_open_set.py etiquetar_qwen"""
    import os
    os.environ.setdefault("VLLM_USE_DEEP_GEMM", "0")
    os.environ.setdefault("VLLM_ALLREDUCE_USE_FLASHINFER", "0")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
    os.environ["PATH"] = str(pathlib.Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    e51 = cargar("e51", E2 / "51_etiquetador_local.py")
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import StructuredOutputsParams
    p = pd.read_parquet(SAL / "t10b_pool.parquet")
    sis, sha = e51.sistema()
    llm = LLM(model=str(RAIZ / "modelos" / "qwen35-122b-a10b-fp8"), tensor_parallel_size=2, max_model_len=8192,
              gpu_memory_utilization=0.85, seed=20261005,
              compilation_config={"pass_config": {"fuse_allreduce_rms": False}}, gdn_prefill_backend="triton")
    sp = SamplingParams(temperature=0.0, max_tokens=300, seed=20261005,
                        structured_outputs=StructuredOutputsParams(json=e51.ESQUEMA))
    filas = [(a, b) for x, y in zip(p["q"], p["e"]) for a, b in ((x, y), (y, x))]
    sal = llm.chat([[{"role": "system", "content": sis}, {"role": "user", "content": "A: {}\nB: {}".format(a, b)}]
                    for a, b in filas], sp, chat_template_kwargs={"enable_thinking": False})
    r = []
    for s_ in sal:
        try:
            r.append(json.loads(s_.outputs[0].text)["mismo"])
        except (ValueError, KeyError, TypeError):
            r.append("")
    p["ab"], p["ba"] = r[0::2], r[1::2]
    p["coherente"] = (p["ab"] == p["ba"]) & p["ab"].isin(["si", "no"])
    p["si"] = np.where(p["coherente"], (p["ab"] == "si").astype(float), np.nan)
    p["rubrica_sha"], p["juez"] = sha, "Qwen3.5-122B"
    p.to_parquet(SAL / "t10b_qwen.parquet", index=False)
    print("{:,} pares; coherentes {:.1%}; si {:.0%}".format(len(p), p["coherente"].mean(), p["si"].mean()))


def medir(fuente="t10b_qwen.parquet", solo_consultas=None, sufijo=""):
    t = pd.read_parquet(SAL / "t10b_decisiones.parquet")
    if solo_consultas is not None:
        t = t[t["q"].isin(solo_consultas)]
    g = pd.read_parquet(SAL / fuente) if isinstance(fuente, str) else fuente
    juicio = {(a, b): s for a, b, s in zip(g["q"], g["e"], g["si"])}
    pool = g.groupby("q").agg(alguno=("si", lambda s: bool((s == 1).any())),
                              todos_no=("si", lambda s: bool((s == 0).all())))
    t["clase"] = t["q"].map(lambda q: "con equivalente" if pool.loc[q, "alguno"] else
                            ("nueva" if pool.loc[q, "todos_no"] else "fuera"))
    t = t[t["clase"] != "fuera"].reset_index(drop=True)
    for s in SISTEMAS:
        t["j_" + s] = [juicio.get((q, e), np.nan) if e else np.nan for q, e in zip(t["q"], t["e_" + s])]

    def aciertos(d, s, u):
        rec = d["s_" + s].to_numpy() >= u
        con = (d["clase"] == "con equivalente").to_numpy()
        j = d["j_" + s].to_numpy()
        ok = np.where(con, rec & (j == 1), ~rec).astype(float)
        ok[con & rec & np.isnan(j)] = np.nan          # elegido incoherente: fuera de ese sistema
        return ok

    def bal(d, ok):
        con = (d["clase"] == "con equivalente").to_numpy()
        return 0.5 * (np.nanmean(ok[con]) + np.nanmean(ok[~con]))

    tc, tp = t[t["parte"] == "calibra"].reset_index(drop=True), t[t["parte"] == "prueba"].reset_index(drop=True)
    out = ["T-010b · OPEN SET con la verdad par a par (pool; fuente: " + (fuente if isinstance(fuente, str) else "GLM, control") + ")",
           "consultas: {:,} con clase ({}); calibra {:,}, prueba {:,}".format(
               len(t), t["clase"].value_counts().to_dict(), len(tc), len(tp)),
           "pool: {:,} pares; juez coherente {:.1%}".format(len(g), g["coherente"].mean()), "",
           "Umbral elegido en calibra:"]
    umb = {"Cfijo": 0.5}
    for s, grilla in (("A", UMBRALES_P), ("B", UMBRALES_P), ("C", UMBRALES_P), ("D", UMBRALES_COS)):
        umb[s] = max(grilla, key=lambda u: bal(tc, aciertos(tc, s, u)))
        out.append("  {}: {}  (calibra {:.4f})".format(s, umb[s], bal(tc, aciertos(tc, s, umb[s]))))
    con = (tp["clase"] == "con equivalente").to_numpy()
    out += ["", "PRUEBA ({:,} con equivalente, {:,} nuevas)".format(con.sum(), (~con).sum())]
    oks = {}
    for s in SISTEMAS:
        ok = aciertos(tp, s, umb[s])
        oks[s] = ok
        rec = tp["s_" + s].to_numpy() >= umb[s]
        j = tp["j_" + s].to_numpy()
        out.append("  {:<6} exactitud balanceada {:.4f}   con equivalente: reconoce bien {:.1%}, reconoce mal {:.1%}, "
                   "desconocido {:.1%}   nuevas: desconocido {:.1%}   (fuera por incoherente {})".format(
                       s, bal(tp, ok), np.nanmean(ok[con]), np.mean(con[con] & rec[con] & (j[con] == 0)),
                       np.mean(~rec[con]), np.nanmean(ok[~con]), int(np.isnan(ok).sum())))
    rng = np.random.default_rng(SEM + 1)
    out.append("")
    for x, y in (("A", "Cfijo"), ("A", "B"), ("A", "C"), ("A", "D")):
        d0 = bal(tp, oks[x]) - bal(tp, oks[y])
        bs = []
        for _ in range(2000):
            ii = rng.integers(0, len(tp), len(tp))
            s_ = tp.iloc[ii].reset_index(drop=True)
            bs.append(bal(s_, oks[x][ii]) - bal(s_, oks[y][ii]))
        lo, hi = np.nanpercentile(bs, [2.5, 97.5])
        out.append("{} - {}: {:+.4f} [{:+.4f}, {:+.4f}]  -> {}".format(
            x, y, d0, lo, hi, "A MEJOR" if lo > 0 else ("A PEOR" if hi < 0 else "no se distingue")))
    (SAL / "t10b_open_set{}.txt".format(sufijo)).write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


def control_glm():
    """Sesgo de la verdad de Qwen: acuerdo con GLM en los pares que GLM alcanzo a juzgar, y la comparacion con la verdad
    de GLM solo en las consultas cuyo pool GLM juzgo completo."""
    q = pd.read_parquet(SAL / "t10b_qwen.parquet")
    h = {}
    for linea in (SAL / "t10b_glm_cache.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(linea)
        h[(r["a"], r["b"])] = r["mismo"]
    q["g_ab"] = [h.get((x, y)) for x, y in zip(q["q"], q["e"])]
    q["g_ba"] = [h.get((y, x)) for x, y in zip(q["q"], q["e"])]
    ambos = q["g_ab"].notna() & q["g_ba"].notna()
    g = q[ambos].copy()
    g["coherente"] = (g["g_ab"] == g["g_ba"]) & g["g_ab"].isin(["si", "no"])
    g["si_glm"] = np.where(g["coherente"], (g["g_ab"] == "si").astype(float), np.nan)
    m = g["coherente"] & q.loc[ambos, "coherente"]
    acu = (g.loc[m, "si_glm"] == g.loc[m, "si"]).mean()
    completas = set(q.groupby("q").filter(lambda d: ambos[d.index].all())["q"])
    print("pares con GLM en los dos ordenes: {:,}; acuerdo GLM-Qwen en los coherentes de ambos: {:.1%} (n={:,}); "
          "consultas con el pool completo en GLM: {:,}".format(int(ambos.sum()), acu, int(m.sum()), len(completas)))
    v = g.assign(si=g["si_glm"], coherente=g["coherente"])[["q", "e", "si", "coherente"]]
    medir(v, completas, "_control_glm")


if __name__ == "__main__":
    {"armar": armar, "etiquetar": etiquetar, "etiquetar_qwen": etiquetar_qwen, "medir": medir,
     "control_glm": control_glm}[sys.argv[1]]()
