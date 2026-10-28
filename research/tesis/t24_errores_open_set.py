"""T-024: analisis de errores del open set del sistema propuesto (descriptivo; registro, T-024).

    .venv/bin/python research/tesis/t24_errores_open_set.py

SALIDAS: salidas/t24_errores.txt (agregados, sin titulos); t24_ejemplos.txt (con titulos, fuera del repo, 600)
"""
import importlib.util
import os
import pathlib
import re
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.idioma import es_ingles  # noqa: E402
from benchmarking.producto.nivel import nivel_rubrica, seniority_lexica  # noqa: E402

SEM = 20261028
UMBRAL = 0.90
CONECTORES = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "E", "EN", "A", "AL", "O", "U", "CON", "POR", "PARA"}


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def categorias(q):
    pal = str(q).upper().split()
    return {
        "ingles": bool(es_ingles(q)),
        "abreviatura": any(p.endswith(".") or (1 <= len(re.sub(r"[^A-ZÑ]", "", p)) <= 3
                                               and re.sub(r"[^A-ZÑ]", "", p) not in CONECTORES) for p in pal),
        "numero o codigo": bool(re.search(r"\d", q)),
        "doble (/)": "/" in q,
        "largo (6+ palabras)": len(pal) >= 6,
        "grado o seniority": bool(seniority_lexica(q)),
    }


def nivel_distinto(q, e):
    a, b = nivel_rubrica(q), nivel_rubrica(e)
    return bool(e) and a is not None and b is not None and a != b


def consultas():
    t22 = cargar("t22", AQUI / "t22_oro_humano.py")
    J = t22.juicios()
    t = pd.read_parquet(SAL / "t10b_decisiones.parquet")
    g = pd.read_parquet(SAL / "t10b_qwen.parquet")
    pool = g.groupby("q").agg(alguno=("si", lambda s: bool((s == 1).any())),
                              todos_no=("si", lambda s: bool((s == 0).all())))
    t["clase"] = t["q"].map(lambda q: "con equivalente" if pool.loc[q, "alguno"] else
                            ("nueva" if pool.loc[q, "todos_no"] else "fuera"))
    t = t[t["clase"] != "fuera"][["q", "clase", "e_A", "s_A"]].assign(fuente="T-010b")
    n19 = t22.nuevas_t19(J)[["q", "e_A", "s_A"]].assign(clase="nueva", fuente="T-019")
    d = pd.concat([t, n19], ignore_index=True)          # T-019: el mismo titulo, otros candidatos (sin su familia)
    d["j"] = [J.get((q, e), np.nan) if e else np.nan for q, e in zip(d["q"], d["e_A"])]
    rec = d["s_A"].to_numpy() >= UMBRAL
    con = (d["clase"] == "con equivalente").to_numpy()
    j = d["j"].to_numpy()
    d["resultado"] = np.select(
        [con & rec & (j == 1), con & rec & (j == 0), con & rec, con & ~rec, ~con & rec],
        ["acierto", "reconoce mal", "sin verdad", "no reconoce", "falso reconocido"], "acierto")
    d = d[d["resultado"] != "sin verdad"].reset_index(drop=True)
    cat = pd.DataFrame([categorias(q) for q in d["q"]])
    d = pd.concat([d, cat], axis=1)
    d["nivel distinto (par elegido)"] = [nivel_distinto(q, e) for q, e in zip(d["q"], d["e_A"])]
    return d, list(cat.columns)


def tasa_ic(x, rng, b=2000):
    x = np.asarray(x, float)
    if len(x) == 0:
        return np.nan, np.nan, np.nan
    bs = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(b)]
    return x.mean(), *np.percentile(bs, [2.5, 97.5])


def dif_ic(a, b_, rng, b=2000):
    a, b_ = np.asarray(a, float), np.asarray(b_, float)
    if len(a) == 0 or len(b_) == 0:
        return np.nan, np.nan, np.nan
    bs = [a[rng.integers(0, len(a), len(a))].mean() - b_[rng.integers(0, len(b_), len(b_))].mean() for _ in range(b)]
    return a.mean() - b_.mean(), *np.percentile(bs, [2.5, 97.5])


