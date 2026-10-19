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
sys.path.insert(0, str(LAYA))      # rl_common / rl_agent_api de Laya (codigo revisado, sin red)
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


REJILLA = [("completo", 2e-5, 3), ("completo", 2e-5, 6), ("completo", 5e-5, 3), ("completo", 5e-5, 6),
           ("cabeza", 6e-4, 6)]     # enmiendas 1 y 2: (variante, tasa, epocas)


def entrenar1():
    """Enmiendas de T-012: rejilla de 5 variantes; gana la de menor perdida propia en la validacion."""
    import shutil
    res = []
    for var, lr, ep in REJILLA:
        val, info = (_entrenar_completo if var == "completo" else _entrenar_cabeza)(lr, ep)
        res.append((val, var, lr, ep, info))
        print("VARIANTE {} lr {} epocas {}: perdida de validacion {:.4f} | {}".format(var, lr, ep, val, info), flush=True)
    val, var, lr, ep, info = min(res, key=lambda x: x[0])
    dst = SAL / "t12_laya_ajustado"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(SAL / "t12_tmp_{}_{}_{}".format(var, lr, ep)), str(dst))
    for _, v_, l_, e_, _ in res:
        shutil.rmtree(SAL / "t12_tmp_{}_{}_{}".format(v_, l_, e_), ignore_errors=True)
    linea = "T-012 entrenamiento: elegida {} lr {} epocas {} (perdida de validacion {:.4f}; {}). Rejilla: {}".format(
        var, lr, ep, val, info, "; ".join("{} {} {}: {:.4f}".format(v_, l_, e_, x_) for x_, v_, l_, e_, _ in res))
    (SAL / "t12_entrenamiento.txt").write_text(linea + "\n", encoding="utf-8")
    print(linea, flush=True)


def _preparar():
    import random
    import torch
    sys.path.insert(0, str(LAYA))
    from rl_agent_api import RLAgent
    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    ag = RLAgent(str(LAYA / "multilingual"), device=dispositivo)
    juicio = _juicios()
    d = pd.read_parquet(SAL / "t12_entrena.parquet")
    recs = [r for r in (_registro(q, list(c), juicio) for q, c in zip(d["q"], d["cands"])) if r]
    rng = random.Random(SEM)
    rng.shuffle(recs)
    n_val = len(recs) * 15 // 100
    print("preguntas: entrenamiento {:,}, validacion {:,}; NINGUNO como objetivo {:.0%}".format(
        len(recs) - n_val, n_val, np.mean([r["qs"][0]["soft"][-1] == 1.0 for r in recs])), flush=True)
    return ag.model, ag.tok, ag.cfg, recs[n_val:], recs[:n_val], dispositivo, rng


def _calibrar_y_guardar(m, cfg, L, tgt, mask, qtype, dst, extra):
    """Temperatura por numero de opciones (cubetas de Laya, >= 20 preguntas; si no, la general); perdida propia en
    validacion; guarda el modelo como un checkpoint de Laya."""
    import json
    import shutil
    import torch
    from rl_common import proper_reward, temp_bucket
    from safetensors.torch import save_file
    rejilla = np.arange(0.30, 3.001, 0.05)
    nll = lambda Lx, tx, T: float(-(tx * torch.log_softmax(Lx / T, -1).clamp_min(-30)).sum(-1).mean())  # noqa: E731
    Tg = float(min(rejilla, key=lambda T: nll(L, tgt, T)))
    k = mask.sum(-1).tolist()
    cub = [temp_bucket(int(q), int(kk)) for q, kk in zip(qtype.tolist(), k)]
    por = {}
    for c in sorted(set(cub)):
        sel = torch.tensor([x == c for x in cub])
        if int(sel.sum()) >= 20:
            por[c] = float(min(rejilla, key=lambda T: nll(L[sel], tgt[sel], T)))
    Ts = torch.tensor([por.get(c, Tg) for c in cub])[:, None]
    perdida = float(-proper_reward(torch.softmax(L / Ts, -1), tgt, qtype, mask.float()).mean())
    acc = float((tgt.gather(1, L.argmax(-1, keepdim=True)) > 0).float().mean())     # cualquier opcion correcta
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(LAYA / "multilingual" / "tokenizer", dst / "tokenizer")
    shutil.copytree(LAYA / "multilingual" / "encoder", dst / "encoder")
    save_file({kk: v.detach().cpu().contiguous() for kk, v in m.state_dict().items()}, str(dst / "model.safetensors"))
    (dst / "rl_agent_config.json").write_text(json.dumps(dict(cfg, temperature=[Tg] * 3, temperature_by_options=por),
                                                         indent=1), encoding="utf-8")
    return perdida, "{}; validacion: acierto {:.1%}, T general {:.2f}, por opciones {}".format(
        extra, acc, Tg, {c: round(t, 2) for c, t in por.items()})


