"""Un LLM abierto en local como etiquetador de «mismo cargo» con la rubrica v6 (sin costo por consulta).

Elige el modelo contra juicios del autor que YA existen, sin pedir juicios nuevos:
    lejos   la auditoria de D-045 §2 (`45_auditoria_*`): 130 pares de coseno < 0,85
    cerca   `calibra` del paquete v6 (`21_paquete_v6/calibra.csv`): 187 pares
Mismo formato que D-035 (`15_piloto_llm.py`): la instruccion, el esquema JSON (razon, paso, mismo) y
los dos ordenes del par; temperatura 0; la rubrica v6 sin el historial. Salida estructurada con el
esquema (decodificacion guiada de vLLM) y sin modo de razonamiento.

CRITERIO (fijado antes de medir): se elige el que mas coincide con el autor en `lejos`; para usarlo
tiene que coincidir >= 85 % ahi y tener kappa >= 0,79 en `cerca` (el de Gemini en D-035). Si ninguno
lo cumple, no se usa ninguno. Coincidencia por par: el veredicto coherente en los dos ordenes; un
par incoherente cuenta como fallo.

    CUDA_VISIBLE_DEVICES=0 .venv-llm/bin/python 51_etiquetador_local.py --modelo qwen35-35b-a3b-fp8
    CUDA_VISIBLE_DEVICES=0,1 .venv-llm/bin/python 51_etiquetador_local.py --modelo qwen35-122b-a10b-fp8 --tp 2
    .venv-llm/bin/python 51_etiquetador_local.py --resumen

SALIDAS: salidas/51_<modelo>.csv (respuestas), salidas/51_etiquetador_local.txt (resumen)
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
RUBRICA = AQUI / "rubrica_mismo_cargo_v6.md"
# los tres de la primera idea (Qwen3-235B, Qwen3-32B, Qwen2.5-72B) se cambiaron por una generacion
# mas nueva y mas chica: la red del servidor estaba a 0,5 MB/s (2026-10-05)
MODELOS = ("qwen35-35b-a3b-fp8", "gemma4-26b-a4b", "qwen35-122b-a10b-fp8")
UMBRAL_LEJOS, KAPPA_CERCA = 0.85, 0.79

INSTRUCCION = """Eres un analista de benchmarking salarial. Vas a recibir dos titulos de
cargo, A y B. Decide si son el mismo cargo siguiendo EXACTAMENTE la rubrica de abajo:
recorre los pasos en orden y el primero que diga `no` decide; si ninguno lo dice, es `si`.

Responde solo con el JSON pedido:
- `razon`: una frase corta con lo que decidio.
- `paso`: el paso que decidio (`p1` a `p5`), o `ninguno` si ningun paso dijo `no`.
- `mismo`: `si` o `no`.

=== RUBRICA ===

