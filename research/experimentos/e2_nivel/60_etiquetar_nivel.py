"""D-049: Qwen3.5-122B (local) etiqueta el nivel jerarquico de cada titulo de `base_v18`.

Recibe el titulo y, si existe, la descripcion de Gemini (D-045, `46_descripciones.csv`). NO ve
sueldos. Temperatura 0, sin razonamiento, salida JSON guiada (como `51`).

    CUDA_VISIBLE_DEVICES=1,3 ../../../.venv-llm/bin/python 60_etiquetar_nivel.py --tp 2
    CUDA_VISIBLE_DEVICES=1,3 ../../../.venv-llm/bin/python 60_etiquetar_nivel.py --tp 2 --n 300   # prueba

SALIDA: salidas/60_niveles_qwen.parquet (titulo, nivel, explicito, posibles, razon, error)
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
MODELO = "qwen35-122b-a10b-fp8"
BASE = "base_v18.npz"

INSTRUCCION = """Eres un analista de compensaciones en Ecuador. Recibes el titulo de un cargo (tal como lo
escribio una empresa, a veces con abreviaturas, errores o en ingles) y, a veces, una descripcion breve
de sus funciones. Clasificalo en un NIVEL JERARQUICO de esta escala:

1  operativo, auxiliar, asistente, ayudante, de apoyo, practicante, obrero, operador, vendedor,
   asesor, ejecutivo o representante comercial, guardia, chofer, cajero, mensajero.
2  tecnico o profesional que trabaja por su cuenta, sin equipo a cargo: analista, tecnico, contador,
   medico, ingeniero, abogado, docente, desarrollador, consultor.
3  especialista experto, coordinador o supervisor: coordina personas o procesos, o es la referencia
   tecnica de su area, sin ser jefe de area.
4  jefe o subgerente: responsable formal de un area o departamento y de su equipo.
5  gerente, director, vicepresidente, presidente o alta direccion.

Reglas:
- Decide por lo que el cargo ES, no por lo que podria cobrar.
- Si el titulo declara el escalon con una palabra de rango (AUXILIAR, ASISTENTE, ANALISTA, TECNICO,
  COORDINADOR, SUPERVISOR, ESPECIALISTA, ENCARGADO, JEFE, SUBGERENTE, GERENTE, DIRECTOR, ASESOR,
  EJECUTIVO...), ESE escalon manda. La descripcion es generica: solo sirve cuando el titulo no lo declara.
- `ASISTENTE DE GERENCIA` es un asistente (1): lo que va tras DE dice a quien apoya, no su nivel.
- La seniority (JUNIOR, SENIOR, I, II, 1, 2) NO cambia el nivel: es un matiz dentro del escalon.
- En ingles: MANAGER = 5 salvo ASSISTANT MANAGER (4); HEAD OF = 4 o 5 segun el alcance; LEAD = 3;
  OFFICER y ASSOCIATE segun las funciones.
- `explicito` = `si` si el titulo declara el escalon (una palabra de rango clara); `no` si lo infieres de
  la ocupacion o de la descripcion.
- `posibles` = todos los niveles que el texto admite razonablemente (incluye `nivel`). Si el texto lo
  dice claro, solo uno.
- Si no es un cargo (un codigo, un nombre de contrato, texto sin sentido), `nivel` = 0 y `posibles` = [0].

{extra}Responde solo con el JSON pedido; `razon` en una frase de 25 palabras como maximo."""

# v2 (enmienda de D-049): la v1 subia a 3 cargos operativos porque la descripcion dice «supervisa»
EXTRA_V2 = """- INSPECTOR, AGENTE, GESTOR, OFICIAL y MAYORDOMO no son rango: clasificalos por la funcion; por
  defecto son 1 (operativo) o 2 (tecnico o profesional). INSPECTOR DE CALIDAD es 1 o 2, no 3.
- `supervisa`, `coordina` o `controla` en la descripcion NO suben el nivel: casi todas las
  descripciones lo dicen. Sube a 3 o mas solo por el TITULO: personas o un area a cargo, o un rol
  de experto (arquitecto de soluciones, especialista, lider tecnico).