def _entrenar_completo(lr_enc, epocas, lote=16):
    """Ajuste de TODO laya-multilingual (codificador + cabeza; cabeza a 5x la tasa), regla de puntuacion propia,
    opciones barajadas."""
    import torch
    from rl_common import collate_items, encode_record, proper_reward
    m, tok, cfg, ent, val, dispositivo, rng = _preparar()
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
            b = collate_items([encode_record(r, tok, cfg, rng, True) for r in ent[i:i + lote]], tok.pad_token_id)
            if b is None:
                continue
            with torch.autocast(device_type=dispositivo, dtype=dt, enabled=dispositivo == "cuda"):
                logits, _ = m(b["input_ids"].to(dispositivo), b["attention_mask"].to(dispositivo),
                              b["marker_pos"].to(dispositivo), b["marker_mask"].to(dispositivo), b["qtype"].to(dispositivo))
            perdida = -proper_reward(torch.softmax(logits.float(), -1), b["target"].to(dispositivo),
                                     b["qtype"].to(dispositivo), b["marker_mask"].to(dispositivo).float()).mean()
            opt.zero_grad()
            perdida.backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
            sched.step()
            paso += 1
            if paso % 50 == 0:
                print("  completo epoca {} paso {}/{} perdida {:.4f} ({:.0f} s)".format(
                    ep + 1, paso, pasos, float(perdida), time.time() - t0), flush=True)
    m.eval()
    items = [it for r in val for it in encode_record(r, tok, cfg, None, False)]
    Ls = []
    with torch.no_grad():
        for i in range(0, len(items), 64):
            b = collate_items([items[i:i + 64]], tok.pad_token_id)
            L, _ = m(b["input_ids"].to(dispositivo), b["attention_mask"].to(dispositivo),
                     b["marker_pos"].to(dispositivo), b["marker_mask"].to(dispositivo), b["qtype"].to(dispositivo))
            Ls.append((L.float().cpu(), b["target"], b["marker_mask"], b["qtype"]))
    L, tgt, mask, qt = _juntar(Ls)
    return _calibrar_y_guardar(m, cfg, L, tgt, mask, qt, SAL / "t12_tmp_completo_{}_{}".format(lr_enc, epocas),
                               "{:,} preguntas, {:.0f} min en {}".format(len(ent), (time.time() - t0) / 60, dispositivo))


def _juntar(partes):
    """Une lotes de logits / objetivos / mascaras con distinto numero de opciones (relleno a la derecha)."""
    import torch
    kmax = max(p[0].shape[1] for p in partes)
    pad = lambda x, v: torch.nn.functional.pad(x, (0, kmax - x.shape[1]), value=v)  # noqa: E731
    return (torch.cat([pad(p[0], -1e4) for p in partes]), torch.cat([pad(p[1], 0.0) for p in partes]),
            torch.cat([pad(p[2], False) for p in partes]), torch.cat([p[3] for p in partes]))


def _cabeza(m, h, att, mpos, mmask, qtype):
    """El forward de DecisionModel desde la salida del codificador (sin la cabeza de escalamiento)."""
    import torch
    h = h + m.type_emb(qtype)[:, None, :]
    pad = ~att.bool()
    for layer in m.head.layers:
        h = layer(h, src_key_padding_mask=pad)
    idx = mpos.clamp(min=0)[:, :, None].expand(-1, -1, h.size(-1))
    return m.scorer(torch.gather(h, 1, idx)).squeeze(-1).float().masked_fill(~mmask, -1e4)


