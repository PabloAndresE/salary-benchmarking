"""D-066: la prima del titulo en ingles, bruta y ajustada por tamano de empresa (D-063).

Pares de D-055 (titulo en ingles con datos directos cuya traduccion cae en OTRO grupo con datos), con la base v26
configurada como la API (juez, nivel por grupo, traductor con glosario). Por par: mediana de votos del ingles menos
la del equivalente; bruta y con `voto - delta(L, s)`. Mediana entre pares e IC por bootstrap de pares.

    ../../../.venv/bin/python 76_prima_ingles_tamano.py

SALIDA: salidas/76_prima_ingles_tamano.txt (agregados; sin titulos ni sueldos por empresa)
"""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto import idioma  # noqa: E402
from benchmarking.producto.base_referencia import (MIN_EMPRESAS, SEGMENTOS, BaseReferencia,  # noqa: E402
                                                   _norm_segmento)
from benchmarking.producto.juez import cargar as cargar_juez  # noqa: E402


def pct(x):
    return 100 * (np.exp(x) - 1)


def resumen(x, rng, n=1000):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 5:
        return "n={} (pocos)".format(len(x))
    b = [np.median(rng.choice(x, len(x))) for _ in range(n)]
    lo, hi = np.percentile(b, [2.5, 97.5])
    return "{:+.1f} % [{:+.1f}, {:+.1f}] (n={})".format(pct(np.median(x)), pct(lo), pct(hi), len(x))


def main():
    spec = importlib.util.spec_from_file_location("e41", AQUI / "41_base_v16.py")
    e41 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e41)
    marco = e41.cargar_marco()
    b = BaseReferencia.cargar(RAIZ / "demo" / "base_v26.npz", e41._Ajustes.get_sbu)
    b.juez = cargar_juez(RAIZ / "modelos" / "juez_v3")
    b.juez_vecinos = True
    b.nivel_por_grupo()
    b.candado_nivel = True
    b.traductor = idioma.cargar(RAIZ / "modelos" / "opus-mt-en-es")
    b.idioma_sueldo = "siempre"
    b.candado_glosario = True
    emb = {c: b.Z[i] for i, c in enumerate(b.celdas)}
    et = np.load(SAL / "72_emb_traducciones.npz", allow_pickle=True)
    emb.update({str(x): z for x, z in zip(et["textos"], et["X"])})
    ing = [c for c in b.celdas if idioma.es_ingles(c) and b.emp[b.idx[c]] >= MIN_EMPRESAS]
    r = b.resolver_idioma(ing, emb)
    pares = [(b.idx[t], v[0]) for t, v in r.items()
             if b.grupo[b.idx[t]] != b.grupo[v[0]] and b.emp[v[0]] >= MIN_EMPRESAS]

    # votos por (grupo, empresa), con segmento y nivel del grupo
    d = marco[["cargo_norm", "empresa_ruc", "segmento", "y"]].dropna(subset=["y"]).copy()
    i = d["cargo_norm"].astype(str).map(b.idx)
    d = d[i.notna()].copy()
    d["g"] = b.grupo[i[i.notna()].astype(int).to_numpy()]
    v = d.groupby(["g", "empresa_ruc"]).agg(voto=("y", "median"), seg=("segmento", "first")).reset_index()
    v["k"] = v["seg"].map(lambda s: SEGMENTOS.index(_norm_segmento(s)) if _norm_segmento(s) else -1)
    nivel_g = pd.Series(b.nivel).groupby(b.grupo).first()
    v["L"] = v["g"].map(nivel_g)
    ok = (v["k"] >= 0) & v["L"].notna()
    v["aj"] = np.nan
    v.loc[ok, "aj"] = v.loc[ok, "voto"] - b.delta_tam[v.loc[ok, "L"].astype(int), v.loc[ok, "k"]]
    v["grande"] = v["k"] == SEGMENTOS.index("GRANDE")
    por_g = {g: x for g, x in v.groupby("g")}

    filas = []
    for a, c in pares:
        ga, gc = b.grupo[a], b.grupo[c]
        if ga not in por_g or gc not in por_g:
            continue
        va, vc = por_g[ga], por_g[gc]
        fa, fc = va[va["k"] >= 0], vc[vc["k"] >= 0]
        filas.append({"L": b.nivel[a], "bruta": va["voto"].median() - vc["voto"].median(),
                      "bruta_seg": (fa["voto"].median() - fc["voto"].median()) if len(fa) >= 3 and len(fc) >= 3 else np.nan,
                      "ajustada": (fa["aj"].median() - fc["aj"].median()) if len(fa) >= 3 and len(fc) >= 3 else np.nan,
                      "grande_en": fa["grande"].mean() if len(fa) else np.nan,
                      "grande_es": fc["grande"].mean() if len(fc) else np.nan})
    f = pd.DataFrame(filas)
    rng = np.random.default_rng(66)
    out = ["76 · PRIMA DEL TITULO EN INGLES Y TAMANO DE EMPRESA (D-066)",
           "pares (ingles con datos -> equivalente en otro grupo con datos): {}".format(len(f)),
           "",
           "prima bruta (todos los votos):              " + resumen(f["bruta"], rng),
           "prima bruta (solo votos con segmento):      " + resumen(f["bruta_seg"], rng),
           "prima AJUSTADA por tamano (voto - delta):   " + resumen(f["ajustada"], rng),
           "",
           "empresas GRANDE: ingles {:.0%} | equivalente en espanol {:.0%} (mediana entre pares)".format(
               f["grande_en"].median(), f["grande_es"].median()),
           "", "por nivel (ajustada):"]
    for lv, x in f.groupby("L"):
        out.append("   nivel {:.0f}: bruta {} | ajustada {}".format(lv, resumen(x["bruta_seg"], rng),
                                                                  resumen(x["ajustada"], rng)))
    (SAL / "76_prima_ingles_tamano.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
