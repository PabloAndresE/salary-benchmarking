"""¿Las bandas tienen sentido con respecto al cargo? Dos pruebas (exploratorias, sin criterio previo).

1. COBERTURA. Con la configuracion del producto (base agrupada de D-046 + juez en la consulta, D-048) y
   las empresas apartadas de `54`: que fraccion de los votos (la mediana de una empresa en un cargo) cae
   dentro de la banda que recibio su cargo. Si la banda esta bien calibrada: ~50 % en p25-p75 y ~80 % en
   p10-p90. Por tipo de resultado, confianza y respaldo.

2. COHERENCIA INTERNA, sobre `demo/base_v17.npz` (grupos con >= 3 empresas): ¿la mediana respeta el
   orden que esperaria un experto?
     grado        `LABORATORISTA 1` < `2` < `3` (mismo titulo salvo el numero de grado final)
     seniority    `X JR` < `X` < `X SR` (mismo titulo salvo la marca)
     nivel        en la misma AREA (el titulo sin palabras de rango ni conectores), mas nivel de la
                  rubrica -> mas sueldo: `ASISTENTE DE COMPRAS` < `ANALISTA` < `JEFE` < `GERENTE`
   Se cuenta la fraccion de pares en el orden esperado y se listan las inversiones con mas personas.

    .venv/bin/python 58_validacion_bandas.py

SALIDA: salidas/58_validacion_bandas.txt
"""
import itertools
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.ingesta.composicion import _norm  # noqa: E402
from benchmarking.producto import capa0 as c0  # noqa: E402
from benchmarking.producto.nivel import (CONECTORES, RANGOS_RUBRICA, SENIORIDAD,  # noqa: E402
                                         nivel_rubrica, seniority_lexica)

MIN_EMP = 3
SBU = 470.0


def cobertura(out):
    f = SAL / "54_juez_50_clusters_confiable_cargos_venv.parquet"
    d = pd.read_parquet(f)
    d = d[np.isfinite(d["p25_log"]) & np.isfinite(d["p75_log"]) & np.isfinite(d["voto"])].copy()
    d["en50"] = (d["voto"] >= d["p25_log"]) & (d["voto"] <= d["p75_log"])
    ok80 = np.isfinite(d["p10_log"]) & np.isfinite(d["p90_log"])
    d["en80"] = np.where(ok80, (d["voto"] >= d["p10_log"]) & (d["voto"] <= d["p90_log"]), np.nan)
    d["debajo"] = d["voto"] < d["p25_log"]
    d["tipo"] = np.where(d["p_juez"].notna(), "asignado por el juez", d["base"].astype(str))
    d["respaldo"] = pd.cut(d["empresas_ref"], [0, 5, 10, 30, 100, 1e9],
                           labels=["3-5", "6-10", "11-30", "31-100", ">100"], right=True)
    out("1. COBERTURA: ¿cae el voto de una empresa nueva dentro de la banda de su cargo?")
    out("   votos con banda: {:,} (de {:,} empresas apartadas)".format(len(d), d["empresa"].nunique()))
    out("   esperado si la banda esta bien calibrada: 50 % en p25-p75, 80 % en p10-p90")

    def fila(nombre, g):
        out("   {:<34} n={:>6,}   p25-p75 {:5.1%}   p10-p90 {:5.1%}   debajo de p25 {:5.1%}".format(
            nombre, len(g), g["en50"].mean(), np.nanmean(g["en80"].astype(float)), g["debajo"].mean()))
    fila("TODOS", d)
    for col in ("tipo", "confianza", "respaldo"):
        out("   por {}:".format(col))
        for k, g in d.groupby(col, observed=True):
            if len(g) >= 100:
                fila("  " + str(k), g)


