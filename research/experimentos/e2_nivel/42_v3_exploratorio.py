"""El cross-encoder v3 en `prueba` y `prueba 2`. EXPLORATORIO (D-041): los dos ya se abrieron.

Lo que registra el plan de D-041 (§4), y nada mas:
    - v3 - coseno y v3 - v2 (y v2 - coseno como referencia), AUC con IC 95 % por bootstrap
      pareado por par (10.000, las funciones de `24`);
    - con DOS varas: las etiquetas y la exclusion ORIGINALES (`mismo_v5`, `23_fuera_por_capa0`:
      las de H1 y H4) y las NUEVAS (`mismo` v6, `39_fuera_capa0_v1`). Asi se ve que parte del
      cambio es del juez y que parte de la vara;
    - aparte, los pares con numero de grado distinto (`capa0.compatibles` False): con la v6
      todos son `no`; cuantos junta cada juez (P calibrada >= 0,5).
Los puntajes salen de las mismas funciones que H1 y H4 (`22.construir`, `22.puntuar`,
`22.puntaje`, fp32). Nada de esto cambia H1 ni H4.

    .venv/bin/python 42_v3_exploratorio.py

SALIDAS: salidas/42_v3_exploratorio.txt, salidas/42_puntajes.csv
"""
import contextlib
import importlib.util
import json
import os
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto import capa0  # noqa: E402

JUECES = {"v1": SAL / "22_modelos" / "elegido", "v2": SAL / "22_modelos_v2" / "elegido",
          "v3": SAL / "22_modelos_v3" / "elegido"}
SEM = 20261003


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def leer(p):
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                       keep_default_na=False)


def pares():
    """Todos los pares juzgados de `prueba` y `prueba 2`, con las dos varas."""
    meta13 = leer(SAL / "13e_pares_400.csv")
    meta13 = meta13[meta13["particion"] == "prueba"]
    partes = [("prueba", "13e", meta13, leer(SAL / "13e_para_juzgar.csv")),
              ("prueba", "20", leer(SAL / "20_pares_400.csv"), leer(SAL / "20_para_juzgar.csv")),
              ("prueba 2", "29", leer(SAL / "29_prueba2_pares.csv"),
               leer(SAL / "29_prueba2_para_juzgar.csv"))]
    f_orig = pd.read_csv(SAL / "23_fuera_por_capa0.csv", dtype=str)
    f_v1 = pd.read_csv(SAL / "39_fuera_capa0_v1.csv", dtype=str)
    out = []
    for conj, cj, m, j in partes:
        d = m[["n", "comun", "raro", "sim", "estrato"]].merge(
            j[["n", "mismo", "mismo_v5"]], on="n", validate="one_to_one")
        d["conjunto"], d["cj"] = conj, cj
        d["y_orig"] = d["mismo_v5"].str.strip().str.lower()
        d["y_v6"] = d["mismo"].str.strip().str.lower()
        d["fuera_orig"] = d["n"].isin(set(f_orig.loc[f_orig["conjunto"] == cj, "n"]))
        d["fuera_v1"] = d["n"].isin(set(f_v1.loc[f_v1["conjunto"] == cj, "n"]))
        out.append(d)
    d = pd.concat(out, ignore_index=True)
    d["num_distinto"] = [not capa0.compatibles(a, b) for a, b in zip(d["comun"], d["raro"])]
    return d


