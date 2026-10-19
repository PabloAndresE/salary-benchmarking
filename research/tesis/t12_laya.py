"""T-012: Laya (modelo de decision abierto) para el open set como UNA pregunta de opcion multiple (registro, T-012).

    .venv/bin/python research/tesis/t12_laya.py etapa0          laya-multilingual sin ajuste, CPU, prueba de T-010b

Pregunta: estado = el titulo nuevo; choice entre sus 10 candidatos de Qwen (sin candado) + «NINGUNO».
SALIDAS: salidas/t12_etapa0.txt, t12_etapa0.parquet (fuera del repo)
"""
import importlib.util
import pathlib
import sys
import time

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
SAL = AQUI / "salidas"
LAYA = pathlib.Path("/root/salary-benchmarking/modelos/laya")
SEM = 20261014
NINGUNO = "NINGUNO"
INSTRUCCION = ("¿Cuál de estos cargos es el mismo puesto de trabajo que el título del estado? Mismo puesto = "
               "mismas funciones y mismo nivel (asistente, analista, jefe, gerente). Si ninguno lo es, elige NINGUNO.")
UMBRALES = (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def candidatos_qwen(consultas):
    """Los 10 candidatos de Qwen (sin candado, sin el grupo propio) de cada consulta, en CPU."""
    t10 = cargar("t10", AQUI / "t10_open_set.py")
    e43 = cargar("e43", E2 / "43_perdida_vertex.py")
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    tit = np.array([str(c) for c in b["celdas"]], dtype=object)
    idx = {t: i for i, t in enumerate(tit)}
    grupo = np.asarray(b["grupo"]).astype(int)
    norm = lambda X: X / np.linalg.norm(X, axis=1, keepdims=True)  # noqa: E731
    Qd = norm(np.load(SAL / "t01_emb_qwen_desc.npy").astype(np.float32))
    Qc = norm(np.load(SAL / "t02_emb_qwen_consulta.npy").astype(np.float32))
    filas = np.array([idx[q] for q in consultas])
    S = Qc[filas] @ Qd.T
    out = {}
    for k, i in enumerate(filas):
        v = np.argpartition(-S[k], 400)[:400]
        v = v[np.argsort(-S[k][v])]
        c = t10.candidatos(v, S[k][v], {int(grupo[i])}, str(tit[i]), tit, grupo, e43.bloqueado)
        out[str(tit[i])] = [str(tit[j]) for j, _, _ in c]
    return out


def agente():
    sys.path.insert(0, str(LAYA))
    from rl_agent_api import RLAgent
    return RLAgent(str(LAYA / "multilingual"), device="cpu")


def preguntar(ag, titulo, cands):
    crit = {c: None for c in cands}
    crit[NINGUNO] = "ninguno de los anteriores es el mismo puesto"
    r = ag.system_one("Título del cargo: " + titulo,
                      {"q": {"type": "choice", "instructions": INSTRUCCION, "criteria": crit}})["answers"]["q"]
    return r["choice"], float(r["probabilities"][r["choice"]]), r["probabilities"]


def etapa0():
    t = pd.read_parquet(SAL / "t10b_decisiones.parquet")
    g = pd.read_parquet(SAL / "t10b_qwen.parquet")
    juicio = {(a, b): s for a, b, s in zip(g["q"], g["e"], g["si"])}
    pool = g.groupby("q").agg(alguno=("si", lambda s: bool((s == 1).any())),
                              todos_no=("si", lambda s: bool((s == 0).all())))
    t["clase"] = t["q"].map(lambda q: "con equivalente" if pool.loc[q, "alguno"] else
                            ("nueva" if pool.loc[q, "todos_no"] else "fuera"))
    t = t[t["clase"] != "fuera"].reset_index(drop=True)
    cand = candidatos_qwen(t["q"].tolist())
    ag = agente()
    t0 = time.time()
    res = [preguntar(ag, q, cand[q]) if cand[q] else (NINGUNO, 1.0, {}) for q in t["q"]]
    seg = (time.time() - t0) / len(t)
    t["e_L"] = [c if c != NINGUNO else "" for c, _, _ in res]
    t["s_L"] = [p if c != NINGUNO else -1.0 for c, p, _ in res]
    t["j_L"] = [juicio.get((q, e), np.nan) if e else np.nan for q, e in zip(t["q"], t["e_L"])]
    t["j_A"] = [juicio.get((q, e), np.nan) if e else np.nan for q, e in zip(t["q"], t["e_A"])]
    t.drop(columns=[c for c in t.columns if c.startswith(("e_B", "e_C", "s_B", "s_C", "e_D", "s_D"))]).to_parquet(
        SAL / "t12_etapa0.parquet", index=False)

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
    uL = max(UMBRALES, key=lambda u: bal(tc, aciertos(tc, "L", u)))
    con = (tp["clase"] == "con equivalente").to_numpy()
    okL, okA = aciertos(tp, "L", uL), aciertos(tp, "A", 0.90)
    recL = tp["s_L"].to_numpy() >= uL
    elige = (tp["e_L"] != "").to_numpy()
    out = ["T-012 etapa 0 · laya-multilingual SIN ajuste (CPU), consultas de T-010b",
           "consultas con clase: {:,} (calibra {:,}, prueba {:,}); {:.2f} s por consulta".format(len(t), len(tc), len(tp), seg),
           "elige NINGUNO: {:.1%} (con equivalente {:.1%}, nuevas {:.1%})".format(
               (~elige).mean(), (~elige[con]).mean(), (~elige[~con]).mean()),
           "umbral elegido en calibra: {}".format(uL),
           "elegidos sin verdad (fuera del pool juzgado): {}".format(int((elige & np.isnan(tp['j_L'].to_numpy())).sum())),
           "",
           "PRUEBA ({} con equivalente, {} nuevas)".format(int(con.sum()), int((~con).sum())),
           "  Laya sin ajuste   exactitud balanceada {:.4f}  con equivalente: reconoce bien {:.1%}  nuevas: desconocido {:.1%}".format(
               bal(tp, okL), np.nanmean(okL[con]), np.nanmean(okL[~con])),
           "  Qwen + cross-encoder reentrenado (T-010b)  {:.4f}  con equivalente: {:.1%}  nuevas: {:.1%}".format(
               bal(tp, okA), np.nanmean(okA[con]), np.nanmean(okA[~con])),
           "  Laya: cuando reconoce, su elegido es «sí» en {:.1%} de los juzgados".format(
               np.nanmean(tp.loc[recL & elige, "j_L"]))]
    (SAL / "t12_etapa0.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


# ----------------------------------------------------------------------------- etapa 1 (con ajuste)
N_ENTRENA = 2000


def _excluidos():
    e52 = cargar("e52", E2 / "52_validacion_glm.py")
    fuera = set(pd.read_parquet(SAL / "t10b_decisiones.parquet")["q"])
    for f, a, c in (("13e_pares_400.csv", "comun", "raro"), ("20_pares_400.csv", "comun", "raro"),
                    ("29_prueba2_pares.csv", "comun", "raro")):
        d = e52.leer(E2 / "salidas" / f)
        if "particion" in d:
            d = d[d["particion"].isin(["prueba", "prueba2"])]
        fuera |= set(d[a]) | set(d[c])
    v = e52.leer(E2 / "salidas" / "52_validacion_para_juzgar.csv")
    return fuera | set(v["a"]) | set(v["b"])


def armar1():
    """2.000 titulos de entrenamiento con sus 10 candidatos, y los candidatos de las consultas de T-010b; los pares sin
    juicio van a etiquetar."""
    import json
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    desc = pd.read_csv(E2 / "salidas" / "46_descripciones.csv", keep_default_na=False)
    con_desc = {t for t, r in zip(desc["titulo"].astype(str), desc["respuesta"])
                if json.loads(r).get("descripcion", "").strip()}
    fuera = _excluidos()
    pos = sorted(t for t in (str(c) for c in b["celdas"]) if t in con_desc and t not in fuera)
    ent = list(np.random.default_rng(SEM + 12).choice(pos, N_ENTRENA, replace=False))
    ev = sorted(set(pd.read_parquet(SAL / "t10b_decisiones.parquet")["q"]))
    cand = candidatos_qwen(ent + ev)
    pd.DataFrame({"q": ent, "cands": [cand[q] for q in ent]}).to_parquet(SAL / "t12_entrena.parquet", index=False)
    pd.DataFrame({"q": ev, "cands": [cand[q] for q in ev]}).to_parquet(SAL / "t12_eval.parquet", index=False)
    ya = {(a, c) for a, c in zip(*pd.read_parquet(SAL / "t10b_qwen.parquet")[["q", "e"]].T.to_numpy())}
    pares = sorted({(q, c) for q in ent + ev for c in cand[q]} - ya)
    pd.DataFrame(pares, columns=["q", "e"]).to_parquet(SAL / "t12_a_etiquetar.parquet", index=False)
    print("entrenamiento {:,} titulos; evaluacion {:,}; pares a etiquetar {:,}".format(len(ent), len(ev), len(pares)))


def etiquetar1():
    """Qwen3.5-122B (vLLM, 2 GPUs, sin razonamiento, rubrica v7) sobre `t12_a_etiquetar`, como `t10b etiquetar_qwen`."""
    t10b = cargar("t10b", AQUI / "t10b_open_set.py")
    t10b_pool = SAL / "t10b_pool.parquet"
    orig = t10b.SAL
    import shutil
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp(dir=SAL))
    shutil.copy(SAL / "t12_a_etiquetar.parquet", tmp / "t10b_pool.parquet")
    t10b.SAL = tmp
    t10b.etiquetar_qwen()
    t10b.SAL = orig
    shutil.move(str(tmp / "t10b_qwen.parquet"), str(SAL / "t12_etiquetas.parquet"))
    shutil.rmtree(tmp, ignore_errors=True)
    assert t10b_pool.exists()


def _juicios():
    g = pd.concat([pd.read_parquet(SAL / "t10b_qwen.parquet")[["q", "e", "si"]],
                   pd.read_parquet(SAL / "t12_etiquetas.parquet")[["q", "e", "si"]]])
    return {(a, b): s for a, b, s in zip(g["q"], g["e"], g["si"])}


def _registro(q, cands, juicio):
    """Pregunta de Laya con su objetivo, o None si la verdad no alcanza (algun incoherente y ningun «si»)."""
    opciones = list(cands) + [NINGUNO]
    j = [juicio.get((q, c), np.nan) for c in cands]
    si = [k for k, x in enumerate(j) if x == 1]
    if si:
        soft = [1.0 / len(si) if k in si else 0.0 for k in range(len(opciones))]
    elif cands and all(x == 0 for x in j):
        soft = [0.0] * len(cands) + [1.0]
    else:
        return None
    crit = {c: None for c in cands}
    crit[NINGUNO] = "ninguno de los anteriores es el mismo puesto"
    return {"state": "Título del cargo: " + q,
            "qs": [{"t": "choice", "ins": INSTRUCCION, "crit": crit, "soft": soft, "y": int(np.argmax(soft))}]}


REJILLA = [(2e-5, 3), (2e-5, 6), (5e-5, 3), (5e-5, 6)]     # enmienda: (tasa del codificador, epocas)


def entrenar1():
    """Enmienda de T-012: rejilla de 4 configuraciones; gana la de menor perdida propia en la validacion."""
    import json
    mejores = []
    for lr, ep in REJILLA:
        val, info = _entrenar_uno(lr, ep)
        mejores.append((val, lr, ep, info))
        print("CONFIG lr {} epocas {}: perdida de validacion {:.4f}".format(lr, ep, val), flush=True)
    val, lr, ep, info = min(mejores, key=lambda x: x[0])
    import shutil
    dst = SAL / "t12_laya_ajustado"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(SAL / "t12_tmp_{}_{}".format(lr, ep)), str(dst))
    for _, l_, e_, _ in mejores:
        shutil.rmtree(SAL / "t12_tmp_{}_{}".format(l_, e_), ignore_errors=True)
    linea = "T-012 entrenamiento (rejilla {}): elegida lr {} epocas {} (perdida de validacion {:.4f}); {}".format(
        "; ".join("lr {} ep {}: {:.4f}".format(l_, e_, v_) for v_, l_, e_, _ in mejores), lr, ep, val, info)
    (SAL / "t12_entrenamiento.txt").write_text(linea + "\n", encoding="utf-8")
    print(linea, flush=True)


