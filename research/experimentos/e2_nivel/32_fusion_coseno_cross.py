"""Criterio B de D-040: ¿la fusion por coseno >= 0,95 (D-015) junta cosas que el cross rechaza?

QUE SE MIDE (criterio registrado antes en D-040, commit 2c620e8):
    - todos los pares que la fusion semantica unio en `base_v15`: coseno >= 0,95 DENTRO del
      mismo grupo (con enlace completo, todo par de un grupo semantico pasa el umbral; los que
      unieron las pasadas de errata o genero sin llegar a 0,95 no cuentan);
    - el cross-encoder v2 (juez operativo, D-039), en fp32, con P calibrada (T de la v2);
    - "rechazado" = P < 0,5.
    Se confirma, y D-015 se enmienda, si el cross rechaza >= 1 % de los pares Y al menos la mitad
    de 50 rechazados revisados a mano son de verdad distintos.

LA REVISION ES CIEGA Y MEZCLADA: 50 rechazados y 50 aceptados, al azar, barajados, sin `sim`,
sin P y sin marcar cual es cual. Se juzgan con la rubrica v5.

DESCRIPTIVO, aparte: cuantos de esos pares juntaria igual la capa 0 de texto (prefijo,
puntuacion, grado al final): esos no dependen de D-015.

USO
    python 32_fusion_coseno_cross.py medir      puntua, informa y arma la revision
    (juzgar `32_revisar_coseno.csv`: `mismo` = si / no, a ciegas)
    python 32_fusion_coseno_cross.py evaluar    lee los juicios y aplica el criterio B

SALIDAS
    32_fusion_coseno.txt          informe (agregados; sin titulos)
    32_pares_coseno.csv           los 24.654 pares con su P (titulos; en .gitignore)
    32_revisar_coseno.csv         los 100 a ciegas (titulos; se versiona con -f)
    32_revisar_coseno_mapa.csv    n -> par, P, rechazado. NO se abre antes de juzgar
"""
import argparse
import contextlib
import importlib.util
import json
import os
import pathlib
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.nivel import _es_grado  # noqa: E402

BASE = RAIZ / "demo" / "base_v15.npz"
V2 = SAL / "22_modelos_v2" / "elegido"
INFORME = SAL / "32_fusion_coseno.txt"
PARES = SAL / "32_pares_coseno.csv"
REVISAR = SAL / "32_revisar_coseno.csv"
MAPA = SAL / "32_revisar_coseno_mapa.csv"
UMBRAL = 0.95
SEM = 20261006
N_REVISION = 50
PREF = re.compile(r"^(?:[\d.\-*+#'\[\]()]+\s*|\d+[.\-]?\d*\s+)+")


def limpia(t):
    """Borrador de la limpieza de D-040: sin codigo inicial ni puntuacion."""
    s = PREF.sub("", str(t).strip())
    s = s if re.search(r"[A-Z]", s) else str(t)
    return " ".join(re.sub(r"[^\w\s]|_", " ", s).split())


def sin_grado_final(t):
    ws = t.split()
    while ws and (_es_grado(ws[-1]) or (len(ws[-1]) == 1 and ws[-1].isalpha()
                                        and ws[-1] not in "EYOU")):
        ws = ws[:-1]
        if ws and ws[-1] in ("NIVEL", "GRADO", "CATEGORIA", "LEVEL", "CAT"):
            ws = ws[:-1]
    return " ".join(ws)