"""
# v3 (D-053): la v2 marcaba UN solo nivel posible en el 95 % de los titulos, por dos reglas de estas
# instrucciones ("la palabra de rango manda", "MANAGER = 5"): ni el sueldo podia desempatar. La v3 quita
# la regla fija del ingles y pide `posibles` honestos para las palabras ambiguas.
_V3_INGLES_V2 = """- En ingles: MANAGER = 5 salvo ASSISTANT MANAGER (4); HEAD OF = 4 o 5 segun el alcance; LEAD = 3;
  OFFICER y ASSOCIATE segun las funciones.
"""
_V3_INGLES = """- En ingles los titulos no fijan el nivel por la palabra, sino por la FUNCION. MANAGER con un area o
  un equipo a cargo (SALES MANAGER, PLANT MANAGER, HR MANAGER) es 4 o 5; MANAGER de una cartera, una
  cuenta, un producto o un proyecto (ACCOUNT MANAGER, KEY ACCOUNT MANAGER, CUSTOMER SUCCESS MANAGER,
  PRODUCT MANAGER, PROJECT MANAGER) suele ser 2 o 3. GENERAL MANAGER, COUNTRY MANAGER, DIRECTOR, VP,
  CHIEF = 5. HEAD OF = 4 o 5. LEAD o TEAM LEAD = 3. OFFICER, ASSOCIATE, PARTNER y EXECUTIVE, por la
  funcion. ASSISTANT MANAGER = 4 si es subgerente, 1 si es asistente.
"""
_V3_POSIBLES_V2 = """- `posibles` = todos los niveles que el texto admite razonablemente (incluye `nivel`). Si el texto lo
  dice claro, solo uno.
"""
_V3_POSIBLES = """- `posibles` = TODOS los niveles que ese titulo puede tener en distintas empresas (incluye `nivel`).
  Se usa para desempatar con otros datos, asi que no lo recortes: un solo nivel SOLO si no hay duda
  posible (AUXILIAR DE BODEGA, GERENTE GENERAL). Son AMBIGUOS y casi siempre llevan varios:
  MANAGER, HEAD, LEAD, OFFICER, ASSOCIATE; GERENTE DE CUENTA(S) / DE PRODUCTO / DE PROYECTO / DE
  TIENDA / DE AGENCIA / DE ZONA (2 a 5); JEFE DE TURNO / DE GRUPO / DE CUADRILLA / DE LINEA (3 o 4);
  ADMINISTRADOR (2 a 5); ENCARGADO (1 a 3); COORDINADOR (2 o 3); ESPECIALISTA (2 o 3); DIRECTOR de
  escuela, de obra o de proyecto (3 a 5); EJECUTIVO y ASESOR (1 o 2); SUPERVISOR (3 o 4).
- `nivel` = el MAS probable. Con una palabra de rango en espanol, el de esa palabra en la escala de
  arriba; en ingles, por la funcion.
