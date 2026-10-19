"""T-013: Laya como experto de NIVEL jerarquico (pregunta `score`), frente al clasificador actual (registro, T-013).

    .venv/bin/python research/tesis/t13_laya_nivel.py

Particion de `t03_diagnostico_nivel` (por grupo, semilla 3, 20 % a prueba); validacion = 10 % de los grupos de
entrenamiento. Variantes: codificador congelado + cabeza (siempre) y ajuste completo (solo con GPU >= 12 GB).
SALIDAS: salidas/t13_nivel.txt, t13_laya_nivel/ (el modelo elegido, fuera del repo)
"""
import copy
import importlib.util
import json
import pathlib
import shutil
import sys
import time

import numpy as np
import pandas as pd
import torch

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
spec = importlib.util.spec_from_file_location("t12", AQUI / "t12_laya.py")
t12 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t12)
from rl_common import collate_items, encode_record, proper_reward  # noqa: E402  (Laya, via t12)

NIVELES = ["operativo o asistente", "técnico o analista", "supervisión o coordinación", "jefatura",
           "gerencia o dirección"]
PREGUNTA = "¿Qué nivel jerárquico tiene este cargo?"


def normal(X):
    X = np.asarray(X, np.float32)
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def particion():
    from benchmarking.config.settings import cargar_settings
    from benchmarking.producto.base_referencia import BaseReferencia
    b = BaseReferencia.cargar(RAIZ / "demo" / "base_v31.npz", cargar_settings().get_sbu)
    b.nivel_por_grupo()
    niv, grupo = np.asarray(b.nivel, float), np.asarray(b.grupo)
    ok = np.isfinite(niv)
    rng = np.random.default_rng(3)                       # la misma de t03_diagnostico_nivel
    gs = np.unique(grupo[ok])
    test_g = set(rng.choice(gs, len(gs) // 5, replace=False))
    te = ok & np.isin(grupo, list(test_g))
    tr = ok & ~te
    gtr = np.unique(grupo[tr])
    val_g = set(np.random.default_rng(31).choice(gtr, len(gtr) // 10, replace=False))
    va = tr & np.isin(grupo, list(val_g))
    return b, niv, grupo, tr & ~va, va, te


def registro(titulo, nivel):
    return {"state": "Título del cargo: " + titulo,
            "qs": [{"t": "score", "ins": PREGUNTA, "crit": NIVELES, "y": int(nivel) - 1}]}


def logits_de(m, tok, cfg, items, dispositivo, cabeza_sola=None):
    """Logits de Laya para items ya codificados (5 opciones, todas)."""
    out = []
    m.eval()
    with torch.no_grad():
        for i in range(0, len(items), 256):
            b = collate_items([items[i:i + 256]], tok.pad_token_id)
            with torch.autocast(device_type=dispositivo, dtype=torch.bfloat16, enabled=dispositivo == "cuda"):
                L, _ = m(b["input_ids"].to(dispositivo), b["attention_mask"].to(dispositivo),
                         b["marker_pos"].to(dispositivo), b["marker_mask"].to(dispositivo), b["qtype"].to(dispositivo))
            out.append(L.float().cpu())
    return torch.cat(out)


def perdida_val(L, y, T=1.0):
    tgt = torch.nn.functional.one_hot(torch.tensor(y), 5).float()
    q = torch.full((len(y),), 1, dtype=torch.long)      # tipo `score`
    return float(-proper_reward(torch.softmax(L / T, -1), tgt, q, torch.ones_like(tgt)).mean())


def entrenar_cabeza(m, tok, cfg, ent, y_ent, dispositivo, lr=6e-4, epocas=6, lote=32, val=None):
    """layaMOE: codificador congelado (salidas cacheadas), solo la cabeza; calentamiento 6 %, mejor epoca."""
    for n, p in m.named_parameters():
        p.requires_grad_(not n.startswith("encoder."))
    items = [encode_record(registro(t, y + 1), tok, cfg, None, False)[0] for t, y in zip(ent, y_ent)]
    t0 = time.time()
    H = []
    m.eval()
    with torch.no_grad():
        for i in range(0, len(items), 256):
            b = collate_items([items[i:i + 256]], tok.pad_token_id)
            with torch.autocast(device_type=dispositivo, dtype=torch.bfloat16, enabled=dispositivo == "cuda"):
                h = m.encoder(input_ids=b["input_ids"].to(dispositivo),
                              attention_mask=b["attention_mask"].to(dispositivo)).last_hidden_state
            for r, it in enumerate(items[i:i + 256]):
                H.append(h[r, :len(it["ids"])].to(torch.float16).cpu())
    print("  cabeza: {:,} salidas cacheadas en {:.0f} s".format(len(H), time.time() - t0), flush=True)
    params = [p for p in m.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    pasos = epocas * ((len(H) + lote - 1) // lote)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / (0.06 * pasos)) * max(0.0, 1 - s / pasos))
    y_t = torch.tensor(y_ent)
    mejor, estado, mejor_ep = float("inf"), None, 0
    rng = np.random.default_rng(13)
    for ep in range(epocas):
        m.train()
        for idx in np.array_split(rng.permutation(len(H)), max(1, len(H) // lote)):
            cs = [H[j] for j in idx]
            Lm = max(c.shape[0] for c in cs)
            h = torch.zeros(len(cs), Lm, cs[0].shape[1])
            att = torch.zeros(len(cs), Lm, dtype=torch.long)
            for k, c in enumerate(cs):
                h[k, :c.shape[0]], att[k, :c.shape[0]] = c.float(), 1
            mpos = torch.tensor([items[j]["markers"] for j in idx])
            mmask = torch.ones_like(mpos, dtype=torch.bool)
            q = torch.ones(len(idx), dtype=torch.long)
            L = t12._cabeza(m, h.to(dispositivo), att.to(dispositivo), mpos.to(dispositivo), mmask.to(dispositivo),
                            q.to(dispositivo))
            tgt = torch.nn.functional.one_hot(y_t[idx], 5).float().to(dispositivo)
            perdida = -proper_reward(torch.softmax(L, -1), tgt, q.to(dispositivo), mmask.float()).mean()
            opt.zero_grad()
            perdida.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            sched.step()
        v = perdida_val(logits_de(m, tok, cfg, val[0], dispositivo), val[1])
        print("  cabeza epoca {}: perdida de validacion {:.4f} ({:.0f} s)".format(ep + 1, v, time.time() - t0), flush=True)
        if v < mejor:
            mejor, mejor_ep = v, ep + 1
            estado = copy.deepcopy({k: x for k, x in m.state_dict().items() if not k.startswith("encoder.")})
    m.load_state_dict(estado, strict=False)
    return "cabeza 6e-4, mejor epoca {} de {}, {:.0f} min".format(mejor_ep, epocas, (time.time() - t0) / 60)


def entrenar_completo(m, tok, cfg, ent, y_ent, dispositivo, lr=3e-5, epocas=2, lote=32, val=None):
    for p in m.parameters():
        p.requires_grad_(True)
    items = [encode_record(registro(t, y + 1), tok, cfg, None, False)[0] for t, y in zip(ent, y_ent)]
    enc_p = [p for n, p in m.named_parameters() if n.startswith("encoder.")]
    head_p = [p for n, p in m.named_parameters() if not n.startswith("encoder.")]
    opt = torch.optim.AdamW([{"params": enc_p, "lr": lr}, {"params": head_p, "lr": 5 * lr}], weight_decay=0.01)
    pasos = epocas * ((len(items) + lote - 1) // lote)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / (0.06 * pasos)) * max(0.0, 1 - s / pasos))
    t0, rng = time.time(), np.random.default_rng(17)
    mejor, estado, mejor_ep = float("inf"), None, 0
    for ep in range(epocas):
        m.train()
        for idx in np.array_split(rng.permutation(len(items)), max(1, len(items) // lote)):
            b = collate_items([[items[j] for j in idx]], tok.pad_token_id)
            with torch.autocast(device_type=dispositivo, dtype=torch.bfloat16, enabled=dispositivo == "cuda"):
                L, _ = m(b["input_ids"].to(dispositivo), b["attention_mask"].to(dispositivo),
                         b["marker_pos"].to(dispositivo), b["marker_mask"].to(dispositivo), b["qtype"].to(dispositivo))
            tgt = torch.nn.functional.one_hot(torch.tensor([y_ent[j] for j in idx]), 5).float().to(dispositivo)
            perdida = -proper_reward(torch.softmax(L.float(), -1), tgt, b["qtype"].to(dispositivo),
                                     b["marker_mask"].to(dispositivo).float()).mean()
            opt.zero_grad()
            perdida.backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
            sched.step()
        v = perdida_val(logits_de(m, tok, cfg, val[0], dispositivo), val[1])
        print("  completo epoca {}: perdida de validacion {:.4f} ({:.0f} s)".format(ep + 1, v, time.time() - t0), flush=True)
        if v < mejor:
            mejor, mejor_ep = v, ep + 1
            estado = copy.deepcopy(m.state_dict())
    m.load_state_dict(estado)
    return "completo 3e-5, mejor epoca {} de {}, {:.0f} min".format(mejor_ep, epocas, (time.time() - t0) / 60)


def main():
    from sklearn.linear_model import LogisticRegression
    from rl_agent_api import RLAgent
    b, niv, grupo, tr, va, te = particion()
    tit = np.array([str(c) for c in b.celdas], dtype=object)
    y = np.where(np.isfinite(niv), niv, 1).astype(int) - 1
    print("entrenamiento {:,}, validacion {:,}, prueba {:,}".format(int(tr.sum()), int(va.sum()), int(te.sum())), flush=True)
    # lineas base: el clasificador actual (regresion logistica) sobre Qwen consulta y sobre Vertex, misma particion
    base = {}
    for nom, X in (("Qwen consulta", normal(np.load(SAL / "t02_emb_qwen_consulta.npy"))), ("Vertex", normal(b.Z))):
        clf = LogisticRegression(max_iter=2000, C=1.0).fit(X[tr | va], y[tr | va])
        base[nom] = clf.predict(X[te])
    libre = 0
    if torch.cuda.is_available():
        libre = torch.cuda.mem_get_info()[0] / 2 ** 30
    dispositivo = "cuda" if libre >= 12 else "cpu"
    variantes = [("cabeza", entrenar_cabeza)] + ([("completo", entrenar_completo)] if dispositivo == "cuda" else [])
    res = []
    for nom, f in variantes:
        ag = RLAgent(str(t12.LAYA / "multilingual"), device=dispositivo)
        m, tok, cfg = ag.model, ag.tok, ag.cfg
        val_items = [encode_record(registro(t, k + 1), tok, cfg, None, False)[0] for t, k in zip(tit[va], y[va])]
        info = f(m, tok, cfg, list(tit[tr]), list(y[tr]), dispositivo, val=(val_items, list(y[va])))
        Lv = logits_de(m, tok, cfg, val_items, dispositivo)
        T = float(min(np.arange(0.3, 3.001, 0.05), key=lambda T: perdida_val(Lv, list(y[va]), T)))
        pv = perdida_val(Lv, list(y[va]), T)
        te_items = [encode_record(registro(t, k + 1), tok, cfg, None, False)[0] for t, k in zip(tit[te], y[te])]
        t0 = time.time()
        Lt = logits_de(m, tok, cfg, te_items, dispositivo)
        seg = (time.time() - t0) / len(te_items)
        res.append((pv, nom, info, T, Lt.argmax(-1).numpy(), seg, m, cfg))
        print("VARIANTE {}: perdida de validacion {:.4f} (T {:.2f}) | {}".format(nom, pv, T, info), flush=True)
    pv, nom, info, T, pred, seg, m, cfg = min(res, key=lambda r: r[0])
    dst = SAL / "t13_laya_nivel"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(t12.LAYA / "multilingual" / "tokenizer", dst / "tokenizer")
    shutil.copytree(t12.LAYA / "multilingual" / "encoder", dst / "encoder")
    from safetensors.torch import save_file
    save_file({k: v.detach().cpu().contiguous() for k, v in m.state_dict().items()}, str(dst / "model.safetensors"))
    (dst / "rl_agent_config.json").write_text(json.dumps(dict(cfg, temperature=[T] * 3), indent=1), encoding="utf-8")
    yt, gt = y[te], grupo[te]
    ok = {"Laya": pred == yt, **{k: v == yt for k, v in base.items()}}
    esc = {"Laya": np.abs(pred - yt), **{k: np.abs(v - yt) for k, v in base.items()}}
    gru = np.unique(gt)
    pos = {g: np.flatnonzero(gt == g) for g in gru}
    rng = np.random.default_rng(20261019)
    out = ["T-013 · Laya como experto de nivel (score), particion de t03 (prueba {:,} titulos, {:,} grupos)".format(
        int(te.sum()), len(gru)),
           "variante elegida: {} | {}; T {:.2f}; {:.1f} ms por titulo ({})".format(nom, info, T, 1000 * seg, dispositivo),
           "rejilla: " + "; ".join("{} {:.4f}".format(r[1], r[0]) for r in res), ""]
    for k in ("Laya", "Qwen consulta", "Vertex"):
        out.append("  {:<14} exactitud {:.1%}   error medio {:.3f} escalones   errores de 2+ escalones {:.2%}".format(
            k, ok[k].mean(), esc[k].mean(), (esc[k] >= 2).mean()))
    for ref in ("Qwen consulta", "Vertex"):
        d = ok["Laya"].astype(float) - ok[ref].astype(float)
        bs = []
        for _ in range(2000):
            ii = np.concatenate([pos[g] for g in rng.choice(gru, len(gru))])
            bs.append(d[ii].mean())
        lo, hi = np.percentile(bs, [2.5, 97.5])
        out.append("Laya - {}: {:+.2%} [{:+.2%}, {:+.2%}] -> {}".format(
            ref, d.mean(), lo, hi, "LAYA MEJOR" if lo > 0 else ("LAYA PEOR" if hi < 0 else "no se distingue")))
    (SAL / "t13_nivel.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
