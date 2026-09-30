"""H4: el cross-encoder v2 contra el v1 sobre `prueba 2`. Se corre UNA vez. D-038.

ESTO ABRE `prueba 2`, el examen que nadie ha mirado: se armo y se juzgo antes de entrenar la
v2 y quedo congelado en git (36fd6b5). El guion se niega a correr si algo no esta en su sitio,
y se niega a correr dos veces.

QUE SE MIDE (prerregistro de la v2, D-038)
==============================================================================
    H4   (confirmatoria)  AUC(v2) - AUC(v1) en `prueba 2`. Bootstrap pareado por par, 10.000
                          remuestreos, IC 95 % bilateral. Se adopta la v2 si el IC queda
                          entero sobre cero. Un nulo es "no demostrado": la v1 sigue.
    Replica de H1         AUC(v1) - AUC(coseno), con el criterio de H1.
    H4b  (secundaria)     v2 contra NLI congelado y contra coseno, con IC, sin criterio.
    descriptivos          el ENSAMBLE (media de las P calibradas de las tres semillas de la v2)
                          contra la v2 sola; AUC por estrato; calibracion (ECE) de v1 y v2;
                          errores por direccion (junta / separa de mas) con P >= 0,5.

    v1  = `22_modelos/elegido/`     (SHA-256 040b4dc4a6c5..., el de H1)
    v2  = `22_modelos_v2/elegido/`  (SHA-256 ed6979378599...)
    Las dos en fp32 (Enmienda 6 de D-036). P = log-odds / T, con la T de cada una.

ANTES DE ABRIR, SE COMPRUEBA (si falla una, se detiene sin leer `prueba 2`)
==============================================================================
    1. repo limpio: ademas de la ficha, garantiza que `prueba 2` esta como se congelo;
    2. v1 y v2 son exactamente esos pesos (SHA-256);
    3. la v2 se eligio con el paquete vigente y la `calibra` de 191;
    4. el NLI congelado da en `calibra` el AUC_BASE de `22` (0,7346);
    5. no existe ya `31_h4.txt`.

`--ensayo` corre todo sobre `calibra`, sin leer `prueba 2`, para probar el mecanismo.

SALIDAS
    31_h4.txt                  el informe (agregados, sin titulos)
    31_puntajes_prueba2.csv    n, estrato, y, y el puntaje de cada juez
"""
import argparse
import contextlib
import datetime as dt
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
V1 = SAL / "22_modelos" / "elegido"
V2_DIR = SAL / "22_modelos_v2"
V2 = V2_DIR / "elegido"
PAQUETE = SAL / "21_paquete"
P2_JUICIOS = SAL / "29_prueba2_para_juzgar.csv"
P2_META = SAL / "29_prueba2_pares.csv"
INFORME = SAL / "31_h4.txt"
PUNTAJES = SAL / "31_puntajes_prueba2.csv"
ENSAYO = SAL / "31_ensayo.txt"
SHA_V1 = "040b4dc4a6c5ce4338d4c2ea7b8430999993d3d9da7c8414ef2cf599b13507e0"
SHA_V2_12 = "ed6979378599"
CALIBRA_PARES = 191
SEM = 20261005


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def calibrada(s, T):
    z = np.log(np.clip(s, 1e-6, 1 - 1e-6) / np.clip(1 - s, 1e-6, 1))
    return 1 / (1 + np.exp(-z / T))


def comprobar(ensayo, e24):
    avisos = []

    def falla(msg):
        if ensayo:
            avisos.append(msg)
        else:
            raise SystemExit("ALTO, `prueba 2` no se abre: " + msg)

    if e24.git("status", "--porcelain"):
        falla("hay cambios sin commitear.")
    if not ensayo and INFORME.exists():
        raise SystemExit("ALTO: {} ya existe. `prueba 2` se abre una sola vez.".format(INFORME))
    if e24.sha256(V1 / "model.safetensors") != SHA_V1:
        falla("la v1 no es el cross-encoder de H1.")
    if not e24.sha256(V2 / "model.safetensors").startswith(SHA_V2_12):
        falla("la v2 no es la registrada en D-038.")
    res = json.loads((V2_DIR / "resultados.json").read_text(encoding="utf-8"))
    paq = {f: e24.sha256(PAQUETE / f) for f in ("plata.csv", "calibra.csv", "manifiesto.json")}
    if res["datos_sha256"] != paq:
        falla("la v2 no se eligio con el paquete vigente de `21`.")
    if res["paquete_manifiesto"]["calibra"]["pares"] != CALIBRA_PARES:
        falla("la v2 se eligio con una `calibra` de otro tamano.")
    return res, avisos


