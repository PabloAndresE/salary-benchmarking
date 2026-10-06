"""D-046 criterio b: utilidad de la base agrupada, con el protocolo de D-025 / D-031 (`10`).

Sobre el 80 % de entrenamiento (`splits.partir`; el 20 % de test no se toca), un 25 % de las
empresas se aparta como validacion. La base se construye con el resto y se evalua el pinball de su
banda (p25 / p75) contra el voto de cada empresa apartada (la mediana de su gente en ese cargo). El
contraste es pareado por (empresa, cargo) y el IC por bootstrap de empresas (400, como en `10`).

VARIANTES (todas con los mismos datos y vectores):
    v15         la base de hoy: fusion por coseno >= 0,95 (D-015), erratas y genero
    v16         solo la capa 0 v1 (D-040, D-041), sin fusion por coseno
    clusters    v16 + los grupos de un clustering (`--clusters 50_clusters_<...>.parquet`)
    placebo     los MISMOS tamanos de cluster, con los nodos repartidos al azar entre ellos

D-046: la base agrupada se adopta si, frente a v15, el IC de la diferencia de pinball no queda
entero sobre cero, y el placebo SI empeora.

    python3 54_pinball.py --variante v15
    python3 54_pinball.py --variante clusters --clusters 50_clusters_completo_cargos.parquet
    python3 54_pinball.py --juntar

(Python del sistema: BigQuery. Los vectores salen de `demo/base_v15.npz`.)
SALIDAS: salidas/54_<variante>.parquet, 54_pinball.txt
"""
import argparse
import importlib.util
import json
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.evaluacion import splits  # noqa: E402
from benchmarking.producto import capa0 as c0mod  # noqa: E402
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402

SEM, N_REPLICAS = 20260917, 400          # los de `10`
# La particion de empresas depende de las versiones de numpy/pandas: corridas de entornos distintos
# NO se pueden emparejar (lo comprobado: 324 de 1.343 empresas en comun). `--entorno` marca el
# archivo para comparar solo corridas del mismo entorno.
ENTORNO = ""


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pinball(y, lo, hi):
    a = np.maximum(0.25 * (y - lo), -0.75 * (y - lo))
    b = np.maximum(0.75 * (y - hi), -0.25 * (y - hi))
    return (a + b) / 2.0


