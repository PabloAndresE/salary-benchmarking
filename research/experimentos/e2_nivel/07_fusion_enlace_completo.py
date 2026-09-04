"""Fusion con enlace COMPLETO: .desaparece el dano y se queda la cobertura?

`05` midio la fusion de cuasi-duplicados y `06` inspecciono los grupos. La inspeccion
encontro que la implementacion tenia dos defectos, no que fusionar fuese mala idea:

  1. ENLACE SIMPLE con cierre transitivo. Union-find junta A con D si existe la cadena
     A~B~C~D, aunque A y D no se parezcan. A 0,95 produjo un grupo de 1.758 titulos con
     `ASISTENTE CONTABLE` y `AUXILIAR DE LIMPIEZA` dentro. A 0,97 ya habia grupos de 116.

  2. EL PUENTE DE NIVEL DESCONOCIDO. El candado de escalon solo bloqueaba el par cuando
     LOS DOS titulos tenian palabra de rango. `GESTOR DE TALENTO HUMANO` no tiene nivel
     lexico (`GESTOR` esta excluido por ambiguo), asi que unia `JEFE DE TALENTO HUMANO`
     (4) con `GERENTE DE TALENTO HUMANO` (5) rodeando el candado.

EL ARREGLO ES UNO SOLO. Enlace completo: un grupo vale solo si TODOS sus pares superan el
umbral y son compatibles de escalon. Eso mata las cadenas por construccion, y de paso mata
el puente: para que `ASISTENTE`(1) y `JEFE`(4) acaben juntos haria falta que el par
directo entre ellos fuese una arista valida, y el candado lo prohibe.

Se implementa aglomerativo y voraz: las aristas se recorren de mas a menos similares y dos
grupos se unen solo si el par PEOR entre ellos aguanta el umbral. Con el vecindario de
10-NN las aristas candidatas salen baratas, y como los grupos quedan chicos, comprobar
todos los pares cruzados es una multiplicacion de matrices diminuta.

QUE SE MIDE. Lo mismo que `05`, para que sea comparable: contraste pareado sobre los
titulos afectados, y cobertura directa. Se anade el diagnostico de `06` en la misma
corrida —tamano de grupo y dispersion de pago— para poder ver de inmediato si los grupos
monstruo desaparecieron.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.evaluacion.referencia import _cuantil_por_grupo, componentes_varianza
from benchmarking.producto.base_referencia import VECINOS, _lambda_semantica, _vecinos
from benchmarking.producto.nivel import efecto_nivel, nivel_lexico

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 150
MIN_EMPRESAS = 3
UMBRALES = (0.97, 0.95, 0.93)
TOPE_GRUPO = 60


def aristas_validas(vec, sim, umbral, niveles):
    """Pares (i,j) del 10-NN que superan el umbral y no cruzan escalon, sin repetir."""
    vistos = set()
    out = []
    for i in range(len(niveles)):
        for j, s in zip(vec[i], sim[i]):
            if s < umbral:
                break
            j = int(j)
            if j == i:
                continue
            a, b = (i, j) if i < j else (j, i)
            if (a, b) in vistos:
                continue
            vistos.add((a, b))
            na, nb = niveles[a], niveles[b]
            if np.isfinite(na) and np.isfinite(nb) and na != nb:
                continue
            out.append((float(s), a, b))
    out.sort(key=lambda t: -t[0])
    return out


def agrupar_completo(Z, vec, sim, umbral, niveles, tope=TOPE_GRUPO):
    """Enlace completo voraz. Devuelve etiqueta -> grupo, y cuantas uniones se rechazaron.

    Une dos grupos solo si el par PEOR entre ellos supera el umbral y no hay dos escalones
    distintos en la union. La diferencia con union-find es esa comprobacion: sin ella el
    grupo crece por cadena y acaba juntando cosas que no se parecen.
    """
    n = len(niveles)
    de = np.arange(n)
    miembros = {}
    rech_sim = rech_niv = rech_tope = 0
    for s, i, j in aristas_validas(vec, sim, umbral, niveles):
        gi, gj = int(de[i]), int(de[j])
        if gi == gj:
            continue
        A = miembros.get(gi, [gi])
        B = miembros.get(gj, [gj])
        if len(A) + len(B) > tope:
            rech_tope += 1
            continue
        niv = np.concatenate([niveles[A], niveles[B]])
        niv = np.unique(niv[np.isfinite(niv)])
        if len(niv) > 1:
            rech_niv += 1
            continue
        if float((Z[A] @ Z[B].T).min()) < umbral:
            rech_sim += 1
            continue
        nuevo = A + B
        miembros[gi] = nuevo
        miembros.pop(gj, None)
        de[nuevo] = gi
    return de, (rech_sim, rech_niv, rech_tope)


def agrupar_simple(vec, sim, umbral, niveles):
    """La version de `05`, enlace simple, para tenerla al lado como control."""
    padre = list(range(len(niveles)))

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for s, i, j in aristas_validas(vec, sim, umbral, niveles):
        ri, rj = raiz(i), raiz(j)
        if ri != rj:
            padre[ri] = rj
    return np.array([raiz(i) for i in range(len(niveles))])


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
    d = train.reset_index(drop=True)
    val = set(rng.choice(emp0, max(1, len(emp0) // 4), replace=False))
    tr = d[~d.empresa_ruc.isin(val)].reset_index(drop=True)
    ts = d[d.empresa_ruc.isin(val)].reset_index(drop=True)
    print(f"train {len(tr):,} filas / {tr.empresa_ruc.nunique():,} empresas")

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
    print("buscando vecinos (una sola vez)...")
    vecQ, simQ = _vecinos(Z, Z, VECINOS, excluir_propio=False)
    vecP, simP = _vecinos(Z, Z, VECINOS, excluir_propio=True)
    m0, W0, e0 = votos(tr, cod_tr, tau2, sigma2, len(celdas))
    lam = _lambda_semantica(m0, W0, vecP, simP)
    print(f"lambda = {lam:.3f}")

    def referencia(grupo, m, W, emp):
        g = grupo
        mg, Wg, eg = m[g], W[g], emp[g]
        vg = g[vecQ]
        mv, Wv, ev = m[vg], W[vg], emp[vg]
        dist = lam * (1.0 - simQ)
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

    # ---- construir las agrupaciones -----------------------------------------
    grupos = {"sin fusionar": np.arange(len(celdas))}
    for u in UMBRALES:
        g, (rs, rn, rt) = agrupar_completo(Z, vecP, simP, u, niveles)
        grupos[f"completo >{u}"] = g
        print(f"  enlace completo >{u}: rechazadas {rs:,} por similitud, "
              f"{rn:,} por escalon, {rt:,} por tope")
    grupos["simple >0.95"] = agrupar_simple(vecP, simP, 0.95, niveles)

    # ---- diagnostico: .quedan grupos monstruo? -------------------------------
    med = train.groupby(train.cargo_norm.astype(str))["y"].median().reindex(celdas)
    med = med.to_numpy()
    print("\n" + "=" * 78)
    print("FORMA DE LOS GRUPOS (el defecto que `06` encontro)")
    print("=" * 78)
    print(f"  {'variante':<16} {'grupos 2+':>10} {'mayor':>8} {'p99':>7} "
          f"{'disp.mediana':>13} {'disp.p99':>10}")
    for nombre, g in grupos.items():
        if nombre == "sin fusionar":
            continue
        tam = pd.Series(g).value_counts()
        multi = tam[tam > 1]
        disp = []
        for k in multi.index:
            v = med[np.flatnonzero(g == k)]
            v = v[np.isfinite(v)]
            if len(v) > 1:
                disp.append(float(np.exp(v.max() - v.min())))
        disp = np.array(disp) if disp else np.array([np.nan])
        print(f"  {nombre:<16} {len(multi):>10,} {int(tam.max()):>8,} "
              f"{int(np.quantile(tam.to_numpy(), 0.99)):>7,} "
              f"{np.nanmedian(disp):>12.2f}x {np.nanquantile(disp, 0.99):>9.2f}x")

    print("\n" + "=" * 78)
    print("COBERTURA DIRECTA: cuanta gente se contesta con datos propios")
    print("=" * 78)
    for nombre, g in grupos.items():
        m, W, e = votos(tr, g[cod_tr], tau2, sigma2, len(celdas))
        _, directo = referencia(g, m, W, e)
        print(f"  {nombre:<16} {len(np.unique(g)):>7,} celdas   "
              f"directo: {directo[cod_ts].mean():>6.1%} de la gente")

    # ---- contraste pareado ---------------------------------------------------
    print("\n" + "=" * 78)
    print(f"CONTRASTE PAREADO ({N_REPLICAS} replicas), solo sobre los titulos AFECTADOS")
    print("=" * 78)
    emp_tr = np.array(sorted(tr.empresa_ruc.unique()))
    emp_ts = np.array(sorted(ts.empresa_ruc.unique()))
    p_tr = {e: np.flatnonzero((tr.empresa_ruc == e).to_numpy()) for e in emp_tr}
    p_ts = {e: np.flatnonzero((ts.empresa_ruc == e).to_numpy()) for e in emp_ts}
    afectada = {n: np.isin(g[cod_ts],
                           np.flatnonzero(np.bincount(g, minlength=len(celdas)) > 1))
                for n, g in grupos.items() if n != "sin fusionar"}
    rb = np.random.default_rng(13)
    difs = {n: [] for n in afectada}
    for r in range(N_REPLICAS):
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
        if (r + 1) % 25 == 0:
            print(f"    replica {r + 1}/{N_REPLICAS}", flush=True)
    for n, dd in difs.items():
        dd = np.array(dd)
        if not len(dd):
            print(f"  {n}: sin datos suficientes")
            continue
        lo, hi = np.quantile(dd, [.025, .975])
        v = "MEJORA" if hi < 0 else ("sin efecto" if lo < 0 < hi else "EMPEORA")
        print(f"  {n:<16} = {dd.mean():+.4f}  IC 95% [{lo:+.4f}, {hi:+.4f}]  {v}"
              f"   ({afectada[n].mean():.1%} de la gente afectada)")

    # ---- ejemplos de los grupos mas grandes que sobreviven -------------------
    print("\n" + "=" * 78)
    print("LOS GRUPOS MAS GRANDES QUE SOBREVIVEN AL ENLACE COMPLETO")
    print("=" * 78)
    npers = train.groupby(train.cargo_norm.astype(str))["y"].size().reindex(
        celdas).fillna(0).to_numpy()
    for u in UMBRALES:
        g = grupos[f"completo >{u}"]
        tam = pd.Series(g).value_counts()
        print(f"\n--- umbral {u}")
        for k in tam[tam > 1].head(2).index:
            mi = np.flatnonzero(g == k)
            mi = mi[np.argsort(-npers[mi])]
            v = med[mi][np.isfinite(med[mi])]
            print(f"\n  grupo de {len(mi)} titulos   dispersion "
                  f"{np.exp(v.max() - v.min()) if len(v) > 1 else 1.0:.2f}x")
            for i in mi[:6]:
                print(f"    {celdas[i][:52]:<54} {med[i]:>7.3f} {int(npers[i]):>7,} pers.")
            if len(mi) > 6:
                print(f"    ... y {len(mi) - 6} mas")


if __name__ == "__main__":
    main()
