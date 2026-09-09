""".Vale la pena la segunda pasada de fusion por errata (D-025)?

QUE SE AFIRMA. Que absorber el grupo-dedazo dentro del grupo comun sube la COBERTURA
DIRECTA —su gente pasa de contestarse por analogia a tener datos propios— sin estropear
la respuesta. Es la misma forma de ganancia que D-015: alli la precision salio neutra
rozando la mejora y lo que subio fue la cobertura, del 57,7% al 64,1%.

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
Y AQUI ME APARTO DEL GUION HABITUAL, a proposito. Los experimentos 15, 16 y 17 declararon
pinball como primaria porque median cambios en el ESTIMADOR. Este no cambia el estimador:
cambia a QUE CELDA pertenece un titulo. Declarar pinball como primaria seria medir algo
que no esperamos que se mueva, y despues interpretar su ruido.

PRIMARIA:  cobertura directa —fraccion de PERSONAS de empresas apartadas contestadas con
           datos de su propia celda— sobre los titulos que la absorcion toca.

GUARDARRAIL, y es el que puede tumbar la decision: pinball medio en q=0,25 y q=0,75 sobre
           la banda de EMPRESAS, contraste pareado sobre empresas apartadas, restringido a
           los votos donde la absorcion actua.

SE ADOPTA si y solo si:
    1. la cobertura directa SUBE sobre los titulos afectados
    2. el guardarrail NO empeora: el IC 95% de la diferencia pareada no queda entero por
       encima de cero
    3. el PLACEBO SI empeora el guardarrail

EL PLACEBO ES LA PIEZA QUE DISCRIMINA. La cobertura sube por construccion en cualquier
absorcion, real o barajada — asi que la cobertura sola no prueba nada. El placebo absorbe
los MISMOS grupos raros hacia destinos AL AZAR: si la distancia de edicion esta acertando,
el real debe dejar el pinball donde estaba y el placebo debe estropearlo. Si los dos lo
dejan igual, es que da lo mismo donde caiga la gente y la regla no esta aportando.

TRES BASES, construidas en serie y liberadas: sin erratas / con erratas / placebo. Se
construyen enteras porque cambiar los grupos cambia todos los estadisticos.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import gc

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import (MIN_EMPRESAS, MIN_PERSONAS,
                                                   BaseReferencia)

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
    cols = [c for c in ("cargo_norm", "empresa_ruc", "y", "segmento", "ciiu_n1")
            if c in mk.columns]
    mk = mk[cols].copy()
    mk["cargo_norm"] = mk.cargo_norm.astype(str)
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    en_val = train.empresa_ruc.isin(val)
    tr = train[~en_val].copy()
    ts = train[en_val][["cargo_norm", "empresa_ruc", "y"]].copy()
    del mk, train, en_val
    gc.collect()
    print(f"construir {tr.empresa_ruc.nunique():,} empresas   "
          f"evaluar {ts.empresa_ruc.nunique():,}")

    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    X = embeddings.embeber(etiquetas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    emb = dict(zip(etiquetas, X))

    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc"], sort=False)["y"]
           .median().rename("voto").reset_index())
    n_per = (ts.dropna(subset=["y"]).groupby("cargo_norm").size()
               .reindex(sorted(set(v.cargo_norm))).fillna(0))
    titulos = sorted(set(v.cargo_norm))
    print(f"votos de empresas apartadas: {len(v):,} sobre {len(titulos):,} titulos")

    def construir(**kw):
        b = BaseReferencia.construir(tr, emb, s.get_sbu, **kw)
        r = b.referenciar(titulos, emb).set_index("cargo")
        g = dict(zip(b.celdas, b.grupo))
        del b
        gc.collect()
        return r, g

    print("\n[1/3] base SIN erratas...")
    ref_sin, gru_sin = construir(erratas=False)
    print("[2/3] base CON erratas...")
    ref_con, gru_con = construir(erratas=True)

    # que titulos toca la absorcion
    tocados = {t for t in titulos
               if t in gru_sin and gru_sin[t] != gru_con.get(t, gru_sin[t])}
    print(f"\ntitulos que la absorcion mueve de grupo: {len(tocados):,}")
    if len(tocados) < 20:
        print("MUY POCOS titulos afectados en las empresas apartadas: no concluyente.")
        return

    # PLACEBO: los mismos grupos raros, destinos al azar entre los comunes
    cambios = {gru_sin[t]: gru_con[t] for t in tocados if t in gru_sin}
    comunes = sorted(set(gru_sin.values()) - set(cambios))
    rp = np.random.default_rng(99)
    mapa_plac = {raro: int(rp.choice(comunes)) for raro in cambios}
    print(f"[3/3] base PLACEBO ({len(mapa_plac):,} absorciones al azar)...")
    ref_pla, _ = construir(mapa_erratas=mapa_plac)

    print("\n" + "=" * 78)
    print("A. PRIMARIA: cobertura directa sobre los titulos afectados")
    print("=" * 78)
    print(f"  {'variante':<16} {'directa':>9} {'personas':>10} {'empresas detras':>17}")
    for nom, r in (("sin erratas", ref_sin), ("con erratas", ref_con)):
        sub = r.reindex(sorted(tocados))
        d = (sub["base"] == "datos directos")
        gente = int(n_per.reindex(sorted(tocados)).fillna(0)[d.to_numpy()].sum())
        print(f"  {nom:<16} {d.mean():>8.1%} {gente:>10,} "
              f"{int(sub['empresas'].median()):>17,}")

    print("\n" + "=" * 78)
    print("B. GUARDARRAIL: pinball sobre los votos que la absorcion toca")
    print("=" * 78)
    ok = v.cargo_norm.isin(tocados).to_numpy() & np.isfinite(v["voto"].to_numpy(float))
    col = {}
    for nom, r in (("sin erratas", ref_sin), ("con erratas", ref_con),
                   ("PLACEBO", ref_pla)):
        col[nom] = {c: r[c].reindex(v.cargo_norm).to_numpy(float)
                    for c in ("referencia_log", "p25_log", "p75_log")}
        ok &= np.isfinite(col[nom]["p25_log"]) & np.isfinite(col[nom]["p75_log"])
    y = v["voto"].to_numpy(float)
    print(f"  votos utilizables: {int(ok.sum()):,}")
    print(f"\n  {'variante':<16} {'PINBALL':>9} {'|sesgo|':>9} {'cob 50%':>9}")
    for nom, c in col.items():
        pb = pinball(y[ok], c["p25_log"][ok], c["p75_log"][ok]).mean()
        sg = float(np.mean(y[ok] - c["referencia_log"][ok]))
        cb = float(((y[ok] >= c["p25_log"][ok]) & (y[ok] <= c["p75_log"][ok])).mean())
        print(f"  {nom:<16} {pb:>9.4f} {abs(np.exp(sg) - 1):>8.1%} {cb:>8.1%}")

    emp = v.empresa_ruc.to_numpy()
    unicas = np.array(sorted(set(emp[ok])))
    pos = {e: np.flatnonzero((emp == e) & ok) for e in unicas}
    rb = np.random.default_rng(13)
    idxs = [i for i in (np.concatenate([pos[e] for e in rb.choice(unicas, len(unicas))])
                        for _ in range(N_REPLICAS)) if len(i) >= 30]
    g0 = col["sin erratas"]
    print(f"\n  contraste pareado ({len(idxs)} replicas)")
    for nom in ("con erratas", "PLACEBO"):
        c = col[nom]
        d = np.array([float(pinball(y[i], c["p25_log"][i], c["p75_log"][i]).mean())
                      - float(pinball(y[i], g0["p25_log"][i], g0["p75_log"][i]).mean())
                      for i in idxs])
        lo, hi = np.quantile(d, [.025, .975])
        vv = "MEJORA" if hi < 0 else ("sin efecto" if lo < 0 < hi else "EMPEORA")
        print(f"    {nom:<14} - sin erratas = {d.mean():+.5f}  "
              f"IC 95% [{lo:+.5f}, {hi:+.5f}]  {vv}")


if __name__ == "__main__":
    main()
