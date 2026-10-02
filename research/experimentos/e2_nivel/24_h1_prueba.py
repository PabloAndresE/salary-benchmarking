"""H1: el cross-encoder B contra el coseno sobre `prueba`. Se corre UNA vez. D-036.

ESTO ABRE `prueba`. Es la unica medida del proyecto que no ha influido en ninguna decision,
y deja de serlo en cuanto se calcula un puntaje sobre ella. Por eso el guion se niega a
correr si algo no esta en su sitio, y se niega a correr dos veces.

QUE SE MIDE (prerregistro de D-036 y sus enmiendas)
==============================================================================
    H1  (confirmatoria)  AUC(B) - AUC(coseno) sobre `prueba`, bootstrap pareado por par,
                         10.000 remuestreos, IC 95 % bilateral. Se adopta si el IC queda
                         entero sobre cero. Un nulo se lee como "no demostrado".
    H1b (secundaria)     AUC(B) - AUC(NLI congelado), con su IC, sin criterio de adopcion.
    descriptivos         AUC por estrato y por mitad (`13e` / `20`); heterogeneidad del
                         coseno entre mitades (Enmienda 2); los 8 modelos de `corridas/`
                         (ablacion); calibracion de B con su temperatura (ECE).

    B          = `22_modelos/elegido/`, P(mismo) = P(A=>B) * P(B=>A), en fp32. La
                 temperatura no cambia el AUC (es monotona); solo entra en la calibracion.
    coseno     = `sim` de `base_v15`, el mismo de `13e` y `20`.
    NLI        = el modelo base sin ajustar, media de las dos direcciones (la de `13c`/`19`).
    etiqueta   = `mismo` (v3 con el grado corregido, Enmienda 5). Fuera: `duda` (Enmienda 4)
                 y lo que fusiona la capa 0 (`23_fuera_por_capa0.csv`, Enmienda 5).

ANTES DE ABRIR, SE COMPRUEBA (si falla una, se detiene sin leer `prueba`)
==============================================================================
    1. el repo esta limpio: la ficha tiene que poder decir con que codigo se abrio;
    2. `elegido/` viene de la corrida que eligio con el paquete vigente (hashes de
       `resultados.json` contra los del paquete, y `calibra` de 191);
    3. no queda ningun par de `prueba` por juzgar en `23_revisar_grado.csv`;
    4. el NLI sin entrenar da en `calibra` el AUC_BASE de `22` (plantilla y modelo intactos);
    5. no existe ya `24_h1.txt`: `prueba` no se abre dos veces.

ENSAYO. `--ensayo` corre todo lo mismo sobre `calibra`, sin leer ningun archivo de
`prueba`, para comprobar el mecanismo. Sus numeros no significan nada (calibra eligio B) y
se escriben aparte (`24_ensayo.txt`).

SALIDAS
    24_h1.txt                  el informe. Solo agregados, sin titulos
    24_puntajes_prueba.csv     n, conjunto, estrato, y, y los puntajes de cada juez
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
MODELOS = SAL / "22_modelos"
ELEGIDO = MODELOS / "elegido"
PAQUETE = SAL / "21_paquete"
FUERA = SAL / "23_fuera_por_capa0.csv"
REVISAR = SAL / "23_revisar_grado.csv"
INFORME = SAL / "24_h1.txt"
PUNTAJES = SAL / "24_puntajes_prueba.csv"
ENSAYO = SAL / "24_ensayo.txt"

B_BOOT = 10_000
SEM = 20261002
CALIBRA_PARES = 191


def cargar_22():
    spec = importlib.util.spec_from_file_location("e22", AQUI / "22_entrenar_cross.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def leer(p, **kw):
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                       keep_default_na=False, **kw)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def git(*c):
    return subprocess.run(["git", *c], cwd=RAIZ, capture_output=True, text=True,
                          check=True).stdout.strip()


# ---------------------------------------------------------------------------------------
# comprobaciones: ninguna lee `prueba`
# ---------------------------------------------------------------------------------------
def comprobar(ensayo):
    avisos = []

    def falla(msg):
        if ensayo:
            avisos.append(msg)
        else:
            raise SystemExit("ALTO, `prueba` no se abre: " + msg)

    if git("status", "--porcelain"):
        falla("hay cambios sin commitear.")
    if not ensayo and INFORME.exists():
        raise SystemExit("ALTO: {} ya existe. `prueba` se abre una sola vez.".format(INFORME))
    res = json.loads((MODELOS / "resultados.json").read_text(encoding="utf-8"))
    paq = {f: sha256(PAQUETE / f) for f in ("plata.csv", "calibra.csv", "manifiesto.json")}
    if res["datos_sha256"] != paq:
        falla("`elegido/` no se eligio con el paquete vigente de `21`.")
    if res["paquete_manifiesto"]["calibra"]["pares"] != CALIBRA_PARES:
        falla("`elegido/` se eligio con una `calibra` de {} pares, no {}.".format(
            res["paquete_manifiesto"]["calibra"]["pares"], CALIBRA_PARES))
    info = json.loads((ELEGIDO / "info.json").read_text(encoding="utf-8"))
    rev = leer(REVISAR)
    rev = rev[(rev.get("vigente", "si") == "si") & rev["conjunto"].isin(["13e", "20"])
              & (rev["mismo_nuevo"].str.strip() == "")]
    if len(rev):
        falla("quedan pares de `prueba` por juzgar en {}: {}.".format(
            REVISAR.name, [f"{c}#{n}" for c, n in zip(rev["conjunto"], rev["n"])]))
    return res, info, avisos


# ---------------------------------------------------------------------------------------
# datos
# ---------------------------------------------------------------------------------------
def conjunto_calibra():
    c = pd.read_csv(PAQUETE / "calibra.csv", dtype={"n": str}, keep_default_na=False)
    c["conjunto"] = "13e"
    return c


def conjunto_prueba():
    """Los pares de `prueba`: 13e (particion prueba) y 20, sin `duda` ni capa 0."""
    fu = pd.read_csv(FUERA, dtype=str)
    partes = []
    for conj, meta, juicio in (("13e", "13e_pares_400.csv", "13e_para_juzgar.csv"),
                               ("20", "20_pares_400.csv", "20_para_juzgar.csv")):
        m = leer(SAL / meta)
        m = m[m["particion"] == "prueba"] if conj == "13e" else m
        j = leer(SAL / juicio)
        # D-041: la v6 corrige `mismo`; H1 se lee con la etiqueta con que se registro.
        j = j.assign(mismo=j["mismo_v5"]) if "mismo_v5" in j.columns else j
        j = j[["n", "mismo"]]
        d = m.merge(j, on="n", validate="one_to_one")
        d["mismo"] = d["mismo"].str.strip().str.lower()
        d = d[d["mismo"].isin(["si", "no"])]
        d = d[~d["n"].isin(set(fu.loc[fu["conjunto"] == conj, "n"]))]
        d["conjunto"] = conj
        partes.append(d[["n", "conjunto", "comun", "raro", "sim", "estrato", "mismo"]])
    return pd.concat(partes, ignore_index=True)


# ---------------------------------------------------------------------------------------
# estadistica
# ---------------------------------------------------------------------------------------
def auc(y, s):
    return float(roc_auc_score(y, s))


def boot_dif(y, s1, s2, rng, b=B_BOOT):
    """IC 95 % de AUC(s1) - AUC(s2): bootstrap pareado por par (prerregistro de H1)."""
    n = len(y)
    d = []
    while len(d) < b:
        ix = rng.integers(0, n, n)
        if y[ix].min() == y[ix].max():
            continue
        d.append(roc_auc_score(y[ix], s1[ix]) - roc_auc_score(y[ix], s2[ix]))
    d = np.array(d)
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def boot_dif_grupos(y, s, g, rng, b=B_BOOT):
    """IC 95 % de AUC(mitad 13e) - AUC(mitad 20) para un mismo juez (no pareado)."""
    ia, ib = np.flatnonzero(g == "13e"), np.flatnonzero(g == "20")
    d = []
    while len(d) < b:
        xa, xb = rng.choice(ia, len(ia)), rng.choice(ib, len(ib))
        if y[xa].min() == y[xa].max() or y[xb].min() == y[xb].max():
            continue
        d.append(roc_auc_score(y[xa], s[xa]) - roc_auc_score(y[xb], s[xb]))
    d = np.array(d)
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def ece(y, p, bins=10):
    e, n = 0.0, len(y)
    cortes = np.linspace(0, 1, bins + 1)
    for a, b in zip(cortes[:-1], cortes[1:]):
        m = (p >= a) & (p < b) if b < 1 else (p >= a) & (p <= b)
        if m.any():
            e += m.sum() / n * abs(y[m].mean() - p[m].mean())
    return float(e)


# ---------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensayo", action="store_true",
                    help="todo sobre `calibra`, sin leer `prueba`; para probar el mecanismo")
    ap.add_argument("--dispositivo", default="auto", choices=["auto", "cuda", "cpu"])
    args = ap.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    from transformers import AutoTokenizer

    e22 = cargar_22()
    dev = ("cuda" if torch.cuda.is_available() else "cpu") if args.dispositivo == "auto" \
        else args.dispositivo
    fp32 = contextlib.nullcontext
    lineas = []

    def out(s=""):
        print(s, flush=True)
        lineas.append(s)

    out("=" * 78)
    out("24 · H1 SOBRE `prueba` (D-036){}".format("   [ENSAYO sobre calibra]" if args.ensayo
                                                 else ""))
    out("=" * 78)

    # --- 1. comprobaciones, sin leer `prueba` -----------------------------------------
    res, info, avisos = comprobar(args.ensayo)
    base = RAIZ / "modelos" / "mdeberta-xnli"
    e22.verificar_modelo(base)
    tok = AutoTokenizer.from_pretrained(base)
    cal = conjunto_calibra()
    y_cal = (cal["mismo"] == "si").astype(int).to_numpy()
    nli = e22.construir(base, False, dev)
    ab, ba = e22.puntuar(nli, tok, cal["comun"].tolist(), cal["raro"].tolist(), dev, fp32)
    auc_base = auc(y_cal, (ab + ba) / 2)
    if abs(auc_base - e22.AUC_BASE) > e22.TOL_BASE:
        raise SystemExit("ALTO: el NLI sin entrenar da {:.4f} en calibra y no {:.4f}.".format(
            auc_base, e22.AUC_BASE))
    for a in avisos:
        out("  AVISO (solo en ensayo): " + a)
    out("\ncomprobaciones: repo {} | elegido {} (commit {}, calibra {}) | NLI en calibra "
        "{:.4f}".format("limpio" if not git("status", "--porcelain") else "CON CAMBIOS",
                        info["nombre"], res["ficha"]["git_commit"][:7],
                        res["paquete_manifiesto"]["calibra"]["pares"], auc_base))

    # --- 2. el conjunto: aqui se abre `prueba` ----------------------------------------
    t = conjunto_calibra() if args.ensayo else conjunto_prueba()
    y = (t["mismo"] == "si").astype(int).to_numpy()
    out("\n{}: {} pares ({} si / {} no){}".format(
        "calibra (ENSAYO)" if args.ensayo else "prueba", len(t), y.sum(), len(y) - y.sum(),
        "" if args.ensayo else "; por conjunto {}".format(t["conjunto"].value_counts()
                                                          .to_dict())))
    a_, b_ = t["comun"].tolist(), t["raro"].tolist()

    # --- 3. puntajes -------------------------------------------------------------------
    jueces = {"coseno": t["sim"].astype(float).to_numpy()}
    ab, ba = e22.puntuar(nli, tok, a_, b_, dev, fp32)
    jueces["NLI"] = (ab + ba) / 2
    del nli
    ablacion = {}
    for ruta in [ELEGIDO] + sorted((MODELOS / "corridas").iterdir()):
        inf = json.loads((ruta / "info.json").read_text(encoding="utf-8"))
        m = e22.construir(ruta, False, dev)
        ab, ba = e22.puntuar(m, tok, a_, b_, dev, fp32)
        del m
        s = e22.puntaje(inf["modo"], ab, ba)
        if ruta == ELEGIDO:
            jueces["B"] = s
        else:
            ablacion[ruta.name] = s
        if dev == "cuda":
            torch.cuda.empty_cache()

    # --- 4. H1 y H1b -------------------------------------------------------------------
    rng = np.random.default_rng(SEM)
    aucs = {k: auc(y, v) for k, v in jueces.items()}
    lo1, hi1 = boot_dif(y, jueces["B"], jueces["coseno"], rng)
    lo2, hi2 = boot_dif(y, jueces["B"], jueces["NLI"], rng)
    d1, d2 = aucs["B"] - aucs["coseno"], aucs["B"] - aucs["NLI"]
    out("\nAUC:  B {:.4f}   NLI congelado {:.4f}   coseno {:.4f}".format(
        aucs["B"], aucs["NLI"], aucs["coseno"]))
    out("\nH1   B - coseno   {:+.4f}   IC95 [{:+.4f}, {:+.4f}]   -> {}".format(
        d1, lo1, hi1, "SE ADOPTA (IC entero sobre 0)" if lo1 > 0 else
        "NO DEMOSTRADO (el IC toca o cruza 0)"))
    out("H1b  B - NLI      {:+.4f}   IC95 [{:+.4f}, {:+.4f}]   (sin criterio de adopcion)"
        .format(d2, lo2, hi2))
    out("     bootstrap pareado por par, {:,} remuestreos, semilla {}".format(B_BOOT, SEM))

    # --- 5. descriptivos ---------------------------------------------------------------
    out("\nPOR ESTRATO (descriptivo)")
    for e, g in t.groupby("estrato"):
        ix = g.index.to_numpy()
        if len(set(y[ix])) == 2:
            out("  {:<6} n={:>3} ({:>3} no)   B {:.4f}   NLI {:.4f}   coseno {:.4f}".format(
                e, len(ix), int((y[ix] == 0).sum()), auc(y[ix], jueces["B"][ix]),
                auc(y[ix], jueces["NLI"][ix]), auc(y[ix], jueces["coseno"][ix])))
        else:
            out("  {:<6} n={:>3}   una sola clase: sin AUC".format(e, len(ix)))
    if not args.ensayo:
        out("\nPOR MITAD (descriptivo; Enmienda 2)")
        g = t["conjunto"].to_numpy()
        for conj in ("13e", "20"):
            ix = np.flatnonzero(g == conj)
            out("  {:<4} n={:>3}   B {:.4f}   NLI {:.4f}   coseno {:.4f}".format(
                conj, len(ix), auc(y[ix], jueces["B"][ix]), auc(y[ix], jueces["NLI"][ix]),
                auc(y[ix], jueces["coseno"][ix])))
        lo, hi = boot_dif_grupos(y, jueces["coseno"], g, rng)
        out("  coseno 13e - 20: IC95 [{:+.4f}, {:+.4f}]  -> {}".format(
            lo, hi, "HETEROGENEO: se declara (la vara no cambia)" if lo > 0 or hi < 0
            else "sin heterogeneidad detectable"))

    out("\nABLACION (descriptivo; `corridas/`)")
    for k, s in ablacion.items():
        out("  {:<22} AUC {:.4f}".format(k, auc(y, s)))

    temp = info.get("temperatura")
    if temp:
        z = np.log(np.clip(jueces["B"], 1e-6, 1 - 1e-6) / np.clip(1 - jueces["B"], 1e-6, 1))
        pt = 1 / (1 + np.exp(-z / temp))
        out("\nCALIBRACION de B (T = {:.3f}, ajustada en calibra): ECE {:.3f} sin T, {:.3f} "
            "con T".format(temp, ece(y, jueces["B"]), ece(y, pt)))

    # --- 6. escribir -------------------------------------------------------------------
    ficha = {"fecha": dt.datetime.now().isoformat(timespec="seconds"),
             "git_commit": git("rev-parse", "HEAD"),
             "git_sin_commitear": bool(git("status", "--porcelain")),
             "elegido": info["nombre"], "elegido_commit_entrenamiento":
             res["ficha"]["git_commit"], "modelo_elegido_sha256":
             sha256(ELEGIDO / "model.safetensors"), "torch": torch.__version__,
             "dispositivo": dev}
    out("\nficha: " + json.dumps(ficha, ensure_ascii=False))
    destino = ENSAYO if args.ensayo else INFORME
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    if not args.ensayo:
        p = t[["n", "conjunto", "estrato"]].copy()
        p["y"] = y
        for k, v in list(jueces.items()) + list(ablacion.items()):
            p[k] = v
        p.to_csv(PUNTAJES, index=False, encoding="utf-8")
    print("\n-> {}".format(destino))


if __name__ == "__main__":
    main()
