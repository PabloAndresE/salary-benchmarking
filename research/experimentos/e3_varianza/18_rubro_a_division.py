""".A que nivel de CIIU debe armarse la banda sectorial: seccion o division?

EL HUECO. Hoy el rubro es la SECCION (`ciiu_n1`, una letra, 18 valores). Eso mete en la
misma bolsa a una libreria y a un concesionario: los dos son `G`, cuyo nombre oficial es
"comercio al por mayor y al por menor; reparacion de vehiculos". Un cliente lee eso y con
razon no se reconoce.

La DIVISION (`ciiu_n6[:3]`, letra + 2 digitos, 79 valores) separa `G46` mayorista de `G47`
minorista de `G45` vehiculos. Es 4,4x mas especifica. El coste, contado sobre gente:

    seccion    18 rubros    34,3% de la gente con banda sectorial   17 empresas/celda
    division   79 rubros    21,9%                                   15
    grupo     199 rubros    13,4%                                   14
    clase     314 rubros    11,1%                                   13

Pero NO hay que elegir. Toda celda que pasa el suelo en division lo pasa tambien en
seccion —la seccion agrupa divisiones, luego tiene mas empresas por construccion—, asi
que division-que-pasa es un SUBCONJUNTO de seccion-que-pasa. Una CASCADA division ->
seccion -> mercado da la misma cobertura de hoy (34,3%) con dos tercios de ella
especifica. Sobre el papel es gratis. Esto lo mide.

POR QUE LA BARRA NO ES "QUE MEJORE". D-023 ya midio que el rubro a nivel seccion NO mejora
la precision: esta montado por legitimidad. Si el valor de la cascada tambien es
legitimidad, exigirle que mejore seria pedirle algo que la version actual tampoco cumple.
La barra correcta es NO EMPEORAR, y para que eso signifique algo hay que fijar el margen
ANTES, no encogerse de hombros despues si sale casi igual.

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
Metrica: pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste pareado
por empresa apartada (bootstrap sobre empresas, no sobre votos).

PRIMARIA — la decision de producto. Cascada (C) contra lo de hoy (A), sobre TODOS los
votos evaluables. SE ADOPTA LA CASCADA si:

    el limite SUPERIOR del IC 95% de (C - A) queda por debajo de +0,001

o sea, no-inferioridad con margen de 0,001 en unidades de pinball (~0,8% relativo sobre
el nivel de ~0,12 que dan las mediciones anteriores). Si sale por debajo de CERO, mejor:
deja de ser cosmetica.

SECUNDARIA — la pregunta cientifica, y no decide sola. Division (B) contra seccion (A)
restringido a los votos donde LAS DOS dan banda sectorial. Si el IC 95% de (B - A) queda
entero por debajo de cero, la division es de verdad mejor y el argumento sube de
legitimidad a precision.

PLACEBO. Divisiones FALSAS, barajadas entre empresas DENTRO de su misma seccion. Mantiene
el numero de rubros y su tamano y destruye solo el significado. Si el placebo reproduce lo
que salga en la secundaria, lo que se midio no es el sector sino el efecto de partir en
celdas mas chicas.

SE REPORTA Y NO DECIDE: cobertura de cada nivel, y cuantos votos cambian de banda.

TODO SOBRE TRAIN. El 20% de test no se toca.
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
N_REPLICAS = 400
MARGEN = 0.001          # no-inferioridad, declarado arriba


def pinball(y, lo, hi):
    a = np.maximum(0.25 * (y - lo), -0.75 * (y - lo))
    b = np.maximum(0.75 * (y - hi), -0.25 * (y - hi))
    return (a + b) / 2.0


def bandas_por_rubro(base, emb, votos, col_rubro):
    """p25/p75 de cada voto pidiendo SU rubro, y si de verdad se uso el sectorial.

    `referenciar` toma UN rubro por llamada, asi que se agrupa por rubro: 18 llamadas con
    seccion, 79 con division. Dentro de cada una va vectorizado.
    """
    p25 = np.full(len(votos), np.nan)
    p75 = np.full(len(votos), np.nan)
    uso = np.zeros(len(votos), dtype=bool)
    for r, g in votos.groupby(col_rubro, sort=False):
        cargos = sorted(set(g["cargo_norm"]))
        if not cargos:
            continue
        out = base.referenciar(cargos, emb, rubro=str(r)).set_index("cargo")
        p25[g.index] = out["p25_log"].reindex(g["cargo_norm"]).to_numpy(float)
        p75[g.index] = out["p75_log"].reindex(g["cargo_norm"]).to_numpy(float)
        # `rubro` en la salida trae el que se USO, vacio si cayo al mercado entero
        usado = out["rubro"].reindex(g["cargo_norm"]).astype(str).to_numpy()
        uso[g.index] = usado != ""
    return p25, p75, uso


def ic_pareado(dif_por_empresa, rng, n=N_REPLICAS):
    """IC 95% de la diferencia media, remuestreando EMPRESAS.

    Por empresa y no por voto: los votos de una misma empresa comparten su nivel de pago
    y tratarlos como independientes estrecha el intervalo sin derecho.
    """
    e = np.array(sorted(dif_por_empresa))
    medias = np.array([np.mean([dif_por_empresa[k]
                                for k in rng.choice(e, len(e), replace=True)])
                       for _ in range(n)])
    return float(np.mean(list(dif_por_empresa.values()))), \
        float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))


def por_empresa(dif, empresas):
    d = pd.DataFrame({"e": empresas, "d": dif}).dropna()
    return d.groupby("e")["d"].mean().to_dict()


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    mk = mk[[c for c in ("cargo_norm", "empresa_ruc", "y", "segmento", "ciiu_n1",
                         "ciiu_n6") if c in mk.columns]].copy()
    mk["cargo_norm"] = mk.cargo_norm.astype(str)
    mk["_sec"] = mk["ciiu_n1"].astype(str)
    mk["_div"] = mk["ciiu_n6"].astype(str).str[:3]
    mk.loc[~mk["_div"].str.match(r"^[A-Za-z]\d\d$"), "_div"] = ""

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
    print(f"construir {tr.empresa_ruc.nunique():,} empresas   "
          f"evaluar {ts.empresa_ruc.nunique():,}")
    print(f"secciones {tr._sec.nunique()}   divisiones {tr[tr._div != ''] ._div.nunique()}")

    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print(f"embebiendo {len(etiquetas):,} titulos...")
    X = embeddings.embeber(etiquetas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    emb = dict(zip(etiquetas, X))

    # DOS BASES QUE SOLO SE DIFERENCIAN EN EL NIVEL DEL RUBRO. `COL_RUBRO` lee la columna
    # `ciiu_n1`, asi que se le da la division por ese nombre en vez de tocar el producto.
    print("\nbase A: rubro = SECCION ...")
    trA = tr.copy()
    trA["ciiu_n1"] = trA["_sec"]
    bA = BaseReferencia.construir(trA, emb, s.get_sbu)
    del trA
    gc.collect()

    print("\nbase B: rubro = DIVISION ...")
    trB = tr.copy()
    trB["ciiu_n1"] = trB["_div"].replace("", np.nan)
    bB = BaseReferencia.construir(trB, emb, s.get_sbu)
    del trB, tr
    gc.collect()

    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc"], sort=False)
           .agg(voto=("y", "median"), sec=("_sec", "first"),
                div=("_div", "first")).reset_index())
    v = v[v["div"] != ""].reset_index(drop=True)
    del ts
    gc.collect()
    print(f"\nvotos apartados evaluables: {len(v):,} "
          f"sobre {v.empresa_ruc.nunique():,} empresas")

    # Placebo: division falsa, barajada DENTRO de la seccion. Mismo numero de rubros y
    # mismos tamanos; lo unico que se rompe es el significado.
    rp = np.random.default_rng(99)
    v["div_plac"] = (v.groupby("sec")["div"]
                      .transform(lambda x: rp.permutation(x.to_numpy())))

    print("\nreferenciando...")
    p25A, p75A, usoA = bandas_por_rubro(bA, emb, v, "sec")
    p25B, p75B, usoB = bandas_por_rubro(bB, emb, v, "div")
    p25P, p75P, usoP = bandas_por_rubro(bB, emb, v, "div_plac")

    y = v["voto"].to_numpy(float)
    ok = np.isfinite(y) & np.isfinite(p25A) & np.isfinite(p25B)
    print(f"votos con banda en las dos bases: {int(ok.sum()):,}")

    # CASCADA: la division cuando la hay, y si no la seccion.
    p25C = np.where(usoB, p25B, p25A)
    p75C = np.where(usoB, p75B, p75A)

    lA, lB, lC = (pinball(y, p25A, p75A), pinball(y, p25B, p75B),
                  pinball(y, p25C, p75C))
    lP = pinball(y, p25P, p75P)

    print("\n" + "=" * 78)
    print("COBERTURA (votos con banda SECTORIAL, no del mercado entero)")
    print("=" * 78)
    n = int(ok.sum())
    print(f"  seccion  (hoy) : {int((usoA & ok).sum()):>7,}  ({(usoA & ok).sum()/n:6.1%})")
    print(f"  division       : {int((usoB & ok).sum()):>7,}  ({(usoB & ok).sum()/n:6.1%})")
    print(f"  cascada        : {int((usoA & ok).sum()):>7,}  (igual que seccion, por "
          f"construccion)")
    print(f"  ...de esos, con division: {int((usoB & ok).sum()/max((usoA&ok).sum(),1)*100)}%")
    print(f"  votos que CAMBIAN de banda con la cascada: "
          f"{int((usoB & ok).sum()):,}")

    rngb = np.random.default_rng(7)
    print("\n" + "=" * 78)
    print(f"PRIMARIA  cascada - hoy, sobre TODOS los votos evaluables")
    print("=" * 78)
    d = por_empresa((lC - lA)[ok], v["empresa_ruc"].to_numpy()[ok])
    m, lo, hi = ic_pareado(d, rngb)
    print(f"  pinball hoy     {np.mean(lA[ok]):.5f}")
    print(f"  pinball cascada {np.mean(lC[ok]):.5f}")
    print(f"  diferencia      {m:+.5f}   IC95 [{lo:+.5f}, {hi:+.5f}]")
    print(f"  CRITERIO: se adopta si el limite superior < {MARGEN:+.5f}")
    veredicto = ("SE ADOPTA" if hi < MARGEN else "NO se adopta")
    if hi < 0:
        veredicto += " (y ademas MEJORA: el IC entero bajo cero)"
    print(f"  VEREDICTO: {veredicto}")

    print("\n" + "=" * 78)
    print("SECUNDARIA  division - seccion, donde LAS DOS dan banda sectorial")
    print("=" * 78)
    amb = ok & usoA & usoB
    print(f"  votos en la interseccion: {int(amb.sum()):,}")
    if amb.sum() > 30:
        d2 = por_empresa((lB - lA)[amb], v["empresa_ruc"].to_numpy()[amb])
        m2, lo2, hi2 = ic_pareado(d2, rngb)
        print(f"  pinball seccion  {np.mean(lA[amb]):.5f}")
        print(f"  pinball division {np.mean(lB[amb]):.5f}")
        print(f"  diferencia       {m2:+.5f}   IC95 [{lo2:+.5f}, {hi2:+.5f}]")
        print(f"  -> {'la division es MEJOR' if hi2 < 0 else
                       'la division es PEOR' if lo2 > 0 else
                       'sin diferencia demostrada'}")

        print("\n  PLACEBO  divisiones barajadas dentro de la seccion")
        ap = ok & usoA & usoP
        d3 = por_empresa((lP - lA)[ap], v["empresa_ruc"].to_numpy()[ap])
        m3, lo3, hi3 = ic_pareado(d3, rngb)
        print(f"  votos: {int(ap.sum()):,}")
        print(f"  diferencia       {m3:+.5f}   IC95 [{lo3:+.5f}, {hi3:+.5f}]")
        # El placebo aqui no es "reproduce o no": los dos degradan. Lo que importa es
        # CUANTO de la degradacion es mecanica —partir en celdas mas chicas— y cuanto
        # se recupera porque la division significa algo.
        print(f"  degradacion del placebo  {m3:+.5f}  (celdas mas chicas, sin sentido)")
        print(f"  degradacion de la real   {m2:+.5f}")
        print(f"  -> el sector REAL recupera {100*(m3-m2)/m3:.0f}% del coste de partir, "
              f"pero {'no todo: la seccion sigue ganando' if m2 > 0 else 'y lo supera'}")

    pd.DataFrame({"empresa": v["empresa_ruc"], "cargo": v["cargo_norm"],
                  "sec": v["sec"], "div": v["div"], "ok": ok,
                  # `usoP` tambien: sin el, el contraste del placebo no se puede
                  # rehacer desde el parquet y hay que volver a correr dos horas.
                  "usoA": usoA, "usoB": usoB, "usoP": usoP,
                  "lA": lA, "lB": lB, "lC": lC, "lP": lP}
                 ).to_parquet("research/experimentos/e3_varianza/salidas/"
                              "18_rubro_a_division.parquet")
    print("\nvotos guardados en salidas/18_rubro_a_division.parquet")


if __name__ == "__main__":
    main()
