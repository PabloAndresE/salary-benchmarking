""".Mejora el producto el vecindario por area enmascarada x nivel lexico?

`03` midio que la descomposicion tiene senal: dentro del area, el nivel ordena el pago
monotonamente (2,37x, placebo cero) y `area x nivel` recupera el 97,4% de lo que sabe la
etiqueta original. Pero eso mide la SENAL, no la MEJORA del producto.

Aqui se compara lo que de verdad importa, con contraste pareado:

    A. vecindario sobre el titulo CRUDO, sin ajuste de nivel   (el producto anterior)
    B. vecindario sobre el AREA ENMASCARADA, con ajuste        (la version enmascarada)
    C. vecindario sobre el titulo CRUDO, CON ajuste de nivel   (separa las dos cosas)

C existe porque B mezcla dos cambios y salio sin efecto: enmascarar EMPEORA la
representacion del area —`lambda` sube de 1,78 a 2,48, y el 2,62% de la gente se queda sin
area— mientras el nivel deberia ayudar. C se queda con lo bueno de cada uno: la mejor
representacion del area y el ajuste por escalon.

DONDE SE MIDE, y es la decision que arruino el experimento `13`. Para los titulos con
datos propios los dos metodos dan EXACTAMENTE lo mismo, asi que incluirlos diluye el
contraste hacia cero. Se mide solo sobre la poblacion donde el mecanismo opera: los
titulos que se responden POR ANALOGIA.

COMO SE HACE VIABLE EL BOOTSTRAP. Los vecinos y `lambda` dependen del TEXTO, que no cambia
al remuestrear empresas: se precalculan una vez. Por replica solo se recalculan `m` y `W`.
Sin eso cada replica rehace una busqueda de vecinos de 5.000 x 65.081 y no cabe en el dia.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.evaluacion.referencia import componentes_varianza, tabla_votos
from benchmarking.producto.base_referencia import VECINOS, _lambda_semantica, _vecinos
from benchmarking.producto.nivel import efecto_nivel, enmascarar, nivel_lexico

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
MUESTRA_EMPRESAS = 100000   # todas
N_REPLICAS = 200
# Al filtrar por escalon se descartan vecinos, asi que las variantes con filtro
# arrancan con MAS candidatos para no quedarse con tres. Sin esto su varianza es
# artefacto de haberles dado pocos, no del diseno.
VECINOS_FILTRO = 100
MIN_EMPRESAS = 3


def compilar(tr, ts, textos_celda, cache, cli, s, con_nivel, k=VECINOS):
    """Todo lo que NO cambia al remuestrear: celdas, vecinos, niveles y lambda."""
    celdas = sorted(set(tr.cargo_norm.astype(str)))
    idx = {c: i for i, c in enumerate(celdas)}
    Z = embeddings.embeber([textos_celda(c) for c in celdas], cli,
                           s.vertex_embedding_model, cache=cache)
    Z = Z / np.linalg.norm(Z, axis=1, keepdims=True)

    consulta = sorted(set(ts.cargo_norm.astype(str)))
    Q = embeddings.embeber([textos_celda(c) for c in consulta], cli,
                           s.vertex_embedding_model, cache=cache)
    Q = Q / np.linalg.norm(Q, axis=1, keepdims=True)
    vec, sim = _vecinos(Q, Z, k, excluir_propio=False)

    niv_c = np.array([nivel_lexico(c) or np.nan for c in celdas], dtype=float)
    niv_q = np.array([nivel_lexico(c) or np.nan for c in consulta], dtype=float)
    ef = efecto_nivel(tr) if con_nivel else {}
    var_niv = float(np.var(list(ef.values()))) if len(ef) > 1 else 0.0
    return {"celdas": celdas, "idx": idx, "consulta": consulta,
            "q_idx": {c: k for k, c in enumerate(consulta)},
            "vec": vec, "sim": sim, "niv_c": niv_c, "niv_q": niv_q,
            "ef": ef, "var_niv": var_niv, "Z": Z, "propio":
            np.array([idx.get(c, -1) for c in consulta])}


def votos_de(tr_b, celdas, idx, tau2, sigma2):
    """m y W por celda sobre una muestra de train. Vectorizado."""
    d = pd.DataFrame({"c": tr_b.cargo_norm.astype(str).to_numpy(),
                      "e": tr_b.empresa_ruc.to_numpy(),
                      "y": pd.to_numeric(tr_b["y"], errors="coerce").to_numpy(float)})
    d = d.dropna(subset=["y"])
    v = d.groupby(["c", "e"], sort=False)["y"].agg(voto="median", n="size").reset_index()
    v["w"] = 1.0 / (tau2 + sigma2 / v["n"].to_numpy(float))
    v["cod"] = v["c"].map(idx)
    v = v.dropna(subset=["cod"]).sort_values(["cod", "voto"], kind="mergesort")
    cod = v["cod"].to_numpy(int)
    n = len(celdas)
    m = np.full(n, np.nan)
    if len(cod):
        from benchmarking.evaluacion.referencia import _cuantil_por_grupo
        vis = np.unique(cod)
        m[vis] = _cuantil_por_grupo(np.searchsorted(vis, cod), v["voto"].to_numpy(float),
                                    v["w"].to_numpy(float), len(vis))
    W = np.bincount(cod, weights=v["w"].to_numpy(float), minlength=n)
    emp = np.bincount(cod, minlength=n).astype(float)
    return m, W, emp


def referenciar(C, m, W, emp, lam, tau2, sigma2, solo_analogia, filtrar=False):
    """Referencia por titulo de consulta. NaN donde no se responde."""
    vec, sim = C["vec"], C["sim"]
    mv, Wv, ev = m[vec], W[vec], emp[vec]
    dist = lam * (1.0 - sim)
    with np.errstate(invalid="ignore", divide="ignore"):
        var_j = np.where(Wv > 0, 1.0 / np.where(Wv > 0, Wv, 1.0), np.inf) + dist
        peso = np.where(np.isfinite(mv) & (Wv > 0), 1.0 / var_j, 0.0)
        tot = peso.sum(axis=1, keepdims=True)
        peso = np.where(tot > 0, peso / np.where(tot > 0, tot, 1.0), 0.0)

    # MODO FILTRO: en vez de corregir el escalon de cada vecino, quedarse solo con los
    # del MISMO escalon. Quita el sesgo de la correccion imperfecta —un OPERARIO y un
    # ANALISTA de la misma area se diferencian en mas que el rango— a cambio de menos
    # donantes, o sea mas varianza. Solo aplicable donde se conoce el escalon del puesto
    # preguntado; sin palabra de rango no hay nada que filtrar.
    if filtrar:
        nq = C["niv_q"][:, None]
        nc = C["niv_c"][vec]
        mismo = (~np.isfinite(nq)) | (~np.isfinite(nc)) | (nq == nc)
        peso = np.where(mismo, peso, 0.0)
        tot2 = peso.sum(axis=1, keepdims=True)
        peso = np.where(tot2 > 0, peso / np.where(tot2 > 0, tot2, 1.0), 0.0)

    aj = np.zeros_like(mv)
    if C["ef"] and not filtrar:
        efc = np.array([C["ef"].get(int(k), np.nan) if np.isfinite(k) else np.nan
                        for k in C["niv_c"]])
        efq = np.array([C["ef"].get(int(k), np.nan) if np.isfinite(k) else np.nan
                        for k in C["niv_q"]])
        a = efq[:, None] - efc[vec]
        aj = np.where(np.isfinite(a), a, 0.0)
        sabe = np.isfinite(efq)
    else:
        sabe = np.zeros(len(C["consulta"]), dtype=bool)

    mu = (peso * (np.nan_to_num(mv) + aj)).sum(axis=1)
    ok = peso.sum(axis=1) > 0
    n_emp = (np.where(peso > 0, ev, 0.0)).sum(axis=1)

    # los que tienen datos propios suficientes se responden directo, salvo que se pida
    # medir SOLO la analogia
    pr = C["propio"]
    directo = (pr >= 0) & (emp[np.clip(pr, 0, len(emp) - 1)] >= MIN_EMPRESAS)
    if solo_analogia:
        mu = np.where(directo, np.nan, mu)
        ok = ok & ~directo
    else:
        mu = np.where(directo, m[np.clip(pr, 0, len(m) - 1)], mu)
        ok = ok | directo
    return np.where(ok & (n_emp >= MIN_EMPRESAS), mu, np.nan)


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
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print("compilando A (titulo crudo, sin nivel)...")
    A = compilar(tr, ts, lambda c: c, cache, cli, s, con_nivel=False)
    print("compilando B (area enmascarada, con nivel)...")
    B = compilar(tr, ts, enmascarar, cache, cli, s, con_nivel=True)
    print("compilando A100/B100 (mismos espacios, mas candidatos para el filtro)...")
    A100 = compilar(tr, ts, lambda c: c, cache, cli, s, False, k=VECINOS_FILTRO)
    B100 = compilar(tr, ts, enmascarar, cache, cli, s, True, k=VECINOS_FILTRO)
    print("compilando C (titulo crudo, con nivel)...")
    C = dict(A)                      # mismo espacio de texto que A
    C["ef"] = efecto_nivel(tr)
    C["var_niv"] = float(np.var(list(C["ef"].values()))) if len(C["ef"]) > 1 else 0.0
    cache.volcar()
    print("efecto de nivel:",
          {k: round(v, 3) for k, v in sorted(B["ef"].items())})

    m0, W0, e0 = votos_de(tr, A["celdas"], A["idx"], tau2, sigma2)
    # lambda es propio de cada espacio de texto: mide cuanto difieren dos celdas por
    # unidad de distancia semantica, y esa distancia significa cosas distintas en el
    # espacio crudo y en el enmascarado.
    vA, sA = _vecinos(A["Z"], A["Z"], VECINOS, excluir_propio=True)
    vB, sB = _vecinos(B["Z"], B["Z"], VECINOS, excluir_propio=True)
    lamA = _lambda_semantica(m0, W0, vA, sA)
    lamB = _lambda_semantica(m0, W0, vB, sB)
    print(f"lambda  A={lamA:.3f}   B={lamB:.3f}")

    y_por_titulo = ts.cargo_norm.astype(str).map(A["q_idx"]).to_numpy()
    y = pd.to_numeric(ts["y"], errors="coerce").to_numpy(float)
    # El filtro SOLO actua donde el puesto preguntado tiene palabra de rango: sin ella no
    # hay nada que filtrar y las variantes dan exactamente lo mismo. Incluir esas filas
    # mete empates forzados que empujan cualquier diferencia hacia cero — el mismo error
    # que arruino el experimento `13`.
    con_rango = np.isfinite(A["niv_q"])[y_por_titulo]
    print()
    print(f"de los titulos de eval, con palabra de rango: {con_rango.mean():.1%} "
          f"de las personas   (donde filtro y ajuste se diferencian)")

    def evaluar(sa):
        rA = referenciar(A, m0, W0, e0, lamA, tau2, sigma2, sa)[y_por_titulo]
        rB = referenciar(B, m0, W0, e0, lamB, tau2, sigma2, sa)[y_por_titulo]
        ok = np.isfinite(y) & np.isfinite(rA) & np.isfinite(rB)
        return (float(np.abs(y[ok] - rA[ok]).mean()), float(np.abs(y[ok] - rB[ok]).mean()),
                float(ok.mean()))

    for nombre, sa in (("TODA la nomina", False), ("SOLO por analogia", True)):
        a, b, cob = evaluar(sa)
        print(f"\n{nombre}:  cobertura comun {cob:.1%}   "
              f"MAE  A={a:.4f}  B={b:.4f}   ({b/a-1:+.2%})")

    # ---- contraste pareado, solo sobre la analogia --------------------------
    print("\n" + "=" * 72)
    print(f"CONTRASTE PAREADO ({N_REPLICAS} replicas)")
    print("solo titulos POR ANALOGIA y CON palabra de rango")
    print("=" * 72)
    emp_tr = np.array(sorted(tr.empresa_ruc.unique()))
    emp_ts = np.array(sorted(ts.empresa_ruc.unique()))
    p_tr = {e: np.flatnonzero((tr.empresa_ruc == e).to_numpy()) for e in emp_tr}
    p_ts = {e: np.flatnonzero((ts.empresa_ruc == e).to_numpy()) for e in emp_ts}
    rb = np.random.default_rng(11)
    difs = {n: [] for n in ("B", "C", "D", "E")}
    for _ in range(N_REPLICAS):
        i_tr = np.concatenate([p_tr[e] for e in rb.choice(emp_tr, len(emp_tr))])
        i_ts = np.concatenate([p_ts[e] for e in rb.choice(emp_ts, len(emp_ts))])
        mb, Wb, eb = votos_de(tr.iloc[i_tr], A["celdas"], A["idx"], tau2, sigma2)
        r = {n: referenciar(M, mb, Wb, eb, lam, tau2, sigma2, True, f)
             for n, M, lam, f in (("A", A, lamA, False), ("B", B, lamB, False),
                                  ("C", C, lamA, False), ("D", B100, lamB, True),
                                  ("E", A100, lamA, True))}
        tb = ts.iloc[i_ts]
        qi = tb.cargo_norm.astype(str).map(A["q_idx"]).to_numpy()
        yb = pd.to_numeric(tb["y"], errors="coerce").to_numpy(float)
        v = {n: x[qi] for n, x in r.items()}
        ok = np.isfinite(yb) & np.isfinite(A["niv_q"][qi])
        for x in v.values():
            ok &= np.isfinite(x)
        if ok.sum() < 50:
            continue
        base = float(np.abs(yb[ok] - v["A"][ok]).mean())
        for n in ("B", "C", "D", "E"):
            difs[n].append(float(np.abs(yb[ok] - v[n][ok]).mean()) - base)

    etq = {"B": "enmascarado + ajuste", "C": "crudo + ajuste",
           "D": "enmascarado + FILTRO", "E": "crudo + FILTRO"}
    for n in ("B", "C", "D", "E"):
        dd = np.array(difs[n])
        lo, hi = np.quantile(dd, [.025, .975])
        veredicto = "MEJORA" if hi < 0 else ("sin efecto" if lo < 0 < hi else "EMPEORA")
        print(f"  {n} - A  = {dd.mean():+.4f}  IC 95% [{lo:+.4f}, {hi:+.4f}]  "
              f"{veredicto:<11} {etq[n]}")

    # Comparar cada variante contra el BASELINE no dice cual es mejor ENTRE ellas. Como
    # todas comparten replica, la diferencia entre dos de ellas es pareada tambien, y es
    # el contraste que decide.
    print()
    print("  ENTRE VARIANTES (todas sobre la misma replica):")
    import itertools
    for x, z in itertools.combinations(("B", "C", "D", "E"), 2):
        dd = np.array(difs[x]) - np.array(difs[z])
        lo, hi = np.quantile(dd, [.025, .975])
        if hi < 0:
            v = f"gana {x}"
        elif lo > 0:
            v = f"gana {z}"
        else:
            v = "indistinguibles"
        print(f"    {x} - {z}  = {dd.mean():+.4f}  [{lo:+.4f}, {hi:+.4f}]  {v}")

    print()
    print("  ESTABILIDAD (desviacion del MAE entre replicas; menos es mas fiable):")
    for n in ("B", "C", "D", "E"):
        print(f"    {n}  sd = {np.std(difs[n]):.4f}   {etq[n]}")


if __name__ == "__main__":
    main()
