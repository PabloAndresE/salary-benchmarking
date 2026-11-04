"""T-027: Qwen3.5-122B zero-shot como DECISOR de «mismo cargo», frente al cross-encoder destilado.

Preregistro: docs/registro_decisiones.md, bloque `## T-027`.

    CUDA_VISIBLE_DEVICES=0,1 /root/salary-benchmarking/.venv-llm/bin/python research/tesis/t27_llm_decisor.py etiquetar
    CUDA_VISIBLE_DEVICES=0 PYTHONPATH=.libs_tesis .venv/bin/python research/tesis/t27_llm_decisor.py medir

Conjuntos (los mismos de T-009 etapa 1 y T-016 parte B, via `t09_etapa1.conjuntos()`):
  - lejos: `52`, 100 pares (33 `si`), verdad = juicio ciego del autor. LECTURA PRINCIPAL.
  - cerca: `prueba` + `prueba 2`, 991 pares (790 `si`).

El LLM responde par a par, temperatura 0, JSON guiado, rubrica v7, en los DOS ordenes (A=>B y B=>A).
Decision = producto de las dos direcciones (`si` solo si ambas dicen `si`), igual que el cross-encoder.

SALIDAS: salidas/t27_llm_lejos.parquet, t27_llm_cerca.parquet, t27_tiempos.json, t27_llm_decisor.txt
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
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(RAIZ / "src"))

SEM = 20261005          # la misma semilla de T-009 (t09_qwen_en_52.py)
SEM_BS = 20261102       # bootstrap de T-027
REPLICAS = 10_000
MARGEN = 0.05           # banda de equivalencia del preregistro
USD_GPU_HORA = 3.00     # SUPUESTO declarado: alquiler de una H200 por hora (no es un costo medido)
ARCHIVO = {"lejos (52, autor ciego)": "t27_llm_lejos.parquet",
           "cerca (prueba + prueba 2)": "t27_llm_cerca.parquet"}


def conjuntos():
    spec = importlib.util.spec_from_file_location("t09e1", AQUI / "t09_etapa1.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.conjuntos(), m.MODELOS


# ---------------------------------------------------------------- etiquetar


def etiquetar():
    import os
    os.environ.setdefault("VLLM_USE_DEEP_GEMM", "0")
    os.environ.setdefault("VLLM_ALLREDUCE_USE_FLASHINFER", "0")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
    os.environ["PATH"] = str(pathlib.Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import StructuredOutputsParams

    spec = importlib.util.spec_from_file_location("e51", E2 / "51_etiquetador_local.py")
    e51 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e51)
    sis, sha = e51.sistema()
    conj, _ = conjuntos()

    # una fila por (conjunto, par, direccion)
    filas = []
    for nom, d in conj.items():
        for k, (a, b) in enumerate(zip(d["a"], d["b"])):
            filas.append((nom, k, "ab", a, b))
            filas.append((nom, k, "ba", b, a))
    print("T-027 · {} prompts ({} pares x 2 direcciones), rubrica v7 sha {}".format(
        len(filas), len(filas) // 2, sha), flush=True)

    t_carga = time.time()
    llm = LLM(model=str(pathlib.Path("/root/salary-benchmarking/modelos/qwen35-122b-a10b-fp8")),
              tensor_parallel_size=2, max_model_len=8192, gpu_memory_utilization=0.85, seed=SEM,
              compilation_config={"pass_config": {"fuse_allreduce_rms": False}}, gdn_prefill_backend="triton")
    t_carga = time.time() - t_carga
    sp = SamplingParams(temperature=0.0, max_tokens=300, seed=SEM,
                        structured_outputs=StructuredOutputsParams(json=e51.ESQUEMA))
    t0 = time.time()
    salidas = llm.chat([[{"role": "system", "content": sis},
                         {"role": "user", "content": "A: {}\nB: {}".format(a, b)}]
                        for _, _, _, a, b in filas], sp, chat_template_kwargs={"enable_thinking": False})
    seg = time.time() - t0

    cr = {}
    toks = 0
    for (nom, k, o, a, b), s in zip(filas, salidas):
        txt = s.outputs[0].text
        toks += len(s.outputs[0].token_ids) + len(s.prompt_token_ids)
        try:
            j = json.loads(txt)
            cr[(nom, k, o)] = (str(j.get("mismo", "")), str(j.get("paso", "")), str(j.get("razon", ""))[:300])
        except (ValueError, TypeError):
            cr[(nom, k, o)] = ("", "", "")

    for nom, d in conj.items():
        r = d.copy()
        for o in ("ab", "ba"):
            r["q_" + o] = [cr[(nom, k, o)][0] for k in range(len(d))]
            r["paso_" + o] = [cr[(nom, k, o)][1] for k in range(len(d))]
            r["razon_" + o] = [cr[(nom, k, o)][2] for k in range(len(d))]
        r["rubrica_sha"] = sha
        r.to_parquet(SAL / ARCHIVO[nom], index=False)
        print("  {} -> {} ({} filas)".format(nom, ARCHIVO[nom], len(r)), flush=True)

    (SAL / "t27_tiempos.json").write_text(json.dumps(
        {"prompts": len(filas), "pares": len(filas) // 2, "seg_generacion": seg, "seg_carga_modelo": t_carga,
         "tokens_totales": toks, "gpus": 2, "rubrica_sha": sha, "semilla": SEM}, indent=1), encoding="utf-8")
    print("generacion {:.1f} s ({:.3f} s/prompt), carga del modelo {:.1f} s".format(
        seg, seg / len(filas), t_carga), flush=True)


# ------------------------------------------------------------------- medir


def balanceada(y, p):
    return 0.5 * ((p[y == 1] == 1).mean() + (p[y == 0] == 0).mean())


def auc(y, s):
    from sklearn.metrics import roc_auc_score
    return roc_auc_score(y, s)


def medir():
    from benchmarking.producto.juez import cargar
    conj, MODELOS = conjuntos()
    tiempos = json.loads((SAL / "t27_tiempos.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEM_BS)
    out = ["T-027 · Qwen3.5-122B zero-shot como DECISOR de «mismo cargo», frente al cross-encoder destilado",
           "Preregistro: docs/registro_decisiones.md, bloque `## T-027`. Metrica primaria: exactitud balanceada;",
           "secundaria: AUC. IC 95 % por bootstrap PAREADO por par, {:,} replicas, estratificado por clase".format(
               REPLICAS).replace(",", "."),
           "(mismo esquema de remuestreo que T-009 etapa 1 y T-016 parte B). Semilla {}.".format(SEM_BS), ""]

    jueces = {k: cargar(v) for k, v in MODELOS.items()}
    for k, j in jueces.items():
        assert j is not None, k
    nombre_ce = {"v9": "cross-encoder reentrenado (v9)", "v3": "cross-encoder del producto (v3)"}
    seg_ce = {}

    for nom, d in conj.items():
        r = pd.read_parquet(SAL / ARCHIVO[nom])
        assert len(r) == len(d) and list(r["a"]) == list(d["a"]), "el parquet no coincide con el conjunto"
        y = d["y"].to_numpy()
        ok = r["q_ab"].isin(["si", "no"]) & r["q_ba"].isin(["si", "no"])
        sab, sba = (r["q_ab"] == "si").to_numpy(), (r["q_ba"] == "si").to_numpy()
        coh = (r["q_ab"] == r["q_ba"]).to_numpy() & ok.to_numpy()

        pred, punt = {}, {}
        # decision del LLM = producto de las dos direcciones, como el sistema propuesto
        pred["Qwen3.5-122B zero-shot"] = (sab & sba).astype(int)
        # el LLM no da puntaje continuo: el AUC se calcula sobre el acuerdo de las dos direcciones (0, 0,5, 1)
        punt["Qwen3.5-122B zero-shot"] = (sab.astype(float) + sba.astype(float)) / 2.0
        for k, j in jueces.items():
            t0 = time.time()
            p = np.asarray(j.P(list(zip(d["a"], d["b"]))), dtype=float)
            seg_ce.setdefault(k, 0.0)
            seg_ce[k] += time.time() - t0
            pred[nombre_ce[k]] = (p >= 0.5).astype(int)
            punt[nombre_ce[k]] = p

        out.append("{} · n={}, `si` {} ({:.0%})".format(nom, len(y), int(y.sum()), y.mean()))
        out.append("  coherencia del LLM entre las dos direcciones: {:.1%}  (JSON invalido en alguna direccion: {})"
                   .format(coh.mean(), int((~ok).sum())))
        out.append("")
        out.append("  {:<32} {:>12}  {:>7}  {:>12}  {:>14}".format(
            "metodo", "balanceada", "AUC", "`si` juntos", "`no` separados"))
        for k in pred:
            out.append("  {:<32} {:>12.3f}  {:>7.4f}  {:>11.1%}  {:>13.1%}".format(
                k, balanceada(y, pred[k]), auc(y, punt[k]), (pred[k][y == 1] == 1).mean(),
                (pred[k][y == 0] == 0).mean()))

        # bootstrap pareado: se remuestrean los MISMOS pares para los dos metodos
        i1, i0 = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
        idx = [np.concatenate([rng.choice(i1, len(i1)), rng.choice(i0, len(i0))]) for _ in range(REPLICAS)]
        out.append("")
        for ref in ("cross-encoder reentrenado (v9)", "cross-encoder del producto (v3)"):
            llm = "Qwen3.5-122B zero-shot"
            d0 = balanceada(y, pred[ref]) - balanceada(y, pred[llm])
            bs = np.array([balanceada(y[i], pred[ref][i]) - balanceada(y[i], pred[llm][i]) for i in idx])
            lo, hi = np.percentile(bs, [2.5, 97.5])
            if hi < 0:
                lec = "INFERIORIDAD del cross-encoder"
            elif lo > 0:
                lec = "SUPERIORIDAD del cross-encoder"
            elif lo > -MARGEN and hi < MARGEN:
                lec = "EQUIVALENCIA dentro de +-{:.2f}".format(MARGEN)
            else:
                lec = "no concluyente (el IC cruza cero y sale de la banda)"
            out.append("  balanceada, {} - LLM: {:+.3f} [{:+.3f}, {:+.3f}] -> {}".format(
                ref.split(" (")[1][:-1], d0, lo, hi, lec))
            a0 = auc(y, punt[ref]) - auc(y, punt[llm])
            ba = np.array([auc(y[i], punt[ref][i]) - auc(y[i], punt[llm][i]) for i in idx])
            alo, ahi = np.percentile(ba, [2.5, 97.5])
            out.append("  AUC,        {} - LLM: {:+.3f} [{:+.3f}, {:+.3f}] -> {}".format(
                ref.split(" (")[1][:-1], a0, alo, ahi,
                "cross-encoder MEJOR" if alo > 0 else ("cross-encoder PEOR" if ahi < 0 else "no se distingue")))
        out.append("")

    # ----- costo y latencia (el preregistro los pide)
    n_par = tiempos["pares"]
    s_llm = tiempos["seg_generacion"] / n_par
    n_ce = sum(len(d) for d in conj.values())
    s_v9 = seg_ce["v9"] / n_ce
    gpu_h_llm = s_llm * tiempos["gpus"] * 1000 / 3600
    gpu_h_ce = s_v9 * 1 * 1000 / 3600
    out += ["COSTO Y LATENCIA (medido en este mismo servidor, H200; el LLM con TP=2, el cross-encoder en 1 GPU)",
            "  Qwen3.5-122B zero-shot : {:.3f} s/par ({} prompts, 2 direcciones), carga del modelo {:.0f} s aparte"
            .format(s_llm, tiempos["prompts"], tiempos["seg_carga_modelo"]),
            "  cross-encoder v9 (280 M): {:.4f} s/par".format(s_v9),
            "  razon de latencia: el cross-encoder es {:.0f}x mas rapido por par".format(s_llm / s_v9),
            "  por 1.000 pares: LLM {:.3f} GPU-hora  ({:.2f} USD)   cross-encoder {:.4f} GPU-hora  ({:.3f} USD)"
            .format(gpu_h_llm, gpu_h_llm * USD_GPU_HORA, gpu_h_ce, gpu_h_ce * USD_GPU_HORA),
            "  razon de costo: {:.0f}x a favor del cross-encoder".format(gpu_h_llm / gpu_h_ce),
            "  (SUPUESTO declarado para el USD: {:.2f} USD por H200-hora. Las GPU-hora si son medidas.)".format(
                USD_GPU_HORA),
            "",
            "COMPARADORES YA MEDIDOS, no recalculados aqui:",
            "  ESCO (JobBERT), T-016 parte B: balanceada 0,576 en `lejos` y 0,542 en `cerca`.",
            "  AUC del cross-encoder, T-009 etapa 1: v3 0,5721 / v9 0,7322 en `lejos`; v3 0,9292 / v9 0,9376 en `cerca`.",
            "  Coseno (T-019) y piso lexico TF-IDF (T-020) estan medidos sobre el open set, con su propio protocolo;",
            "  no existen como decisores par a par en estos dos conjuntos y no se recalculan."]

    (SAL / "t27_llm_decisor.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    {"etiquetar": etiquetar, "medir": medir}[sys.argv[1]]()