def _entrenar_uno(lr_enc, epocas, lote=16):
    """Ajuste de laya-multilingual con la regla de puntuacion propia (log + esferica), opciones barajadas; temperatura
    en la validacion (15 %). Devuelve (perdida propia en validacion, resumen)."""
    import json
    import random
    import shutil
    import torch
    sys.path.insert(0, str(LAYA))
    from rl_common import collate_items, encode_record, proper_reward
    from safetensors.torch import save_file
    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    from rl_agent_api import RLAgent
    ag = RLAgent(str(LAYA / "multilingual"), device=dispositivo)
    m, tok, cfg = ag.model, ag.tok, ag.cfg
    juicio = _juicios()
    d = pd.read_parquet(SAL / "t12_entrena.parquet")
    recs = [r for r in (_registro(q, list(c), juicio) for q, c in zip(d["q"], d["cands"])) if r]
    rng = random.Random(SEM)
    rng.shuffle(recs)
    n_val = len(recs) * 15 // 100
    val, ent = recs[:n_val], recs[n_val:]
    print("preguntas: entrenamiento {:,}, validacion {:,}; NINGUNO como objetivo {:.0%}".format(
        len(ent), len(val), np.mean([r["qs"][0]["soft"][-1] == 1.0 for r in recs])), flush=True)
    enc_p = [p for n, p in m.named_parameters() if n.startswith("encoder.")]
    head_p = [p for n, p in m.named_parameters() if not n.startswith("encoder.")]
    opt = torch.optim.AdamW([{"params": enc_p, "lr": lr_enc}, {"params": head_p, "lr": 5 * lr_enc}], weight_decay=0.01)
    pasos = epocas * ((len(ent) + lote - 1) // lote)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / (0.1 * pasos)) * max(0.0, 1 - s / pasos))
    dt = torch.bfloat16 if dispositivo == "cuda" else torch.float32
    m.train()
    t0, paso = time.time(), 0
    for ep in range(epocas):
        rng.shuffle(ent)
        for i in range(0, len(ent), lote):
            items = [encode_record(r, tok, cfg, rng, True) for r in ent[i:i + lote]]
            b = collate_items(items, tok.pad_token_id)
            if b is None:
                continue
            with torch.autocast(device_type=dispositivo, dtype=dt, enabled=dispositivo == "cuda"):
                logits, _ = m(b["input_ids"].to(dispositivo), b["attention_mask"].to(dispositivo),
                              b["marker_pos"].to(dispositivo), b["marker_mask"].to(dispositivo), b["qtype"].to(dispositivo))
            mask = b["marker_mask"].to(dispositivo).float()
            p = torch.softmax(logits.float(), -1)
            perdida = -proper_reward(p, b["target"].to(dispositivo), b["qtype"].to(dispositivo), mask).mean()
            opt.zero_grad()
            perdida.backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
            sched.step()
            paso += 1
            if paso % 25 == 0:
                print("  epoca {} paso {}/{} perdida {:.4f} ({:.0f} s)".format(ep + 1, paso, pasos, float(perdida),
                                                                               time.time() - t0), flush=True)
    # temperatura en la validacion (NLL del objetivo)
    m.eval()
    items = [it for r in val for it in encode_record(r, tok, cfg, None, False)]
    with torch.no_grad():
        b = collate_items([items], tok.pad_token_id)
        L, _ = m(b["input_ids"].to(dispositivo), b["attention_mask"].to(dispositivo), b["marker_pos"].to(dispositivo),
                 b["marker_mask"].to(dispositivo), b["qtype"].to(dispositivo))
    L, tgt = L.float().cpu(), b["target"]
    nll = lambda T: float(-(tgt * torch.log_softmax(L / T, -1).clamp_min(-30)).sum(-1).mean())  # noqa: E731
    T = min(np.arange(0.5, 3.01, 0.05), key=nll)
    acc = float((L.argmax(-1) == tgt.argmax(-1)).float().mean())
    mask_v = b["marker_mask"].float()
    perdida_val = float(-proper_reward(torch.softmax(L / T, -1), tgt, b["qtype"], mask_v).mean())
    dst = SAL / "t12_tmp_{}_{}".format(lr_enc, epocas)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(LAYA / "multilingual" / "tokenizer", dst / "tokenizer")
    shutil.copytree(LAYA / "multilingual" / "encoder", dst / "encoder")
    save_file({k: v.detach().cpu().contiguous() for k, v in m.state_dict().items()}, str(dst / "model.safetensors"))
    cfg = dict(cfg, temperature=[float(T)] * 3)
    (dst / "rl_agent_config.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    return perdida_val, "{:,} preguntas, {:.0f} min en {}; validacion: acierto {:.1%}, T {:.2f}".format(
        len(ent), (time.time() - t0) / 60, dispositivo, acc, T)


def medir1():
    """Laya ajustado frente al sistema propuesto de T-010b, en sus consultas de prueba (umbral de Laya en calibra)."""
    sys.path.insert(0, str(LAYA))
    from rl_agent_api import RLAgent
    ag = RLAgent(str(SAL / "t12_laya_ajustado"), device="cpu")
    juicio = _juicios()
    t = pd.read_parquet(SAL / "t10b_decisiones.parquet")
    g = pd.read_parquet(SAL / "t10b_qwen.parquet")
    pool = g.groupby("q").agg(alguno=("si", lambda s: bool((s == 1).any())),
                              todos_no=("si", lambda s: bool((s == 0).all())))
    t["clase"] = t["q"].map(lambda q: "con equivalente" if pool.loc[q, "alguno"] else
                            ("nueva" if pool.loc[q, "todos_no"] else "fuera"))
    t = t[t["clase"] != "fuera"].reset_index(drop=True)
    ev = pd.read_parquet(SAL / "t12_eval.parquet")
    cand = dict(zip(ev["q"], (list(c) for c in ev["cands"])))
    t0 = time.time()
    res = [preguntar(ag, q, cand[q]) if cand.get(q) else (NINGUNO, 1.0, {}) for q in t["q"]]
    seg = (time.time() - t0) / len(t)
    t["e_L"] = [c if c != NINGUNO else "" for c, _, _ in res]
    t["s_L"] = [p if c != NINGUNO else -1.0 for c, p, _ in res]
    t["j_L"] = [juicio.get((q, e), np.nan) if e else np.nan for q, e in zip(t["q"], t["e_L"])]
    t["j_A"] = [juicio.get((q, e), np.nan) if e else np.nan for q, e in zip(t["q"], t["e_A"])]

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
    uL = max(UMBRALES, key=lambda u: bal(tc, aciertos(tc, "L", u)))
    okL, okA = aciertos(tp, "L", uL), aciertos(tp, "A", 0.90)
    con = (tp["clase"] == "con equivalente").to_numpy()
    rng = np.random.default_rng(SEM + 3)
    bs = []
    for _ in range(2000):
        ii = rng.integers(0, len(tp), len(tp))
        s_ = tp.iloc[ii].reset_index(drop=True)
        bs.append(bal(s_, okL[ii]) - bal(s_, okA[ii]))
    lo, hi = np.nanpercentile(bs, [2.5, 97.5])
    d0 = bal(tp, okL) - bal(tp, okA)
    out = ["T-012 etapa 1 · Laya AJUSTADO frente al sistema propuesto de T-010b",
           (SAL / "t12_entrenamiento.txt").read_text(encoding="utf-8").strip(),
           "umbral de Laya elegido en calibra: {}; {:.2f} s por consulta (CPU)".format(uL, seg),
           "PRUEBA ({} con equivalente, {} nuevas)".format(int(con.sum()), int((~con).sum())),
           "  Laya ajustado   exactitud balanceada {:.4f}  con equivalente: reconoce bien {:.1%}  nuevas: desconocido {:.1%}  "
           "(sin verdad {})".format(bal(tp, okL), np.nanmean(okL[con]), np.nanmean(okL[~con]), int(np.isnan(okL).sum())),
           "  Qwen + cross-encoder reentrenado  {:.4f}  con equivalente: {:.1%}  nuevas: {:.1%}".format(
               bal(tp, okA), np.nanmean(okA[con]), np.nanmean(okA[~con])),
           "Laya - propuesto: {:+.4f} [{:+.4f}, {:+.4f}] -> {}".format(
               d0, lo, hi, "LAYA MEJOR" if lo > 0 else ("LAYA PEOR" if hi < 0 else "no se distingue"))]
    (SAL / "t12_etapa1.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    {"etapa0": etapa0, "armar1": armar1, "etiquetar1": etiquetar1, "entrenar1": entrenar1, "medir1": medir1}[sys.argv[1]]()
