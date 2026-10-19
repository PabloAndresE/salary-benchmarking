"""T-014: el nivel de Laya (ajuste completo de T-013) para los titulos preguntados, entrenado SOLO con las celdas de la
base de entrenamiento de la medicion (registro, T-014). Lo usa `54_pinball.py --variante qwen_laya`."""
import importlib.util
import pathlib

import numpy as np
import torch

AQUI = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("t13", AQUI / "t13_laya_nivel.py")
t13 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t13)
from rl_common import encode_record  # noqa: E402  (Laya, via t12/t13)


def niveles_laya(celdas, nivel, grupo, consultas, placebo=False, semilla=20261019):
    """{titulo preguntado: (nivel 1-5, P calibrada)}. Validacion = 10 % de los grupos de la base (epoca y T)."""
    from rl_agent_api import RLAgent
    celdas, nivel, grupo = np.asarray(celdas, dtype=object), np.asarray(nivel, float), np.asarray(grupo)
    ok = np.isfinite(nivel) & (nivel >= 1) & (nivel <= 5)
    gs = np.unique(grupo[ok])
    val_g = set(np.random.default_rng(semilla).choice(gs, len(gs) // 10, replace=False).tolist())
    va = ok & np.isin(grupo, list(val_g))
    tr = ok & ~va
    y = np.where(ok, nivel, 1).astype(int) - 1
    dispositivo = "cuda" if torch.cuda.is_available() and torch.cuda.mem_get_info()[0] / 2 ** 30 >= 4.5 else "cpu"
    ag = RLAgent(str(t13.t12.LAYA / "multilingual"), device=dispositivo)
    m, tok, cfg = ag.model, ag.tok, ag.cfg
    val_items = [encode_record(t13.registro(str(t), k + 1), tok, cfg, None, False)[0] for t, k in zip(celdas[va], y[va])]
    info = t13.entrenar_completo(m, tok, cfg, [str(t) for t in celdas[tr]], list(y[tr]), dispositivo,
                                 val=(val_items, list(y[va])))
    Lv = t13.logits_de(m, tok, cfg, val_items, dispositivo)
    T = float(min(np.arange(0.3, 3.001, 0.05), key=lambda T: t13.perdida_val(Lv, list(y[va]), T)))
    acc_v = float((Lv.argmax(-1).numpy() == y[va]).mean())
    consultas = sorted({str(c) for c in consultas})
    items = [encode_record(t13.registro(c, 1), tok, cfg, None, False)[0] for c in consultas]
    P = torch.softmax(t13.logits_de(m, tok, cfg, items, dispositivo) / T, -1).numpy()
    niv, p = P.argmax(1) + 1, P.max(1)
    if placebo:                                     # placebo: los niveles de Laya permutados entre los titulos
        perm = np.random.default_rng(semilla + 1).permutation(len(consultas))
        niv, p = niv[perm], p[perm]
    del m, ag
    if dispositivo == "cuda":
        torch.cuda.empty_cache()
    print("Laya nivel: {}; {:,} celdas de entrenamiento, validacion {:.1%}, T {:.2f}; {:,} titulos preguntados{}".format(
        info, int(tr.sum()), acc_v, T, len(consultas), " (PLACEBO)" if placebo else ""), flush=True)
    return {c: (int(n), float(q)) for c, n, q in zip(consultas, niv, p)}
