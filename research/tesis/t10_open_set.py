"""T-010: open set. Un titulo nuevo -> «reconocido» (el grupo equivalente) o «desconocido» (registro, T-010).

    CUDA_VISIBLE_DEVICES=0 .venv/bin/python research/tesis/t10_open_set.py medir
    CUDA_VISIBLE_DEVICES=0,3 /root/salary-benchmarking/.venv-llm/bin/python research/tesis/t10_open_set.py auditar

Sistemas: A (Qwen + cross-encoder reentrenado), B (Qwen + cross-encoder del producto), C (Vertex + cross-encoder del
producto), C fijo (el producto hoy: Vertex coseno >= 0,90 y P >= 0,5) y D (solo coseno de Qwen).
SALIDAS: salidas/t10_open_set.txt, t10_decisiones.parquet (fuera del repo), t10_auditoria.txt
"""
import importlib.util
import json
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
SAL = AQUI / "salidas"
SEM = 20261014
N_CAND = 10
UMBRALES_P = (0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 0.98)
UMBRALES_COS = tuple(np.round(np.arange(0.60, 0.96, 0.02), 2))
JUECES = {"producto": E2 / "salidas/22_modelos_v3/elegido", "reentrenado": E2 / "salidas/t09_modelos/elegido"}


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def oro(idx, grupo):
    """Pares de prueba (nunca vistos por un cross-encoder) y el oro completo para el brazo «nuevo»."""
    e1 = cargar("t09e1", AQUI / "t09_etapa1.py")
    sys.path.insert(0, str(AQUI))
    import oro_pares
    c = e1.conjuntos()
    p = pd.concat([d[d["y"] == 1][["a", "b"]] for d in c.values()], ignore_index=True)
    s = pd.read_csv(RAIZ / "src/benchmarking/producto/datos/sinonimos_v2/sinonimos.csv", dtype=str)
    p = pd.concat([p, pd.DataFrame({"a": s["titulo_a"], "b": s["titulo_b"]})], ignore_index=True)
    p["a"], p["b"] = p["a"].str.strip().str.upper(), p["b"].str.strip().str.upper()
    p = p[p["a"].isin(idx) & p["b"].isin(idx)]
    p = p[[grupo[idx[a]] != grupo[idx[b]] for a, b in zip(p["a"], p["b"])]]
    vistos = set()
    for f in (E2 / "salidas/21_paquete_v6/plata.csv", E2 / "salidas/t09_paquete/plata.csv"):
        q = pd.read_csv(f, dtype=str, keep_default_na=False)
        vistos |= {frozenset((x, y)) for x, y in zip(q["comun"], q["raro"])}
    clave = [frozenset((a, b)) for a, b in zip(p["a"], p["b"])]
    p = p[[k not in vistos for k in clave]]
    p = p[~pd.Series([frozenset((a, b)) for a, b in zip(p["a"], p["b"])]).duplicated().to_numpy()]
    p = p.reset_index(drop=True)
    p["par"] = np.arange(len(p))
    # oro completo (todas las fuentes, si): para sacar del brazo «nuevo» todo equivalente conocido
    todo = oro_pares.pares(idx)
    todo = pd.concat([todo[todo["y"] == 1][["a", "b"]], p[["a", "b"]]])
    eq = {}
    for a, b in zip(todo["a"], todo["b"]):
        eq.setdefault(a, set()).add(grupo[idx[b]])
        eq.setdefault(b, set()).add(grupo[idx[a]])
    return p, eq


def ranking(Q, D, filas, k=400):
    import torch
    Qt = torch.from_numpy(Q[filas]).to("cuda", torch.float16)
    Dt = torch.from_numpy(D).to("cuda", torch.float16)
    s, v = (Qt @ Dt.T).float().topk(k, dim=1)
    return v.cpu().numpy(), s.cpu().numpy()


def candidatos(vec, sim, fuera, q, tit, grupo, bloqueado, cos_min=-1.0):
    out, gs = [], set()
    for j, s in zip(vec, sim):
        if s < cos_min or len(out) == N_CAND:
            break
        g = int(grupo[j])
        if g in fuera or g in gs:
            continue
        gs.add(g)
        if bloqueado(q, tit[j]):
            continue
        out.append((int(j), g, float(s)))
    return out


