"""T-008: clustering semantico, UMAP + HDBSCAN sobre Qwen (Q-d) frente a Vertex, con el oro humano de pares.

    PYTHONPATH=.libs_tesis .venv/bin/python research/tesis/t08_clustering.py

Hiperparametros elegidos en `calibra`; la comparacion, en `prueba` (registro, T-008).
SALIDA: salidas/t08_clustering.txt, salidas/t08_etiquetas.parquet, salidas/t08_umap_*.npy
"""
import itertools
import pathlib
import sys
import time

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import oro_pares  # noqa: E402

RAIZ = AQUI.parents[1]
SAL = AQUI / "salidas"
SEMILLA = 20261013
VECINOS = (15, 50)
MCS = (2, 3, 5, 10)
REPLICAS = 2000


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def partir(p):
    rng = np.random.default_rng(SEMILLA)
    parte = np.empty(len(p), dtype=object)
    for y in (0, 1):
        i = np.flatnonzero(p["y"].to_numpy() == y)
        rng.shuffle(i)
        parte[i[: len(i) // 2]] = "calibra"
        parte[i[len(i) // 2:]] = "prueba"
    return parte


def aciertos(et, ia, ib, y):
    """1 si el par queda bien: los «si» juntos (sin ruido), los «no» separados."""
    juntos = (et[ia] == et[ib]) & (et[ia] >= 0)
    return np.where(y == 1, juntos, ~juntos).astype(float)


def exactitud_bal(ok, y):
    return 0.5 * (ok[y == 1].mean() + ok[y == 0].mean())


def reducir(X, nn, nombre):
    f = SAL / "t08_umap_{}_{}.npy".format(nombre, nn)
    if f.exists():
        return np.load(f)
    import umap
    log("UMAP", nombre, nn, X.shape)
    R = umap.UMAP(n_neighbors=nn, n_components=10, min_dist=0.0, metric="cosine",
                  random_state=SEMILLA, low_memory=True).fit_transform(X).astype(np.float32)
    np.save(f, R)
    log("UMAP listo", nombre, nn)
    return R


def agrupar(R, mcs, ms, metodo):
    import hdbscan
    return hdbscan.HDBSCAN(min_cluster_size=mcs, min_samples=ms, cluster_selection_method=metodo,
                           core_dist_n_jobs=32).fit_predict(R)


def dispersion(et, m, w):
    """Desviacion tipica ponderada de la media log de cada titulo alrededor de la media de su cluster (sin ruido)."""
    d = pd.DataFrame({"g": et, "m": m, "w": w})
    d = d[(d["g"] >= 0) & np.isfinite(d["m"]) & (d["w"] > 0)]
    mu = (d["m"] * d["w"]).groupby(d["g"]).sum() / d["w"].groupby(d["g"]).sum()
    r = d["m"] - d["g"].map(mu)
    return float(np.sqrt((d["w"] * r ** 2).sum() / d["w"].sum()))


def resumen(et):
    v = et[et >= 0]
    tam = np.bincount(v) if len(v) else np.array([0])
    return "ruido {:.1%}  clusters {:,}  mayor {:,}".format((et < 0).mean(), len(tam), int(tam.max()))


def main():
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    celdas = [str(c) for c in b["celdas"]]
    idx = {c: i for i, c in enumerate(celdas)}
    m = np.asarray(b["m"], dtype=float)
    w = np.asarray(b["emp"], dtype=float)
    p = oro_pares.pares(idx)
    p["parte"] = partir(p)
    ia = p["a"].map(idx).to_numpy()
    ib = p["b"].map(idx).to_numpy()
    y = p["y"].to_numpy()
    cal, pru = (p["parte"] == "calibra").to_numpy(), (p["parte"] == "prueba").to_numpy()
    out = ["T-008 · UMAP + HDBSCAN, oro humano de pares",
           "pares: {:,} (calibra {:,}, prueba {:,}); si {:,}, no {:,}".format(
               len(p), cal.sum(), pru.sum(), int(y.sum()), int((y == 0).sum()))]
    emb = {"qwen": np.load(SAL / "t01_emb_qwen_desc.npy").astype(np.float32),
           "vertex": np.asarray(b["Z"], dtype=np.float32)}
    elegidos, etiquetas = {}, {}
    for nombre, X in emb.items():
        X = X / np.linalg.norm(X, axis=1, keepdims=True)
        mejor = None
        for nn in VECINOS:
            R = reducir(X, nn, nombre)
            for mcs, ms_igual, metodo in itertools.product(MCS, (False, True), ("eom", "leaf")):
                ms = mcs if ms_igual else 1
                et = agrupar(R, mcs, ms, metodo)
                ok = aciertos(et, ia, ib, y)
                ba = exactitud_bal(ok[cal], y[cal])
                fila = "  {:<6} nn={:<2} mcs={:<2} ms={:<2} {:<4}  calibra {:.4f}  (si {:.3f}, no {:.3f})  {}".format(
                    nombre, nn, mcs, ms, metodo, ba, ok[cal & (y == 1)].mean(), ok[cal & (y == 0)].mean(), resumen(et))
                log(fila)
                out.append(fila)
                if mejor is None or ba > mejor[0]:
                    mejor = (ba, (nn, mcs, ms, metodo), et)
        elegidos[nombre], etiquetas[nombre] = mejor[1], mejor[2]
        out.append("ELEGIDO {}: nn={} mcs={} ms={} {} (calibra {:.4f})".format(nombre, *mejor[1], mejor[0]))
    etiquetas["producto"] = np.asarray(b["grupo"], dtype=np.int64)
    out.append("")
    out.append("PRUEBA ({:,} pares: si {:,}, no {:,})".format(pru.sum(), int(y[pru].sum()), int((y[pru] == 0).sum())))
    oks = {}
    for nombre, et in etiquetas.items():
        ok = aciertos(et, ia, ib, y)
        oks[nombre] = ok
        out.append("  {:<9} exactitud balanceada {:.4f}  (si juntos {:.3f}, no separados {:.3f})  {}  "
                   "dispersion del sueldo {:.3f}".format(
                       nombre, exactitud_bal(ok[pru], y[pru]), ok[pru & (y == 1)].mean(),
                       ok[pru & (y == 0)].mean(), resumen(et), dispersion(et, m, w)))
    # IC por bootstrap de pares (estratificado por si/no), Qwen - Vertex
    rng = np.random.default_rng(SEMILLA + 1)
    i1, i0 = np.flatnonzero(pru & (y == 1)), np.flatnonzero(pru & (y == 0))
    dif = oks["qwen"] - oks["vertex"]
    bs = []
    for _ in range(REPLICAS):
        a1, a0 = rng.choice(i1, len(i1)), rng.choice(i0, len(i0))
        bs.append(0.5 * (dif[a1].mean() + dif[a0].mean()))
    d0 = 0.5 * (dif[i1].mean() + dif[i0].mean())
    lo, hi = np.percentile(bs, [2.5, 97.5])
    out.append("")
    out.append("Qwen - Vertex (prueba): {:+.4f} [{:+.4f}, {:+.4f}]  -> {}".format(
        d0, lo, hi, "QWEN AGRUPA MEJOR" if lo > 0 else ("VERTEX AGRUPA MEJOR" if hi < 0 else "no se distingue")))
    (SAL / "t08_clustering.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    pd.DataFrame({"titulo": celdas, **{"cluster_" + k: v for k, v in etiquetas.items()}}).to_parquet(
        SAL / "t08_etiquetas.parquet", index=False)
    log("\n".join(out[-8:]))


if __name__ == "__main__":
    main()
