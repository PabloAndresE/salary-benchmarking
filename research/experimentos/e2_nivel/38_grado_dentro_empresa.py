"""Criterio A de D-040, la version que DECIDE: ¿el grado mayor paga mas DENTRO de la empresa?

Registrado antes de medir (D-040, commit 2c620e8):
    - FAMILIA: titulos identicos (tras la capa 0 v1) salvo un grado ORDINAL al final: 1-9 o
      I-X. Las letras se reportan aparte y no deciden.
    - MEDIDA: dentro de la MISMA empresa y el mismo anio, la diferencia de la mediana de
      `y = log(sueldo / SBU)` entre un grado y el siguiente que esa empresa tenga (grado mayor
      menos menor). Media por familia; media entre familias con IC 95 % por bootstrap de
      familias (10.000).
    - TRES RESULTADOS (en %, exp(diferencia) - 1):
        escalon      media >= 5 % y el IC entero sobre cero      -> NO se fusiona
        equivalente  el IC entero dentro de +-5 %                -> se fusiona
        inconcluso   cualquier otro caso                          -> NO se fusiona
DATOS: los mismos con que se construye la base: `nomina_features`, `en_clean`, 2024-2025, el
objetivo y el filtro de `evaluacion.datos` (cargo utilizable, sueldo >= SBU).

No se guarda ni se imprime ningun RUC: la empresa solo sirve para emparejar dentro de ella.
Usa el Python del sistema (BigQuery). Necesita `gcloud auth login`.

SALIDA: 38_grado_dentro_empresa.txt (agregados y ejemplos de familias, sin RUC)
"""
import pathlib
import re
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.ingesta.composicion import _norm  # noqa: E402
from benchmarking.producto import capa0  # noqa: E402

PROYECTO, DATASET = "act-cicd-stage-prueba", "benchmarking_tesis"
SBU = {2024: 460, 2025: 470}
PLACEHOLDERS = {"0", "-", "NA", "N/A", ".", "--", "---", "S/N", "SN", "X", "", "NAN", "NONE"}
B = 10_000
SEM = 20261010
UMBRAL = 0.05
ROM = {r: i + 1 for i, r in enumerate(capa0.ROMANOS)}
SQL = """
SELECT empresa_ruc, anio_valoracion, cargo_norm, sueldo
FROM `{p}.{d}.nomina_features`
WHERE en_clean AND anio_valoracion IN (2024, 2025)
"""


def grado_final(titulo, c):
    """(familia, grado, tipo) si el titulo termina en un grado; si no, None."""
    t = capa0.expandir_abreviaturas(_norm(titulo), c.abreviaturas)
    sin = capa0.quitar_grado_final(t)
    if sin == t:
        return None
    quitado = t[len(sin):].split()
    valor, tipo = None, None
    for tok in quitado:
        x = tok.strip("()#.")
        if x.isdigit():
            valor, tipo = int(x), "ordinal"
        elif x in ROM:
            valor, tipo = ROM[x], "ordinal"
        elif len(x) == 1 and x.isalpha() and tipo is None:
            valor, tipo = x, "letra"
    if valor is None:
        return None
    return c.atomo(sin), valor, tipo


