"""D-049, criterios a, b y c del clasificador de nivel (las etiquetas de Qwen, `60`).

    muestra    los 100 titulos SIN palabra de rango para que el autor los clasifique a ciegas (c).
               Se sortean con peso por personas y no dependen de Qwen; se pueden armar antes.
    medir      a) control: coincidencia con la tabla en los titulos con palabra de rango (>= 90 %)
               b) escalera: en los titulos sin palabra de rango, la mediana del sueldo por nivel de
                  Qwen sube en cada escalon (IC 95 % > 0, bootstrap de empresas), y el placebo no
               c) kappa ponderado con el autor (>= 0,6), si ya lleno la muestra

    ../../../.venv/bin/python 61_validar_nivel.py muestra
    ../../../.venv/bin/python 61_validar_nivel.py medir

SALIDAS: salidas/61_nivel_para_juzgar.csv, 61_validacion_nivel.txt
"""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.nivel import nivel_rubrica  # noqa: E402

SEM, N_REP = 20261006, 400
ETQ = SAL / ("60_niveles_qwen_v2.parquet" if "v2" in sys.argv else "60_niveles_qwen.parquet")


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def base():
    b = np.load(RAIZ / "demo" / "base_v18.npz", allow_pickle=True)
    return pd.DataFrame({"titulo": [str(c) for c in b["celdas"]], "personas": b["personas"].astype(float),
                         "emp": b["emp"].astype(int), "grupo": b["grupo"].astype(int)})


def muestra():
    # por GRUPO de la base (sin repetir `VENDEDOR` / `VENDEDOR (A)`), fuera los grupos donde algun
    # titulo lleva palabra de rango (asi tambien las erratas `ASITENTE`, unidas por la capa 0)
    d = base()
    d["rango"] = [nivel_rubrica(t) is not None for t in d["titulo"]]
    g = d.groupby("grupo")
    d = (d.sort_values("personas", ascending=False).groupby("grupo").head(1).set_index("grupo")
         .assign(personas=g["personas"].sum(), rango=g["rango"].any()))
    d = d[~d["rango"]].reset_index()
    rng = np.random.default_rng(SEM)
    p = d["personas"].to_numpy() / d["personas"].sum()
    i = rng.choice(len(d), 100, replace=False, p=p)
    out = d.iloc[i][["titulo"]].reset_index(drop=True)
    out.insert(0, "n_ciego", np.arange(1, 101))
    out["nivel"] = ""
    out["nota"] = ""
    out.to_csv(SAL / "61_nivel_para_juzgar.csv", index=False, encoding="utf-8-sig")
    print("100 titulos en 61_nivel_para_juzgar.csv. Escala: 1 operativo/auxiliar/asistente, 2 tecnico o "
          "profesional sin equipo, 3 especialista/coordinador/supervisor, 4 jefe/subgerente, 5 gerente/"
          "director; 0 si no es un cargo.")


def mediana_ponderada(y, w):
    o = np.argsort(y)
    c = np.cumsum(w[o])
    return y[o][np.searchsorted(c, c[-1] / 2)]


def escalera(m, col, rng):
    """Mediana de y por nivel y diferencia por escalon, con IC por bootstrap de empresas."""
    emp = m["empresa_ruc"].astype("category").cat.codes.to_numpy()
    ne = emp.max() + 1
    y, niv = m["y"].to_numpy(float), m[col].to_numpy(int)
    niveles = sorted(set(niv) - {0})
    pto = {k: mediana_ponderada(y[niv == k], np.ones((niv == k).sum())) for k in niveles}
    reps = []
    for _ in range(N_REP):
        w = rng.poisson(1.0, ne)[emp].astype(float)
        fila = {}
        for k in niveles:
            s = (niv == k) & (w > 0)
            fila[k] = mediana_ponderada(y[s], w[s]) if s.any() else np.nan
        reps.append(fila)
    r = pd.DataFrame(reps)
    pasos = []
    for a, b in zip(niveles[:-1], niveles[1:]):
        dif = r[b] - r[a]
        pasos.append((a, b, pto[b] - pto[a], np.nanpercentile(dif, 2.5), np.nanpercentile(dif, 97.5)))
    return pto, pasos, {k: int((niv == k).sum()) for k in niveles}


