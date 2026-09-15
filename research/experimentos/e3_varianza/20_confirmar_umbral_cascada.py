"""CONFIRMACION: la cascada con umbral de fiabilidad, en datos que no la eligieron.

QUE SE CONFIRMA Y POR QUE HACE FALTA. En `19` la cascada con el suelo de 10 empresas
perdio (+0,00094, IC [+0,00048, +0,00146]). Despues barri NUEVE umbrales sobre ESOS
MISMOS votos y encontre que a partir de 20-30 empresas la perdida desaparece:

    T=10  +0,00094 [+0,00048,+0,00146]  peor
    T=15  +0,00034 [+0,00002,+0,00076]  peor
    T=20  +0,00011 [-0,00013,+0,00040]  nulo
    T=30  +0,00007 [-0,00004,+0,00018]  nulo
    T=40  -0,00001 [-0,00010,+0,00006]  nulo

Elegir el umbral mirando el resultado es ajustar a ruido. Da igual lo razonable que suene
la historia —"el suelo de 10 es de confidencialidad, no de fiabilidad"—: nueve miradas a
los mismos datos producen un ganador aunque no haya nada que ganar. Por eso esto corre
sobre una PARTICION DISTINTA, elegida con otra semilla, y la decision se toma con lo que
salga aqui y no con la tabla de arriba.

EL 20% DE TEST NO SE TOCA. La particion nueva se saca de train, igual que las demas.

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
PRIMARIA — se confirma EXACTAMENTE lo propuesto: cascada clase->grupo->division->seccion
bajando solo a un nivel con >= 30 empresas. Contra lo de hoy (seccion siempre), pinball
q=0,25 y q=0,75 sobre la banda de empresas, pareado por empresa apartada.

SE ADOPTA si el limite SUPERIOR del IC 95% queda por debajo de +0,0002.

Es no-inferioridad, y el margen sale del propio resultado exploratorio: alli el limite
superior a T=30 fue +0,00018. O sea que se le pide REPLICAR ese orden de magnitud, no
"salir parecido". Si el efecto real fuera el +0,00094 del suelo de 10, este test lo
rechaza sin dudar. En unidades de producto, +0,0002 es un 0,14% del pinball.

SECUNDARIA, se reporta y NO decide:
  - el umbral sobre la INCERTIDUMBRE en vez de sobre el conteo. `1/W` es lo que de verdad
    mide "este centro se conoce bien", y 30 empresas no valen lo mismo en `AUXILIAR DE
    LIMPIEZA` que en `GERENTE GENERAL`, donde los sueldos van de $500 a $13.000. Regla
    relativa: se baja si `1/W_fino <= k * 1/W_seccion`, o sea si el centro fino no es mas
    de k veces menos cierto que el que se usaria si no. Se reportan varias k.
  - cobertura, veredictos que cambian, y a que nivel acaba cada voto.

SI LA PRIMARIA FALLA, no se monta y punto. La secundaria no la rescata: se eligio
despues de ver los datos y tendria que confirmarse a su vez.
"""
import gc

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import NIVELES_RUBRO, BaseReferencia

# SEMILLA DISTINTA de la de `18` y `19` (20260805). Es lo que hace que esto sea una
# confirmacion y no una relectura.
SEM = 20260915
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 500
T_CONFIRMAR = 30            # el umbral propuesto, declarado arriba
MARGEN = 0.0002             # no-inferioridad, declarado arriba
KS = (1.0, 1.5, 2.0, 3.0, 5.0)     # secundaria: umbral relativo sobre 1/W


def pinball(y, lo, hi):
    a = np.maximum(0.25 * (y - lo), -0.75 * (y - lo))
    b = np.maximum(0.75 * (y - hi), -0.25 * (y - hi))
    return (a + b) / 2.0