def medir():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    from transformers import AutoTokenizer
    spec = importlib.util.spec_from_file_location("e22", AQUI / "22_entrenar_cross.py")
    e22 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e22)

    b = np.load(BASE, allow_pickle=True)
    cel = [str(c) for c in b["celdas"]]
    g = b["grupo"].astype(int)
    Z = b["Z"]
    miem = defaultdict(list)
    for i, x in enumerate(g):
        miem[x].append(i)
    filas = []
    for m in miem.values():
        for a in range(len(m)):
            for c in range(a + 1, len(m)):
                i, j = m[a], m[c]
                s = float(Z[i] @ Z[j])
                if s >= UMBRAL:
                    filas.append((i, j, cel[i], cel[j], s))
    d = pd.DataFrame(filas, columns=["i", "j", "a", "b", "sim"])

    info = json.loads((V2 / "info.json").read_text(encoding="utf-8"))
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(V2)
    juez = e22.construir(V2, False, dev)
    ab, ba = e22.puntuar(juez, tok, d["a"].tolist(), d["b"].tolist(), dev,
                         contextlib.nullcontext)
    s = e22.puntaje(info["modo"], ab, ba)
    z = np.log(np.clip(s, 1e-6, 1 - 1e-6) / np.clip(1 - s, 1e-6, 1))
    d["P"] = 1 / (1 + np.exp(-z / info["temperatura"]))
    d["rechazado"] = d["P"] < 0.5
    d["texto_igual"] = [sin_grado_final(limpia(x)) == sin_grado_final(limpia(y))
                        for x, y in zip(d["a"], d["b"])]
    d.to_csv(PARES, index=False, encoding="utf-8")

    n, r = len(d), int(d["rechazado"].sum())
    sin_texto = d[~d["texto_igual"]]
    lineas = [
        "=" * 78,
        "32 · CRITERIO B DE D-040: LA FUSION POR COSENO >= 0,95 PASADA POR EL CROSS v2",
        "=" * 78,
        "pares unidos por la fusion semantica en base_v15: {:,}".format(n),
        "rechazados por el cross v2 (P calibrada < 0,5): {:,} = {:.2%}   (umbral del criterio: "
        "1 %)".format(r, r / n),
        "  primera condicion del criterio B: {}".format("SE CUMPLE" if r / n >= 0.01
                                                         else "NO se cumple"),
        "",
        "descriptivo: pares que la capa 0 de texto juntaria igual (prefijo, puntuacion, grado):"
        " {:,}".format(int(d["texto_igual"].sum())),
        "  sin ellos (los que dependen solo de D-015): {:,}, rechazados {:,} = {:.2%}".format(
            len(sin_texto), int(sin_texto["rechazado"].sum()),
            sin_texto["rechazado"].mean() if len(sin_texto) else 0.0),
        "P del cross v2 en los pares unidos: mediana {:.3f}; percentil 5 {:.3f}".format(
            d["P"].median(), d["P"].quantile(0.05)),
    ]

    rng = np.random.default_rng(SEM)
    rech = d[d["rechazado"]]
    acep = d[~d["rechazado"]]
    k = min(N_REVISION, len(rech))
    muestra = pd.concat([rech.sample(k, random_state=int(rng.integers(1 << 30))),
                         acep.sample(N_REVISION, random_state=int(rng.integers(1 << 30)))])
    muestra = muestra.sample(frac=1.0, random_state=SEM).reset_index(drop=True)
    muestra.insert(0, "n", range(1, len(muestra) + 1))
    muestra[["n", "i", "j", "sim", "P", "rechazado"]].to_csv(MAPA, index=False,
                                                             encoding="utf-8")
    j_ = muestra[["n", "a", "b"]].rename(columns={"a": "comun", "b": "raro"})
    j_["mismo"] = ""
    j_["nota"] = ""
    j_.to_csv(REVISAR, index=False, sep=";", encoding="utf-8-sig")
    lineas += ["", "revision a ciegas: {} rechazados + {} aceptados, barajados -> {}".format(
        k, N_REVISION, REVISAR.name), "  (mapa: {}, NO abrir antes de juzgar)".format(MAPA.name)]
    INFORME.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))


def evaluar():
    j = pd.read_csv(REVISAR, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                    keep_default_na=False)
    j["mismo"] = j["mismo"].str.strip().str.lower()
    if not j["mismo"].isin(["si", "no"]).all():
        raise SystemExit("ALTO: faltan juicios: {}".format(
            j.loc[~j["mismo"].isin(["si", "no"]), "n"].tolist()))
    m = pd.read_csv(MAPA, dtype={"n": str})
    d = j.merge(m, on="n")
    d["rechazado"] = d["rechazado"].astype(str).str.lower() == "true"
    rech, acep = d[d["rechazado"]], d[~d["rechazado"]]
    dist_r = (rech["mismo"] == "no").mean()
    dist_a = (acep["mismo"] == "no").mean()
    pares = pd.read_csv(PARES)
    tasa = pares["rechazado"].mean()
    ok = tasa >= 0.01 and dist_r >= 0.5
    lineas = ["", "EVALUACION (juicios del autor, a ciegas)",
              "  rechazados por el cross: {} revisados, distintos de verdad {:.0%}".format(
                  len(rech), dist_r),
              "  aceptados por el cross:  {} revisados, distintos de verdad {:.0%}".format(
                  len(acep), dist_a),
              "  tasa de rechazo {:.2%} (>= 1 %) y distintos entre rechazados {:.0%} (>= 50 %)"
              .format(tasa, dist_r),
              "  CRITERIO B: {}".format("SE CONFIRMA: D-015 se enmienda" if ok else
                                        "NO se confirma: D-015 se queda")]
    with open(INFORME, "a", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print("\n".join(lineas))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["medir", "evaluar"])
    a = ap.parse_args()
    medir() if a.accion == "medir" else evaluar()
