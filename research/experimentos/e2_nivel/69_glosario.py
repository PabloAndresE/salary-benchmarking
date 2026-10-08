"""Glosario de terminos de RR. HH. en ingles para la capa de idioma (D-050): `collections` es `cobranzas`, no
`colecciones`.

Pasos:
    candidatos  palabras y pares de palabras en ingles de los titulos en ingles de la base (`base_v22`), con
                su peso en personas; fuera conectores
    qwen        Qwen3.5-122B local propone el termino que se usa en titulos de cargo en Ecuador, y el tipo
                (area/funcion, sigla, rango, otro). Los rangos (MANAGER, HEAD, SENIOR...) no van al glosario:
                el traductor los ordena bien
    lista       para cada area o sigla, se traduce `<termino> ASSISTANT` con el traductor tal cual; si no sale
                el termino de Qwen, va a la lista para el autor (con ejemplos de titulos)

    ../../../.venv/bin/python 69_glosario.py candidatos
    CUDA_VISIBLE_DEVICES=1,3 ../../../.venv-llm/bin/python 69_glosario.py qwen
    ../../../.venv/bin/python 69_glosario.py lista

SALIDAS: salidas/69_candidatos.parquet, 69_qwen.parquet, 69_glosario_para_aprobar.csv
"""
import collections
import json
import os
import pathlib
import re
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))

SEMILLAS = """COLLECTIONS COLLECTION HR CX UX UI QA IT AI BI AR AP PAYROLL TREASURY PROCUREMENT RECRUITMENT
TALENT BENEFITS COMPLIANCE AUDIT TAX LEGAL RISK FINANCE CONTROLLING BILLING CREDIT UNDERWRITING CLAIMS
INSURANCE HEALTHCARE LOGISTICS WAREHOUSE FLEET MAINTENANCE PROCUREMENT PURCHASING SOURCING FACILITIES
GOVERNANCE ANALYTICS ENGINEERING DEVOPS CYBERSECURITY SECURITY TRAINING ONBOARDING MERCHANDISING
TRADE BRAND MEDIA CONTENT GROWTH PERFORMANCE PRICING REVENUE OPERATIONS PLANNING DEMAND INVENTORY"""
VACIAS = set("OF AND THE FOR TO WITH IN AT ON BY A AN & - I II III IV V".split())

INSTRUCCION = """Eres experto en recursos humanos en Ecuador. Recibes un termino en ingles que aparece en titulos de
cargos de empresas en Ecuador, con ejemplos de esos titulos. Responde como se dice ese termino en un
titulo de cargo en Ecuador, en espanol, MAYUSCULAS y sin tildes, tal como iria dentro del titulo
(COLLECTIONS -> COBRANZAS; ACCOUNTS RECEIVABLE -> CUENTAS POR COBRAR; HR -> RECURSOS HUMANOS;
CX -> EXPERIENCIA DEL CLIENTE; PAYROLL -> NOMINA; TREASURY -> TESORERIA).

`tipo`:
- `area`: un area, funcion o materia del cargo (COLLECTIONS, PAYROLL, SUPPLY CHAIN, DATA, CUSTOMER SUCCESS);
- `sigla`: una sigla (HR, CX, QA, AR, AP, IT, BI);
- `rango`: una palabra de rango, nivel o seniority (MANAGER, HEAD, LEAD, SENIOR, ASSISTANT, ANALYST,
  SPECIALIST, COORDINATOR, DIRECTOR, CHIEF, EXECUTIVE, REPRESENTATIVE);
- `otro`: un nombre propio, una marca, un codigo o algo que no se traduce.
`seguro`: `si` si esa es la traduccion habitual; `no` si depende del contexto (dilo en `nota`).
Responde solo con el JSON pedido."""

ESQUEMA = {"type": "object",
           "properties": {"es": {"type": "string", "maxLength": 60},
                          "tipo": {"type": "string", "enum": ["area", "sigla", "rango", "otro"]},
                          "seguro": {"type": "string", "enum": ["si", "no"]},
                          "nota": {"type": "string", "maxLength": 150}},
           "required": ["es", "tipo", "seguro", "nota"]}


