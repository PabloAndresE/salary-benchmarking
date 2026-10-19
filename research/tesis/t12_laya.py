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


if __name__ == "__main__":
    {"etapa0": etapa0}[sys.argv[1]]()