def medir():
    q = pd.read_parquet(ETQ)
    q = q[q["nivel"] >= 0]
    out = ["61 · VALIDACION DEL NIVEL DE QWEN (D-049), {}".format(ETQ.name), "etiquetas: {:,} titulos".format(len(q))]
    # a) control
    q["tabla"] = [nivel_rubrica(t) for t in q["titulo"]]
    c = q[q["tabla"].notna() & (q["nivel"] > 0)]
    acu = (c["nivel"] == c["tabla"]).mean()
    out += ["\na) CONTROL: titulos con palabra de rango: {:,}; Qwen coincide con la tabla en {:.1%} "
            "(exigido >= 90 %) -> {}".format(len(c), acu, "CUMPLE" if acu >= 0.90 else "NO CUMPLE"),
            "   matriz (filas tabla, columnas Qwen):",
            pd.crosstab(c["tabla"].astype(int), c["nivel"]).to_string()]
    # b) escalera
    e41 = cargar("e41", "41_base_v16.py")
    mk = e41.cargar_marco()[["cargo_norm", "empresa_ruc", "y"]].dropna()
    mk["cargo_norm"] = mk["cargo_norm"].astype(str)
    # «sin palabra de rango» por GRUPO de la base, como en `muestra`: fuera tambien las erratas de
    # una palabra de rango (`SUPERVOSR`, `JEDE DE VENTAS`), que la tabla no reconoce pero la capa 0
    # une a su grupo. (Corregido 2026-10-06: la primera corrida filtraba por titulo y las contaba.)
    b = base()
    b["rango"] = [nivel_rubrica(t) is not None for t in b["titulo"]]
    con_rango = set(b.loc[b.groupby("grupo")["rango"].transform("any"), "titulo"])
    sin = q[q["tabla"].isna() & (q["nivel"] > 0) & ~q["titulo"].isin(con_rango)].set_index("titulo")["nivel"]
    m = mk[mk["cargo_norm"].isin(sin.index)].copy()
    m["nivel"] = sin.reindex(m["cargo_norm"]).to_numpy()
    rng = np.random.default_rng(SEM)
    perm = pd.Series(rng.permutation(sin.to_numpy()), index=sin.index)
    m["placebo"] = perm.reindex(m["cargo_norm"]).to_numpy()
    ok_b = True
    for col, nombre in (("nivel", "Qwen"), ("placebo", "PLACEBO (niveles permutados entre titulos)")):
        pto, pasos, n = escalera(m, col, rng)
        out.append("\nb) ESCALERA, {}: {:,} personas en {:,} titulos sin palabra de rango".format(
            nombre, len(m), m["cargo_norm"].nunique()))
        out.append("   personas por nivel " + str(n))
        out.append("   mediana de y por nivel " + ", ".join("{}: {:.3f}".format(k, v) for k, v in pto.items()))
        todos = True
        for a, b, d, lo, hi in pasos:
            out.append("   {} -> {}: {:+.3f} [{:+.3f}, {:+.3f}] {}".format(a, b, d, lo, hi, "sube" if lo > 0 else "NO"))
            todos &= lo > 0
        if col == "nivel":
            ok_b = todos
        else:
            ok_b &= not todos
    out.append("\n>>> b) {} <<<".format("CUMPLE" if ok_b else "NO CUMPLE"))
    # c) kappa
    f = SAL / "61_nivel_para_juzgar.csv"
    if f.exists() and "sin_c" not in sys.argv:            # `sin_c`: a y b antes de que el autor cierre c
        j = pd.read_csv(f, sep=None, engine="python", encoding="utf-8-sig", dtype=str, keep_default_na=False)
        j = j[j["nivel"].str.strip() != ""]
        if len(j) == 100:
            from sklearn.metrics import cohen_kappa_score
            jj = j.merge(q[["titulo", "nivel"]], on="titulo", suffixes=("_autor", "_qwen"))
            ka = cohen_kappa_score(jj["nivel_autor"].astype(int), jj["nivel_qwen"].astype(int), weights="quadratic")
            out += ["\nc) AUTOR: kappa ponderado (cuadratico) {:.2f} en {} titulos (exigido >= 0,6) -> {}".format(
                ka, len(jj), "CUMPLE" if ka >= 0.6 else "NO CUMPLE"),
                pd.crosstab(jj["nivel_autor"].astype(int), jj["nivel_qwen"].astype(int)).to_string()]
        else:
            out.append("\nc) AUTOR: faltan juicios ({} de 100)".format(len(j)))
    (SAL / "61_validacion_nivel{}.txt".format("_v2" if "v2" in sys.argv else "")).write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    muestra() if sys.argv[1:] == ["muestra"] else medir()