def candidatos():
    from benchmarking.producto.idioma import es_ingles
    b = np.load(RAIZ / "demo" / "base_v22.npz", allow_pickle=True)
    per = dict(zip((str(c) for c in b["celdas"]), b["personas"].astype(float)))
    peso, ejemplos = collections.Counter(), collections.defaultdict(list)
    for t, p in per.items():
        if not es_ingles(t):
            continue
        ws = [w for w in re.findall(r"[A-Z]+", t.upper())]
        terminos = {w for w in ws if w not in VACIAS and len(w) >= 2}
        terminos |= {a + " " + b_ for a, b_ in zip(ws, ws[1:]) if a not in VACIAS and b_ not in VACIAS}
        for x in terminos:
            peso[x] += p
            if len(ejemplos[x]) < 4:
                ejemplos[x].append(t)
    d = pd.DataFrame([(k, v, " ; ".join(ejemplos[k])) for k, v in peso.items()],
                     columns=["termino", "personas", "ejemplos"])
    # palabras con >= 30 personas; pares con >= 60 (los pares son frases fijas: ACCOUNTS RECEIVABLE)
    d = d[(d["personas"] >= 30) & ((~d["termino"].str.contains(" ")) | (d["personas"] >= 60))]
    # semillas: siglas y terminos frecuentes en titulos de clientes que escriben en ingles
    semillas = set(SEMILLAS.split()) | {"ACCOUNTS RECEIVABLE", "ACCOUNTS PAYABLE", "CUSTOMER SUCCESS",
                                        "CUSTOMER EXPERIENCE", "SUPPLY CHAIN", "BUSINESS PARTNER",
                                        "KEY ACCOUNT", "DATA GOVERNANCE", "DATA ANALYTICS", "EMPLOYEE BENEFITS",
                                        "EMPLOYMENT BENEFITS", "SALES DEVELOPMENT", "BUSINESS DEVELOPMENT",
                                        "TALENT ACQUISITION", "FIELD SERVICE", "INSIDE SALES"}
    faltan = [x for x in semillas if x not in set(d["termino"])]
    d = pd.concat([d, pd.DataFrame({"termino": faltan, "personas": [peso.get(x, 0.0) for x in faltan],
                                    "ejemplos": [" ; ".join(ejemplos.get(x, [])) for x in faltan]})])
    d = d.sort_values("personas", ascending=False).reset_index(drop=True)
    d.to_parquet(SAL / "69_candidatos.parquet", index=False)
    print("{} terminos ({} palabras, {} pares)".format(len(d), (~d["termino"].str.contains(" ")).sum(),
                                                      d["termino"].str.contains(" ").sum()))


def qwen():
    os.environ.setdefault("VLLM_USE_DEEP_GEMM", "0")
    os.environ.setdefault("VLLM_ALLREDUCE_USE_FLASHINFER", "0")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
    os.environ["PATH"] = str(pathlib.Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import StructuredOutputsParams
    d = pd.read_parquet(SAL / "69_candidatos.parquet")
    llm = LLM(model=str(RAIZ / "modelos" / "qwen35-122b-a10b-fp8"), tensor_parallel_size=2, max_model_len=4096,
              gpu_memory_utilization=0.85, seed=20261008,
              compilation_config={"pass_config": {"fuse_allreduce_rms": False}}, gdn_prefill_backend="triton")
    sp = SamplingParams(temperature=0.0, max_tokens=200, seed=20261008,
                        structured_outputs=StructuredOutputsParams(json=ESQUEMA))
    msgs = [[{"role": "system", "content": INSTRUCCION},
             {"role": "user", "content": "Termino: {}\nEjemplos: {}".format(t, e)}]
            for t, e in zip(d["termino"], d["ejemplos"])]
    sal = llm.chat(msgs, sp, chat_template_kwargs={"enable_thinking": False})
    filas = []
    for s in sal:
        try:
            r = json.loads(s.outputs[0].text)
        except ValueError:
            r = {"es": "", "tipo": "otro", "seguro": "no", "nota": "ERROR"}
        filas.append(r)
    d = pd.concat([d, pd.DataFrame(filas)], axis=1)
    d.to_parquet(SAL / "69_qwen.parquet", index=False)
    print(d["tipo"].value_counts().to_dict())


def lista():
    from benchmarking.producto import idioma
    d = pd.read_parquet(SAL / "69_qwen.parquet")
    rangos = set(d.loc[d["tipo"] == "rango", "termino"]) | {"MANAGER", "MANGER", "HEAD", "LEAD", "SENIOR", "JUNIOR",
                                                              "ASSISTANT", "ANALYST", "SPECIALIST", "CONSULTANT",
                                                              "COORDINATOR", "DIRECTOR", "OFFICER", "EXECUTIVE",
                                                              "REPRESENTATIVE", "PLANNER", "MERCHANDISER", "AUDITOR"}
    d = d[d["tipo"].isin(["area", "sigla"]) & (d["es"].str.strip() != "")].copy()
    # un termino que contiene una palabra de rango no va al glosario: el traductor ordena el rango
    d = d[[not (set(t.split()) & rangos) for t in d["termino"]]]
    d["es"] = d["es"].map(idioma.normalizar)
    tr = idioma.cargar(RAIZ / "modelos" / "opus-mt-en-es")
    hoy = tr.traducir([t + " ASSISTANT" for t in d["termino"]])
    d["traductor_hoy"] = [hoy[t + " ASSISTANT"] for t in d["termino"]]
    d["coincide"] = [es in h for es, h in zip(d["es"], d["traductor_hoy"])]
    # una palabra suelta que ya va dentro de un par aprobado se decide en el par
    out = d[~d["coincide"]].sort_values("personas", ascending=False)
    out = out[["termino", "es", "seguro", "nota", "traductor_hoy", "personas", "ejemplos"]].assign(aprobar="", correccion="")
    out = out.rename(columns={"es": "propuesta_es", "traductor_hoy": "traductor_hoy_dice"})
    out.to_csv(SAL / "69_glosario_para_aprobar.csv", index=False, encoding="utf-8-sig")
    print("{} terminos de area o sigla; el traductor ya los dice bien en {}; a revisar: {}".format(
        len(d), int(d["coincide"].sum()), len(out)))


if __name__ == "__main__":
    {"candidatos": candidatos, "qwen": qwen, "lista": lista}[sys.argv[1]]()
