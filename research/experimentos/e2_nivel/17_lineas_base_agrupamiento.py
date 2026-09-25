"""Primera fila de la tabla factorial de D-036: el coseno preentrenado, sin entrenar nada.

Antes de ajustar un solo peso hay que saber contra que compite el juez aprendido. Esto
mide lo que ya se puede medir con el espacio de hoy y con el oro que hay.

QUE SE MIDE (todo en `calibra`; `prueba` no se abre, ver D-035)
==============================================================================

1. RECALL@K POR RANGO. Para cada par `si` del oro, en que puesto sale uno entre los
   vecinos del otro. Dice cuantos pares verdaderos le llegarian al cross si la capa A
   pasara solo los k primeros.

   LO QUE NO SE PUEDE MEDIR, y hay que decirlo: el Recall por debajo de 0,90 de coseno.
   Los 400 de `13e` salieron todos de 0,90-1,01 por construccion, asi que un par `si` a
   0,85 no existe en el oro. Este numero es optimista en ese sentido: cuenta solo lo que
   el oro puede ver.

2. TRES AGRUPAMIENTOS SOBRE EL COSENO, con los grupos de hoy (`grupo` de `base_v15`)
   como atomos. Cada par del oro une dos grupos DISTINTOS de hoy (13e exige
   `g != g`), asi que la pregunta es "deberian fundirse estos dos grupos":

   - componentes conexas sobre el grafo de coseno >= t (enlace simple). Se espera que
     percole: es lo que midio `06` a nivel de celda.
   - pivote de correlation clustering (KwikCluster, Ailon, Charikar y Newman 2008)
     sobre el mismo grafo. Aproximacion 3 del optimo con aristas +/-.
   - Leiden (Traag, Waltman y van Eck 2019) con modularidad, sobre el mismo grafo con
     el coseno como peso.
   - HDBSCAN (sklearn) sobre PCA a 32 dimensiones y sobre UMAP a 10 (coseno, 15
     vecinos): la receta estandar de agrupar textos con embeddings (BERTopic). PCA se
     midio primero, cuando UMAP no estaba instalado; se deja como comparacion.

   El producto de hoy, por construccion, dice `no` a los 400: recall 0.

   LOS UMBRALES SE BARREN, NO SE ELIGEN. Elegir el mejor t en `calibra` y reportarlo
   seria optimista; la curva entera es la linea base.

3. ESTABILIDAD. ARI entre el agrupamiento completo y el de un 80% de los grupos, en
   tres remuestreos, sobre los nodos comunes.

4. EL TAMANO DEL PROBLEMA para el cross: cuantos pasos harian falta con k vecinos.

NO SE IMPRIMEN TITULOS. La salida es solo agregados, para poder versionarla (LOPDP).

SALIDA: salidas/17_lineas_base.txt
"""
import pathlib
import sys
import time

import igraph as ig
import leidenalg as la
import numpy as np
import pandas as pd
import umap
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, cohen_kappa_score, roc_auc_score

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = pathlib.Path(__file__).resolve().parents[3]
BASE = RAIZ / "demo" / "base_v15.npz"
SAL = pathlib.Path(__file__).resolve().parent / "salidas"
META = SAL / "13e_pares_400.csv"
JUICIOS = SAL / "13e_para_juzgar.csv"
SEM = 20260925
PASO = 512
KMAX = 50
KS = (1, 5, 10, 20, 25, 50)
UMBRALES = (0.90, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97)
SEG_POR_PASO = 0.09          # cross en CPU, fp32 (D-034, correccion c885afb)


def representantes(cel, emp, g):
    """Uno por grupo, el de mas empresas y grafia corta. Mismo criterio que `13e`."""
    rep = {}
    for i in range(len(cel)):
        gi = int(g[i])
        if gi not in rep or (-emp[i], len(cel[i])) < (-emp[rep[gi]], len(cel[rep[gi]])):
            rep[gi] = i
    gids = np.array(sorted(rep))
    return gids, np.array([rep[x] for x in gids])


def vecinos(Zr):
    """Top-KMAX vecinos por coseno de cada representante, sin el mismo."""
    n = len(Zr)
    idx = np.empty((n, KMAX), dtype=np.int32)
    sim = np.empty((n, KMAX), dtype=np.float32)
    for a in range(0, n, PASO):
        S = Zr[a:a + PASO] @ Zr.T
        S[np.arange(len(S)), np.arange(a, a + len(S))] = -np.inf
        top = np.argpartition(-S, KMAX, axis=1)[:, :KMAX]
        st = np.take_along_axis(S, top, axis=1)
        orden = np.argsort(-st, axis=1)
        idx[a:a + PASO] = np.take_along_axis(top, orden, axis=1)
        sim[a:a + PASO] = np.take_along_axis(st, orden, axis=1)
    return idx, sim


