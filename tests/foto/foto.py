"""La FOTO de las respuestas de la API: la red de seguridad del refactor a backend.

  grabar    pide a una API en marcha un conjunto fijo de informes, referencias y
            sugerencias, y guarda entradas y respuestas en un .json.gz
  comparar  repite EXACTAMENTE las mismas peticiones contra otra API (la refactorizada)
            y compara valor por valor. Un decimal distinto es un fallo.

Habla por HTTP, asi que no depende de como este organizado el codigo por dentro: sirve
igual antes y despues del refactor. El cambio de contrato (sobre `BaseResponseModel`,
informe sincrono) se absorbe en `_contenido` y `_informe`.

La foto lleva cargos y referencias salidos de la base real: NO VA AL REPO. Por defecto se
guarda en `~/fotos-benchmarking/`.

Uso:
  python tests/foto/foto.py grabar   --url http://127.0.0.1:8097 --base demo/base_v31.npz
  python tests/foto/foto.py comparar --url http://127.0.0.1:8098
"""

import argparse
import gzip
import json
import math
import pathlib
import random
import sys
import time

import numpy as np
import pandas as pd
import requests

from src.services.informe_service import CLAVES_DATO
from src.shared.utils.conversion import a_camel, claves_a_camel

FOTO = pathlib.Path.home() / "fotos-benchmarking" / "foto_v1.3.json.gz"
SEMILLA = 20261023
# Lo que cambia entre corridas sin que cambie la respuesta
VOLATILES = {"id", "caduca_en_s", "carga_s", "titulos_nuevos_embebidos", "fecha_carga"}

# Titulos a mano: los que ya usamos en las pruebas, ingles, erratas, grados y basura
A_MANO = [
    "Asistente Administrativo",
    "Auxiliar de Bodega",
    "Auxiliar de Farmacia",
    "Gerente de Operaciones",
    "Jefe de Bodega",
    "CONTADOR",
    "Contdor Generl",
    "ASIST. CONTABLE",
    "AUXILIAR 3 DE CONTABILIDAD",
    "Chief Operational Officer",
    "Head of Insurance - Consulting",
    "Country Manager",
    "Sales Manager",
    "CEO",
    "General Accountant",
    "Software Engineer",
    "VENDEROR",
    "CONDUCTOR",
    "TALENTO HUMANO",
    "JEFE DE SEGURIDAD PATRIMONIAL",
    "LOTERO",
    "OPERADOR DE PARQUEADERO",
    "XXXX",
    "123",
    "",
    "GERENTE GENERAL",
    "Data Scientist",
    "Head of AI",
    "Recepcionista bilingue",
]


def _perturbar(t: str, rng: random.Random) -> str:
    """Formas en que un cliente escribe un cargo que la base tiene."""
    op = rng.randrange(5)
    if op == 0:
        return t.title()
    if op == 1 and len(t) > 6:
        i = rng.randrange(1, len(t) - 1)
        return t[:i] + t[i + 1 :]  # errata
    if op == 2:
        return f"{t} {rng.choice(['1', '2', 'III', 'SR', 'JR'])}"
    if op == 3:
        return t.lower()
    return t


def construir_entradas(ruta_base: str) -> dict:
    rng = random.Random(SEMILLA)
    z = np.load(ruta_base, allow_pickle=True)
    celdas = [str(c) for c in z["celdas"]]
    muestra = rng.sample(celdas, 220)
    titulos = A_MANO + [_perturbar(t, rng) for t in muestra]
    # RUCs del padron con CIIU, de dos secciones distintas, para la cascada
    rucs = [str(r) for r in z["ruc_lista"]]
    ciius = [str(c) for c in z["ruc_ciiu"]]
    con = [(r, c) for r, c in zip(rucs, ciius) if c]
    ruc_g = next(r for r, c in con if c.startswith("G46"))
    ruc_c = next(r for r, c in con if c.startswith("C10"))

    nomina = pd.DataFrame({"cargo": titulos, "sueldo": [round(rng.uniform(460, 6000), 2) for _ in titulos]})
    corta = nomina.head(40)
    informes = [
        {"nombre": "sin_parametros", "csv": nomina.to_csv(index=False), "form": {}},
        {"nombre": "segmento_mediana", "csv": nomina.to_csv(index=False), "form": {"segmento": "MEDIANA"}},
        {"nombre": "rubro_g", "csv": corta.to_csv(index=False), "form": {"rubro": "G"}},
        {"nombre": "ruc_g46", "csv": corta.to_csv(index=False), "form": {"ruc": ruc_g}},
        {"nombre": "ruc_c10_grande", "csv": corta.to_csv(index=False), "form": {"ruc": ruc_c, "segmento": "GRANDE"}},
        {
            "nombre": "mapeo",
            "csv": corta.to_csv(index=False),
            "form": {"mapeo": json.dumps({"3": "JEFE DE BODEGA", "20": "ODONTOLOGA"})},
        },
        {"nombre": "solo_numeros", "csv": corta.to_csv(index=False), "form": {"columnas_originales": "false"}},
        {"nombre": "anio_2025", "csv": corta.to_csv(index=False), "form": {"anio": "2025"}},
    ]
    sueltos = [t for t in titulos if t][:70]
    referencias = []
    for t in sueltos:
        referencias.append({"cargo": t})
    for t in sueltos[:25]:
        referencias += [{"cargo": t, "segmento": "GRANDE"}, {"cargo": t, "rubro": "C"}, {"cargo": t, "ruc": ruc_g}]
    puestos = [
        {"q": q}
        for q in [
            "CHOFER",
            "contador",
            "jefe de bod",
            "gerente",
            "AUXILIAR",
            "Sales",
            "analista de credito",
            "enfermera",
            "XX",
            "Head of",
            "ASIST",
            "operador",
        ]
    ]
    return {"semilla": SEMILLA, "informes": informes, "referencias": referencias, "puestos": puestos}


