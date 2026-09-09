"""Cuanto CUESTA fusionar las grafias de genero (D-026).

OJO CON EL VERBO, porque cambia el diseno: esto no mide si conviene fusionar, mide cuanto
cuesta. La decision ya esta tomada y no es estadistica — el titulo es un proxy de genero y
al ser la unidad de agrupamiento el modelo estaba segmentando por genero sin que nadie lo
decidiera. Aunque el pinball empeorara un poco, ese argumento seguiria en pie.

Lo que la medicion SI puede hacer es dos cosas:

  1. ACOTAR EL COSTE, para saber que se esta pagando.
  2. COMPROBAR QUE LA REGLA IDENTIFICA OFICIOS EQUIVALENTES. Si juntar `ENFERMERA` con
     `ENFERMERO` costara lo mismo que juntar dos celdas al azar del mismo tamano, la
     regla no estaria reconociendo el mismo oficio: estaria mezclando. ESE es el
     contraste que decide, y es el que a D-025 le falto.

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
PRIMARIA:  pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste pareado
           sobre empresas apartadas, restringido a los votos donde la fusion actua. Aqui
           pinball SI es la primaria correcta —al reves que en D-025— porque fusionar
           cambia el CENTRO de gente que ya tenia respuesta directa.

DISCRIMINANTE: contraste DIRECTO real contra placebo, no cada uno contra el control.

SE REVISA LA DECISION si:
  a) el IC 95% del coste real queda entero por encima de +0,005 —mas de lo que vale la
     fusion semantica entera (D-015: -0,0030) y la mitad de lo que vale el ajuste de
     nivel (`17`: 0,0106)—, o
  b) el real NO sale claramente mas barato que el placebo, porque entonces la regla no
     esta identificando oficios equivalentes.

Cualquier otro resultado deja la decision donde esta, con el coste anotado.

TRES BASES en serie: sin genero / con genero / placebo. TODO SOBRE TRAIN.
"""
import gc

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import BaseReferencia

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
    titulos = sorted(set(v.cargo_norm))
    print(f"votos de empresas apartadas: {len(v):,} sobre {len(titulos):,} titulos")

    def construir(**kw):
        b = BaseReferencia.construir(tr, emb, s.get_sbu, **kw)
        r = b.referenciar(titulos, emb).set_index("cargo")
        g = dict(zip(b.celdas, b.grupo))
        emp = dict(zip(b.celdas, b.emp))
        del b
        gc.collect()
        return r, g, emp

    print("\n[1/3] base SIN genero...")
    ref_sin, gru_sin, emp_sin = construir(genero=False)
    print("[2/3] base CON genero...")
    ref_con, gru_con, _ = construir(genero=True)

    tocados = {t for t in titulos
               if t in gru_sin and gru_sin[t] != gru_con.get(t, gru_sin[t])}
    print(f"\ntitulos que la fusion mueve de celda: {len(tocados):,}")
    if len(tocados) < 30:
        print("MUY POCOS titulos afectados: no concluyente.")
        return

    # PLACEBO: las mismas uniones, pero entre celdas AL AZAR de tamano parecido. Si
    # costara lo mismo que la real, la regla de genero no estaria reconociendo oficios
    # equivalentes sino mezclando celdas cualesquiera.
    uniones = {}
    for t in tocados:
        uniones.setdefault(gru_con[t], set()).add(gru_sin[t])
    grupos_libres = sorted({g for t, g in gru_sin.items()
                            if g not in {x for ss in uniones.values() for x in ss}})
    tam = {g: 0 for g in grupos_libres}
    for t, g in gru_sin.items():
        if g in tam:
            tam[g] = max(tam[g], int(emp_sin.get(t, 0)))
    rp = np.random.default_rng(99)
    mapa_plac, usados = {}, set()
    for dest, subs in uniones.items():
        subs = sorted(subs)
        if len(subs) < 2:
            continue
        # cada subgrupo real se une a uno al azar de tamano comparable
        for sg in subs[1:]:
            objetivo = tam.get(subs[0], 1)
            cands = [g for g in grupos_libres
                     if g not in usados and 0.5 * objetivo <= tam[g] <= 2 * objetivo]
            if not cands:
                cands = [g for g in grupos_libres if g not in usados]
            if not cands:
                break
            elegido = int(rp.choice(cands))
            usados.add(elegido)
            mapa_plac[sg] = elegido
    print(f"[3/3] base PLACEBO ({len(mapa_plac):,} uniones al azar)...")
    ref_pla, _, _ = construir(mapa_genero=mapa_plac)

    y = v["voto"].to_numpy(float)
    ok = v.cargo_norm.isin(tocados).to_numpy() & np.isfinite(y)
    col = {}
    for nom, r in (("sin genero", ref_sin), ("con genero", ref_con),
                   ("PLACEBO", ref_pla)):
        col[nom] = {c: r[c].reindex(v.cargo_norm).to_numpy(float)
                    for c in ("referencia_log", "p25_log", "p75_log")}
        ok &= np.isfinite(col[nom]["p25_log"]) & np.isfinite(col[nom]["p75_log"])
    print(f"\nvotos utilizables: {int(ok.sum()):,}")

    print("\n" + "=" * 78)
    print("PRIMARIA: pinball sobre los votos donde la fusion actua")
    print("=" * 78)
    print(f"  {'variante':<16} {'PINBALL':>9} {'|sesgo|':>9} {'cob 50%':>9} {'ancho':>9}")
    for nom, c in col.items():
        pb = pinball(y[ok], c["p25_log"][ok], c["p75_log"][ok]).mean()
        sg = float(np.mean(y[ok] - c["referencia_log"][ok]))
        cb = float(((y[ok] >= c["p25_log"][ok]) & (y[ok] <= c["p75_log"][ok])).mean())
        an = float(np.mean(np.exp(c["p75_log"][ok] - c["p25_log"][ok]) - 1))
        print(f"  {nom:<16} {pb:>9.4f} {abs(np.exp(sg)-1):>8.1%} {cb:>8.1%} {an:>8.1%}")

    emp = v.empresa_ruc.to_numpy()
    unicas = np.array(sorted(set(emp[ok])))
    pos = {e: np.flatnonzero((emp == e) & ok) for e in unicas}
    rb = np.random.default_rng(13)
    idxs = [i for i in (np.concatenate([pos[e] for e in rb.choice(unicas, len(unicas))])
                        for _ in range(N_REPLICAS)) if len(i) >= 30]
    pb = lambda c, i: float(pinball(y[i], c["p25_log"][i], c["p75_log"][i]).mean())

    print(f"\n  contraste pareado ({len(idxs)} replicas)")
    for nom in ("con genero", "PLACEBO"):
        d = np.array([pb(col[nom], i) - pb(col["sin genero"], i) for i in idxs])
        lo, hi = np.quantile(d, [.025, .975])
        print(f"    {nom:<12} - sin genero = {d.mean():+.5f}  "
              f"IC 95% [{lo:+.5f}, {hi:+.5f}]")

    print("\n  DISCRIMINANTE: real contra placebo, directo")
    d = np.array([pb(col["con genero"], i) - pb(col["PLACEBO"], i) for i in idxs])
    lo, hi = np.quantile(d, [.025, .975])
    vv = ("el real es MAS BARATO" if hi < 0 else
          "indistinguibles" if lo < 0 < hi else "el real es MAS CARO")
    print(f"    con genero - PLACEBO = {d.mean():+.5f}  "
          f"IC 95% [{lo:+.5f}, {hi:+.5f}]   {vv}")


if __name__ == "__main__":
    main()
