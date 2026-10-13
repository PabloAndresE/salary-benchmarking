"""Oro humano de pares «mismo cargo» (si/no) para la tesis: los lotes juzgados a mano y los sinonimos aprobados."""
import io
import pathlib

import pandas as pd

RAIZ = pathlib.Path(__file__).resolve().parents[2]
S = RAIZ / "research/experimentos/e2_nivel/salidas"
LOTES = [("13e_para_juzgar.csv", "comun", "raro"), ("20_para_juzgar.csv", "comun", "raro"),
         ("30_lote_para_juzgar.csv", "comun", "raro"), ("43_auditoria_para_juzgar.csv", "a", "b"),
         ("45_auditoria_para_juzgar.csv", "a", "b"), ("52_validacion_para_juzgar.csv", "a", "b")]


def _leer(f):
    txt = (S / f).read_text(encoding="utf-8-sig")
    sep = ";" if txt.splitlines()[0].count(";") > txt.splitlines()[0].count(",") else ","
    return pd.read_csv(io.StringIO(txt), sep=sep, dtype=str)


def pares(idx):
    """DataFrame a, b, y (1 = mismo cargo), fuente; solo pares con los dos titulos en la base, sin repetir."""
    out = []
    for f, ca, cb in LOTES:
        d = _leer(f)
        y = d["mismo"].fillna("").str.strip().str.lower()
        out.append(pd.DataFrame({"a": d[ca].str.strip().str.upper(), "b": d[cb].str.strip().str.upper(),
                                 "y": y, "fuente": f[:3].rstrip("_")}))
    s = pd.read_csv(RAIZ / "src/benchmarking/producto/datos/sinonimos_v2/sinonimos.csv", dtype=str)
    out.append(pd.DataFrame({"a": s["titulo_a"].str.strip().str.upper(), "b": s["titulo_b"].str.strip().str.upper(),
                             "y": "si", "fuente": "sinonimos"}))
    p = pd.concat(out, ignore_index=True)
    p = p[p["y"].isin(["si", "no"]) & p["a"].isin(idx) & p["b"].isin(idx) & (p["a"] != p["b"])].copy()
    p["y"] = (p["y"] == "si").astype(int)
    k = [tuple(sorted(x)) for x in zip(p["a"], p["b"])]
    p["clave"] = k
    return p.drop_duplicates("clave").drop(columns="clave").reset_index(drop=True)