"""
INSTRUCCION_V3 = (INSTRUCCION.replace(_V3_INGLES_V2, _V3_INGLES).replace(_V3_POSIBLES_V2, _V3_POSIBLES)
                  .replace("""- Si el titulo declara el escalon con una palabra de rango (AUXILIAR, ASISTENTE, ANALISTA, TECNICO,
  COORDINADOR, SUPERVISOR, ESPECIALISTA, ENCARGADO, JEFE, SUBGERENTE, GERENTE, DIRECTOR, ASESOR,
  EJECUTIVO...), ESE escalon manda. La descripcion es generica: solo sirve cuando el titulo no lo declara.""",
                           """- Si el titulo declara el escalon con una palabra de rango (AUXILIAR, ASISTENTE, ANALISTA, TECNICO,
  COORDINADOR, SUPERVISOR, ESPECIALISTA, ENCARGADO, JEFE, SUBGERENTE, GERENTE, DIRECTOR, ASESOR,
  EJECUTIVO...), ese escalon es `nivel`; las palabras ambiguas de abajo llevan ademas sus otros
  niveles en `posibles`. La descripcion es generica: solo sirve cuando el titulo no lo declara."""))
assert INSTRUCCION_V3.count("ambiguas de abajo") == 1 and _V3_INGLES in INSTRUCCION_V3 and _V3_POSIBLES in INSTRUCCION_V3
VERSIONES = {"v1": INSTRUCCION.replace("{extra}", ""), "v2": INSTRUCCION.replace("{extra}", EXTRA_V2),
             "v3": INSTRUCCION_V3.replace("{extra}", EXTRA_V2)}

ESQUEMA = {"type": "object",
           "properties": {"razon": {"type": "string", "maxLength": 300},
                          "nivel": {"type": "integer", "enum": [0, 1, 2, 3, 4, 5]},
                          "explicito": {"type": "string", "enum": ["si", "no"]},
                          "posibles": {"type": "array", "items": {"type": "integer", "enum": [0, 1, 2, 3, 4, 5]},
                                       "minItems": 1, "maxItems": 5}},
           "required": ["razon", "nivel", "explicito", "posibles"]}


def titulos():
    b = np.load(RAIZ / "demo" / BASE, allow_pickle=True)
    return [str(c) for c in b["celdas"]]


def descripciones():
    d = pd.read_csv(SAL / "46_descripciones.csv", keep_default_na=False)
    out = {}
    for t, r in zip(d["titulo"], d["respuesta"]):
        try:
            x = json.loads(r).get("descripcion", "").strip()
        except (ValueError, AttributeError):
            x = ""
        if x:
            out[str(t)] = x
    return out


def mensaje(t, desc, instruccion):
    u = "Titulo: {}".format(t)
    if desc:
        u += "\nDescripcion: {}".format(desc)
    return [{"role": "system", "content": instruccion}, {"role": "user", "content": u}]


def main(tp, n, version):
    instruccion = VERSIONES[version]
    # el nvcc del servidor (12.5) no compila los kernels JIT de DeepGEMM ni los de FlashInfer (all-reduce, muestreo)
    os.environ.setdefault("VLLM_USE_DEEP_GEMM", "0")
    os.environ.setdefault("VLLM_ALLREDUCE_USE_FLASHINFER", "0")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
    os.environ["PATH"] = str(pathlib.Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]  # ninja
    from vllm import LLM, SamplingParams
    try:
        from vllm.sampling_params import StructuredOutputsParams
        guia = {"structured_outputs": StructuredOutputsParams(json=ESQUEMA)}
    except ImportError:
        from vllm.sampling_params import GuidedDecodingParams
        guia = {"guided_decoding": GuidedDecodingParams(json=ESQUEMA)}
    tit = titulos()
    if n:
        tit = list(pd.Series(tit).sample(n, random_state=20261006))
    desc = descripciones()
    print("{:,} titulos; con descripcion {:,}".format(len(tit), sum(t in desc for t in tit)), flush=True)
    llm = LLM(model=str(RAIZ / "modelos" / MODELO), tensor_parallel_size=tp, max_model_len=4096,
              gpu_memory_utilization=0.85, seed=20261006,
              # (ver arriba) sin la fusion all-reduce + norma y con el prefill GDN de triton
              compilation_config={"pass_config": {"fuse_allreduce_rms": False}},
              gdn_prefill_backend="triton")
    sp = SamplingParams(temperature=0.0, max_tokens=400, seed=20261006, **guia)
    t0 = time.time()
    sal = llm.chat([mensaje(t, desc.get(t, ""), instruccion) for t in tit], sp,
                   chat_template_kwargs={"enable_thinking": False})
    filas = []
    for t, s in zip(tit, sal):
        txt = s.outputs[0].text
        try:
            r = json.loads(txt)
            pos = sorted(set(int(x) for x in r["posibles"]) | {int(r["nivel"])})
            filas.append((t, int(r["nivel"]), r["explicito"], json.dumps(pos), r["razon"], t in desc, ""))
        except (ValueError, KeyError, TypeError):
            filas.append((t, -1, "", "[]", "", t in desc, str(txt)[:200]))
    d = pd.DataFrame(filas, columns=["titulo", "nivel", "explicito", "posibles", "razon", "con_desc", "error"])
    d["modelo"] = MODELO
    d["instruccion_sha"] = hashlib.sha256(instruccion.encode()).hexdigest()[:12]
    nombre = "60_niveles_qwen{}{}.parquet".format("" if version == "v1" else "_" + version,
                                                  "_prueba" if n else "")
    d.to_parquet(SAL / nombre, index=False)
    seg = time.time() - t0
    print("{:,} en {:.0f} s; errores {}".format(len(d), seg, int((d["error"] != "").sum())))
    print(d["nivel"].value_counts().sort_index().to_dict(), d["explicito"].value_counts().to_dict())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tp", type=int, default=2)
    ap.add_argument("--n", type=int, default=0, help="solo una muestra (prueba)")
    ap.add_argument("--version", choices=["v1", "v2", "v3"], default="v3")
    a = ap.parse_args()
    main(a.tp, a.n, a.version)