def ic(dif, empresas, rng, n=N_REPLICAS):
    g = pd.DataFrame({"e": empresas, "d": dif}).dropna().groupby("e")["d"].mean()
    if len(g) < 5:
        return np.nan, np.nan, np.nan
    e = g.index.to_numpy()
    b = [g[rng.choice(e, len(e), replace=True)].mean() for _ in range(n)]
    return float(g.mean()), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def elegir_nivel(base, celdas_idx, c6, regla):
    """El codigo de rubro que la cascada elige para cada voto, y a que nivel.

    `regla(fr_fino, fr_seccion) -> bool` decide si el nivel fino es aceptable. Asi la
    misma cascada sirve para el umbral por conteo y para el de incertidumbre sin
    duplicar el recorrido.
    """
    cods, nivs = [], []
    for i, c in zip(celdas_idx, c6):
        sec = str(c)[:1]
        fr_s = base.rub.get((int(i), sec)) if i is not None else None
        elegido, nivel = sec, "seccion"
        if i is not None and str(c):
            for k in NIVELES_RUBRO:
                if k == 1 or k >= len(str(c)):
                    continue
                fr = base.rub.get((int(i), str(c)[:k]))
                if fr is not None and regla(fr, fr_s):
                    elegido, nivel = str(c)[:k], {5: "clase", 4: "grupo",
                                                  3: "division"}[k]
                    break
        cods.append(elegido)
        nivs.append(nivel)
    return np.array(cods, dtype=object), np.array(nivs, dtype=object)