def _entrenar_cabeza(lr, epocas, lote=32):
    """Enmienda 2 (layaMOE): codificador CONGELADO, salidas cacheadas (2 ordenes de opciones por pregunta de
    entrenamiento), solo la cabeza; calentamiento 6 %, mejor epoca en validacion. Antes, prueba de sobreajuste."""
    import copy
    import torch
    from rl_common import collate_items, encode_record, proper_reward
    m, tok, cfg, ent, val, dispositivo, rng = _preparar()
    for n, p in m.named_parameters():
        p.requires_grad_(not n.startswith("encoder."))
    dt = torch.bfloat16 if dispositivo == "cuda" else torch.float32
    t0 = time.time()

    def cachear(items):
        out = []
        m.eval()
        with torch.no_grad():
            for i in range(0, len(items), 32):
                sel = items[i:i + 32]
                b = collate_items([sel], tok.pad_token_id)
                with torch.autocast(device_type=dispositivo, dtype=dt, enabled=dispositivo == "cuda"):
                    h = m.encoder(input_ids=b["input_ids"].to(dispositivo),
                                  attention_mask=b["attention_mask"].to(dispositivo)).last_hidden_state
                for r, it in enumerate(sel):
                    n = len(it["ids"])
                    out.append({"h": h[r, :n].to(torch.float16).cpu(), "markers": it["markers"], "target": it["target"],
                                "qtype": it["qtype"]})
        return out

    def lote_de(cs):
        n, Lm, km = len(cs), max(c["h"].shape[0] for c in cs), max(len(c["markers"]) for c in cs)
        d = cs[0]["h"].shape[1]
        h = torch.zeros(n, Lm, d)
        att = torch.zeros(n, Lm, dtype=torch.long)
        mpos = torch.zeros(n, km, dtype=torch.long)
        mmask = torch.zeros(n, km, dtype=torch.bool)
        tgt = torch.zeros(n, km)
        for i, c in enumerate(cs):
            L_, k_ = c["h"].shape[0], len(c["markers"])
            h[i, :L_], att[i, :L_] = c["h"].float(), 1
            mpos[i, :k_], mmask[i, :k_] = torch.tensor(c["markers"]), True
            tgt[i, :k_] = torch.tensor(c["target"])
        q = torch.tensor([c["qtype"] for c in cs])
        return [x.to(dispositivo) for x in (h, att, mpos, mmask, tgt, q)]

    def perdida_de(cs, entrenar):
        h, att, mpos, mmask, tgt, q = lote_de(cs)
        logits = _cabeza(m, h, att, mpos, mmask, q)
        return -proper_reward(torch.softmax(logits, -1), tgt, q, mmask.float()).mean(), logits, tgt, mmask, q

    c_ent = cachear([it for r in ent for _ in range(2) for it in encode_record(r, tok, cfg, rng, True)])
    c_val = cachear([it for r in val for it in encode_record(r, tok, cfg, None, False)])
    print("  cabeza: salidas del codificador cacheadas ({:,} + {:,}) en {:.0f} s".format(
        len(c_ent), len(c_val), time.time() - t0), flush=True)
    params = [p for p in m.parameters() if p.requires_grad]
    inicial = copy.deepcopy({k: v for k, v in m.state_dict().items() if not k.startswith("encoder.")})
    # prueba de sobreajuste: 64 preguntas, tasa 3e-4, 40 pasos
    m.train()
    o = torch.optim.AdamW(params, lr=3e-4, weight_decay=0.01)
    muestra = c_ent[:64]
    for _ in range(40):
        perdida, logits, tgt, _, _ = perdida_de(muestra, True)
        o.zero_grad()
        perdida.backward()
        o.step()
    sobre = float((tgt.gather(1, logits.argmax(-1, keepdim=True)) > 0).float().mean())   # cualquier opcion correcta
    print("  prueba de sobreajuste (64 preguntas, 40 pasos): acierto {:.0%}".format(sobre), flush=True)
    m.load_state_dict(inicial, strict=False)
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    pasos = epocas * ((len(c_ent) + lote - 1) // lote)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / (0.06 * pasos)) * max(0.0, 1 - s / pasos))
    mejor, mejor_ep, estado = float("inf"), 0, None
    r_ = np.random.default_rng(SEM)
    for ep in range(epocas):
        m.train()
        orden = r_.permutation(len(c_ent))
        for i in range(0, len(orden), lote):
            perdida, *_ = perdida_de([c_ent[j] for j in orden[i:i + lote]], True)
            opt.zero_grad()
            perdida.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            sched.step()
        m.eval()
        with torch.no_grad():
            v = float(np.mean([float(perdida_de(c_val[i:i + 64], False)[0]) for i in range(0, len(c_val), 64)]))
        print("  cabeza epoca {}: perdida de validacion {:.4f} ({:.0f} s)".format(ep + 1, v, time.time() - t0), flush=True)
        if v < mejor:
            mejor, mejor_ep = v, ep + 1
            estado = copy.deepcopy({k: v_ for k, v_ in m.state_dict().items() if not k.startswith("encoder.")})
    m.load_state_dict(estado, strict=False)
    m.eval()
    with torch.no_grad():
        partes = []
        for i in range(0, len(c_val), 64):
            _, logits, tgt, mmask, q = perdida_de(c_val[i:i + 64], False)
            partes.append((logits.cpu(), tgt.cpu(), mmask.cpu(), q.cpu()))
    L, tgt, mask, qt = _juntar(partes)
    return _calibrar_y_guardar(m, cfg, L, tgt, mask, qt, SAL / "t12_tmp_cabeza_{}_{}".format(lr, epocas),
                               "{:,} preguntas x2 ordenes, mejor epoca {}, sobreajuste {:.0%}, {:.0f} min en {}".format(
                                   len(ent), mejor_ep, sobre, (time.time() - t0) / 60, dispositivo))


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
