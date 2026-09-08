""".Mejora usar `lambda` por escalon en vez del global?

`12` midio que `lambda` varia 18x entre escalones y que la variacion es real (test-retest
r = 0,563). Eso justifica estimarlo por escalon. **No demuestra que usarlo mejore nada** —
son dos afirmaciones distintas y esta es la segunda.

DONDE ACTUA. `lambda` solo entra en la rama POR ANALOGIA:

    var_j = 1/W_j + lambda * (1 - sim_j)        peso_j proporcional a 1/var_j

o sea que cambia dos cosas a la vez, y hay que mirar las dos:

    el CENTRO   porque cambia a que vecinos se escucha   -> MAE
    el ANCHO    porque el castigo entra en la varianza   -> cobertura y pinball

QUE SE COMPARA. La misma base, consultada de dos formas: con `lam_nivel` y sin el (que es
caer al global). Como la base es identica, el contraste esta pareado por construccion y la
unica diferencia es el parametro.

Bootstrap sobre las EMPRESAS APARTADAS, no sobre las de construccion: `lambda` no cambia la
base, solo como se consulta, asi que remuestrear la construccion mediria otra cosa y
costaria reembeber en cada replica.

SOLO SOBRE LOS TITULOS POR ANALOGIA. En la rama directa las dos variantes dan exactamente
lo mismo, y meter esos empates forzados empuja cualquier diferencia hacia cero — el error
que ya arruino `e1_premisa/13` y la primera version de `e2_nivel/04`.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import BaseReferencia
from benchmarking.producto.nivel import nivel_lexico

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 300
Z50 = 0.6745


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    mk = mk.copy()
    mk["cargo_norm"] = mk.cargo_norm.astype(str)
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train.empresa_ruc.isin(val)].copy()
    ts = train[train.empresa_ruc.isin(val)].copy()
    print(f"construir {tr.empresa_ruc.nunique():,} empresas   "
          f"evaluar {ts.empresa_ruc.nunique():,}")

    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print(f"embebiendo {len(etiquetas):,} titulos...")
    X = embeddings.embeber(etiquetas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    emb = dict(zip(etiquetas, X))

    print("construyendo la base sobre tr...")
    b = BaseReferencia.construir(tr, emb, s.get_sbu)
    print(f"\nlambda global: {b.lam:.3f}")
    print("lambda por escalon: " + "  ".join(f"{k}:{v:.3f}"
                                             for k, v in sorted(b.lam_nivel.items())))

    titulos = sorted(set(ts.cargo_norm))
    guardado = dict(b.lam_nivel)
    ref = {}
    for nom, ln in (("global (hoy)", {}), ("por escalon", guardado)):
        b.lam_nivel = ln
        ref[nom] = b.referenciar(titulos, emb).set_index("cargo")
    b.lam_nivel = guardado

    # solo la gente contestada POR ANALOGIA: en la rama directa no hay diferencia
    base_col = ref["global (hoy)"]["base"]
    analog = set(base_col[base_col == "por analogia"].index)
    d = ts[ts.cargo_norm.isin(analog)].copy()
    d["nivel"] = d.cargo_norm.map(lambda c: nivel_lexico(c) or np.nan)
    y = pd.to_numeric(d["y"], errors="coerce").to_numpy(float)
    print(f"\npor analogia: {len(d):,} personas en {len(analog):,} titulos "
          f"({len(d)/len(ts):.1%} de la gente apartada)")

    col = {}
    for nom, r in ref.items():
        col[nom] = {c: r[c].reindex(d.cargo_norm).to_numpy(float)
                    for c in ("referencia_log", "p25per_log", "p75per_log")}

    ok = np.isfinite(y)
    for nom in ref:
        ok &= np.isfinite(col[nom]["referencia_log"])
    print(f"evaluables: {int(ok.sum()):,}")

    print("\n" + "=" * 78)
    print("A. GLOBAL, sobre toda la gente por analogia")
    print("=" * 78)
    print(f"  {'variante':<16} {'MAE':>9} {'cob 50%':>9} {'ancho medio':>13}")
    for nom in ref:
        c = col[nom]
        e = np.abs(y[ok] - c["referencia_log"][ok])
        dentro = ((y[ok] >= c["p25per_log"][ok]) & (y[ok] <= c["p75per_log"][ok]))
        an = np.exp((c["p75per_log"][ok] - c["p25per_log"][ok]) / 2) - 1
        print(f"  {nom:<16} {e.mean():>9.4f} {dentro.mean():>8.1%} {np.mean(an):>12.1%}")

    # -- contraste pareado sobre empresas apartadas ----------------------------
    print("\n" + "=" * 78)
    print(f"B. CONTRASTE PAREADO ({N_REPLICAS} replicas de empresas apartadas)")
    print("=" * 78)
    emp = d.empresa_ruc.to_numpy()
    unicas = np.array(sorted(set(emp)))
    pos = {e: np.flatnonzero(emp == e) for e in unicas}
    rb = np.random.default_rng(13)
    difs = []
    a_ref, b_ref = col["global (hoy)"], col["por escalon"]
    for _ in range(N_REPLICAS):
        i = np.concatenate([pos[e] for e in rb.choice(unicas, len(unicas))])
        i = i[ok[i]]
        if len(i) < 50:
            continue
        difs.append(float(np.abs(y[i] - b_ref["referencia_log"][i]).mean())
                    - float(np.abs(y[i] - a_ref["referencia_log"][i]).mean()))
    difs = np.array(difs)
    lo, hi = np.quantile(difs, [.025, .975])
    v = "MEJORA" if hi < 0 else ("sin efecto" if lo < 0 < hi else "EMPEORA")
    print(f"  MAE  por escalon - global = {difs.mean():+.4f}  "
          f"IC 95% [{lo:+.4f}, {hi:+.4f}]  {v}")

    # -- por escalon, que es donde la teoria dice que cambia --------------------
    print("\n" + "=" * 78)
    print("C. POR ESCALON DEL PUESTO PREGUNTADO")
    print("=" * 78)
    print(f"  {'nivel':<10} {'personas':>9} {'MAE global':>11} {'MAE escalon':>12} "
          f"{'dif':>9} {'cob global':>11} {'cob escalon':>12}")
    niv = d["nivel"].to_numpy(float)
    for k in (1, 2, 3, 4, 5):
        sel = ok & (niv == k)
        if sel.sum() < 100:
            continue
        ea = np.abs(y[sel] - a_ref["referencia_log"][sel]).mean()
        eb = np.abs(y[sel] - b_ref["referencia_log"][sel]).mean()
        ca = ((y[sel] >= a_ref["p25per_log"][sel]) & (y[sel] <= a_ref["p75per_log"][sel])).mean()
        cb = ((y[sel] >= b_ref["p25per_log"][sel]) & (y[sel] <= b_ref["p75per_log"][sel])).mean()
        print(f"  {k:<10} {int(sel.sum()):>9,} {ea:>11.4f} {eb:>12.4f} {eb-ea:>+9.4f} "
              f"{ca:>10.1%} {cb:>11.1%}")
    sel = ok & ~np.isfinite(niv)
    if sel.sum() >= 100:
        ea = np.abs(y[sel] - a_ref["referencia_log"][sel]).mean()
        eb = np.abs(y[sel] - b_ref["referencia_log"][sel]).mean()
        print(f"  {'sin rango':<10} {int(sel.sum()):>9,} {ea:>11.4f} {eb:>12.4f} "
              f"{eb-ea:>+9.4f}")


if __name__ == "__main__":
    main()
