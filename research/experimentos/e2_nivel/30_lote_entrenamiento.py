"""Lote de entrenamiento de la zona dificil: 400 pares para juzgar a mano. D-038, mejora 1.

POR QUE. El analisis de errores (`25`) dejo casi todo el error del cross-encoder en el paso 4
(la funcion principal), sobre todo en el estrato bajo, y justo ahi la plata de Gemini es menos
fiable (kappa 0,53 en bajo). Etiquetas humanas en esa zona le ensenan el criterio del autor
donde Gemini se equivoca. Pasos 1-3 (grado, nivel, seniority) ya los aprendio: no entran.

DE DONDE. Del censo de `16` (coseno 0,90-1,01, grupos distintos), SIN:
    - pares que toquen un grupo de `prueba 2`, `prueba`, `calibra` (13e y 20) o `13a`: el
      entrenamiento no puede tocar ningun examen;
    - pares que ya estan en la plata;
    - los que la capa 0 fusiona por el grado (D-037).
Y solo la zona dificil: la misma palabra de puesto (sin el grado), sin nivel ni marcas de
seniority/ambito distintas (la regla de la rubrica, la de `28`), y con palabras distintas.

COMO SE ELIGEN, 400: 60 % del estrato bajo y 40 % de la banda; en cada uno, la mitad donde el
cross-encoder de H1 duda (P calibrada mas cerca de 0,5: aprendizaje activo) y la mitad al azar
(para no sesgar el lote hacia lo que el modelo no sabe). Cada grupo, como mucho dos veces.

SE JUZGA A CIEGAS CON LA RUBRICA v5 (sin sim, sin P, sin criterio de seleccion).

USO (dos pasos, dos Pythons):
    python3 30_lote_entrenamiento.py candidatos        (Python del sistema: lee el censo)
    .venv/bin/python 30_lote_entrenamiento.py armar    (el .venv: puntua con el cross-encoder)

SALIDAS (con titulos)
    30_candidatos.csv              la zona dificil, antes de elegir (en .gitignore)
    30_lote_pares.csv              metadatos: grupos, sim, estrato, P, criterio. NO abrir antes
    30_lote_para_juzgar.csv        n, comun, raro, emp_comun, emp_raro, mismo, nota
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

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.nivel import (CONECTORES, mismo_salvo_grado,  # noqa: E402
                                         quitar_grado)

CENSO = SAL / "16_censo.parquet"
PLATA = SAL / "16_pares_10000.csv"
EXAMENES = [SAL / "13e_pares_400.csv", SAL / "20_pares_400.csv", SAL / "29_prueba2_pares.csv"]
ORO_48 = SAL / "13_para_juzgar.csv"
CANDIDATOS = SAL / "30_candidatos.csv"
META = SAL / "30_lote_pares.csv"
JUZGAR = SAL / "30_lote_para_juzgar.csv"
ELEGIDO = SAL / "22_modelos" / "elegido"
SEM = 20261004
TOTAL = 400
PARTE_BAJO = 0.60
MAX_POR_GRUPO = 2


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def leer(p):
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig")


def palabras(t):
    return [w for w in quitar_grado(t) if w not in CONECTORES]


def candidatos():
    c28 = cargar("c28", "28_consistencia_calibra.py")
    c = pd.read_parquet(CENSO)
    print("censo: {:,} pares".format(len(c)))

    fuera_g = set()
    for f in EXAMENES:
        m = leer(f)
        fuera_g |= set(m["g_comun"]) | set(m["g_raro"])
    t2g = dict(zip(c["comun"], c["g_comun"])) | dict(zip(c["raro"], c["g_raro"]))
    v = leer(ORO_48)
    v.columns = [x.strip() for x in v.columns]
    fuera_g |= {t2g[t] for t in set(v["comun"].astype(str)) | set(v["raro"].astype(str))
                if t in t2g}
    c = c[~c["g_comun"].isin(fuera_g) & ~c["g_raro"].isin(fuera_g)]
    print("  sin grupos de ningun examen (prueba 2, prueba, calibra, 13a): {:,}".format(len(c)))

    pl = leer(PLATA)
    en_plata = {frozenset(x) for x in zip(pl["g_comun"], pl["g_raro"])}
    c = c[[frozenset(x) not in en_plata for x in zip(c["g_comun"], c["g_raro"])]]
    print("  sin pares que ya estan en la plata: {:,}".format(len(c)))

    capa0 = np.array([mismo_salvo_grado(a, b) for a, b in zip(c["comun"], c["raro"])])
    c = c[~capa0]
    print("  sin los que la capa 0 fusiona por el grado: {:,}".format(len(c)))

    def zona(a, b):
        pa, pb = palabras(a), palabras(b)
        if not pa or not pb or pa[0] != pb[0] or set(pa) == set(pb):
            return False
        return c28.conflicto(a, b) is None
    z = np.array([zona(a, b) for a, b in zip(c["comun"], c["raro"])])
    c = c[z].copy()
    c["estrato"] = np.where(c["sim"] < 0.93, "bajo", np.where(c["sim"] < 0.97, "banda", "alto"))
    print("  zona dificil (misma palabra de puesto, sin nivel ni marcas distintas): {:,}"
          .format(len(c)), c["estrato"].value_counts().to_dict())
    c.to_csv(CANDIDATOS, index=False, encoding="utf-8")
    print("-> {}".format(CANDIDATOS.name))


def armar():
    if JUZGAR.exists():
        p = pd.read_csv(JUZGAR, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                        keep_default_na=False)
        if (p["mismo"].str.strip() != "").any():
            raise SystemExit("{} ya tiene juicios; no se sobrescribe.".format(JUZGAR.name))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    from transformers import AutoTokenizer
    e22 = cargar("e22", "22_entrenar_cross.py")
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    c = pd.read_csv(CANDIDATOS)
    c = c[c["estrato"].isin(["bajo", "banda"])].reset_index(drop=True)
    info = json.loads((ELEGIDO / "info.json").read_text(encoding="utf-8"))
    tok = AutoTokenizer.from_pretrained(ELEGIDO)
    juez = e22.construir(ELEGIDO, False, dev)
    ab, ba = e22.puntuar(juez, tok, c["comun"].tolist(), c["raro"].tolist(), dev,
                         contextlib.nullcontext)
    s = ab * ba
    z = np.log(np.clip(s, 1e-6, 1 - 1e-6) / np.clip(1 - s, 1e-6, 1))
    c["P"] = 1 / (1 + np.exp(-z / info["temperatura"]))
    c["duda"] = -np.abs(c["P"] - 0.5)
    print("candidatos puntuados: {:,}".format(len(c)))

    rng = np.random.default_rng(SEM)
    usados, elegidos = {}, []

    def tomar(df, n, criterio):
        tomados = 0
        for i, f in df.iterrows():
            if tomados == n:
                break
            if i in usados or usados_grupo(f):
                continue
            usados[i] = criterio
            for g in (f["g_comun"], f["g_raro"]):
                cuenta[g] = cuenta.get(g, 0) + 1
            elegidos.append(i)
            tomados += 1
        return tomados

    cuenta = {}

    def usados_grupo(f):
        return (cuenta.get(f["g_comun"], 0) >= MAX_POR_GRUPO
                or cuenta.get(f["g_raro"], 0) >= MAX_POR_GRUPO)

    n_bajo = round(TOTAL * PARTE_BAJO)
    for est, n in (("bajo", n_bajo), ("banda", TOTAL - n_bajo)):
        d = c[c["estrato"] == est]
        a = tomar(d.sort_values("duda", ascending=False), n // 2, "duda del modelo")
        b = tomar(d.sample(frac=1.0, random_state=int(rng.integers(1 << 30))), n - a, "azar")
        print("  {}: {} por duda + {} al azar".format(est, a, b))

    m = c.loc[elegidos].copy()
    m["criterio"] = [usados[i] for i in elegidos]
    m = m.sample(frac=1.0, random_state=SEM).reset_index(drop=True)
    m.insert(0, "n", range(1, len(m) + 1))
    m.to_csv(META, index=False, encoding="utf-8-sig", sep=";")
    j = m[["n", "comun", "raro", "emp_comun", "emp_raro"]].copy()
    j["mismo"] = ""
    j["nota"] = ""
    j.to_csv(JUZGAR, index=False, encoding="utf-8-sig", sep=";")
    print("\n  lote: {} pares  por estrato {}  por criterio {}".format(
        len(m), m["estrato"].value_counts().to_dict(), m["criterio"].value_counts().to_dict()))
    print("  P del modelo: mediana {:.2f} (por duda) / {:.2f} (al azar)".format(
        m.loc[m["criterio"] == "duda del modelo", "P"].median(),
        m.loc[m["criterio"] == "azar", "P"].median()))
    print("\n  para juzgar -> {}   (rubrica v5, a ciegas)".format(JUZGAR.name))
    print("  metadatos   -> {}   (NO abrir antes de juzgar)".format(META.name))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["candidatos", "armar"])
    a = ap.parse_args()
    candidatos() if a.accion == "candidatos" else armar()
