"""D-045 §3: los dos lotes de Gemini para el bi-encoder, en modo batch y con la disciplina de D-035.

    descripciones   una descripcion corta de cada nodo de base_v16 (58.051), capa A0: solo sirve
                    para RECUPERAR candidatos; nunca entra al juez (D-036, Enmienda 1 §7).
    propuestas      para ~5.000 nodos sorteados con peso por personas, hasta 20 titulos que sean
                    el mismo cargo (positivos lejanos; la v3 los confirma despues).

Los ejemplos de las instrucciones NO son ninguno de los cinco casos conocidos que se evaluan
(D-045 §5): un ejemplo en la instruccion le daria a Gemini la respuesta de antemano.

Disciplina de D-035: version de modelo fija, temperatura 0, semilla, respuesta JSON con esquema,
hash de la instruccion guardado con cada salida, y todo queda en disco (no se repite una llamada).

USO (desde la raiz del repo, con el entorno `.venv-gemini`):
    python 46_gemini_lotes.py preparar --tipo descripciones     arma la entrada (no llama a nada)
    python 46_gemini_lotes.py enviar   --tipo descripciones     sube y crea el lote
    python 46_gemini_lotes.py estado   --tipo descripciones     en que va
    python 46_gemini_lotes.py bajar    --tipo descripciones     baja, guarda y muestra 30 al azar

La clave se lee de GEMINI_API_KEY (o de ~/.config/gemini_key); nunca se imprime ni se escribe.

SALIDAS (salidas/, en .gitignore salvo el manifiesto): 46_<tipo>_entrada.jsonl,
46_<tipo>_lote.json (manifiesto: modelo, hash, n, nombre del lote), 46_<tipo>.csv
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
MODELO = "gemini-3.8-flash"          # el de D-035
SEM = 20261004
N_PROPUESTAS = 5000

INSTRUCCION = {
    "descripciones": (
        "Eres un analista de puestos de trabajo en Ecuador. Recibes el titulo de un cargo tal como "
        "aparece en una nomina (en mayusculas, a veces con abreviaturas o errores de tipeo). "
        "Escribe UNA frase en espanol, de 8 a 20 palabras, que diga que hace esa persona: sus "
        "tareas principales y su area. Usa palabras comunes, distintas de las del titulo cuando "
        "puedas (por ejemplo, para BODEGUERO: 'recibe, ordena y despacha la mercaderia del "
        "almacen y lleva su inventario'). No inventes nivel, sector ni empresa que el titulo no diga. "
        "Si el titulo no es un cargo o no se entiende, responde con descripcion vacia."),
    "propuestas": (
        "Eres un analista de puestos de trabajo en Ecuador. Recibes el titulo de un cargo tal como "
        "aparece en una nomina. Propon hasta 20 OTROS titulos con los que distintas empresas "
        "ecuatorianas nombran EXACTAMENTE ese mismo puesto: mismo trabajo, mismo nivel y misma "
        "antiguedad (por ejemplo, BODEGUERO: ALMACENERO, OPERARIO DE BODEGA). Escribe "
        "cada titulo en MAYUSCULAS y sin tildes, como en una nomina. No propongas puestos de otro "
        "nivel (ni jefes ni ayudantes del puesto), ni variantes que solo cambien una letra, el "
        "genero o el plural. Si no hay sinonimos claros, devuelve la lista vacia."),
}
ESQUEMA = {
    "descripciones": {"type": "object", "properties": {"descripcion": {"type": "string"}},
                      "required": ["descripcion"]},
    "propuestas": {"type": "object", "properties": {"titulos": {"type": "array",
                                                                "items": {"type": "string"},
                                                                "maxItems": 20}},
                   "required": ["titulos"]},
}


def sha(tipo):
    return hashlib.sha256((MODELO + INSTRUCCION[tipo] + json.dumps(
        ESQUEMA[tipo], sort_keys=True)).encode("utf-8")).hexdigest()[:12]


def rutas(tipo):
    return (SAL / "46_{}_entrada.jsonl".format(tipo), SAL / "46_{}_lote.json".format(tipo),
            SAL / "46_{}.csv".format(tipo))


def cliente():
    clave = os.environ.get("GEMINI_API_KEY")
    if not clave:
        f = pathlib.Path.home() / ".config" / "gemini_key"
        clave = f.read_text().strip() if f.exists() else None
    if not clave:
        sys.exit("Falta la clave: exporta GEMINI_API_KEY o crea ~/.config/gemini_key.")
    from google import genai
    return genai.Client(api_key=clave)


def nodos():
    spec = importlib.util.spec_from_file_location("e43", AQUI / "43_perdida_vertex.py")
    e43 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e43)
    tit, _, per = e43.nodos()
    return tit, per


def preparar(tipo):
    tit, per = nodos()
    if tipo == "descripciones":
        ix = np.arange(len(tit))
    else:
        rng = np.random.default_rng(SEM)
        ix = np.sort(rng.choice(len(tit), N_PROPUESTAS, replace=False, p=per / per.sum()))
    entrada, manifiesto, _ = rutas(tipo)
    cfg = {"temperature": 0.0, "seed": SEM, "responseMimeType": "application/json",
           "responseJsonSchema": ESQUEMA[tipo]}
    with open(entrada, "w", encoding="utf-8") as f:
        for i in ix:
            f.write(json.dumps({"key": str(int(i)), "request": {
                "systemInstruction": {"parts": [{"text": INSTRUCCION[tipo]}]},
                "contents": [{"role": "user", "parts": [{"text": str(tit[i])}]}],
                "generationConfig": cfg}}, ensure_ascii=False) + "\n")
    caracteres = len(INSTRUCCION[tipo]) * len(ix) + sum(len(str(tit[i])) for i in ix)
    man = {"tipo": tipo, "modelo": MODELO, "instruccion_sha": sha(tipo), "n": int(len(ix)),
           "semilla": SEM, "preparado": dt.datetime.now().isoformat(timespec="seconds"),
           "entrada_sha256_12": hashlib.sha256(entrada.read_bytes()).hexdigest()[:12],
           "tokens_entrada_aprox": int(caracteres / 4)}
    manifiesto.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(man, ensure_ascii=False, indent=2))


def enviar(tipo):
    entrada, manifiesto, _ = rutas(tipo)
    man = json.loads(manifiesto.read_text(encoding="utf-8"))
    if man.get("lote"):
        sys.exit("Este lote ya se envio ({}). Usa `estado`.".format(man["lote"]))
    if hashlib.sha256(entrada.read_bytes()).hexdigest()[:12] != man["entrada_sha256_12"]:
        sys.exit("ALTO: la entrada cambio desde `preparar`.")
    cli = cliente()
    from google.genai import types
    print("subiendo {} ({:,} peticiones)...".format(entrada.name, man["n"]))
    archivo = cli.files.upload(file=str(entrada), config=types.UploadFileConfig(
        display_name=entrada.name, mime_type="jsonl"))
    lote = cli.batches.create(model=MODELO, src=archivo.name, config={
        "display_name": "d045-{}-{}".format(tipo, man["instruccion_sha"])})
    man.update({"lote": lote.name, "archivo_entrada": archivo.name,
                "enviado": dt.datetime.now().isoformat(timespec="seconds")})
    manifiesto.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    print("lote creado: {}  estado: {}".format(lote.name, lote.state))


def estado(tipo):
    man = json.loads(rutas(tipo)[1].read_text(encoding="utf-8"))
    cli = cliente()          # guardado: si el cliente es temporal, se cierra antes de llamar
    lote = cli.batches.get(name=man["lote"])
    print("{}  estado: {}".format(lote.name, lote.state))
    if getattr(lote, "batch_stats", None):
        print(lote.batch_stats)
    return lote


def bajar(tipo):
    _, manifiesto, salida = rutas(tipo)
    man = json.loads(manifiesto.read_text(encoding="utf-8"))
    cli = cliente()
    lote = cli.batches.get(name=man["lote"])
    if str(lote.state) not in ("JobState.JOB_STATE_SUCCEEDED", "JOB_STATE_SUCCEEDED"):
        sys.exit("El lote no termino: {}".format(lote.state))
    crudo = cli.files.download(file=lote.dest.file_name).decode("utf-8")
    tit, _ = nodos()
    filas = []
    for linea in crudo.splitlines():
        r = json.loads(linea)
        i = int(r["key"])
        texto, error = "", ""
        try:
            texto = r["response"]["candidates"][0]["content"]["parts"][0]["text"]
            json.loads(texto)
        except (KeyError, IndexError, ValueError):
            error = json.dumps(r.get("error") or r.get("response", {}))[:300]
        filas.append({"nodo": i, "titulo": str(tit[i]), "respuesta": texto, "error": error,
                      "modelo": MODELO, "instruccion_sha": man["instruccion_sha"]})
    d = pd.DataFrame(filas).sort_values("nodo")
    d.to_csv(salida, index=False, encoding="utf-8")
    ok = d[d["error"] == ""]
    print("{:,} respuestas; {:,} con error; guardadas en {}".format(len(d), len(d) - len(ok),
                                                                  salida.name))
    man.update({"bajado": dt.datetime.now().isoformat(timespec="seconds"),
                "respuestas": int(len(d)), "errores": int(len(d) - len(ok))})
    manifiesto.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    muestra = ok.sample(min(30, len(ok)), random_state=SEM)
    print("\n30 AL AZAR (para revisar que no salgan genericas):")
    for _, r in muestra.iterrows():
        v = json.loads(r["respuesta"])
        v = v.get("descripcion") if tipo == "descripciones" else ", ".join(v.get("titulos", []))
        print("  {:<40} -> {}".format(r["titulo"][:40], v))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["preparar", "enviar", "estado", "bajar"])
    ap.add_argument("--tipo", required=True, choices=list(INSTRUCCION))
    a = ap.parse_args()
    {"preparar": preparar, "enviar": enviar, "estado": estado, "bajar": bajar}[a.accion](a.tipo)