def bandas_de(base, emb, votos, cods):
    n = len(votos)
    p25, p75 = np.full(n, np.nan), np.full(n, np.nan)
    v = votos.assign(_cod=cods)
    for r, g in v.groupby("_cod", sort=False):
        if not str(r):
            continue
        cargos = sorted(set(g["cargo_norm"]))
        out = base.referenciar(cargos, emb, rubro=str(r)).set_index("cargo")
        p25[g.index] = out["p25_log"].reindex(g["cargo_norm"]).to_numpy(float)
        p75[g.index] = out["p75_log"].reindex(g["cargo_norm"]).to_numpy(float)
    return p25, p75


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    mk = mk[[c for c in ("cargo_norm", "empresa_ruc", "y", "segmento", "ciiu_n1",
                         "ciiu_n6") if c in mk.columns]].copy()
    mk["cargo_norm"] = mk.cargo_norm.astype(str)
    mk["_c6"] = mk["ciiu_n6"].astype(str)
    mk.loc[~mk["_c6"].str.match(r"^[A-Za-z]\d{3}"), "_c6"] = ""

    train, _ = splits.partir(mk, splits.empresas_test(mk))
    del mk
    gc.collect()
    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train.empresa_ruc.isin(val)].copy()
    ts = train[train.empresa_ruc.isin(val)].copy()
    del train
    gc.collect()
    print(f"PARTICION NUEVA (semilla {SEM}, distinta de la de 18 y 19)")
    print(f"construir {tr.empresa_ruc.nunique():,}   evaluar {ts.empresa_ruc.nunique():,}")

    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print(f"embebiendo {len(etiquetas):,} titulos...")
    X = embeddings.embeber(etiquetas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    emb = dict(zip(etiquetas, X))
    print("construyendo la base (ya guarda los cuatro niveles)...")
    b = BaseReferencia.construir(tr, emb, s.get_sbu)
    del tr
    gc.collect()

    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc"], sort=False)
           .agg(voto=("y", "median"), c6=("_c6", "first")).reset_index())
    v = v[v["c6"] != ""].reset_index(drop=True)
    del ts
    gc.collect()
    idx = [b.idx.get(c) for c in v["cargo_norm"]]
    y = v["voto"].to_numpy(float)
    emps = v["empresa_ruc"].to_numpy()
    print(f"votos apartados: {len(v):,} sobre {v.empresa_ruc.nunique():,} empresas")

    # HOY: seccion siempre
    cods_sec = np.array([str(c)[:1] for c in v["c6"]], dtype=object)
    p25A, p75A = bandas_de(b, emb, v, cods_sec)
    lA = pinball(y, p25A, p75A)
    fin = np.isfinite(y) & np.isfinite(p25A)
    rb = np.random.default_rng(11)

    print("\n" + "=" * 78)
    print(f"PRIMARIA  cascada con T>={T_CONFIRMAR} empresas, contra hoy")
    print("=" * 78)
    cods, nivs = elegir_nivel(b, idx, v["c6"],
                              lambda fr, frs: int(b.rub_emp[fr]) >= T_CONFIRMAR)
    p25C, p75C = bandas_de(b, emb, v, cods)
    lC = pinball(y, p25C, p75C)
    baja = nivs != "seccion"
    m, lo, hi = ic((lC - lA)[fin], emps[fin], rb)
    print(f"  votos que bajan de nivel: {int((baja & fin).sum()):,} "
          f"({(baja & fin).sum()/fin.sum():.1%})")
    print(f"  pinball hoy     {np.mean(lA[fin]):.5f}")
    print(f"  pinball cascada {np.mean(lC[fin]):.5f}")
    print(f"  diferencia      {m:+.5f}   IC95 [{lo:+.5f}, {hi:+.5f}]")
    print(f"  CRITERIO: se adopta si el limite superior < {MARGEN:+.5f}")
    print(f"  VEREDICTO: {'SE CONFIRMA' if hi < MARGEN else 'NO se confirma'}")
    if lo > 0:
        print(f"  (ojo: el IC excluye el cero, o sea que es peor aunque sea poco)")

    lec = lambda yy, a, c: np.where(yy < a, "bajo", np.where(yy > c, "sobre", "dentro"))
    camb = (lec(y, p25A, p75A) != lec(y, p25C, p75C)) & fin
    print(f"  veredictos que cambian: {int(camb.sum()):,} ({camb.sum()/fin.sum():.2%})")
    if camb.sum() > 30:
        m2, l2, h2 = ic((lC - lA)[camb], emps[camb], rb)
        print(f"  ...y en esos, {m2:+.5f} IC [{l2:+.5f},{h2:+.5f}] "
              f"-> {'gana hoy' if l2 > 0 else 'gana la cascada' if h2 < 0 else 'empate'}")

    print("\n" + "=" * 78)
    print("SECUNDARIA (no decide)  umbral sobre la INCERTIDUMBRE 1/W")
    print("=" * 78)
    print(f"{'k':>5} {'bajan':>14} {'diferencia':>12} {'IC95':>24}")
    for k in KS:
        ck, nk = elegir_nivel(
            b, idx, v["c6"],
            lambda fr, frs, k=k: (frs is not None
                                  and 1.0/float(b.rub_W[fr])
                                  <= k * 1.0/float(b.rub_W[frs])))
        p25k, p75k = bandas_de(b, emb, v, ck)
        lk = pinball(y, p25k, p75k)
        bk = (nk != "seccion") & fin
        mk_, lk_, hk_ = ic((lk - lA)[fin], emps[fin], rb)
        print(f"{k:>5.1f} {int(bk.sum()):>8,} ({bk.sum()/fin.sum():>4.1%}) "
              f"{mk_:>+12.5f} [{lk_:+.5f},{hk_:+.5f}]")

    print("\n" + "=" * 78)
    print("SECUNDARIA  el conteo, a varios umbrales (replica de la exploracion)")
    print("=" * 78)
    print(f"{'T':>5} {'bajan':>14} {'diferencia':>12} {'IC95':>24}")
    for T in (10, 15, 20, 25, 30, 40, 60):
        cT, nT = elegir_nivel(b, idx, v["c6"],
                              lambda fr, frs, T=T: int(b.rub_emp[fr]) >= T)
        p25T, p75T = bandas_de(b, emb, v, cT)
        lT = pinball(y, p25T, p75T)
        bT = (nT != "seccion") & fin
        mT, loT, hiT = ic((lT - lA)[fin], emps[fin], rb)
        print(f"{T:>5} {int(bT.sum()):>8,} ({bT.sum()/fin.sum():>4.1%}) "
              f"{mT:>+12.5f} [{loT:+.5f},{hiT:+.5f}]")

    pd.DataFrame({"empresa": emps, "cargo": v.cargo_norm, "c6": v.c6, "fin": fin,
                  "nivel": nivs, "lA": lA, "lC": lC}).to_parquet(
        "research/experimentos/e3_varianza/salidas/20_confirmar_umbral.parquet")
    print("\nguardado en salidas/20_confirmar_umbral.parquet")


if __name__ == "__main__":
    main()