def representantes():
    b = np.load(RAIZ / "demo" / "base_v17.npz", allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    capa = c0.Capa0.de_json(str(b["capa0_json"]), celdas)
    grupo = b["grupo"].astype(int)
    rep = {}
    for i, (c, g) in enumerate(zip(celdas, grupo)):
        clave = (c != capa.atomo(c), len(c), c)
        if g not in rep or clave < rep[g][0]:
            rep[g] = (clave, i)
    filas = [(g, celdas[i], float(b["m"][i]), int(b["emp"][i]), int(b["personas"][i]))
             for g, (_, i) in rep.items()]
    d = pd.DataFrame(filas, columns=["grupo", "titulo", "m", "emp", "personas"])
    return d[d["emp"] >= MIN_EMP].reset_index(drop=True)


def palabras(t):
    return c0.limpiar(_norm(t)).split()


def contraste(out, nombre, familias, rango):
    """familias: clave -> filas (titulo, m, emp, personas, valor). Pares con valor distinto."""
    pares = []
    for clave, fs in familias.items():
        for a, b in itertools.combinations(fs, 2):
            if a["valor"] == b["valor"]:
                continue
            lo, hi = (a, b) if a["valor"] < b["valor"] else (b, a)
            pares.append({"familia": clave, "bajo": lo["titulo"], "alto": hi["titulo"],
                          "dif": hi["m"] - lo["m"], "personas": min(lo["personas"], hi["personas"])})
    p = pd.DataFrame(pares)
    if not len(p):
        out("   {}: sin pares".format(nombre))
        return
    ok = (p["dif"] > 0).mean()
    w = np.average(p["dif"] > 0, weights=p["personas"])
    out("\n   {}: {:,} pares en {:,} familias; en el orden esperado {:.0%} (ponderado por personas {:.0%});"
        " diferencia mediana {:+.1%}".format(nombre, len(p), p["familia"].nunique(), ok, w,
                                            np.expm1(p["dif"].median())))
    inv = p[p["dif"] < 0].sort_values("personas", ascending=False).head(10)
    for _, r in inv.iterrows():
        out("      invertido: {:<34} ({}) gana {:+.0%} frente a {:<34} ({})".format(
            r["bajo"][:34], rango, np.expm1(-r["dif"]), r["alto"][:34], "mas alto"))


def coherencia(out):
    d = representantes()
    out("\n2. COHERENCIA INTERNA (base_v17, {:,} grupos con >= {} empresas)".format(len(d), MIN_EMP))
    # grado
    fam = {}
    for _, r in d.iterrows():
        g = c0.grado_numerico(r["titulo"])
        if len(g) == 1:
            fam.setdefault(c0.quitar_grado_final(r["titulo"]), []).append({**r, "valor": min(g)})
    contraste(out, "GRADO (mayor numero, mas sueldo)", {k: v for k, v in fam.items() if len(v) > 1}, "grado menor")
    # seniority
    marcas = {w for w in SENIORIDAD if " " not in w}
    fam = {}
    for _, r in d.iterrows():
        clave = " ".join(w for w in palabras(r["titulo"]) if w not in marcas)
        fam.setdefault(clave, []).append({**r, "valor": seniority_lexica(r["titulo"])})
    contraste(out, "SENIORITY (JR < sin marca < SR)", {k: v for k, v in fam.items() if len(v) > 1}, "menos senior")
    # nivel
    rangos = set(RANGOS_RUBRICA)
    fam = {}
    for _, r in d.iterrows():
        n = nivel_rubrica(r["titulo"])
        if not n:
            continue
        area = " ".join(w for w in palabras(r["titulo"]) if w not in rangos and w not in CONECTORES)
        if area and seniority_lexica(r["titulo"]) == 0 and not c0.grado_numerico(r["titulo"]):
            fam.setdefault(area, []).append({**r, "valor": n})
    contraste(out, "NIVEL (misma area, mas nivel, mas sueldo)", {k: v for k, v in fam.items() if len(v) > 1}, "nivel menor")


def main():
    lineas = []

    def out(s=""):
        print(s, flush=True)
        lineas.append(s)
    cobertura(out)
    coherencia(out)
    (SAL / "58_validacion_bandas.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
