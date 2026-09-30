"""Donde se equivoca el cross-encoder de H1. Para decidir que pares juzgar a mano (D-038).

NO MIRA `prueba`. `prueba` ya se abrio una vez (H1) y el cross-encoder v2 tendra su propio
examen (`prueba 2`); para que ese examen valga, lo que se decida sobre la v2 no puede salir
de mirar los errores en `prueba`. Aqui se usan:
    calibra   191 pares con juicio humano. Optimista (eligio epoca, semilla y configuracion),
              pero es el unico sitio donde el error es contra TU criterio.
    valida    1.500 pares de la plata con etiqueta de Gemini (o humana en los 139). El error
              aqui es desacuerdo con Gemini: dice donde el cross-encoder NO imita a la plata.

QUE SE MIDE, por rasgo del par (los rasgos salen solo de los titulos, sin sueldos):
    estrato        el de `13e`/`16`: coseno 0,90-0,93 / 0,93-0,97 / >= 0,97
    escalon        palabras de rango en niveles distintos (`nivel_lexico`)
    seniority      marca de seniority distinta (`seniority_lexica`)
    grado          alguno lleva grado (`tiene_grado`, D-037)
    contenido      las palabras de uno estan todas en el otro: funcion anadida o acotada
    misma_cabeza   la primera palabra (la del puesto) coincide
    sigla          alguno lleva `.`, `/` o `&`
    ingles         alguna palabra inglesa frecuente (MANAGER, ASSISTANT, ...)
    solapamiento   Jaccard de palabras (sin conectores), en tercios
y por el paso de la rubrica que dio Gemini (solo `valida`).

Para cada grupo: n, tasa de `si`, AUC del cross-encoder, y errores con P calibrada >= 0,5
(junta de mas / separa de mas).

SALIDAS
    25_analisis_errores.txt        agregados, sin titulos (versionado)
    25_errores_calibra.csv         los pares de calibra con su P y rasgos (en .gitignore)
    25_errores_valida.csv          lo mismo para valida (en .gitignore)
"""
import argparse
import contextlib
import importlib.util
import json
import os
import pathlib
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.nivel import (CONECTORES, nivel_lexico,  # noqa: E402
                                         seniority_lexica, tiene_grado)

ELEGIDO = SAL / "22_modelos" / "elegido"
PAQUETE = SAL / "21_paquete"
INGLES = {"MANAGER", "ASSISTANT", "ANALYST", "LEADER", "SUPERVISOR", "SPECIALIST",
          "ENGINEER", "COORDINATOR", "SALES", "OFFICER", "HEAD", "SENIOR", "JUNIOR",
          "DEVELOPER", "EXECUTIVE", "REPRESENTATIVE", "SERVICE", "CUSTOMER", "KEY",
          "ACCOUNT", "PLANNER", "BUYER", "TRAINEE"}