def aristas(idx, sim, t, vivos=None, con_peso=False):
    n = len(idx)
    fil = np.repeat(np.arange(n), idx.shape[1])
    col, s = idx.ravel(), sim.ravel()
    m = s >= t
    fil, col, s = fil[m], col[m], s[m]
    if vivos is not None:
        m = vivos[fil] & vivos[col]
        fil, col, s = fil[m], col[m], s[m]
    return (fil, col, s) if con_peso else (fil, col)


def leiden(n, fil, col, s, seed=SEM):
    """Leiden con modularidad sobre el grafo no dirigido, peso = coseno."""
    a, b = np.minimum(fil, col), np.maximum(fil, col)
    par = pd.DataFrame({"a": a, "b": b, "s": s}).groupby(["a", "b"], as_index=False)["s"].max()
    G = ig.Graph(n=n, edges=list(zip(par["a"], par["b"])))
    G.es["weight"] = par["s"].tolist()
    part = la.find_partition(G, la.ModularityVertexPartition, weights="weight", seed=seed)
    return np.array(part.membership, dtype=np.int64)


def hdbscan_etiquetas(X, mcs):
    lab = HDBSCAN(min_cluster_size=mcs, n_jobs=-1, copy=True).fit(X).labels_.astype(np.int64)
    ruido = lab < 0
    lab[ruido] = lab.max() + 1 + np.arange(ruido.sum())
    return lab, float(ruido.mean())


def reducir_umap(Zr):
    return umap.UMAP(n_components=10, n_neighbors=15, min_dist=0.0, metric="cosine",
                     random_state=SEM).fit_transform(Zr)


def componentes(n, fil, col):
    A = coo_matrix((np.ones(len(fil), dtype=np.int8), (fil, col)), shape=(n, n))
    return connected_components(A, directed=False)[1]


def pivote(n, fil, col, rng):
    """KwikCluster: pivote al azar, se lleva a sus vecinos positivos no asignados."""
    orden_fil = np.argsort(fil, kind="stable")
    fil, col = fil[orden_fil], col[orden_fil]
    # grafo no dirigido: cada arista en los dos sentidos
    f2 = np.concatenate([fil, col])
    c2 = np.concatenate([col, fil])
    o = np.argsort(f2, kind="stable")
    f2, c2 = f2[o], c2[o]
    ini = np.searchsorted(f2, np.arange(n))
    fin = np.searchsorted(f2, np.arange(n), side="right")
    lab = np.full(n, -1, dtype=np.int64)
    k = 0
    for p in rng.permutation(n):
        if lab[p] >= 0:
            continue
        lab[p] = k
        vec = c2[ini[p]:fin[p]]
        vec = vec[lab[vec] < 0]
        lab[vec] = k
        k += 1
    return lab


def evaluar(lab, pos_a, pos_b, y):
    pred = (lab[pos_a] == lab[pos_b]).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if tp else 0.0
    kap = cohen_kappa_score(y, pred) if pred.min() != pred.max() else 0.0
    return prec, rec, f1, kap


def tamanos(lab):
    _, c = np.unique(lab, return_counts=True)
    return int(c.max()), int((c > 1).sum())


def estabilidad(fn_lab, n, rng, veces=3):
    """ARI entre el agrupamiento completo y el de un 80%, sobre los nodos comunes."""
    completo = fn_lab(np.ones(n, dtype=bool))
    aris = []
    for _ in range(veces):
        vivos = rng.random(n) < 0.8
        sub = fn_lab(vivos)
        aris.append(adjusted_rand_score(completo[vivos], sub[vivos]))
    return float(np.mean(aris)), float(np.min(aris))