def main():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    from transformers import AutoTokenizer
    e22 = cargar("e22", "22_entrenar_cross.py")
    e24 = cargar("e24", "24_h1_prueba.py")
    e31 = cargar("e31", "31_h4_prueba2.py")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    lineas = []

    def out(s=""):
        print(s, flush=True)
        lineas.append(s)

    d = pares()
    base = RAIZ / "modelos" / "mdeberta-xnli"
    e22.verificar_modelo(base)
    tok = AutoTokenizer.from_pretrained(base)
    a_, b_ = d["comun"].tolist(), d["raro"].tolist()
    s = {"coseno": d["sim"].astype(float).to_numpy()}
    T = {}
    for nombre, ruta in JUECES.items():
        inf = json.loads((ruta / "info.json").read_text(encoding="utf-8"))
        m = e22.construir(ruta, False, dev)
        ab, ba = e22.puntuar(m, tok, a_, b_, dev, contextlib.nullcontext)
        del m
        s[nombre] = e22.puntaje(inf["modo"], ab, ba)
        T[nombre] = inf["temperatura"]
    for k, v in s.items():
        d[k] = v

    out("=" * 78)
    out("42 · CROSS-ENCODER v3 EN `prueba` Y `prueba 2` — EXPLORATORIO (D-041)")
    out("=" * 78)
    out("T: " + ", ".join("{} {:.3f}".format(k, v) for k, v in T.items()))
    out("H1 y H4 no cambian: son confirmatorios con la vara original. Esto es exploratorio.")
    rng = np.random.default_rng(SEM)
    for conj in ("prueba", "prueba 2"):
        for vara, col_y, col_f in (("ORIGINAL (la de H1/H4)", "y_orig", "fuera_orig"),
                                   ("v6 + capa 0 v1", "y_v6", "fuera_v1")):
            t = d[(d["conjunto"] == conj) & d[col_y].isin(["si", "no"]) & ~d[col_f]]
            y = (t[col_y] == "si").astype(int).to_numpy()
            out("\n{} · vara {}: {} pares ({} si / {} no)".format(
                conj, vara, len(t), y.sum(), len(y) - y.sum()))
            out("   AUC  " + "   ".join("{} {:.4f}".format(k, e24.auc(y, t[k].to_numpy()))
                                        for k in ("v3", "v2", "v1", "coseno")))
            for a, b in (("v3", "coseno"), ("v3", "v2"), ("v2", "coseno")):
                lo, hi = e24.boot_dif(y, t[a].to_numpy(), t[b].to_numpy(), rng)
                dif = e24.auc(y, t[a].to_numpy()) - e24.auc(y, t[b].to_numpy())
                out("   {} - {:<7} {:+.4f}   IC95 [{:+.4f}, {:+.4f}]".format(a, b, dif, lo, hi))

    out("\nPARES CON NUMERO DE GRADO DISTINTO (con la v6 todos son `no`)")
    g = d[d["num_distinto"]]
    out("   {} pares ({} en `prueba`, {} en `prueba 2`)".format(
        len(g), int((g["conjunto"] == "prueba").sum()), int((g["conjunto"] == "prueba 2").sum())))
    for k in ("v1", "v2", "v3"):
        p = e31.calibrada(g[k].to_numpy(), T[k])
        out("   {}: junta {} de {} (P calibrada >= 0,5); P mediana {:.3f}".format(
            k, int((p >= .5).sum()), len(g), float(np.median(p))))
    out("   coseno mediano {:.3f}".format(float(g["coseno"].median())))
    for _, f in g.iterrows():
        out("      {:<38} / {:<38} v2 {:.2f}  v3 {:.2f}".format(
            f["comun"][:38], f["raro"][:38], e31.calibrada(np.array([f["v2"]]), T["v2"])[0],
            e31.calibrada(np.array([f["v3"]]), T["v3"])[0]))

    out("\nficha: commit {}, sin commitear {}, v3 sha {}".format(
        e24.git("rev-parse", "HEAD")[:7], bool(e24.git("status", "--porcelain")),
        e24.sha256(JUECES["v3"] / "model.safetensors")[:12]))
    (SAL / "42_v3_exploratorio.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    d[["conjunto", "cj", "n", "estrato", "y_orig", "y_v6", "fuera_orig", "fuera_v1",
       "num_distinto", "coseno", "v1", "v2", "v3"]].to_csv(SAL / "42_puntajes.csv",
                                                          index=False, encoding="utf-8")


if __name__ == "__main__":
    main()