def main():
    from google.cloud import bigquery
    cli = bigquery.Client(project=PROYECTO)
    df = cli.query(SQL.format(p=PROYECTO, d=DATASET)).to_dataframe()
    df["sueldo"] = pd.to_numeric(df["sueldo"], errors="coerce")
    df["y"] = np.log(df["sueldo"] / df["anio_valoracion"].map(SBU))
    ok = (df["y"].notna() & (df["y"] >= -1e-9)
          & ~df["cargo_norm"].astype(str).str.strip().str.upper().isin(PLACEHOLDERS)
          & ~df["cargo_norm"].astype(str).str.fullmatch(r"[0-9]+"))
    df = df[ok].copy()
    lineas = []

    def p(s=""):
        print(s, flush=True)
        lineas.append(s)

    p("=" * 78)
    p("38 · CRITERIO A DE D-040, DENTRO DE EMPRESA: ¿EL GRADO ES UN ESCALON SALARIAL?")
    p("=" * 78)
    p("filas evaluables 2024-2025: {:,}; titulos distintos: {:,}".format(
        len(df), df["cargo_norm"].nunique()))

    c = capa0.nueva("v1").preparar(sorted(set(df["cargo_norm"].astype(str))))
    titulos = df["cargo_norm"].astype(str).unique()
    info = {t: grado_final(t, c) for t in titulos}
    df["g"] = df["cargo_norm"].astype(str).map(info)
    g = df[df["g"].notna()].copy()
    g["familia"] = g["g"].map(lambda x: x[0])
    g["grado"] = g["g"].map(lambda x: x[1])
    g["tipo"] = g["g"].map(lambda x: x[2])
    p("filas con un grado al final: {:,} ({:.1%}); ordinal {:,}, letra {:,}".format(
        len(g), len(g) / len(df), int((g["tipo"] == "ordinal").sum()),
        int((g["tipo"] == "letra").sum())))

    def contrastes(sub, ordenable=True):
        med = (sub.groupby(["empresa_ruc", "anio_valoracion", "familia", "grado"])["y"]
               .agg(["median", "size"]).reset_index())
        filas = []
        for (_, _, fam), h in med.groupby(["empresa_ruc", "anio_valoracion", "familia"]):
            if len(h) < 2:
                continue
            h = h.sort_values("grado") if ordenable else h
            gr, m, n = h["grado"].tolist(), h["median"].to_numpy(), h["size"].to_numpy()
            for k in range(len(gr) - 1):
                filas.append({"familia": fam, "bajo": gr[k], "alto": gr[k + 1],
                              "dif": float(m[k + 1] - m[k]),
                              "personas": int(n[k] + n[k + 1])})
        return pd.DataFrame(filas)

    pares = contrastes(g[g["tipo"] == "ordinal"])
    fam = pares.groupby("familia")["dif"].mean()
    pct = lambda x: np.expm1(x)
    rng = np.random.default_rng(SEM)
    v = fam.to_numpy()
    bs = np.array([rng.choice(v, len(v)).mean() for _ in range(B)])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    media = v.mean()
    if pct(media) >= UMBRAL and lo > 0:
        res = "ESCALON -> no se fusiona"
    elif pct(lo) > -UMBRAL and pct(hi) < UMBRAL:
        res = "EQUIVALENTE -> se fusiona"
    else:
        res = "INCONCLUSO -> no se fusiona"
    p("\nORDINALES (deciden)")
    p("   contrastes dentro de empresa (empresa x anio x familia, grados consecutivos): {:,}".format(
        len(pares)))
    p("   familias: {:,}; empresas-anio distintas: implicitas en los contrastes".format(len(fam)))
    p("   diferencia media entre familias (grado mayor - menor): {:+.1%}   IC 95 % [{:+.1%}, "
      "{:+.1%}]".format(pct(media), pct(lo), pct(hi)))
    p("   >>> CRITERIO A: {} <<<".format(res))
    p("   descriptivo: familias donde el grado mayor paga mas: {:.0%}; contrastes donde paga mas: "
      "{:.0%}; mediana de los contrastes {:+.1%}".format((v > 0).mean(), (pares["dif"] > 0).mean(),
                                                         pct(pares["dif"].median())))
    pw = np.average(pares["dif"], weights=pares["personas"])
    p("   descriptivo: media ponderada por personas de los contrastes {:+.1%}".format(pct(pw)))
    por_salto = pares.assign(salto=lambda d: d["alto"] - d["bajo"]).groupby("salto")["dif"]
    p("   por tamano del salto de grado: {}".format(
        {int(k): "{:+.1%} (n={})".format(pct(x.mean()), len(x)) for k, x in por_salto
         if len(x) >= 10}))
    top = pares.groupby("familia").agg(n=("dif", "size"), dif=("dif", "mean")).sort_values(
        "n", ascending=False).head(15)
    p("   las 15 familias con mas contrastes:")
    for f_, r in top.iterrows():
        p("      {:<45} n={:>4}   {:+.1%}".format(f_[:45], int(r.n), pct(r.dif)))

    letras = contrastes(g[g["tipo"] == "letra"], ordenable=False)
    if len(letras):
        p("\nLETRAS (no deciden: sin orden fiable): {:,} contrastes en {:,} familias; diferencia "
          "absoluta media {:.1%}".format(len(letras), letras["familia"].nunique(),
                                        pct(letras["dif"].abs().mean())))
    (SAL / "38_grado_dentro_empresa.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
