"""D-045 §2: auditoria de los positivos lejanos de la v3, antes de entrenar el bi-encoder.

Registrado antes (D-045, commit 7fc818c). 100 pares de `43_pares.csv` con coseno < 0,85, P >= 0,9
y sin candado (al azar, sin los que ya estan en la auditoria de D-043), mezclados con 30 de
coseno < 0,85 y P <= 0,2. El autor los juzga a ciegas con la rubrica v6.

    python3 45_auditoria_lejanos.py            arma la auditoria
    python3 45_auditoria_lejanos.py decidir    aplica la regla

REGLA: si el autor dice `si` en el 80 % o mas de los 100 de P >= 0,9, los positivos lejanos entran
con P >= 0,9; si no, entran solo los que el autor revise.

SALIDAS: salidas/45_auditoria_para_juzgar.csv (n_ciego, a, b, mismo, nota), 45_auditoria_mapa.csv
(no abrir antes de juzgar), 45_auditoria_lejanos.txt
"""
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
SEM = 20261004
N_SI, N_NO = 100, 30
UMBRAL = 0.80


def armar():
    d = pd.read_csv(SAL / "43_pares.csv")
    d = d[~d["bloqueado"] & (d["coseno"] < 0.85)]
    ya = pd.read_csv(SAL / "43_auditoria_mapa.csv")
    ya = set(zip(ya["i"], ya["j"]))
    d = d[[(i, j) not in ya for i, j in zip(d["i"], d["j"])]]
    si = d[d["P"] >= 0.9].sample(N_SI, random_state=SEM).assign(grupo="P>=0,9")
    no = d[d["P"] <= 0.2].sample(N_NO, random_state=SEM).assign(grupo="P<=0,2")
    a = pd.concat([si, no]).sample(frac=1, random_state=SEM).reset_index(drop=True)
    a["n_ciego"] = np.arange(1, len(a) + 1)
    gira = np.random.default_rng(SEM).random(len(a)) < 0.5     # el orden del par, al azar
    a["A"] = np.where(gira, a["b"], a["a"])
    a["B"] = np.where(gira, a["a"], a["b"])
    a[["n_ciego", "A", "B"]].rename(columns={"A": "a", "B": "b"}).assign(
        mismo="", nota="").to_csv(SAL / "45_auditoria_para_juzgar.csv", index=False,
                                  encoding="utf-8-sig")
    a[["n_ciego", "i", "j", "a", "b", "grupo", "P", "coseno"]].to_csv(
        SAL / "45_auditoria_mapa.csv", index=False, encoding="utf-8")
    print("auditoria: {} pares ({} de P >= 0,9, {} de P <= 0,2)".format(len(a), N_SI, N_NO))
    print(pd.cut(si["coseno"], [0, .7, .75, .8, .85]).value_counts().sort_index().to_string())


def decidir():
    j = pd.read_csv(SAL / "45_auditoria_para_juzgar.csv", sep=None, engine="python",
                    encoding="utf-8-sig", dtype=str, keep_default_na=False)
    j["mismo"] = j["mismo"].str.strip().str.lower()
    if not j["mismo"].isin(["si", "no"]).all():
        raise SystemExit("ALTO: faltan {} juicios".format(int((~j["mismo"].isin(["si", "no"])).sum())))
    m = pd.read_csv(SAL / "45_auditoria_mapa.csv").merge(
        j[["n_ciego", "mismo"]].astype({"n_ciego": int}), on="n_ciego")
    out = []

    def p(s=""):
        print(s)
        out.append(s)

    p("45 · AUDITORIA DE LOS POSITIVOS LEJANOS DE LA v3 (D-045 §2)")
    for g, x in m.groupby("grupo"):
        p("   {}: {} pares; el autor dice si en {:.0%}".format(g, len(x), (x["mismo"] == "si").mean()))
    s = m[m["grupo"] == "P>=0,9"]
    p("\n   P >= 0,9 por tramo de coseno:")
    for t, x in s.groupby(pd.cut(s["coseno"], [0, .7, .75, .8, .85]), observed=True):
        p("      {}  n={:>3}  si {:.0%}".format(t, len(x), (x["mismo"] == "si").mean()))
    tasa = (s["mismo"] == "si").mean()
    p("\n>>> REGLA D-045: {:.0%} de si en los P >= 0,9 -> {} <<<".format(
        tasa, "los positivos lejanos entran con P >= 0,9" if tasa >= UMBRAL
        else "entran SOLO los positivos lejanos que revise el autor"))
    (SAL / "45_auditoria_lejanos.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    decidir() if sys.argv[1:] == ["decidir"] else armar()