def main():
    t0 = time.time()
    d = np.load(BASE, allow_pickle=True)
    cel = np.array([str(c) for c in d["celdas"]])
    Z = d["Z"].astype(np.float32)
    Z /= np.linalg.norm(Z, axis=1, keepdims=True)
    g = d["grupo"].astype(np.int64)
    emp = d["emp"]

    gids, reps = representantes(cel, emp, g)
    pos = {int(x): i for i, x in enumerate(gids)}
    n = len(reps)
    Zr = Z[reps]

    print("=" * 78)
    print("17 · LINEAS BASE DE AGRUPAMIENTO SOBRE EL COSENO (fila 1 de D-036)")
    print("=" * 78)
    print("\nTAMANO DEL PROBLEMA")
    print("  titulos (celdas)          {:>8,}".format(len(cel)))
    print("  grupos de hoy (atomos)    {:>8,}".format(n))
    for k in (10, 20):
        pasos = n * k            # pares dirigidos; cada uno en las 2 direcciones = 2 pasos,
        pares = pasos / 2        # pero (i,j) y (j,i) se repiten: ~n*k/2 pares unicos
        horas = pares * 2 * SEG_POR_PASO / 3600
        print("  k={:<3} ~{:>9,.0f} pares unicos x 2 direcciones x {:.2f} s = {:>5.1f} h CPU"
              .format(k, pares, SEG_POR_PASO, horas))

    # --- el oro, solo calibra -------------------------------------------------
    meta = pd.read_csv(META, sep=";", encoding="utf-8-sig")
    jui = pd.read_csv(JUICIOS, sep=";", encoding="utf-8-sig", dtype=str,
                      keep_default_na=False)[["n", "mismo"]]
    jui["n"] = jui["n"].astype(int)
    oro = meta.merge(jui, on="n")
    oro = oro[oro["particion"] == "calibra"].copy()
    oro["mismo"] = oro["mismo"].str.strip().str.lower()
    dudas = int((~oro["mismo"].isin(["si", "no"])).sum())
    oro = oro[oro["mismo"].isin(["si", "no"])]
    oro = oro[oro["g_comun"].isin(pos) & oro["g_raro"].isin(pos)]
    y = (oro["mismo"] == "si").astype(int).to_numpy()
    pa = oro["g_comun"].map(pos).to_numpy()
    pb = oro["g_raro"].map(pos).to_numpy()
    print("\nORO: calibra, {} pares ({} si, {} no; {} sin si/no fuera). prueba NO se abre."
          .format(len(oro), y.sum(), len(y) - y.sum(), dudas))

    sim_oro = np.einsum("ij,ij->i", Zr[pa], Zr[pb])
    print("  AUC del coseno sobre estos pares: {:.3f}".format(roc_auc_score(y, sim_oro)))

    # --- vecinos ----------------------------------------------------------------
    print("\n  calculando top-{} vecinos de {:,} grupos...".format(KMAX, n), flush=True)
    idx, sim = vecinos(Zr)
    print("  listo en {:.0f} s".format(time.time() - t0), flush=True)

    # --- 1. Recall@K --------------------------------------------------------------
    rango = []
    for a, b in zip(pa, pb):
        ra = np.flatnonzero(idx[a] == b)
        rb = np.flatnonzero(idx[b] == a)
        r = min([x + 1 for x in list(ra) + list(rb)], default=KMAX + 1)
        rango.append(r)
    rango = np.array(rango)
    print("\n1. RECALL@K de los pares `si` (rango del mejor de los dos sentidos)")
    print("   ATENCION: solo pares con coseno >= 0,90; lo de abajo el oro no lo ve.")
    for est in ["todos", "bajo", "banda", "alto"]:
        m = (y == 1) if est == "todos" else ((y == 1) & (oro["estrato"].to_numpy() == est))
        if m.sum() == 0:
            continue
        cols = "  ".join("@{}={:.2f}".format(k, (rango[m] <= k).mean()) for k in KS)
        print("   {:<6} n={:>3}  {}".format(est, m.sum(), cols))

    # --- 2. agrupamientos -------------------------------------------------------------
    rng = np.random.default_rng(SEM)
    print("\n2. AGRUPAMIENTO: precision / recall / F1 / kappa del `si`, sobre calibra")
    print("   producto de hoy: recall 0 por construccion (los 400 cruzan grupos)")
    print("\n   {:<22} {:>5} {:>6} {:>6} {:>6} {:>6} {:>8} {:>9}".format(
        "metodo", "t", "prec", "rec", "F1", "kappa", "mayor", "grupos>1"))
    for t in UMBRALES:
        fil, col = aristas(idx, sim, t)
        lab_cc = componentes(n, fil, col)
        lab_pv = pivote(n, fil, col, rng)
        for nom, lab in (("componentes conexas", lab_cc), ("pivote (corr. clust.)", lab_pv)):
            p, r, f, k = evaluar(lab, pa, pb, y)
            mx, ng = tamanos(lab)
            print("   {:<22} {:>5.2f} {:>6.3f} {:>6.3f} {:>6.3f} {:>6.3f} {:>8,} {:>9,}".format(
                nom, t, p, r, f, k, mx, ng), flush=True)

    print("\n   HDBSCAN sobre PCA-32 (ruido = grupo de uno)", flush=True)
    X = PCA(n_components=32, random_state=SEM).fit_transform(Zr)
    lab_hd = {}
    for mcs in (2, 5):
        t1 = time.time()
        h = HDBSCAN(min_cluster_size=mcs, n_jobs=-1, copy=True).fit(X)
        lab = h.labels_.astype(np.int64).copy()
        ruido = lab < 0
        lab[ruido] = lab.max() + 1 + np.arange(ruido.sum())
        lab_hd[mcs] = lab
        p, r, f, k = evaluar(lab, pa, pb, y)
        mx, ng = tamanos(lab)
        print("   {:<22} {:>5} {:>6.3f} {:>6.3f} {:>6.3f} {:>6.3f} {:>8,} {:>9,}   "
              "ruido {:.0%}, {:.0f} s".format("HDBSCAN mcs={}".format(mcs), "-", p, r, f, k,
                                            mx, ng, ruido.mean(), time.time() - t1),
              flush=True)

    # --- 3. estabilidad -----------------------------------------------------------
    print("\n3. ESTABILIDAD: ARI completo vs 80% de los grupos (media, minimo de 3)")
    for t in (0.93, 0.95):
        def f_cc(v, t=t):
            fl, cl = aristas(idx, sim, t, v)
            return componentes(n, fl, cl)

        def f_pv(v, t=t):
            fl, cl = aristas(idx, sim, t, v)
            return pivote(n, fl, cl, np.random.default_rng(SEM))
        print("   componentes conexas  t={:.2f}   ARI {:.3f} (min {:.3f})".format(
            t, *estabilidad(f_cc, n, rng)))
        print("   pivote               t={:.2f}   ARI {:.3f} (min {:.3f})".format(
            t, *estabilidad(f_pv, n, rng)), flush=True)

    def f_hd(v):
        lab = np.arange(n, dtype=np.int64) + n       # los ausentes, cada uno solo
        sub = HDBSCAN(min_cluster_size=2, n_jobs=-1, copy=True).fit(X[v]).labels_.astype(np.int64)
        ruido = sub < 0
        sub[ruido] = sub.max() + 1 + np.arange(ruido.sum())
        lab[v] = sub
        return lab if not v.all() else lab_hd[2]
    print("   HDBSCAN PCA mcs=2            ARI {:.3f} (min {:.3f})".format(
        *estabilidad(f_hd, n, rng)), flush=True)

    # --- 4. Leiden y UMAP (anadidos despues; no alteran la semilla de lo de arriba) ----
    print("\n4. LEIDEN (modularidad, peso = coseno) sobre el mismo grafo")
    print("\n   {:<22} {:>5} {:>6} {:>6} {:>6} {:>6} {:>8} {:>9}".format(
        "metodo", "t", "prec", "rec", "F1", "kappa", "mayor", "grupos>1"))
    for t in UMBRALES:
        lab = leiden(n, *aristas(idx, sim, t, con_peso=True))
        p, r, f, k = evaluar(lab, pa, pb, y)
        mx, ng = tamanos(lab)
        print("   {:<22} {:>5.2f} {:>6.3f} {:>6.3f} {:>6.3f} {:>6.3f} {:>8,} {:>9,}".format(
            "Leiden", t, p, r, f, k, mx, ng), flush=True)

    print("\n   HDBSCAN sobre UMAP-10 (coseno, 15 vecinos; ruido = grupo de uno)", flush=True)
    t1 = time.time()
    U = reducir_umap(Zr)
    print("   UMAP en {:.0f} s".format(time.time() - t1), flush=True)
    lab_um = {}
    for mcs in (2, 5):
        t1 = time.time()
        lab, ruido = hdbscan_etiquetas(U, mcs)
        lab_um[mcs] = lab
        p, r, f, k = evaluar(lab, pa, pb, y)
        mx, ng = tamanos(lab)
        print("   {:<22} {:>5} {:>6.3f} {:>6.3f} {:>6.3f} {:>6.3f} {:>8,} {:>9,}   "
              "ruido {:.0%}, {:.0f} s".format("HDBSCAN UMAP mcs={}".format(mcs), "-", p, r, f,
                                            k, mx, ng, ruido, time.time() - t1), flush=True)

    rng2 = np.random.default_rng(SEM + 1)
    print("\n   estabilidad (ARI completo vs 80%, media y minimo de 3)")
    for t in (0.93, 0.95):
        def f_ld(v, t=t):
            return leiden(n, *aristas(idx, sim, t, v, con_peso=True))
        print("   Leiden               t={:.2f}   ARI {:.3f} (min {:.3f})".format(
            t, *estabilidad(f_ld, n, rng2)), flush=True)

    def f_um(v):
        if v.all():
            return lab_um[2]
        lab = np.arange(n, dtype=np.int64) + n
        lab[v] = hdbscan_etiquetas(reducir_umap(Zr[v]), 2)[0]
        return lab
    print("   HDBSCAN UMAP mcs=2           ARI {:.3f} (min {:.3f})   (UMAP se reajusta)"
          .format(*estabilidad(f_um, n, rng2)), flush=True)

    print("\n  total {:.0f} s".format(time.time() - t0))


if __name__ == "__main__":
    main()
