"""Fusionar cuasi-duplicados: .estrecha el intervalo o solo muda la varianza de sitio?

`ANALISTA DE RIESGO CREDITICIO` compite en la base contra seis grafias del mismo puesto:

    ANALISTA DE RIESGO DE CREDITO      sim 0,971   paga 0,977
    ANALISTA RIESGO DE CREDITO         sim 0,968   paga 0,777
    ANALISTA DE CREDITO (RIESGOS)      sim 0,960   paga 0,338
    ANALISTA DE RIESGO DE CREDITO (E)  sim 0,947   paga 0,371

Cada una con 1-2 empresas, y al preguntarlas se paga un castigo por "distancia semantica"
—`lambda*(1-sim)`— entre textos que son la misma cosa.

LA HIPOTESIS Y SU TRAMPA. Fusionarlas daria una celda de diez empresas en vez de seis de
dos: dato directo en vez de analogia, y sin castigo de distancia. PERO esos seis pagan de
0,34 a 0,98 — el triple. Si se fusionan, esa dispersion no desaparece: **se muda** de
"castigo por distancia" a "varianza dentro de la celda". El intervalo podria quedarse
igual.

Y hay un antecedente en contra: el barrido de granularidad (`e1_premisa/11`) midio que
agrupar PIERDE precision. Pero aquello fusionaba a lo bruto —hasta 1.000 celdas— y aqui
solo se juntan cuasi-duplicados.

QUE SE MIDE. Contraste pareado A (sin fusionar) contra fusionar a varios umbrales de
similitud, sobre los titulos afectados. Y por separado, el efecto en COBERTURA DIRECTA:
cuanta gente pasa de "por analogia" a "datos propios".

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.evaluacion.referencia import (_cuantil_por_grupo, componentes_varianza)
from benchmarking.producto.base_referencia import VECINOS, _lambda_semantica, _vecinos
from benchmarking.producto.nivel import efecto_nivel, nivel_lexico

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
MUESTRA_EMPRESAS = 100000
N_REPLICAS = 150
MIN_EMPRESAS = 3
UMBRALES = (0.99, 0.97, 0.95)


def agrupar(celdas, Z, umbral, niveles):
    """Une celdas cuasi-identicas EN EL MISMO ESCALON. Devuelve etiqueta -> grupo.

    Se exige el mismo nivel lexico ademas de la similitud: `ASISTENTE DE CAJA` y
    `SUPERVISOR DE CAJA` pueden pasar de 0,95 y NO son el mismo puesto. Sin esa condicion
    la fusion desharia el eje que costo cuatro experimentos montar.

    Union-find sobre los pares que superan el umbral, sobre los vecinos ya calculados.
    """
    padre = list(range(len(celdas)))

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    vec, sim = _vecinos(Z, Z, 10, excluir_propio=True)
    for i in range(len(celdas)):
        for j, s in zip(vec[i], sim[i]):
            if s < umbral:
                break
            ni, nj = niveles[i], niveles[j]
            if np.isfinite(ni) and np.isfinite(nj) and ni != nj:
                continue
            ri, rj = raiz(i), raiz(int(j))
            if ri != rj:
                padre[ri] = rj
    return np.array([raiz(i) for i in range(len(celdas))])


def votos(tr_b, clave, tau2, sigma2, n_grupos):
    d = pd.DataFrame({"c": clave, "e": tr_b.empresa_ruc.to_numpy(),
                      "y": pd.to_numeric(tr_b["y"], errors="coerce").to_numpy(float)})
    d = d.dropna(subset=["y"])
    v = d.groupby(["c", "e"], sort=False)["y"].agg(voto="median", n="size").reset_index()
    v["w"] = 1.0 / (tau2 + sigma2 / v["n"].to_numpy(float))
    v = v.sort_values(["c", "voto"], kind="mergesort")
    cod = v["c"].to_numpy(int)
    m = np.full(n_grupos, np.nan)
    if len(cod):
        vis = np.unique(cod)
        m[vis] = _cuantil_por_grupo(np.searchsorted(vis, cod), v["voto"].to_numpy(float),
                                    v["w"].to_numpy(float), len(vis))
    W = np.bincount(cod, weights=v["w"].to_numpy(float), minlength=n_grupos)
    emp = np.bincount(cod, minlength=n_grupos).astype(float)
    return m, W, emp


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

    tau2, sigma2 = componentes_varianza(tr, "cargo_norm")
    celdas = sorted(set(tr.cargo_norm.astype(str)) | set(ts.cargo_norm.astype(str)))
    idx = {c: i for i, c in enumerate(celdas)}
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print(f"embebiendo {len(celdas):,} titulos...")
    Z = embeddings.embeber(celdas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    Z = Z / np.linalg.norm(Z, axis=1, keepdims=True)
    niveles = np.array([nivel_lexico(c) or np.nan for c in celdas], dtype=float)
    ef = efecto_nivel(tr)

    cod_tr = tr.cargo_norm.astype(str).map(idx).to_numpy()
    cod_ts = ts.cargo_norm.astype(str).map(idx).to_numpy()
    y = pd.to_numeric(ts["y"], errors="coerce").to_numpy(float)
    vecQ, simQ = _vecinos(Z, Z, VECINOS, excluir_propio=False)
    m0, W0, e0 = votos(tr, cod_tr, tau2, sigma2, len(celdas))
    lam = _lambda_semantica(m0, W0, *_vecinos(Z, Z, VECINOS, excluir_propio=True))
    print(f"lambda = {lam:.3f}")

    def referencia(grupo, m, W, emp):
        """Referencia por celda, con las celdas mapeadas a sus grupos."""
        g = grupo
        mg, Wg, eg = m[g], W[g], emp[g]        # cada celda hereda su grupo
        vg = g[vecQ]
        mv, Wv, ev = m[vg], W[vg], emp[vg]
        dist = lam * (1.0 - simQ)
        # dentro del mismo grupo la distancia semantica es cero: es el mismo puesto
        dist = np.where(vg == g[:, None], 0.0, dist)
        with np.errstate(invalid="ignore", divide="ignore"):
            var_j = np.where(Wv > 0, 1.0 / np.where(Wv > 0, Wv, 1.0), np.inf) + dist
            peso = np.where(np.isfinite(mv) & (Wv > 0), 1.0 / var_j, 0.0)
            tot = peso.sum(axis=1, keepdims=True)
            peso = np.where(tot > 0, peso / np.where(tot > 0, tot, 1.0), 0.0)
        aj = np.zeros_like(mv)
        if ef:
            efc = np.array([ef.get(int(k), np.nan) if np.isfinite(k) else np.nan
                            for k in niveles])
            a = efc[:, None] - efc[vg]
            aj = np.where(np.isfinite(a), a, 0.0)
        mu_an = (peso * (np.nan_to_num(mv) + aj)).sum(axis=1)
        directo = eg >= MIN_EMPRESAS
        mu = np.where(directo, mg, mu_an)
        n_emp = np.where(directo, eg, (np.where(peso > 0, ev, 0.0)).sum(axis=1))
        return np.where(n_emp >= MIN_EMPRESAS, mu, np.nan), directo

    print("\n" + "=" * 74)
    print("COBERTURA DIRECTA: cuanta gente pasa de analogia a datos propios")
    print("=" * 74)
    grupos = {"sin fusionar": np.arange(len(celdas))}
    for u in UMBRALES:
        grupos[f"fusion >{u}"] = agrupar(celdas, Z, u, niveles)
    for nombre, g in grupos.items():
        m, W, e = votos(tr, g[cod_tr], tau2, sigma2, len(celdas))
        _, directo = referencia(g, m, W, e)
        n_grupos = len(np.unique(g))
        print(f"  {nombre:<16} {n_grupos:>7,} celdas   "
              f"directo: {directo[cod_ts].mean():>6.1%} de la gente")

    print("\n" + "=" * 74)
    print(f"CONTRASTE PAREADO ({N_REPLICAS} replicas), solo sobre los titulos AFECTADOS")
    print("=" * 74)
    emp_tr = np.array(sorted(tr.empresa_ruc.unique()))
    emp_ts = np.array(sorted(ts.empresa_ruc.unique()))
    p_tr = {e: np.flatnonzero((tr.empresa_ruc == e).to_numpy()) for e in emp_tr}
    p_ts = {e: np.flatnonzero((ts.empresa_ruc == e).to_numpy()) for e in emp_ts}
    base_g = grupos["sin fusionar"]
    afectada = {n: (g[cod_ts] != base_g[cod_ts]) | np.isin(
        g[cod_ts], np.flatnonzero(np.bincount(g, minlength=len(celdas)) > 1))
        for n, g in grupos.items() if n != "sin fusionar"}
    rb = np.random.default_rng(13)
    difs = {n: [] for n in afectada}
    for _ in range(N_REPLICAS):
        i_tr = np.concatenate([p_tr[e] for e in rb.choice(emp_tr, len(emp_tr))])
        i_ts = np.concatenate([p_ts[e] for e in rb.choice(emp_ts, len(emp_ts))])
        trb = tr.iloc[i_tr]
        yb = y[i_ts]
        ref = {}
        for n, g in grupos.items():
            m, W, e = votos(trb, g[cod_tr[i_tr]], tau2, sigma2, len(celdas))
            ref[n], _ = referencia(g, m, W, e)
        for n in afectada:
            sel = afectada[n][i_ts]
            a = ref["sin fusionar"][cod_ts[i_ts]]
            b = ref[n][cod_ts[i_ts]]
            ok = sel & np.isfinite(yb) & np.isfinite(a) & np.isfinite(b)
            if ok.sum() < 50:
                continue
            difs[n].append(float(np.abs(yb[ok] - b[ok]).mean())
                           - float(np.abs(yb[ok] - a[ok]).mean()))
    for n, dd in difs.items():
        dd = np.array(dd)
        if not len(dd):
            print(f"  {n}: sin datos suficientes")
            continue
        lo, hi = np.quantile(dd, [.025, .975])
        v = "MEJORA" if hi < 0 else ("sin efecto" if lo < 0 < hi else "EMPEORA")
        print(f"  {n:<16} = {dd.mean():+.4f}  IC 95% [{lo:+.4f}, {hi:+.4f}]  {v}"
              f"   ({afectada[n].mean():.1%} de la gente afectada)")


if __name__ == "__main__":
    main()
