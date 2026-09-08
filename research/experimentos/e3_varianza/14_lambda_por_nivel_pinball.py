"""`lambda` por escalon, medido como se debe: regla propia y placebo.

`13` comparo con MAE y cobertura POR SEPARADO, y eso esta mal por dos razones. El producto
entrega una BANDA, no un punto: el MAE premia solo el centro y la cobertura se puede
ensanchar a voluntad, asi que reportar los dos deja elegir cual pesa mas DESPUES de verlos.
Es el jardin de senderos que se bifurcan. Una regla de puntuacion PROPIA integra centro y
anchura en un numero que empeora si mientes en cualquiera de los dos.

Y le faltaba PLACEBO. Van 13 experimentos en E3; a un 5%, algunos "significativos" son
azar. En D-018 el placebo eligio MAS cargos que la senal real, y sin el se habria reportado
una mejora inexistente.

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
PRIMARIA:   pinball medio en q=0,25 y q=0,75 sobre la banda de PERSONAS, contraste pareado
            sobre empresas apartadas, solo en titulos contestados POR ANALOGIA (que es
            donde `lambda` actua; en la rama directa las dos variantes son identicas).

SE ADOPTA si y solo si se cumplen LAS DOS:
    1. el IC 95% de la diferencia pareada de pinball queda ENTERO por debajo de cero
    2. el PLACEBO no reproduce esa mejora

SECUNDARIAS, se reportan y NO deciden: MAE, cobertura del 50%, y el desglose por escalon.

EL PLACEBO. Se barajan las etiquetas de escalon ENTRE CARGOS y se vuelve a estimar
`lambda` por grupo con el mismo procedimiento. Mismo numero de grupos, misma estimacion,
misma flexibilidad — solo se rompe la correspondencia cargo-escalon. Se deja intacto
`b.nivel`, que alimenta el ajuste de escalon: si se barajara tambien, el placebo estaria
midiendo dos cosas.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import (VECINOS, BaseReferencia,
                                                   _lambda_por_nivel, _vecinos)
from benchmarking.producto.nivel import nivel_lexico

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 300


def pinball(y, lo, hi):
    """Perdida pinball media de los dos cuantiles entregados, observacion a observacion."""
    a = np.maximum(0.25 * (y - lo), -0.75 * (y - lo))
    b = np.maximum(0.75 * (y - hi), -0.25 * (y - hi))
    return (a + b) / 2.0


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

    # Real y placebo se estiman con LOS MISMOS insumos para que sean comparables.
    Zn = b.Z / np.linalg.norm(b.Z, axis=1, keepdims=True)
    vec, sim = _vecinos(Zn, Zn, VECINOS, excluir_propio=True)
    lam_real = _lambda_por_nivel(b.m, b.W, vec, sim, b.nivel, b.lam)
    rp = np.random.default_rng(99)
    niv_barajado = b.nivel.copy()
    hay = np.isfinite(niv_barajado)
    niv_barajado[hay] = rp.permutation(niv_barajado[hay])
    lam_plac = _lambda_por_nivel(b.m, b.W, vec, sim, niv_barajado, b.lam)

    print(f"\nlambda global:  {b.lam:.3f}")
    print("  real:    " + "  ".join(f"{k}:{v:.3f}" for k, v in sorted(lam_real.items())))
    print("  PLACEBO: " + "  ".join(f"{k}:{v:.3f}" for k, v in sorted(lam_plac.items())))
    print("  (si el placebo da cinco numeros parecidos entre si y al global, la particion")
    print("   por escalon lleva senal; si da tanta variedad como el real, no)")

    titulos = sorted(set(ts.cargo_norm))
    ref = {}
    for nom, ln in (("global", {}), ("por escalon", lam_real), ("PLACEBO", lam_plac)):
        b.lam_nivel = ln
        ref[nom] = b.referenciar(titulos, emb).set_index("cargo")
    b.lam_nivel = lam_real

    base_col = ref["global"]["base"]
    analog = set(base_col[base_col == "por analogia"].index)
    d = ts[ts.cargo_norm.isin(analog)].copy()
    d["nivel"] = d.cargo_norm.map(lambda c: nivel_lexico(c) or np.nan)
    y = pd.to_numeric(d["y"], errors="coerce").to_numpy(float)
    col = {n: {c: r[c].reindex(d.cargo_norm).to_numpy(float)
               for c in ("referencia_log", "p25per_log", "p75per_log")}
           for n, r in ref.items()}
    ok = np.isfinite(y)
    for n in ref:
        ok &= np.isfinite(col[n]["referencia_log"]) & np.isfinite(col[n]["p25per_log"])
    print(f"\npor analogia y evaluables: {int(ok.sum()):,} personas "
          f"({ok.sum()/len(ts):.1%} de la gente apartada)")

    print("\n" + "=" * 82)
    print("PRIMARIA: pinball. Secundarias abajo, y NO deciden")
    print("=" * 82)
    print(f"  {'variante':<14} {'PINBALL':>9} {'MAE':>9} {'cob 50%':>9} {'ancho':>9}")
    for n in ref:
        c = col[n]
        pb = pinball(y[ok], c["p25per_log"][ok], c["p75per_log"][ok]).mean()
        e = np.abs(y[ok] - c["referencia_log"][ok]).mean()
        dentro = ((y[ok] >= c["p25per_log"][ok]) & (y[ok] <= c["p75per_log"][ok])).mean()
        an = np.mean(np.exp((c["p75per_log"][ok] - c["p25per_log"][ok]) / 2) - 1)
        print(f"  {n:<14} {pb:>9.4f} {e:>9.4f} {dentro:>8.1%} {an:>8.1%}")

    print("\n" + "=" * 82)
    print(f"CONTRASTE PAREADO ({N_REPLICAS} replicas de empresas apartadas)")
    print("=" * 82)
    emp = d.empresa_ruc.to_numpy()
    unicas = np.array(sorted(set(emp)))
    pos = {e: np.flatnonzero(emp == e) for e in unicas}
    rb = np.random.default_rng(13)
    idxs = []
    for _ in range(N_REPLICAS):
        i = np.concatenate([pos[e] for e in rb.choice(unicas, len(unicas))])
        i = i[ok[i]]
        if len(i) >= 50:
            idxs.append(i)

    g = col["global"]
    for n in ("por escalon", "PLACEBO"):
        c = col[n]
        dif = np.array([
            float(pinball(y[i], c["p25per_log"][i], c["p75per_log"][i]).mean())
            - float(pinball(y[i], g["p25per_log"][i], g["p75per_log"][i]).mean())
            for i in idxs])
        lo, hi = np.quantile(dif, [.025, .975])
        v = "MEJORA" if hi < 0 else ("sin efecto" if lo < 0 < hi else "EMPEORA")
        print(f"  pinball  {n:<12} - global = {dif.mean():+.5f}  "
              f"IC 95% [{lo:+.5f}, {hi:+.5f}]  {v}")

    print("\n" + "=" * 82)
    print("SECUNDARIO (no decide): desglose por escalon")
    print("=" * 82)
    niv = d["nivel"].to_numpy(float)
    print(f"  {'nivel':<10} {'personas':>9} {'pin global':>11} {'pin escalon':>12} "
          f"{'dif':>10} {'cob glob':>9} {'cob esc':>9}")
    e_ = col["por escalon"]
    for k in (1, 2, 3, 4, 5):
        sel = ok & (niv == k)
        if sel.sum() < 100:
            continue
        pg = pinball(y[sel], g["p25per_log"][sel], g["p75per_log"][sel]).mean()
        pe = pinball(y[sel], e_["p25per_log"][sel], e_["p75per_log"][sel]).mean()
        cg = ((y[sel] >= g["p25per_log"][sel]) & (y[sel] <= g["p75per_log"][sel])).mean()
        ce = ((y[sel] >= e_["p25per_log"][sel]) & (y[sel] <= e_["p75per_log"][sel])).mean()
        print(f"  {k:<10} {int(sel.sum()):>9,} {pg:>11.4f} {pe:>12.4f} {pe-pg:>+10.4f} "
              f"{cg:>8.1%} {ce:>8.1%}")


if __name__ == "__main__":
    main()