def ic(dif, empresas, rng, n=N_REPLICAS):
    g = pd.DataFrame({"e": empresas, "d": dif}).dropna().groupby("e")["d"].mean()
    e = g.index.to_numpy()
    b = [g[rng.choice(e, len(e), replace=True)].mean() for _ in range(n)]
    return float(g.mean()), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def grupos_de_clusters(archivo, placebo=False):
    """etiqueta -> cluster, por el grupo de base_v16 de cada etiqueta (los nodos del clustering)."""
    b = np.load(RAIZ / "demo" / "base_v16.npz", allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    g16 = dict(zip(celdas, b["grupo"].astype(int)))
    cl = pd.read_parquet(SAL / archivo)
    clus = cl["cluster"].to_numpy().copy()
    if placebo:
        clus = np.random.default_rng(99).permutation(clus)     # mismos tamanos, nodos al azar
    por_grupo = {g16[str(t)]: int(c) for t, c in zip(cl["titulo"], clus)}
    return {c: por_grupo[g16[c]] for c in celdas if g16[c] in por_grupo}


def una_variante(nom, clusters):
    e41 = cargar("e41", "41_base_v16.py")
    mk = e41.cargar_marco()
    mk = mk[[c for c in ("cargo_norm", "empresa_ruc", "y", "segmento", "ciiu_n1", "id_hash",
                         "n_empleados", "ciiu_n6") if c in mk.columns]].copy()
    mk["cargo_norm"] = mk["cargo_norm"].astype(str)
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train["empresa_ruc"].unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train["empresa_ruc"].isin(val)].copy()
    ts = train[train["empresa_ruc"].isin(val)].copy()
    v = (ts.dropna(subset=["y"]).groupby(["cargo_norm", "empresa_ruc"], sort=False)["y"]
           .median().reset_index().rename(columns={"y": "voto"}))
    b15 = np.load(RAIZ / "demo" / "base_v15.npz", allow_pickle=True)
    emb = {str(c): z for c, z in zip(b15["celdas"], b15["Z"])}
    kw = {}
    if nom != "v15":
        kw = dict(umbral_fusion=None, capa0=c0mod.nueva("v1"))
    con_nivel = ("nivel_v1", "nivel_v1_placebo", "nivel_v2", "nivel_v2_placebo")
    con_juez = ("juez", "juez_placebo", "juez_tabla", "juez_vecinos", "juez_vecinos_placebo") + con_nivel
    if nom in ("clusters", "placebo") + con_juez:
        kw["grupos"] = grupos_de_clusters(clusters, placebo=(nom == "placebo"))
    if nom in con_nivel:                 # D-049: el nivel de Qwen (y su placebo: permutado entre titulos)
        q = pd.read_parquet(SAL / ("60_niveles_qwen.parquet" if "v1" in nom else "60_niveles_qwen_v2.parquet"))
        niveles = dict(zip(q["titulo"].astype(str), q["nivel"].astype(int)))
        if nom.endswith("placebo"):
            t_ = list(niveles)
            niveles = dict(zip(t_, np.random.default_rng(7).permutation([niveles[x] for x in t_])))
        kw["niveles"] = niveles
    base = BaseReferencia.construir(tr, emb, e41._Ajustes.get_sbu, **kw)
    if nom in con_juez:                                       # D-048: el juez en la consulta
        from benchmarking.producto.juez import cargar as cargar_juez
        base.juez = cargar_juez(RAIZ / "research/experimentos/e2_nivel/salidas/22_modelos_v3/elegido")
        assert base.juez is not None, "no se pudo cargar el juez"
        base.juez_placebo = nom == "juez_placebo"
        # 2026-10-06: el juez filtra los vecinos de la analogia (y su placebo). `juez_tabla` es el
        # producto con la tabla de niveles en ingles; los de abajo, ademas, con el filtro.
        base.juez_vecinos = nom in ("juez_vecinos", "juez_vecinos_placebo") + con_nivel
        base.juez_vecinos_placebo = nom == "juez_vecinos_placebo"
    cargos = sorted(set(v["cargo_norm"]))
    out = base.referenciar(cargos, emb).set_index("cargo")
    perdida = pinball(v["voto"].to_numpy(float),
                      out["p25_log"].reindex(v["cargo_norm"]).to_numpy(float),
                      out["p75_log"].reindex(v["cargo_norm"]).to_numpy(float))
    directa = (out["base"].reindex(v["cargo_norm"]) == "datos directos").to_numpy()
    p_juez = (out["p_juez"].reindex(v["cargo_norm"]).to_numpy(float) if "p_juez" in out
              else np.full(len(v), np.nan))
    sufijo = nom if nom in ("v15", "v16") else "{}_{}".format(nom, pathlib.Path(clusters).stem)
    if ENTORNO:
        sufijo += "_" + ENTORNO
    print("{}: el juez asigno {:,} titulos de {:,}".format(
        sufijo, int(np.isfinite(out["p_juez"].to_numpy(float)).sum()) if "p_juez" in out else 0, len(cargos)))
    pd.DataFrame({"empresa": v["empresa_ruc"].to_numpy(), "cargo": v["cargo_norm"].to_numpy(),
                  "pinball": perdida, "directa": directa, "p_juez": p_juez,
                  # para la cobertura de las bandas (58): el voto y la banda que recibio
                  "voto": v["voto"].to_numpy(float),
                  **{c: out[c].reindex(v["cargo_norm"]).to_numpy(float)
                     for c in ("p10_log", "p25_log", "p75_log", "p90_log") if c in out},
                  "base": out["base"].reindex(v["cargo_norm"]).to_numpy(),
                  "confianza": out["confianza"].reindex(v["cargo_norm"]).to_numpy(),
                  "empresas_ref": out["empresas"].reindex(v["cargo_norm"]).to_numpy()}).to_parquet(
        SAL / "54_{}.parquet".format(sufijo), index=False)
    print("{}: {:,} votos de {:,} empresas apartadas; grupos {:,}".format(
        sufijo, len(v), v["empresa_ruc"].nunique(), len(set(np.asarray(base.grupo).tolist()))))


def juntar():
    archivos = sorted(SAL.glob("54_*.parquet"))
    tabla = None
    for f in archivos:
        nom = f.stem[3:]
        d = pd.read_parquet(f).rename(columns={"pinball": "p_" + nom, "directa": "d_" + nom})
        tabla = d if tabla is None else tabla.merge(d, on=["empresa", "cargo"], how="inner")
    noms = [f.stem[3:] for f in archivos]
    out = ["54 · PINBALL DE LA BANDA, empresas apartadas (protocolo de D-025 / D-031)",
           "votos emparejados: {:,}; empresas: {:,}".format(len(tabla), tabla["empresa"].nunique())]
    rng = np.random.default_rng(11)
    p0 = tabla["p_v15"].to_numpy()
    for nom in noms:
        pn = tabla["p_" + nom].to_numpy()
        fila = "   {:<40} pinball medio {:.5f}   cobertura directa {:.2%}".format(
            nom, np.nanmean(pn), tabla["d_" + nom].mean())
        if nom != "v15":
            m_, lo, hi = ic(pn - p0, tabla["empresa"].to_numpy(), rng)
            fila += "   frente a v15 {:+.5f} [{:+.5f}, {:+.5f}] {}".format(
                m_, lo, hi, "EMPEORA" if lo > 0 else ("MEJORA" if hi < 0 else "no se distingue"))
        out.append(fila)
    (SAL / "54_pinball.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variante", choices=["v15", "v16", "clusters", "placebo", "juez", "juez_placebo",
                                           "juez_tabla", "juez_vecinos", "juez_vecinos_placebo",
                                           "nivel_v1", "nivel_v1_placebo", "nivel_v2", "nivel_v2_placebo"])
    ap.add_argument("--clusters")
    ap.add_argument("--juntar", action="store_true")
    ap.add_argument("--entorno", default="", help="marca del entorno (p. ej. venv)")
    a = ap.parse_args()
    ENTORNO = a.entorno
    juntar() if a.juntar else una_variante(a.variante, a.clusters)
