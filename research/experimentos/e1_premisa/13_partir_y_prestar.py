"""PARTIR Y PRESTAR: la sinergia, con contraste pareado.

Las dos piezas medidas por separado no funcionan solas:

  PARTIR por sector arregla las etiquetas anchas —dentro de `OBRERO` el sector explica
  omega2 = 0,43 (D-014)— pero deja las celdas mas delgadas, y `04` ya midio que el 44,6%
  del error de las celdas delgadas es error de ESTIMACION.

  PRESTAR FUERZA arregla las celdas delgadas (`12`: -1,63% a cobertura constante) pero no
  toca la heterogeneidad de las anchas: el vecindario de `OBRERO` mezcla obreros de todos
  los sectores.

La tesis es que se habilitan mutuamente: **se puede partir fino PRECISAMENTE porque se
presta fuerza.** Partir solo mata la estimabilidad; prestar solo deja la heterogeneidad.

Cuatro metodos, todos con el mismo estimador y el mismo split:

  1. CARGO crudo                     el baseline de la industria
  2. CARGO + vecindario              solo prestar   (`12`)
  3. CARGO x sector                  solo partir
  4. CARGO x sector + vecindario     las dos

Y un CONTRASTE PAREADO por bootstrap de dos etapas, porque el -1,63% de `12` esta medido
sobre un solo split y hasta que no tenga intervalo no es un numero, es un indicio.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.evaluacion.referencia import (SUELO_EMPRESAS, _cuantil_por_grupo,
                                                componentes_varianza)

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
MUESTRA_EMPRESAS = 1200
K_VECINOS = 50          # el optimo de `12`; NO se reelige aqui
K_CANDIDATOS = 120      # se precalculan de mas para no rehacer la matriz por replica
N_REPLICAS = 150
SEP = chr(31)           # separador de celda: hay cargos que contienen '|'


def preparar(tr, etiquetas, X, pos, clave):
    """Estructura fija de un metodo: celdas, su texto, y sus vecinos por similitud.

    Los vecinos se precalculan UNA vez: dependen solo del texto, que no cambia al
    remuestrear empresas. Por replica solo se recalculan `m` y `W`. Sin esto, cada
    replica rehace una matriz de 12k x 12k y el bootstrap no cabe en el dia.
    """
    celdas = pd.Index(sorted(set(clave(tr))))
    idx_celda = {c: i for i, c in enumerate(celdas)}
    # el texto de una celda es el de su cargo, aunque la celda lleve sector
    cargo_de = [c.split(SEP)[0] for c in celdas]
    Z = X[[pos[c] for c in cargo_de]]
    Z = Z / np.linalg.norm(Z, axis=1, keepdims=True)

    K = min(K_CANDIDATOS, len(celdas) - 1)
    vec = np.zeros((len(celdas), K), dtype=np.int32)
    sim = np.zeros((len(celdas), K), dtype=np.float32)
    paso = 512
    for i0 in range(0, len(celdas), paso):
        S = Z[i0:i0 + paso] @ Z.T
        for j in range(S.shape[0]):
            fila = S[j]
            fila[i0 + j] = -np.inf
            cand = np.argpartition(-fila, K)[:K]
            orden = cand[np.argsort(-fila[cand])]
            vec[i0 + j] = orden
            sim[i0 + j] = np.clip(fila[orden], 0.0, None)
    return {"celdas": celdas, "idx": idx_celda, "vec": vec, "sim": sim}


def estimar(est, tr_b, clave, tau2, sigma2, prestar):
    """(referencia por celda, empresas por celda) sobre una muestra de train.

    El cuantil ponderado de TODAS las celdas se calcula de una vez con
    `_cuantil_por_grupo`, la version vectorizada que ya vive en `metricas`. Un bucle
    de Python por celda son 15.495 iteraciones x 4 metodos x 150 replicas = 9,3
    millones, y el bootstrap pasa de minutos a horas. Ese error ya se habia cometido
    y corregido una vez en el modulo; aqui se repitio al escribir el experimento.
    """
    d = pd.DataFrame({"c": clave(tr_b), "e": tr_b["empresa_ruc"].to_numpy(),
                      "y": pd.to_numeric(tr_b["y"], errors="coerce").to_numpy(float)})
    d = d.dropna(subset=["y"])
    v = d.groupby(["c", "e"], sort=False)["y"].agg(voto="median", n="size").reset_index()
    v["w"] = 1.0 / (tau2 + sigma2 / v["n"].to_numpy(float))

    n = len(est["celdas"])
    v["cod"] = v["c"].map(est["idx"])
    v = v.dropna(subset=["cod"]).sort_values(["cod", "voto"], kind="mergesort")
    cod = v["cod"].to_numpy(int)
    m = np.full(n, np.nan)
    if len(cod):
        vistas = np.unique(cod)
        q = _cuantil_por_grupo(np.searchsorted(vistas, cod),
                               v["voto"].to_numpy(float), v["w"].to_numpy(float),
                               len(vistas))
        m[vistas] = q
    W = np.bincount(cod, weights=v["w"].to_numpy(float), minlength=n)
    emp = np.bincount(cod, minlength=n).astype(float)
    if not prestar:
        return m, emp

    vec, sim = est["vec"][:, :K_VECINOS], est["sim"][:, :K_VECINOS]
    mv, Wv = m[vec], W[vec]
    peso = sim * np.where(np.isfinite(mv), Wv, 0.0)
    tot = peso.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        syn = np.where(tot > 0, np.nansum(peso * np.nan_to_num(mv), axis=1) / tot, np.nan)
        emp_v = np.where(tot > 0,
                         np.where(np.isfinite(mv), emp[vec], 0.0).sum(axis=1), 0.0)
        vc = np.where(W > 0, 1.0 / W, np.inf)
    hay = np.isfinite(m) & np.isfinite(syn)
    su2 = max(1e-9, float(np.var((m - syn)[hay])) - float(np.mean(vc[hay])))
    gamma = np.where(np.isfinite(syn), su2 / (su2 + vc), 1.0)
    fin = np.where(np.isfinite(m),
                   np.where(np.isfinite(syn), gamma * m + (1 - gamma) * syn, m),
                   syn)
    return fin, np.where(np.isfinite(m), emp, emp_v)


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(mk, splits.empresas_test(mk))

    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    if len(emp0) > MUESTRA_EMPRESAS:
        emp0 = rng.choice(emp0, MUESTRA_EMPRESAS, replace=False)
    d = train[train.empresa_ruc.isin(emp0)].reset_index(drop=True)
    val = set(rng.choice(emp0, max(1, len(emp0) // 4), replace=False))
    tr = d[~d.empresa_ruc.isin(val)].reset_index(drop=True)
    ts = d[d.empresa_ruc.isin(val)].reset_index(drop=True)
    print(f"train {len(tr):,} filas / {tr.empresa_ruc.nunique()} empresas")
    print(f"eval  {len(ts):,} filas / {ts.empresa_ruc.nunique()} empresas")

    tau2, sigma2 = componentes_varianza(tr, "cargo_norm")
    cache = embeddings.CacheArchivo(s.gcs_cache_embeddings or CACHE)
    cliente = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                        s.vertex_location)
    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    print(f"embebiendo {len(etiquetas):,} etiquetas...")
    X = embeddings.embeber(etiquetas, cliente, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    pos = {e: i for i, e in enumerate(etiquetas)}

    solo_cargo = lambda df: df["cargo_norm"].astype(str).to_numpy()
    # `ciiu_n1` tiene nulos y la concatenacion los propaga a NaN, que luego no se
    # puede ordenar contra texto. Un sector desconocido es una categoria mas.
    con_sector = lambda df: (df["cargo_norm"].astype(str) + SEP
                             + df["ciiu_n1"].fillna("SIN_SECTOR").astype(str)).to_numpy()

    METODOS = [("CARGO crudo", solo_cargo, False),
               ("CARGO + vecindario", solo_cargo, True),
               ("CARGO x sector", con_sector, False),
               ("CARGO x sector + vecindario", con_sector, True)]

    print("preparando vecindarios (una sola vez)...")
    ests = {}
    for nombre, clave, prestar in METODOS:
        k = "sector" if clave is con_sector else "cargo"
        if k not in ests:
            todo = pd.concat([tr, ts], ignore_index=True)
            ests[k] = preparar(todo, etiquetas, X, pos, clave)
            print(f"  {k}: {len(ests[k]['celdas']):,} celdas")

    y_ts = pd.to_numeric(ts["y"], errors="coerce").to_numpy(float)

    def referencias(tr_b, ts_b, clave, prestar, est):
        fin, emp = estimar(est, tr_b, clave, tau2, sigma2, prestar)
        cod = np.array([est["idx"].get(c, -1) for c in clave(ts_b)])
        ref = np.where(cod >= 0, fin[np.clip(cod, 0, len(fin) - 1)], np.nan)
        ne = np.where(cod >= 0, emp[np.clip(cod, 0, len(emp) - 1)], 0.0)
        return np.where(ne >= SUELO_EMPRESAS, ref, np.nan)

    print("\n" + "=" * 74)
    print("PUNTO ESTIMADO")
    print("=" * 74)
    print(f"{'metodo':<30} {'cobertura':>10} {'MAE':>10}")
    print("-" * 74)
    base_ref = {}
    for nombre, clave, prestar in METODOS:
        est = ests["sector" if clave is con_sector else "cargo"]
        r = referencias(tr, ts, clave, prestar, est)
        base_ref[nombre] = r
        ok = np.isfinite(r) & np.isfinite(y_ts)
        print(f"{nombre:<30} {ok.mean():>10.1%} "
              f"{np.abs(y_ts[ok] - r[ok]).mean():>10.4f}")

    print("\n" + "=" * 74)
    print(f"CONTRASTE PAREADO ({N_REPLICAS} replicas, dos etapas, numeros comunes)")
    print("=" * 74)
    emp_tr = np.array(sorted(tr.empresa_ruc.unique()))
    emp_ts = np.array(sorted(ts.empresa_ruc.unique()))
    p_tr = {e: np.flatnonzero((tr.empresa_ruc == e).to_numpy()) for e in emp_tr}
    p_ts = {e: np.flatnonzero((ts.empresa_ruc == e).to_numpy()) for e in emp_ts}
    rb = np.random.default_rng(7)
    guardadas = []
    for _ in range(N_REPLICAS):
        i_tr = np.concatenate([p_tr[e] for e in rb.choice(emp_tr, len(emp_tr))])
        i_ts = np.concatenate([p_ts[e] for e in rb.choice(emp_ts, len(emp_ts))])
        trb, tsb = tr.iloc[i_tr], ts.iloc[i_ts]
        yb = pd.to_numeric(tsb["y"], errors="coerce").to_numpy(float)
        rr = {}
        for nombre, clave, prestar in METODOS:
            est = ests["sector" if clave is con_sector else "cargo"]
            rr[nombre] = referencias(trb, tsb, clave, prestar, est)
        # Se guarda la referencia CRUDA de cada metodo, no un MAE ya agregado: cada
        # contraste necesita SU PROPIA interseccion de dos. Agregar sobre la
        # interseccion de los cuatro comparaba sobre el 23% mejor poblado —el que
        # cubre `CARGO x sector`— que es justo donde prestar fuerza no hace falta.
        # El test no tenia potencia para detectar el efecto que busca.
        guardadas.append((yb, rr))

    def par(a, b):
        """Diferencia pareada de a-b sobre SU PROPIA interseccion, replica a replica."""
        da = []
        for yb, rr in guardadas:
            ok = np.isfinite(yb) & np.isfinite(rr[a]) & np.isfinite(rr[b])
            if ok.sum() < 50:
                continue
            da.append(float(np.abs(yb[ok] - rr[a][ok]).mean())
                      - float(np.abs(yb[ok] - rr[b][ok]).mean()))
        cob = float((np.isfinite(guardadas[0][1][a])
                     & np.isfinite(guardadas[0][1][b])).mean())
        return np.array(da), cob

    print(f"  replicas: {len(guardadas)}   cada contraste sobre SU interseccion")
    print()
    print(f"  {'contraste':<46} {'dif':>9} {'IC 95%':>20}")
    print("  " + "-" * 70)
    for a, b in [("CARGO + vecindario", "CARGO crudo"),
                 ("CARGO x sector", "CARGO crudo"),
                 ("CARGO x sector + vecindario", "CARGO crudo"),
                 ("CARGO x sector + vecindario", "CARGO + vecindario")]:
        dd, cob = par(a, b)
        if not len(dd):
            print(f"  {a} - {b}: sin interseccion suficiente")
            continue
        lo, hi = np.quantile(dd, [.025, .975])
        signo = "SI" if hi < 0 else ("no" if lo < 0 < hi else "PEOR")
        print(f"  {a + chr(32) + chr(45) + chr(32) + b:<44} {dd.mean():>+8.4f} "
              f"[{lo:>+7.4f}, {hi:>+7.4f}] {signo:<4} n={cob:.0%}")

    print()
    print("SI = el IC de la diferencia no cruza el cero y es negativo: mejora real.")
    print("El contraste es PAREADO sobre la misma replica, asi que el efecto empresa")
    print("—que domina el error y es identico para los cuatro— se cancela.")


if __name__ == "__main__":
    main()