def medir():
    sys.path.insert(0, str(RAIZ / "src"))
    from benchmarking.producto.juez import cargar as cargar_juez
    e43 = cargar("e43", E2 / "43_perdida_vertex.py")
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    tit = np.array([str(c) for c in b["celdas"]], dtype=object)
    idx = {t: i for i, t in enumerate(tit)}
    grupo = np.asarray(b["grupo"]).astype(int)
    norm = lambda X: (X / np.linalg.norm(X, axis=1, keepdims=True)).astype(np.float32)  # noqa: E731
    Qd = norm(np.load(SAL / "t01_emb_qwen_desc.npy").astype(np.float32))
    Qc = norm(np.load(SAL / "t02_emb_qwen_consulta.npy").astype(np.float32))
    Zv = norm(np.asarray(b["Z"], dtype=np.float32))
    p, eq = oro(idx, grupo)
    cons = pd.concat([pd.DataFrame({"par": p["par"], "q": p["a"], "e": p["b"]}),
                      pd.DataFrame({"par": p["par"], "q": p["b"], "e": p["a"]})], ignore_index=True)
    rng = np.random.default_rng(SEM)
    cal = set(rng.choice(p["par"].to_numpy(), len(p) // 2, replace=False).tolist())
    cons["parte"] = np.where(cons["par"].isin(cal), "calibra", "prueba")
    filas = cons["q"].map(idx).to_numpy()
    rq = ranking(Qc, Qd, filas)
    rv = ranking(Zv, Zv, filas)
    jueces = {k: cargar_juez(v) for k, v in JUECES.items()}
    dec = []
    for brazo in ("conocido", "nuevo"):
        for k, r in enumerate(cons.itertuples()):
            gq, ge = int(grupo[idx[r.q]]), int(grupo[idx[r.e]])
            fuera = {gq} if brazo == "conocido" else {gq, ge} | eq.get(r.q, set())
            cq = candidatos(rq[0][k], rq[1][k], fuera, r.q, tit, grupo, e43.bloqueado)
            cv = candidatos(rv[0][k], rv[1][k], fuera, r.q, tit, grupo, e43.bloqueado)
            cf = [c for c in cv if c[2] >= 0.90]
            dec.append(dict(brazo=brazo, par=r.par, parte=r.parte, q=r.q, e=r.e, ge=ge, cq=cq, cv=cv, cf=cf))
    # puntuar todos los pares con los dos cross-encoders (con cache)
    for nom, j in jueces.items():
        pares = sorted({(d["q"], str(tit[c[0]])) for d in dec for c in d["cq"] + d["cv"]})
        P = dict(zip(pares, j.P(pares)))
        for d in dec:
            for clave in ("cq", "cv", "cf"):
                d["P_" + nom + "_" + clave] = [P[(d["q"], str(tit[c[0]]))] for c in d[clave]]
    def decision(d, cand, puntajes):
        if not cand:
            return -1, -np.inf
        i = int(np.argmax(puntajes))
        return cand[i][1], float(puntajes[i])
    filas_out = []
    for d in dec:
        f = {k: d[k] for k in ("brazo", "par", "parte", "q", "e", "ge")}
        for sis, cand, punt in (("A", d["cq"], d["P_reentrenado_cq"]), ("B", d["cq"], d["P_producto_cq"]),
                                ("C", d["cv"], d["P_producto_cv"]), ("Cfijo", d["cf"], d["P_producto_cf"]),
                                ("D", d["cq"], [c[2] for c in d["cq"]])):
            g, s = decision(d, cand, punt)
            f["g_" + sis], f["s_" + sis] = g, s
            if sis == "A":
                f["titulo_A"] = str(tit[cand[int(np.argmax(punt))][0]]) if cand else ""
        filas_out.append(f)
    t = pd.DataFrame(filas_out)
    t.to_parquet(SAL / "t10_decisiones.parquet", index=False)

    def aciertos(t, sis, u):
        rec = t["s_" + sis] >= u
        ok = np.where(t["brazo"] == "conocido", rec & (t["g_" + sis] == t["ge"]), ~rec)
        return ok.astype(float)

    def bal(t, ok):
        return 0.5 * (ok[(t["brazo"] == "conocido").to_numpy()].mean() + ok[(t["brazo"] == "nuevo").to_numpy()].mean())

    tc, tp = t[t["parte"] == "calibra"], t[t["parte"] == "prueba"].reset_index(drop=True)
    umb = {}
    out = ["T-010 · OPEN SET (reconocido / desconocido)",
           "pares de oro: {:,} (calibra {:,}, prueba {:,}); consultas por brazo: {:,}".format(
               len(p), len(cal), len(p) - len(cal), len(cons)), "", "Umbral elegido en calibra:"]
    for sis, grilla in (("A", UMBRALES_P), ("B", UMBRALES_P), ("C", UMBRALES_P), ("D", UMBRALES_COS)):
        mejor = max(grilla, key=lambda u: bal(tc, aciertos(tc, sis, u)))
        umb[sis] = mejor
        out.append("  {}: {}  (calibra {:.4f})".format(sis, mejor, bal(tc, aciertos(tc, sis, mejor))))
    umb["Cfijo"] = 0.5
    out += ["", "PRUEBA ({:,} consultas por brazo)".format(int((tp["brazo"] == "conocido").sum()))]
    oks = {}
    for sis in ("A", "B", "C", "Cfijo", "D"):
        ok = aciertos(tp, sis, umb[sis])
        oks[sis] = ok
        con = (tp["brazo"] == "conocido").to_numpy()
        rec = (tp["s_" + sis] >= umb[sis]).to_numpy()
        otro = (con & rec & (tp["g_" + sis] != tp["ge"]).to_numpy()).sum() / con.sum()
        out.append("  {:<6} exactitud balanceada {:.4f}   conocido: reconocido bien {:.1%}, en otro grupo {:.1%}, "
                   "desconocido {:.1%}   nuevo: desconocido {:.1%}".format(
                       sis, bal(tp, ok), ok[con].mean(), otro, (~rec[con]).mean(), ok[~con].mean()))
    pares_p = tp["par"].unique()
    rng = np.random.default_rng(SEM + 1)
    pos = {k: np.flatnonzero(tp["par"].to_numpy() == k) for k in pares_p}
    out.append("")
    for x, y in (("A", "Cfijo"), ("A", "B"), ("A", "C"), ("A", "D")):
        d0 = bal(tp, oks[x]) - bal(tp, oks[y])
        bs = []
        for _ in range(2000):
            ii = np.concatenate([pos[k] for k in rng.choice(pares_p, len(pares_p))])
            s_ = tp.iloc[ii]
            bs.append(bal(s_, oks[x][ii]) - bal(s_, oks[y][ii]))
        lo, hi = np.percentile(bs, [2.5, 97.5])
        out.append("{} - {}: {:+.4f} [{:+.4f}, {:+.4f}]  -> {}".format(
            x, y, d0, lo, hi, "A MEJOR" if lo > 0 else ("A PEOR" if hi < 0 else "no se distingue")))
    (SAL / "t10_open_set.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    json.dump({k: float(v) for k, v in umb.items()}, open(SAL / "t10_umbrales.json", "w"))
    print("\n".join(out))


def auditar(n=200):
    """200 «reconocidos» del brazo nuevo de A (prueba): ¿era realmente el mismo cargo? (Qwen3.5-122B, rubrica v7)."""
    import os
    os.environ.setdefault("VLLM_USE_DEEP_GEMM", "0")
    os.environ.setdefault("VLLM_ALLREDUCE_USE_FLASHINFER", "0")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
    os.environ["PATH"] = str(pathlib.Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    e51 = cargar("e51", E2 / "51_etiquetador_local.py")
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import StructuredOutputsParams
    u = json.load(open(SAL / "t10_umbrales.json"))["A"]
    t = pd.read_parquet(SAL / "t10_decisiones.parquet")
    m = t[(t["parte"] == "prueba") & (t["brazo"] == "nuevo") & (t["s_A"] >= u)]
    m = m.sample(min(n, len(m)), random_state=SEM).reset_index(drop=True)
    sis, sha = e51.sistema()
    llm = LLM(model=str(RAIZ / "modelos" / "qwen35-122b-a10b-fp8"), tensor_parallel_size=2, max_model_len=8192,
              gpu_memory_utilization=0.85, seed=20261005,
              compilation_config={"pass_config": {"fuse_allreduce_rms": False}}, gdn_prefill_backend="triton")
    sp = SamplingParams(temperature=0.0, max_tokens=300, seed=20261005,
                        structured_outputs=StructuredOutputsParams(json=e51.ESQUEMA))
    filas = [(k, a, b) for k, (x, y) in enumerate(zip(m["q"], m["titulo_A"])) for a, b in ((x, y), (y, x))]
    sal = llm.chat([[{"role": "system", "content": sis}, {"role": "user", "content": "A: {}\nB: {}".format(a, b)}]
                    for _, a, b in filas], sp, chat_template_kwargs={"enable_thinking": False})
    r = []
    for s in sal:
        try:
            r.append(json.loads(s.outputs[0].text)["mismo"])
        except (ValueError, KeyError, TypeError):
            r.append("")
    ab, ba = r[0::2], r[1::2]
    coh = [x == y and x in ("si", "no") for x, y in zip(ab, ba)]
    si = sum(1 for x, c in zip(ab, coh) if c and x == "si")
    linea = ("T-010 auditoria: {} «reconocidos» del brazo nuevo de A (umbral {}); Qwen3.5-122B coherente en {}; de esos, "
             "mismo cargo {:.0%} (equivalentes reales que el oro no registra)".format(len(m), u, sum(coh),
                                                                                    si / max(1, sum(coh))))
    (SAL / "t10_auditoria.txt").write_text(linea + "\n", encoding="utf-8")
    print(linea)


if __name__ == "__main__":
    {"medir": medir, "auditar": auditar}[sys.argv[1]]()