"""
ESQUEMA = {"type": "object",
           "properties": {"razon": {"type": "string"},
                          "paso": {"type": "string", "enum": ["p1", "p2", "p3", "p4", "p5", "ninguno"]},
                          "mismo": {"type": "string", "enum": ["si", "no"]}},
           "required": ["razon", "paso", "mismo"]}


def sistema():
    texto = RUBRICA.read_text(encoding="utf-8").split("\n## Historial")[0].rstrip()
    return INSTRUCCION + texto, hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


def leer(p):
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                       keep_default_na=False)


def conjuntos():
    j = leer(SAL / "45_auditoria_para_juzgar.csv")
    m = pd.read_csv(SAL / "45_auditoria_mapa.csv", dtype=str)
    lejos = m.merge(j[["n_ciego", "mismo"]], on="n_ciego")[["a", "b", "mismo"]].assign(conjunto="lejos")
    cal = pd.read_csv(SAL / "21_paquete_v6" / "calibra.csv", dtype=str, keep_default_na=False)
    cerca = cal.rename(columns={"comun": "a", "raro": "b"})[["a", "b", "mismo"]].assign(conjunto="cerca")
    d = pd.concat([lejos, cerca], ignore_index=True)
    d["mismo"] = d["mismo"].str.strip().str.lower()
    d["id"] = np.arange(len(d))
    return d


def correr(modelo, tp):
    from vllm import LLM, SamplingParams
    try:
        from vllm.sampling_params import StructuredOutputsParams
        guia = {"structured_outputs": StructuredOutputsParams(json=ESQUEMA)}
    except ImportError:
        from vllm.sampling_params import GuidedDecodingParams
        guia = {"guided_decoding": GuidedDecodingParams(json=ESQUEMA)}
    d = conjuntos()
    sis, sha = sistema()
    filas = [(r.id, o, a, b) for r in d.itertuples() for o, a, b in (("ab", r.a, r.b), ("ba", r.b, r.a))]
    llm = LLM(model=str(RAIZ / "modelos" / modelo), tensor_parallel_size=tp, max_model_len=8192,
              gpu_memory_utilization=0.85, seed=20261005)
    sp = SamplingParams(temperature=0.0, max_tokens=300, seed=20261005, **guia)
    mensajes = [[{"role": "system", "content": sis},
                 {"role": "user", "content": "A: {}\nB: {}".format(a, b)}] for _, _, a, b in filas]
    t0 = time.time()
    salidas = llm.chat(mensajes, sp, chat_template_kwargs={"enable_thinking": False})
    seg = time.time() - t0
    out = []
    for (i, o, a, b), s in zip(filas, salidas):
        txt = s.outputs[0].text
        try:
            r = json.loads(txt)
            out.append((i, o, a, b, r["mismo"], r["paso"], r["razon"], ""))
        except (ValueError, KeyError):
            out.append((i, o, a, b, "", "", "", txt[:200]))
    r = pd.DataFrame(out, columns=["id", "orden", "a", "b", "mismo", "paso", "razon", "error"])
    r["modelo"], r["rubrica_sha"] = modelo, sha
    r.to_csv(SAL / "51_{}.csv".format(modelo), index=False, encoding="utf-8")
    print("{}: {} respuestas en {:.0f} s ({:.1f} por segundo); errores {}".format(
        modelo, len(r), seg, len(r) / seg, int((r["error"] != "").sum())))


def kappa(y, p):
    po = (y == p).mean()
    pe = (y.mean() * p.mean()) + ((1 - y.mean()) * (1 - p.mean()))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def resumen():
    d = conjuntos()
    out = ["51 · ETIQUETADOR LOCAL CON LA RUBRICA v6, contra juicios del autor",
           "lejos = auditoria D-045 (130 pares, coseno < 0,85); cerca = calibra v6 (187)",
           "{:<16} {:>10} {:>14} {:>14} {:>12} {:>12}".format(
               "modelo", "coherencia", "acierto lejos", "kappa lejos", "acierto cerca", "kappa cerca")]
    mejores = []
    for m in MODELOS:
        f = SAL / "51_{}.csv".format(m)
        if not f.exists():
            out.append("{:<16} (sin correr)".format(m))
            continue
        r = pd.read_csv(f, dtype={"mismo": str}, keep_default_na=False)
        w = r.pivot_table(index="id", columns="orden", values="mismo", aggfunc="first")
        x = d.set_index("id").join(w)
        coh = (x["ab"] == x["ba"]) & x["ab"].isin(["si", "no"])
        x["pred"] = np.where(coh, x["ab"], "incoherente")
        fila = [m, coh.mean()]
        for c in ("lejos", "cerca"):
            g = x[x["conjunto"] == c]
            acierto = (g["pred"] == g["mismo"]).mean()
            gc = g[g["pred"] != "incoherente"]
            fila += [acierto, kappa((gc["mismo"] == "si").astype(int).to_numpy(),
                                    (gc["pred"] == "si").astype(int).to_numpy())]
        out.append("{:<16} {:>10.1%} {:>14.1%} {:>14.2f} {:>12.1%} {:>12.2f}".format(*fila))
        if fila[2] >= UMBRAL_LEJOS and fila[5] >= KAPPA_CERCA:
            mejores.append((fila[2], m))
    out.append("\n>>> CRITERIO: {} <<<".format(
        "se usa {} (acierto lejos {:.1%})".format(max(mejores)[1], max(mejores)[0]) if mejores
        else "ningun modelo cumple (acierto lejos >= 85 % y kappa cerca >= 0,79)"))
    (SAL / "51_etiquetador_local.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", choices=MODELOS)
    ap.add_argument("--tp", type=int, default=1)
    ap.add_argument("--resumen", action="store_true")
    a = ap.parse_args()
    resumen() if a.resumen else correr(a.modelo, a.tp)