def main():
    d, cats = consultas()
    rng = np.random.default_rng(SEM)
    con = d[d["clase"] == "con equivalente"]
    nue = d[d["clase"] == "nueva"]
    out = ["T-024 · errores del open set del sistema propuesto (Qwen + cross-encoder reentrenado, P >= 0,90)",
           "consultas con verdad: {:,} con equivalente, {:,} nuevas (T-010b {:,}; nuevas de T-019 {:,})".format(
               len(con), len(nue), int((d["fuente"] == "T-010b").sum()), int((d["fuente"] == "T-019").sum())),
           "", "RESULTADOS"]
    for clase, x in (("con equivalente", con), ("nueva", nue)):
        vc = x["resultado"].value_counts()
        out.append("  {}: ".format(clase) + "; ".join("{} {:,} ({:.1%})".format(k, v, v / len(x)) for k, v in vc.items()))
    rm = con[con["resultado"] == "reconoce mal"]
    out += ["", "P DEL ELEGIDO EN LOS ERRORES DE RECONOCIMIENTO",
            "  reconoce mal (n = {}): cerca del umbral (0,90-0,95) {:.0%}; confiada (>= 0,98) {:.0%}".format(
                len(rm), ((rm["s_A"] >= 0.90) & (rm["s_A"] < 0.95)).mean(), (rm["s_A"] >= 0.98).mean()),
            "  falso reconocido (n = {}): cerca del umbral {:.0%}; confiada {:.0%}".format(
                int((nue["resultado"] == "falso reconocido").sum()),
                ((nue["s_A"] >= 0.90) & (nue["s_A"] < 0.95))[nue["resultado"] == "falso reconocido"].mean(),
                (nue["s_A"] >= 0.98)[nue["resultado"] == "falso reconocido"].mean()),
            "  no reconoce (n = {}): P entre 0,80 y 0,90 {:.0%}; P < 0,50 {:.0%}".format(
                int((con["resultado"] == "no reconoce").sum()),
                ((con["s_A"] >= 0.80) & (con["s_A"] < 0.90))[con["resultado"] == "no reconoce"].mean(),
                (con["s_A"] < 0.50)[con["resultado"] == "no reconoce"].mean())]
    out += ["", "TASA DE ERROR POR CATEGORIA DEL TITULO (con la categoria - sin ella; IC 95 %)"]
    for err, x in (("no reconoce", con), ("reconoce mal", con), ("falso reconocido", nue)):
        out.append("  {} (entre {:,} consultas {}):".format(err, len(x), "con equivalente" if x is con else "nuevas"))
        y = (x["resultado"] == err).to_numpy(float)
        for c in cats + (["nivel distinto (par elegido)"] if err != "no reconoce" else []):
            m = x[c].to_numpy(bool)
            if m.sum() < 5:
                out.append("    {:<30} n = {:>3}: muy pocos".format(c, int(m.sum())))
                continue
            dd, lo, hi = dif_ic(y[m], y[~m], rng)
            out.append("    {:<30} n = {:>3}: {:.1%} frente a {:.1%}  dif {:+.1%} [{:+.1%}, {:+.1%}]{}".format(
                c, int(m.sum()), y[m].mean(), y[~m].mean(), dd, lo, hi,
                "  <- MAS ERROR" if lo > 0 else ("  <- MENOS ERROR" if hi < 0 else "")))
    out += ["", "MEZCLA DE CATEGORIAS DENTRO DE LOS ERRORES (frente a los aciertos de la misma clase)"]
    for err, x in (("no reconoce", con), ("reconoce mal", con), ("falso reconocido", nue)):
        e_, a_ = x[x["resultado"] == err], x[x["resultado"] == "acierto"]
        out.append("  {} (n = {}): ".format(err, len(e_)) + "; ".join(
            "{} {:.0%} ({:.0%})".format(c, e_[c].mean(), a_[c].mean()) for c in cats + ["nivel distinto (par elegido)"]))
    (SAL / "t24_errores.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    ej = ["T-024 · ejemplos (con titulos de clientes: NO subir al repo)"]
    for err in ("reconoce mal", "no reconoce", "falso reconocido"):
        x = d[d["resultado"] == err].sort_values("s_A", ascending=False)
        ej += ["", "== " + err] + ["  {:.3f}  {}  ->  {}".format(s, q, e) for q, e, s in zip(x["q"], x["e_A"], x["s_A"])]
    (SAL / "t24_ejemplos.txt").write_text("\n".join(ej) + "\n", encoding="utf-8")
    os.chmod(SAL / "t24_ejemplos.txt", 0o600)


if __name__ == "__main__":
    main()
