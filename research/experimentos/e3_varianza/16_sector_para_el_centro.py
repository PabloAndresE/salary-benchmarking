"""El SECTOR para el centro: la medicion que nadie hizo.

EL HUECO. `07` midio el sector para la BANDA y pierde (pinball 0,1289 contra 0,1255). Pero
con el TAMANO paso exactamente eso y la conclusion era otra:

    tamano   para la BANDA   pierde                       -> descartado
             para el CENTRO  sesgo de 43,3 a 5,0 puntos   -> montado (D-018)

Nadie hizo la segunda medicion con el sector. Y hay razon para sospecharla: un `VENDEDOR`
de banca y uno de retail probablemente no cobran igual, y ese sesgo tendria la misma forma
que el del tamano.

Ademas D-014 dice textualmente que *"el sector entra como segundo eje del arquetipo"*, con
13,2% de reduccion de sd dentro de las etiquetas anchas y placebo de 0,9%. Esa decision
puso como condicion medirlo FUERA DE MUESTRA, `07` lo hizo para la banda y lo desmiente, y
para el centro sigue sin comprobarse. Este script cierra las dos puntas.

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
PRIMARIA:   pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste pareado
            sobre empresas apartadas, restringido a los votos donde la correccion ACTUA.

SE ADOPTA si y solo si:
    1. el IC 95% de la diferencia pareada queda ENTERO por debajo de cero
    2. el PLACEBO —sector barajado entre empresas— no lo reproduce

SECUNDARIO, se reporta y no decide: el sesgo con signo por sector.

DOS DIFERENCIAS con D-018, y son deliberadas:

  - SIN restriccion de escalon. Con el tamano el sesgo seguia al nivel y por eso se limito
    a >= 4. Con el sector no hay razon medida para esperar ese patron, asi que se deja
    entrar cualquier cargo y que la parte A diga si hay que estrechar.
  - 19 sectores contra 4 segmentos, o sea celdas mucho mas finas. Se exige el mismo minimo
    de 10 empresas, y se reporta a cuantas celdas les alcanza.

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
MIN_EMP_GRUPO = 10
N_REPLICAS = 300


def pinball(y, lo, hi):
    a = np.maximum(0.25 * (y - lo), -0.75 * (y - lo))
    b = np.maximum(0.75 * (y - hi), -0.25 * (y - hi))
    return (a + b) / 2.0


def ajustes(tr, colc, colg, celdas, tau2_c, sigma2_c, min_emp=MIN_EMP_GRUPO):
    """Desplazamiento en log de cada (celda, grupo). Mismo estimador que `_ajuste_segmento`
    pero sobre una columna cualquiera, para poder probar el sector sin tocar el producto."""
    idx = {c: i for i, c in enumerate(celdas)}
    d = tr[[colc, "empresa_ruc", colg, "y"]].dropna(subset=["y"])
    v = (d.groupby([colc, "empresa_ruc"], sort=False)
          .agg(voto=("y", "median"), n=("y", "size"), g=(colg, "first")).reset_index())
    c = v[colc].astype(str).map(idx)
    ok = c.notna()
    v, c = v[ok], c[ok].astype(int)
    t2 = np.asarray(tau2_c)[c.to_numpy()]
    s2 = np.asarray(sigma2_c)[c.to_numpy()]
    den = t2 + s2 / v["n"].to_numpy(float)
    v = v.assign(w=np.where(den > 0, 1.0 / np.where(den > 0, den, 1.0), 1.0))

    def med(g):
        g = g.sort_values("voto")
        w = g["w"].to_numpy(float)
        return float(np.interp(0.5, (np.cumsum(w) - 0.5 * w) / w.sum(),
                               g["voto"].to_numpy(float)))

    fuera = {}
    for cargo, g in v.groupby(colc, sort=False):
        if len(g) < 2:
            continue
        base = med(g)
        for grp, gs in g.groupby("g", sort=False):
            if len(gs) >= min_emp:
                off = med(gs) - base
                if off:
                    fuera[(str(cargo), str(grp))] = off
    return fuera


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    mk = mk.copy()
    mk["cargo_norm"] = mk.cargo_norm.astype(str)
    mk["_sec"] = mk["ciiu_n1"].astype(str).fillna("NA")
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train.empresa_ruc.isin(val)].copy()
    ts = train[train.empresa_ruc.isin(val)].copy()
    print(f"construir {tr.empresa_ruc.nunique():,} empresas   "
          f"evaluar {ts.empresa_ruc.nunique():,}   sectores: {tr._sec.nunique()}")

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

    off = ajustes(tr, "cargo_norm", "_sec", b.celdas, b.tau2_c, b.sigma2_c)
    cargos_con = {c for c, _ in off}
    print(f"\ncorrecciones (cargo x sector) con {MIN_EMP_GRUPO}+ empresas: {len(off):,}")
    print(f"cargos con al menos una: {len(cargos_con):,} de {len(b.celdas):,}")

    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc"], sort=False)
           .agg(voto=("y", "median"), sec=("_sec", "first")).reset_index())
    rp = np.random.default_rng(99)
    v["sec_plac"] = rp.permutation(v["sec"].to_numpy())
    v["nivel"] = v.cargo_norm.map(lambda c: nivel_lexico(c) or np.nan)

    ref = b.referenciar(sorted(set(v.cargo_norm)), emb).set_index("cargo")
    base = {c: ref[c].reindex(v.cargo_norm).to_numpy(float)
            for c in ("referencia_log", "p25_log", "p75_log")}

    def con(colg):
        a = np.array([off.get((c, g), 0.0)
                      for c, g in zip(v.cargo_norm, v[colg])], dtype=float)
        return {k: base[k] + a for k in base}, a

    real, a_real = con("sec")
    plac, a_plac = con("sec_plac")
    y = v["voto"].to_numpy(float)
    ok = (a_real != 0) & np.isfinite(y) & np.isfinite(base["p25_log"])
    print(f"votos donde la correccion actua: {int(ok.sum()):,} de {len(v):,} "
          f"({ok.sum()/len(v):.1%})")

    print("\n" + "=" * 78)
    print("A. .HAY SESGO POR SECTOR EN LA REFERENCIA DE HOY?")
    print("=" * 78)
    print(f"  {'sector':<30} {'votos':>7} {'sesgo hoy':>11} {'con sector':>12}")
    sec = v["sec"].to_numpy(object)
    vals_a, vals_c = [], []
    for g in sorted(set(sec[ok])):
        sel = ok & (sec == g)
        if sel.sum() < 30:
            continue
        sa = float(np.mean(y[sel] - base["referencia_log"][sel]))
        sc = float(np.mean(y[sel] - real["referencia_log"][sel]))
        vals_a.append(np.exp(sa) - 1)
        vals_c.append(np.exp(sc) - 1)
        print(f"  {g[:29]:<30} {int(sel.sum()):>7,} {np.exp(sa)-1:>+10.1%} "
              f"{np.exp(sc)-1:>+11.1%}")
    if len(vals_a) > 1:
        print(f"  {'RECORRIDO':<30} {'':>7} {max(vals_a)-min(vals_a):>10.1%} "
              f"{max(vals_c)-min(vals_c):>11.1%}")

    print("\n" + "=" * 78)
    print("B. PRIMARIA: pinball sobre los votos corregibles")
    print("=" * 78)
    print(f"  {'variante':<16} {'PINBALL':>9} {'|sesgo|':>9} {'cob 50%':>9}")
    for nom, c in (("sin sector", base), ("con sector", real), ("PLACEBO", plac)):
        pb = pinball(y[ok], c["p25_log"][ok], c["p75_log"][ok]).mean()
        sg = float(np.mean(y[ok] - c["referencia_log"][ok]))
        cb = float(((y[ok] >= c["p25_log"][ok]) & (y[ok] <= c["p75_log"][ok])).mean())
        print(f"  {nom:<16} {pb:>9.4f} {abs(np.exp(sg)-1):>8.1%} {cb:>8.1%}")

    print(f"\n  contraste pareado ({N_REPLICAS} replicas de empresas apartadas)")
    emp = v.empresa_ruc.to_numpy()
    unicas = np.array(sorted(set(emp[ok])))
    pos = {e: np.flatnonzero((emp == e) & ok) for e in unicas}
    rb = np.random.default_rng(13)
    idxs = [i for i in (np.concatenate([pos[e] for e in rb.choice(unicas, len(unicas))])
                        for _ in range(N_REPLICAS)) if len(i) >= 50]
    for nom, c in (("con sector", real), ("PLACEBO", plac)):
        d = np.array([float(pinball(y[i], c["p25_log"][i], c["p75_log"][i]).mean())
                      - float(pinball(y[i], base["p25_log"][i], base["p75_log"][i]).mean())
                      for i in idxs])
        lo, hi = np.quantile(d, [.025, .975])
        vv = "MEJORA" if hi < 0 else ("sin efecto" if lo < 0 < hi else "EMPEORA")
        print(f"    {nom:<14} - sin sector = {d.mean():+.5f}  "
              f"IC 95% [{lo:+.5f}, {hi:+.5f}]  {vv}")

    print("\n" + "=" * 78)
    print("C. .DONDE ESTA EL SESGO? por escalon, para ver si hay que estrechar")
    print("=" * 78)
    niv = v["nivel"].to_numpy(float)
    print(f"  {'nivel':<10} {'votos':>7} {'recorrido hoy':>15} {'con sector':>12}")
    for k in (1, 2, 3, 4, 5):
        sel = ok & (niv == k)
        if sel.sum() < 60:
            continue
        va, vc = [], []
        for g in sorted(set(sec[sel])):
            s2 = sel & (sec == g)
            if s2.sum() >= 20:
                va.append(np.exp(np.mean(y[s2] - base["referencia_log"][s2])) - 1)
                vc.append(np.exp(np.mean(y[s2] - real["referencia_log"][s2])) - 1)
        if len(va) > 1:
            print(f"  {k:<10} {int(sel.sum()):>7,} {max(va)-min(va):>14.1%} "
                  f"{max(vc)-min(vc):>11.1%}")


if __name__ == "__main__":
    main()