# ---- adaptadores al contrato --------------------------------------------------------


def _es_contrato_nuevo(url: str) -> bool:
    """La API refactorizada tiene `/health` y el sobre; la v1.3 no."""
    try:
        return requests.get(f"{url}/health", timeout=30).status_code == 200
    except requests.RequestException:
        return False


def _contenido(r: requests.Response):
    """Lo util de una respuesta, con o sin el sobre `BaseResponseModel`."""
    d = r.json()
    if isinstance(d, dict) and {"status", "content"} <= set(d) and "message" in d:
        if d["status"] != 0:
            return {"_http": r.status_code, "_message": d["message"]}
        c = d["content"]
        return {"_http": r.status_code, **(c if isinstance(c, dict) else {"_lista": c})}
    if r.status_code >= 400 and isinstance(d, dict) and "detail" in d:
        return {"_http": r.status_code, "_message": d["detail"]}
    return {"_http": r.status_code, **(d if isinstance(d, dict) else {"_lista": d})}


def _informe(url: str, e: dict, nuevo: bool) -> dict:
    files = {"archivo": ("nomina.csv", e["csv"].encode())}
    form = {"formato_libre": "true", "columna_cargo": "cargo", **e["form"]}
    if nuevo:
        form = {a_camel(k): v for k, v in form.items()}
    r = requests.post(f"{url}/informes", files=files, data=form, timeout=600)
    if r.status_code == 202:  # contrato viejo: 202 + consulta
        tid = r.json()["id"]
        while True:
            q = requests.get(f"{url}/informes/{tid}", timeout=60)
            if q.json().get("estado") not in ("en_cola", "procesando"):
                return {"_http": q.status_code, **q.json()}
            time.sleep(1)
    return _contenido(r)


def pedir_todo(url: str, entradas: dict) -> dict:
    nuevo = _es_contrato_nuevo(url)
    print(f"  contrato {'nuevo (sobre + camelCase)' if nuevo else 'v1.3'}", flush=True)
    out = {"informes": {}, "referencias": [], "puestos": []}
    for e in entradas["informes"]:
        out["informes"][e["nombre"]] = _informe(url, e, nuevo)
        print(f"  informe {e['nombre']}", flush=True)
    for p in entradas["referencias"]:
        out["referencias"].append(_contenido(requests.get(f"{url}/referencia", params=p, timeout=120)))
    print(f"  {len(out['referencias'])} referencias", flush=True)
    for p in entradas["puestos"]:
        out["puestos"].append(_contenido(requests.get(f"{url}/puestos", params=p, timeout=120)))
    print(f"  {len(out['puestos'])} sugerencias", flush=True)
    return out


# ---- comparacion --------------------------------------------------------------------


def _diferencias(a, b, ruta="", out=None, rtol=1e-9):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in VOLATILES:
                continue
            if k not in a or k not in b:
                out.append(f"{ruta}.{k}: {'falta en la nueva' if k not in b else 'sobra en la nueva'}")
            else:
                _diferencias(a[k], b[k], f"{ruta}.{k}", out, rtol)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{ruta}: largo {len(a)} -> {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            _diferencias(x, y, f"{ruta}[{i}]", out, rtol)
    elif isinstance(a, float) or isinstance(b, float):
        if (
            a is None
            or b is None
            or not ((math.isnan(a) and math.isnan(b)) or math.isclose(a, b, rel_tol=rtol, abs_tol=1e-12))
        ):
            out.append(f"{ruta}: {a!r} -> {b!r}")
    elif a != b:
        out.append(f"{ruta}: {a!r} -> {b!r}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["grabar", "comparar"])
    ap.add_argument("--url", required=True)
    ap.add_argument("--base", default="demo/base_v31.npz", help="solo para grabar")
    ap.add_argument("--foto", default=str(FOTO))
    ap.add_argument("--ignorar", default="", help="claves extra a ignorar, separadas por coma")
    a = ap.parse_args()
    VOLATILES.update(k for k in a.ignorar.split(",") if k)
    ruta = pathlib.Path(a.foto)

    if a.modo == "grabar":
        entradas = construir_entradas(a.base)
        respuestas = pedir_todo(a.url, entradas)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(ruta, "wt") as f:
            json.dump({"entradas": entradas, "respuestas": respuestas}, f)
        print(f"foto guardada en {ruta}")
        return

    with gzip.open(ruta, "rt") as f:
        foto = json.load(f)
    nuevas = pedir_todo(a.url, foto["entradas"])
    viejas = foto["respuestas"]
    if _es_contrato_nuevo(a.url):
        # la foto es v1.3: se lleva a la forma nueva con LAS MISMAS reglas que la API, y se
        # ignora solo lo que el contrato nuevo agrega
        def conv(x):
            return claves_a_camel(
                x, conservar=frozenset({"cargo", "sueldo", "_http", "_message", "_lista"}), claves_dato=CLAVES_DATO
            )

        viejas = {
            "informes": {k: conv(v) for k, v in viejas["informes"].items()},
            "referencias": [conv(x) for x in viejas["referencias"]],
            "puestos": [conv(x) for x in viejas["puestos"]],
        }
        VOLATILES.update({"estado", "idCarga", "filas", "columnaCargo", "empresa", "excelBase64"})
        VOLATILES.update({a_camel(k) for k in list(VOLATILES)})
    difs = _diferencias(viejas, nuevas)
    if difs:
        print(f"{len(difs)} DIFERENCIAS. Las primeras:")
        for d in difs[:40]:
            print("  ", d)
        sys.exit(1)
    print("identica a la foto")


if __name__ == "__main__":
    main()