def conjunto_prueba2():
    j = pd.read_csv(P2_JUICIOS, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                    keep_default_na=False)
    m = pd.read_csv(P2_META, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    d = j[["n", "comun", "raro", "mismo"]].merge(m[["n", "sim", "estrato"]], on="n",
                                                  validate="one_to_one")
    d["mismo"] = d["mismo"].str.strip().str.lower()
    return d[d["mismo"].isin(["si", "no"])].reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensayo", action="store_true")
    ap.add_argument("--dispositivo", default="auto", choices=["auto", "cuda", "cpu"])
    args = ap.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    from transformers import AutoTokenizer

    e22 = cargar("e22", "22_entrenar_cross.py")
    e24 = cargar("e24", "24_h1_prueba.py")
    dev = ("cuda" if torch.cuda.is_available() else "cpu") if args.dispositivo == "auto" \
        else args.dispositivo
    fp32 = contextlib.nullcontext
    lineas = []

    def out(s=""):
        print(s, flush=True)
        lineas.append(s)

    out("=" * 78)
    out("31 · H4 SOBRE `prueba 2`: CROSS-ENCODER v2 CONTRA v1 (D-038){}".format(
        "   [ENSAYO sobre calibra]" if args.ensayo else ""))
    out("=" * 78)

    # --- 1. comprobaciones, sin leer `prueba 2` ----------------------------------------
    res, avisos = comprobar(args.ensayo, e24)
    base = RAIZ / "modelos" / "mdeberta-xnli"
    e22.verificar_modelo(base)
    tok = AutoTokenizer.from_pretrained(base)
    cal = e24.conjunto_calibra()
    y_cal = (cal["mismo"] == "si").astype(int).to_numpy()
    nli = e22.construir(base, False, dev)
    ab, ba = e22.puntuar(nli, tok, cal["comun"].tolist(), cal["raro"].tolist(), dev, fp32)
    auc_base = e24.auc(y_cal, (ab + ba) / 2)
    if abs(auc_base - e22.AUC_BASE) > e22.TOL_BASE:
        raise SystemExit("ALTO: el NLI sin entrenar da {:.4f} en calibra y no {:.4f}.".format(
            auc_base, e22.AUC_BASE))
    for a in avisos:
        out("  AVISO (solo en ensayo): " + a)
    out("\ncomprobaciones: repo {} | v1 {} | v2 {} (commit {}, calibra {}) | NLI en calibra "
        "{:.4f}".format("limpio" if not e24.git("status", "--porcelain") else "CON CAMBIOS",
                        SHA_V1[:12], SHA_V2_12, res["ficha"]["git_commit"][:7],
                        res["paquete_manifiesto"]["calibra"]["pares"], auc_base))

    # --- 2. el conjunto: aqui se abre `prueba 2` ---------------------------------------
    t = cal if args.ensayo else conjunto_prueba2()
    y = (t["mismo"] == "si").astype(int).to_numpy()
    out("\n{}: {} pares ({} si / {} no)".format(
        "calibra (ENSAYO)" if args.ensayo else "prueba 2", len(t), y.sum(), len(y) - y.sum()))
    a_, b_ = t["comun"].tolist(), t["raro"].tolist()

    # --- 3. puntajes -------------------------------------------------------------------
    s = {"coseno": t["sim"].astype(float).to_numpy()}
    ab, ba = e22.puntuar(nli, tok, a_, b_, dev, fp32)
    s["NLI"] = (ab + ba) / 2
    del nli
    T = {}
    for nombre, ruta in (("v1", V1), ("v2", V2)):
        inf = json.loads((ruta / "info.json").read_text(encoding="utf-8"))
        m = e22.construir(ruta, False, dev)
        ab, ba = e22.puntuar(m, tok, a_, b_, dev, fp32)
        del m
        s[nombre] = e22.puntaje(inf["modo"], ab, ba)
        T[nombre] = inf["temperatura"]
    ps = []
    for ruta in sorted((V2_DIR / "semillas").iterdir()):
        inf = json.loads((ruta / "info.json").read_text(encoding="utf-8"))
        m = e22.construir(ruta, False, dev)
        ab, ba = e22.puntuar(m, tok, a_, b_, dev, fp32)
        del m
        ps.append(calibrada(e22.puntaje(inf["modo"], ab, ba), inf["temperatura"]))
    s["ensamble_v2"] = np.mean(ps, axis=0)
    if dev == "cuda":
        torch.cuda.empty_cache()

    # --- 4. H4, replica de H1 y H4b ----------------------------------------------------
    rng = np.random.default_rng(SEM)
    aucs = {k: e24.auc(y, v) for k, v in s.items()}
    out("\nAUC:  v2 {:.4f}   v1 {:.4f}   ensamble v2 {:.4f}   NLI {:.4f}   coseno {:.4f}".format(
        aucs["v2"], aucs["v1"], aucs["ensamble_v2"], aucs["NLI"], aucs["coseno"]))

    def contraste(nombre, a, b, criterio):
        lo, hi = e24.boot_dif(y, s[a], s[b], rng)
        d = aucs[a] - aucs[b]
        veredicto = ""
        if criterio:
            veredicto = "   -> " + ("SE ADOPTA (IC entero sobre 0)" if lo > 0 else
                                    "NO DEMOSTRADO (el IC toca o cruza 0)")
        out("{:<16} {:+.4f}   IC95 [{:+.4f}, {:+.4f}]{}".format(nombre, d, lo, hi, veredicto))
        return {"dif": d, "ic95": [lo, hi]}

    out("")
    r = {"H4 v2 - v1": contraste("H4   v2 - v1", "v2", "v1", True),
         "replica H1 v1 - coseno": contraste("H1r  v1 - coseno", "v1", "coseno", True),
         "H4b v2 - NLI": contraste("H4b  v2 - NLI", "v2", "NLI", False),
         "H4b v2 - coseno": contraste("H4b  v2 - coseno", "v2", "coseno", False),
         "ensamble - v2": contraste("desc ensamble-v2", "ensamble_v2", "v2", False)}
    out("     bootstrap pareado por par, {:,} remuestreos, semilla {}".format(e24.B_BOOT, SEM))

    # --- 5. descriptivos ---------------------------------------------------------------
    out("\nPOR ESTRATO (descriptivo)")
    for e, g in t.groupby("estrato"):
        ix = g.index.to_numpy()
        if len(set(y[ix])) == 2:
            out("  {:<6} n={:>3} ({:>2} no)   v2 {:.4f}   v1 {:.4f}   NLI {:.4f}   coseno {:.4f}"
                .format(e, len(ix), int((y[ix] == 0).sum()), e24.auc(y[ix], s["v2"][ix]),
                        e24.auc(y[ix], s["v1"][ix]), e24.auc(y[ix], s["NLI"][ix]),
                        e24.auc(y[ix], s["coseno"][ix])))
    out("\nCALIBRACION Y ERRORES (P calibrada, umbral 0,5; descriptivo)")
    for k in ("v1", "v2"):
        p = calibrada(s[k], T[k])
        out("  {}  T {:.3f}  ECE {:.3f}   junta mal {:>2}/{}   separa mal {:>2}/{}".format(
            k, T[k], e24.ece(y, p), int(((p >= .5) & (y == 0)).sum()), int((y == 0).sum()),
            int(((p < .5) & (y == 1)).sum()), int(y.sum())))
    p = s["ensamble_v2"]
    out("  ensamble v2        ECE {:.3f}   junta mal {:>2}/{}   separa mal {:>2}/{}".format(
        e24.ece(y, p), int(((p >= .5) & (y == 0)).sum()), int((y == 0).sum()),
        int(((p < .5) & (y == 1)).sum()), int(y.sum())))

    # --- 6. escribir -------------------------------------------------------------------
    ficha = {"fecha": dt.datetime.now().isoformat(timespec="seconds"),
             "git_commit": e24.git("rev-parse", "HEAD"),
             "git_sin_commitear": bool(e24.git("status", "--porcelain")),
             "v1_sha256": SHA_V1, "v2_sha256": e24.sha256(V2 / "model.safetensors"),
             "v2_commit_entrenamiento": res["ficha"]["git_commit"],
             "torch": torch.__version__, "dispositivo": dev}
    out("\nficha: " + json.dumps(ficha, ensure_ascii=False))
    (ENSAYO if args.ensayo else INFORME).write_text("\n".join(lineas) + "\n", encoding="utf-8")
    if not args.ensayo:
        q = t[["n", "estrato"]].copy()
        q["y"] = y
        for k, v in s.items():
            q[k] = v
        q.to_csv(PUNTAJES, index=False, encoding="utf-8")
    print("\n-> {}".format(ENSAYO if args.ensayo else INFORME))


if __name__ == "__main__":
    main()
