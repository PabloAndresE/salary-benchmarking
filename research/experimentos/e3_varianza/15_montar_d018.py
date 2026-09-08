""".Mejora la correccion por tamano, tal y como esta MONTADA?

`09` midio que el centro esta sesgado por tamano en los cargos altos y que segmentar lo
arregla. Eso justifica la idea. **No mide esta implementacion**, que es distinta en tres
cosas y hay que comprobarla tal cual:

  1. se aplica solo a los cargos de escalon >= 4, no a todos
  2. desplaza la banda entera en vez de reestimarla por segmento — porque `07` midio que
     reestimar la ANCHURA pierde y `09` que el CENTRO esta sesgado
  3. exige 10 empresas en el segmento; por debajo no mueve nada

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
PRIMARIA:   pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste pareado
            sobre empresas apartadas, restringido a los votos de cargos CORREGIBLES (donde
            las dos variantes difieren; en el resto son identicas por construccion).

SE ADOPTA si y solo si:
    1. el IC 95% de la diferencia pareada queda ENTERO por debajo de cero
    2. el PLACEBO —segmento barajado entre empresas— no lo reproduce

SECUNDARIO, se reporta y no decide: el sesgo con signo por segmento, que es el defecto
que motivo todo esto.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import (NIVEL_MIN_SEGMENTAR, SEGMENTOS,
                                                   BaseReferencia, _norm_segmento)
from benchmarking.producto.nivel import nivel_lexico

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 300


def pinball(y, lo, hi):
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
    con = (b.ajuste_seg != 0).any(axis=1)
    print(f"celdas con correccion: {int(con.sum()):,}   "
          f"{int(b.personas[con].sum()):,} personas")

    # un voto por (cargo, empresa) de las apartadas, con su segmento real
    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc"], sort=False)
           .agg(voto=("y", "median"), seg=("segmento", "first")).reset_index())
    v["seg"] = v["seg"].map(_norm_segmento)
    rp = np.random.default_rng(99)
    hay = v["seg"].notna()
    v.loc[hay, "seg_plac"] = rp.permutation(v.loc[hay, "seg"].to_numpy())

    titulos = sorted(set(v.cargo_norm))
    ref = {None: b.referenciar(titulos, emb).set_index("cargo")}
    for g in SEGMENTOS:
        ref[g] = b.referenciar(titulos, emb, segmento=g).set_index("cargo")

    def arma(colseg):
        out = {}
        for c in ("referencia_log", "p25_log", "p75_log"):
            base = ref[None][c].reindex(v.cargo_norm).to_numpy(float)
            for g in SEGMENTOS:
                sel = (v[colseg] == g).to_numpy()
                if sel.any():
                    base = np.where(sel, ref[g][c].reindex(v.cargo_norm).to_numpy(float),
                                    base)
            out[c] = base
        return out

    col = {"sin segmentar": arma("_ninguno") if False else
           {c: ref[None][c].reindex(v.cargo_norm).to_numpy(float)
            for c in ("referencia_log", "p25_log", "p75_log")},
           "con segmento": arma("seg"),
           "PLACEBO": arma("seg_plac")}

    y = v["voto"].to_numpy(float)
    # solo donde las variantes difieren: en el resto son identicas por construccion
    dif = (col["con segmento"]["referencia_log"] != col["sin segmentar"]["referencia_log"])
    ok = dif & np.isfinite(y)
    for n in col:
        ok &= np.isfinite(col[n]["p25_log"]) & np.isfinite(col[n]["p75_log"])
    print(f"\nvotos de empresa donde la correccion actua: {int(ok.sum()):,} "
          f"de {len(v):,} ({ok.sum()/len(v):.1%})")

    print("\n" + "=" * 78)
    print("PRIMARIA: pinball sobre los votos corregibles")
    print("=" * 78)
    print(f"  {'variante':<16} {'PINBALL':>9} {'|sesgo|':>9} {'cob 50%':>9}")
    for n, c in col.items():
        pb = pinball(y[ok], c["p25_log"][ok], c["p75_log"][ok]).mean()
        sesgo = float(np.mean(y[ok] - c["referencia_log"][ok]))
        cob = float(((y[ok] >= c["p25_log"][ok]) & (y[ok] <= c["p75_log"][ok])).mean())
        print(f"  {n:<16} {pb:>9.4f} {abs(np.exp(sesgo)-1):>8.1%} {cob:>8.1%}")

    print("\n" + "=" * 78)
    print(f"CONTRASTE PAREADO ({N_REPLICAS} replicas de empresas apartadas)")
    print("=" * 78)
    emp = v.empresa_ruc.to_numpy()
    unicas = np.array(sorted(set(emp[ok])))
    pos = {e: np.flatnonzero((emp == e) & ok) for e in unicas}
    rb = np.random.default_rng(13)
    idxs = []
    for _ in range(N_REPLICAS):
        i = np.concatenate([pos[e] for e in rb.choice(unicas, len(unicas))])
        if len(i) >= 50:
            idxs.append(i)
    g = col["sin segmentar"]
    for n in ("con segmento", "PLACEBO"):
        c = col[n]
        d = np.array([float(pinball(y[i], c["p25_log"][i], c["p75_log"][i]).mean())
                      - float(pinball(y[i], g["p25_log"][i], g["p75_log"][i]).mean())
                      for i in idxs])
        lo, hi = np.quantile(d, [.025, .975])
        vv = "MEJORA" if hi < 0 else ("sin efecto" if lo < 0 < hi else "EMPEORA")
        print(f"  {n:<16} - sin segmentar = {d.mean():+.5f}  "
              f"IC 95% [{lo:+.5f}, {hi:+.5f}]  {vv}")

    print("\n" + "=" * 78)
    print("SECUNDARIO (no decide): el sesgo con signo, que es lo que motivo D-018")
    print("=" * 78)
    print(f"  {'segmento':<14} {'votos':>7} {'sin segmentar':>15} {'con segmento':>15}")
    seg = v["seg"].to_numpy(object)
    for gname in SEGMENTOS:
        sel = ok & (seg == gname)
        if sel.sum() < 30:
            continue
        a = float(np.mean(y[sel] - g["referencia_log"][sel]))
        c = float(np.mean(y[sel] - col["con segmento"]["referencia_log"][sel]))
        print(f"  {gname:<14} {int(sel.sum()):>7,} {np.exp(a)-1:>+14.1%} "
              f"{np.exp(c)-1:>+14.1%}")
    vals_a, vals_c = [], []
    for gname in SEGMENTOS:
        sel = ok & (seg == gname)
        if sel.sum() >= 30:
            vals_a.append(np.exp(np.mean(y[sel] - g["referencia_log"][sel])) - 1)
            vals_c.append(np.exp(np.mean(y[sel] - col["con segmento"]["referencia_log"][sel])) - 1)
    if len(vals_a) > 1:
        print(f"  {'recorrido':<14} {'':>7} {max(vals_a)-min(vals_a):>14.1%} "
              f"{max(vals_c)-min(vals_c):>14.1%}")


if __name__ == "__main__":
    main()