def cargar_22():
    spec = importlib.util.spec_from_file_location("e22", AQUI / "22_entrenar_cross.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def palabras(t):
    return [w for w in str(t).upper().replace("/", " ").replace("-", " ").split()
            if w not in CONECTORES]


def rasgos(a, b, sim):
    pa, pb = palabras(a), palabras(b)
    sa, sb = set(pa), set(pb)
    na, nb = nivel_lexico(a), nivel_lexico(b)
    jac = len(sa & sb) / max(len(sa | sb), 1)
    return {
        "escalon": bool(na is not None and nb is not None and na == na and nb == nb
                        and na != nb),
        "seniority": seniority_lexica(a) != seniority_lexica(b),
        "grado": tiene_grado(a) or tiene_grado(b),
        "contenido": (sa < sb) or (sb < sa),
        "misma_cabeza": bool(pa and pb and pa[0] == pb[0]),
        "sigla": any(c in f"{a} {b}" for c in "./&"),
        "ingles": bool((sa | sb) & INGLES) and not ({"SUPERVISOR"} >= ((sa | sb) & INGLES)),
        "solapamiento": "bajo (<1/3)" if jac < 1 / 3 else ("medio" if jac < 2 / 3
                                                           else "alto (>=2/3)"),
    }


def tabla(d, col, out):
    out("\n  por {}:".format(col))
    out("    {:<16} {:>5} {:>6} {:>7} {:>11} {:>11}".format(
        "", "n", "% si", "AUC", "junta mal", "separa mal"))
    for k, g in d.groupby(col, sort=True):
        y, p = g["y"].to_numpy(), g["P"].to_numpy()
        a = "{:.3f}".format(roc_auc_score(y, p)) if len(set(y)) == 2 else "  —"
        fp = int(((p >= .5) & (y == 0)).sum())
        fn = int(((p < .5) & (y == 1)).sum())
        out("    {:<16} {:>5} {:>5.0f}% {:>7} {:>5}/{:<5} {:>5}/{:<5}".format(
            str(k), len(g), 100 * y.mean(), a, fp, int((y == 0).sum()), fn,
            int((y == 1).sum())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dispositivo", default="auto", choices=["auto", "cuda", "cpu"])
    args = ap.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    from transformers import AutoTokenizer

    e22 = cargar_22()
    dev = ("cuda" if torch.cuda.is_available() else "cpu") if args.dispositivo == "auto" \
        else args.dispositivo
    info = json.loads((ELEGIDO / "info.json").read_text(encoding="utf-8"))
    T = info["temperatura"]
    tok = AutoTokenizer.from_pretrained(ELEGIDO)
    juez = e22.construir(ELEGIDO, False, dev)

    cal = pd.read_csv(PAQUETE / "calibra.csv", dtype={"n": str}, keep_default_na=False)
    cal["y"] = (cal["mismo"] == "si").astype(int)
    pla = pd.read_csv(PAQUETE / "plata.csv", dtype={"n": str, "motivo": str},
                      keep_default_na=False)
    val = pla[pla["particion"] == "valida"].copy()
    val["y"] = (val["etiqueta"].astype(float) >= 0.5).astype(int)

    lineas = []

    def out(s=""):
        print(s, flush=True)
        lineas.append(s)

    out("=" * 78)
    out("25 · DONDE SE EQUIVOCA EL CROSS-ENCODER DE H1   ({}, T = {:.3f})".format(
        info["nombre"], T))
    out("=" * 78)
    out("P = probabilidad calibrada; 'junta mal' = P >= 0,5 con etiqueta no;")
    out("'separa mal' = P < 0,5 con etiqueta si. `prueba` no se mira.")

    for nombre, d, destino in (("CALIBRA (juicio humano)", cal, "25_errores_calibra.csv"),
                               ("VALIDA (etiqueta de Gemini)", val, "25_errores_valida.csv")):
        ab, ba = e22.puntuar(juez, tok, d["comun"].tolist(), d["raro"].tolist(), dev,
                             contextlib.nullcontext)
        s = ab * ba
        z = np.log(np.clip(s, 1e-6, 1 - 1e-6) / np.clip(1 - s, 1e-6, 1))
        d["P"] = 1 / (1 + np.exp(-z / T))
        d["P_ab"], d["P_ba"] = ab, ba
        r = pd.DataFrame([rasgos(a, b, float(x)) for a, b, x in
                          zip(d["comun"], d["raro"], d["sim"].astype(float))], index=d.index)
        d = pd.concat([d, r], axis=1)
        y, p = d["y"].to_numpy(), d["P"].to_numpy()
        out("\n" + nombre + ": {} pares ({} si / {} no)   AUC {:.3f}   junta mal {}   "
            "separa mal {}".format(len(d), y.sum(), len(y) - y.sum(), roc_auc_score(y, p),
                                   int(((p >= .5) & (y == 0)).sum()),
                                   int(((p < .5) & (y == 1)).sum())))
        for col in ("estrato", "escalon", "seniority", "grado", "contenido",
                    "misma_cabeza", "sigla", "ingles", "solapamiento"):
            tabla(d, col, out)
        if "motivo" in d and nombre.startswith("VALIDA"):
            tabla(d.assign(paso_gemini=d["motivo"].replace("", "(sin paso)")),
                  "paso_gemini", out)
        d["error"] = np.where((p >= .5) & (y == 0), "junta mal",
                              np.where((p < .5) & (y == 1), "separa mal", ""))
        d["confianza_error"] = np.where(d["error"] == "junta mal", p,
                                        np.where(d["error"] == "separa mal", 1 - p, 0))
        cols = ["n", "comun", "raro", "sim", "y", "P", "P_ab", "P_ba", "error",
                "confianza_error", "estrato", "escalon", "seniority", "grado", "contenido",
                "misma_cabeza", "sigla", "ingles", "solapamiento"]
        cols += [c for c in ("motivo", "origen") if c in d]
        d.sort_values("confianza_error", ascending=False)[cols].to_csv(
            SAL / destino, index=False, encoding="utf-8")
        out("  -> {} (con titulos; en .gitignore)".format(destino))

    (SAL / "25_analisis_errores.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
