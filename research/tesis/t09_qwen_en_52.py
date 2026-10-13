"""T-009: Qwen3.5-122B (local, sin razonamiento, rubrica v7) en la validacion limpia de `52` (100 pares, juicio ciego
del autor), con la misma medida que D-047 aplico a GLM: coherencia y acuerdo con el autor en los coherentes.

    CUDA_VISIBLE_DEVICES=0,3 /root/salary-benchmarking/.venv-llm/bin/python research/tesis/t09_qwen_en_52.py
"""
import importlib.util
import json
import pathlib
import sys

import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
E2 = AQUI.parents[1] / "research/experimentos/e2_nivel"
spec = importlib.util.spec_from_file_location("e51", E2 / "51_etiquetador_local.py")
e51 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e51)


def main():
    import os
    os.environ.setdefault("VLLM_USE_DEEP_GEMM", "0")
    os.environ.setdefault("VLLM_ALLREDUCE_USE_FLASHINFER", "0")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
    os.environ["PATH"] = str(pathlib.Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import StructuredOutputsParams
    v = pd.read_csv(E2 / "salidas" / "52_validacion_para_juzgar.csv", encoding="utf-8-sig", dtype=str)
    v["y"] = v["mismo"].str.strip().str.lower()
    sis, sha = e51.sistema()
    filas = [(k, o, a, b) for k, (x, y) in enumerate(zip(v["a"], v["b"])) for o, a, b in (("ab", x, y), ("ba", y, x))]
    llm = LLM(model=str(E2.parents[2] / "modelos" / "qwen35-122b-a10b-fp8"), tensor_parallel_size=2,
              max_model_len=8192, gpu_memory_utilization=0.85, seed=20261005,
              compilation_config={"pass_config": {"fuse_allreduce_rms": False}}, gdn_prefill_backend="triton")
    sp = SamplingParams(temperature=0.0, max_tokens=300, seed=20261005,
                        structured_outputs=StructuredOutputsParams(json=e51.ESQUEMA))
    sal = llm.chat([[{"role": "system", "content": sis}, {"role": "user", "content": "A: {}\nB: {}".format(a, b)}]
                    for _, _, a, b in filas], sp, chat_template_kwargs={"enable_thinking": False})
    m = {}
    for (k, o, a, b), s in zip(filas, sal):
        try:
            m[(k, o)] = json.loads(s.outputs[0].text)["mismo"]
        except (ValueError, KeyError, TypeError):
            m[(k, o)] = ""
    v["q_ab"] = [m[(k, "ab")] for k in range(len(v))]
    v["q_ba"] = [m[(k, "ba")] for k in range(len(v))]
    coh = (v["q_ab"] == v["q_ba"]) & v["q_ab"].isin(["si", "no"]) & v["y"].isin(["si", "no"])
    acu = (v.loc[coh, "q_ab"] == v.loc[coh, "y"]).mean()
    linea = ("T-009 · Qwen3.5-122B en `52` (100 pares, autor ciego, rubrica v7 sha {}): coherente {:.0%}; acuerdo con "
             "el autor en los coherentes {:.1%} (GLM en D-047: 80 % y 71,2 %)".format(sha, coh.mean(), acu))
    (AQUI / "salidas" / "t09_qwen_en_52.txt").write_text(linea + "\n", encoding="utf-8")
    print(linea)


if __name__ == "__main__":
    main()
