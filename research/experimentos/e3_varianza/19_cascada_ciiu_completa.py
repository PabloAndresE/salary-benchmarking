"""La escalera CIIU entera: clase -> grupo -> division -> seccion -> mercado.

DE DONDE VIENE. `18` midio division contra seccion y la division PIERDE (+0,00269 de
pinball, IC [+0,00079, +0,00462]). El placebo —divisiones falsas barajadas dentro de su
seccion— pierde MAS (+0,00443), asi que el sector real recupera un 39% del coste mecanico
de partir en celdas mas chicas y deja el 61% sin recuperar.

Queda la pregunta que `18` no contesta: .y si en vez de un nivel fijo se baja TODO lo que
se pueda, celda por celda? Una celda con 200 empresas en su clase puede permitirse la
clase; una con 12 en su seccion no puede bajar de ahi. La cascada elige por celda el nivel
mas fino que aguante el suelo, asi que nunca usa una celda mas pobre que la de hoy — solo
mas especifica cuando hay con que.

LA DUDA RAZONABLE, y es la que hace que valga la pena medirlo: `18` comparo la division
contra la seccion EN LOS MISMOS VOTOS, y ahi la division siempre tiene menos empresas. La
cascada no hace eso: solo baja cuando el nivel fino tiene respaldo de sobra. Puede que el
coste de `18` fuera de las celdas que bajaron con lo justo, y que exigiendo lo mismo a
todos los niveles el resultado cambie.

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
LA BARRA SUBE, y a proposito. En `18` la puse en no-inferioridad porque la premisa era
que la cascada salia gratis. Esa premisa esta MEDIDA Y MUERTA: bajar de nivel cuesta
precision. Con un coste conocido, "no empeorar mucho" ya no basta —seria pagar precision
por una etiqueta—, asi que:

SE ADOPTA la cascada si y solo si:
    el IC 95% de (cascada - hoy) queda ENTERO POR DEBAJO DE CERO,
    o sea si de verdad MEJORA, medido sobre todos los votos apartados.

Es la barra que se le exige a cualquier cambio del modelo en este proyecto. Que en `18`
fuera mas laxa era consecuencia de una premisa falsa.

SE REPORTA Y NO DECIDE:
  - cada nivel POR SEPARADO contra la seccion, en la interseccion donde los dos aplican;
  - a que nivel acaba cada voto en la cascada, y con cuantas empresas detras;
  - el placebo de cada nivel: codigos barajados DENTRO del nivel inmediatamente superior,
    que conserva el numero de rubros y su tamano y rompe solo el significado;
  - varios RUCs concretos: que nivel les toca y cuanto se les mueve la referencia. Es la
    parte que se puede enseñar a un cliente, y la que dice si el cambio se NOTA.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import gc

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import (BaseReferencia,
                                                   _bandas_por_rubro)

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 400
# De mas fino a mas grueso. El numero es cuantos caracteres de `ciiu_n6` se toman.
NIVELES = [("clase", 5), ("grupo", 4), ("division", 3), ("seccion", 1)]


def pinball(y, lo, hi):
    a = np.maximum(0.25 * (y - lo), -0.75 * (y - lo))
    b = np.maximum(0.75 * (y - hi), -0.25 * (y - hi))
    return (a + b) / 2.0


def poner_rubro(base, tabla):
    """Cambia la tabla de bandas por rubro de una base ya construida.

    Se calcula con `_bandas_por_rubro`, el MISMO codigo que usa el producto, y se enchufa
    aqui en vez de reconstruir una base por nivel: lo unico que distingue a las cuatro
    variantes es esta tabla —celdas, fusion, tau, sigma y la banda global son identicas—,
    y reconstruir cuatro veces meteria el ruido de cuatro fusiones en una comparacion que
    no va de eso.
    """
    (base.rub_cel, base.rub_cod, base.rub_m, base.rub_W, base.rub_emp,
     base.rub_per, base.rub_bandas, base.rub_bandas_per, rr) = tabla
    base.rubros = list(rr)
    base.rub = {(int(c), base.rubros[int(k)]): i
                for i, (c, k) in enumerate(zip(base.rub_cel, base.rub_cod))}
    return base


def bandas(base, emb, votos, col_rubro):
    """p25/p75 de cada voto pidiendo SU rubro, si se uso el sectorial, y con cuantas
    empresas detras."""
    n = len(votos)
    p25, p75 = np.full(n, np.nan), np.full(n, np.nan)
    uso = np.zeros(n, dtype=bool)
    emp = np.zeros(n, dtype=np.int64)
    for r, g in votos.groupby(col_rubro, sort=False):
        if not str(r):
            continue
        cargos = sorted(set(g["cargo_norm"]))
        out = base.referenciar(cargos, emb, rubro=str(r)).set_index("cargo")
        idx = g["cargo_norm"]
        p25[g.index] = out["p25_log"].reindex(idx).to_numpy(float)
        p75[g.index] = out["p75_log"].reindex(idx).to_numpy(float)
        uso[g.index] = out["rubro"].reindex(idx).astype(str).to_numpy() != ""
        emp[g.index] = out["empresas"].reindex(idx).fillna(0).to_numpy(np.int64)
    return p25, p75, uso, emp


def ic(dif, empresas, rng, n=N_REPLICAS):
    """IC 95% pareado remuestreando EMPRESAS: los votos de una empresa comparten su
    nivel de pago y tratarlos como independientes estrecha el intervalo sin derecho."""
    g = pd.DataFrame({"e": empresas, "d": dif}).dropna().groupby("e")["d"].mean()
    if len(g) < 5:
        return np.nan, np.nan, np.nan
    e = g.index.to_numpy()
    b = [g[rng.choice(e, len(e), replace=True)].mean() for _ in range(n)]
    return float(g.mean()), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def veredicto(lo, hi):
    return "MEJOR" if hi < 0 else "PEOR" if lo > 0 else "nulo"


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    mk = mk[[c for c in ("cargo_norm", "empresa_ruc", "y", "segmento", "ciiu_n1",
                         "ciiu_n6") if c in mk.columns]].copy()
    mk["cargo_norm"] = mk.cargo_norm.astype(str)
    mk["_c6"] = mk["ciiu_n6"].astype(str)
    ok6 = mk["_c6"].str.match(r"^[A-Za-z]\d{3}")
    mk.loc[~ok6, "_c6"] = ""
    for nom, k in NIVELES:
        mk["_" + nom] = mk["_c6"].str[:k]

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
    print(f"construir {tr.empresa_ruc.nunique():,}   evaluar {ts.empresa_ruc.nunique():,}")
    for nom, _ in NIVELES:
        print(f"  {nom:9} {tr[tr['_'+nom] != '']['_'+nom].nunique():>4} rubros")

    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print(f"embebiendo {len(etiquetas):,} titulos...")
    X = embeddings.embeber(etiquetas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    emb = dict(zip(etiquetas, X))

    print("\nconstruyendo UNA base...")
    b = BaseReferencia.construir(tr, emb, s.get_sbu)

    # Las entradas de `_bandas_por_rubro`, reconstruidas desde la base ya hecha.
    d = tr.copy()
    d["_g"] = d["cargo_norm"].map(dict(zip(b.celdas, (int(g) for g in b.grupo))))
    d = d.dropna(subset=["_g"])
    d["_g"] = d["_g"].astype(np.int64)
    clave_et = b.grupo
    t2_cl = pd.Series(b.tau2_c, index=clave_et)
    s2_cl = pd.Series(b.sigma2_c, index=clave_et)
    t2_cl = t2_cl[~t2_cl.index.duplicated()]
    s2_cl = s2_cl[~s2_cl.index.duplicated()]

    tablas = {}
    for nom, _ in NIVELES:
        dd = d.copy()
        dd["ciiu_n1"] = dd["_" + nom].replace("", np.nan)
        tablas[nom] = _bandas_por_rubro(dd, "_g", clave_et, t2_cl, s2_cl)
        print(f"  banda por rubro [{nom}]: {len(tablas[nom][0]):,} pares, "
              f"{len(tablas[nom][8])} rubros")
        del dd
    del d, tr
    gc.collect()

    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc"], sort=False)
           .agg(voto=("y", "median"),
                **{n: ("_" + n, "first") for n, _ in NIVELES}).reset_index())
    v = v[v["seccion"] != ""].reset_index(drop=True)
    del ts
    gc.collect()
    print(f"\nvotos apartados: {len(v):,} sobre {v.empresa_ruc.nunique():,} empresas")

    # PLACEBO por nivel: el codigo se baraja DENTRO del nivel inmediatamente superior,
    # asi que conserva cuantos rubros hay y como de grandes son, y solo rompe el sentido.
    rp = np.random.default_rng(99)
    padre = {"clase": "grupo", "grupo": "division", "division": "seccion",
             "seccion": None}
    for nom, _ in NIVELES:
        p = padre[nom]
        v["plac_" + nom] = (v.groupby(p)[nom].transform(
            lambda x: rp.permutation(x.to_numpy())) if p else v[nom])

    print("referenciando cada nivel...")
    res = {}
    for nom, _ in NIVELES:
        poner_rubro(b, tablas[nom])
        res[nom] = bandas(b, emb, v, nom)
        res["plac_" + nom] = bandas(b, emb, v, "plac_" + nom)
        print(f"  {nom}: banda sectorial en {int(res[nom][2].sum()):,} votos")

    y = v["voto"].to_numpy(float)
    fin = np.isfinite(y) & np.isfinite(res["seccion"][0])
    emps = v["empresa_ruc"].to_numpy()

    # CASCADA: el nivel mas fino que de banda sectorial; si ninguno, lo de la seccion
    # (que a su vez cae al mercado entero cuando tampoco aguanta).
    p25C, p75C = res["seccion"][0].copy(), res["seccion"][1].copy()
    nivel_usado = np.array(["mercado/seccion"] * len(v), dtype=object)
    emp_usado = res["seccion"][3].copy()
    # Se aplica de GRUESO a FINO para que el fino sobrescriba: al final cada voto lleva
    # el nivel mas especifico que aguanto el suelo.
    for nom, _ in reversed(NIVELES):
        u = res[nom][2]
        p25C = np.where(u, res[nom][0], p25C)
        p75C = np.where(u, res[nom][1], p75C)
        emp_usado = np.where(u, res[nom][3], emp_usado)
        nivel_usado = np.where(u, nom, nivel_usado)

    lA = pinball(y, res["seccion"][0], res["seccion"][1])
    lC = pinball(y, p25C, p75C)

    print("\n" + "=" * 78)
    print("A QUE NIVEL ACABA CADA VOTO EN LA CASCADA")
    print("=" * 78)
    t = pd.DataFrame({"nivel": nivel_usado[fin], "emp": emp_usado[fin]})
    r = t.groupby("nivel").agg(votos=("nivel", "size"),
                               emp_mediana=("emp", "median"))
    r["pct"] = (100 * r["votos"] / fin.sum()).round(1)
    print(r.sort_values("votos", ascending=False).to_string())

    rb = np.random.default_rng(7)
    print("\n" + "=" * 78)
    print("PRIMARIA  cascada - hoy (seccion), sobre TODOS los votos")
    print("=" * 78)
    m, lo, hi = ic((lC - lA)[fin], emps[fin], rb)
    print(f"  pinball hoy     {np.mean(lA[fin]):.5f}")
    print(f"  pinball cascada {np.mean(lC[fin]):.5f}")
    print(f"  diferencia      {m:+.5f}   IC95 [{lo:+.5f}, {hi:+.5f}]   "
          f"rel {100*m/np.mean(lA[fin]):+.2f}%")
    print(f"  CRITERIO: se adopta solo si el IC queda ENTERO bajo cero")
    print(f"  VEREDICTO: {'SE ADOPTA' if hi < 0 else 'NO se adopta'}  ({veredicto(lo, hi)})")

    print("\n" + "=" * 78)
    print("CADA NIVEL CONTRA LA SECCION, donde los dos dan banda sectorial")
    print("=" * 78)
    print(f"{'nivel':10} {'votos':>7} {'dif':>10} {'IC95':>24} {'':>6}   placebo")
    for nom, _ in NIVELES[:-1]:
        u = fin & res["seccion"][2] & res[nom][2]
        if u.sum() < 50:
            print(f"{nom:10} {int(u.sum()):>7}   (pocos votos)")
            continue
        ln = pinball(y, res[nom][0], res[nom][1])
        m1, l1, h1 = ic((ln - lA)[u], emps[u], rb)
        up = fin & res["seccion"][2] & res["plac_" + nom][2]
        lp = pinball(y, res["plac_" + nom][0], res["plac_" + nom][1])
        m2, l2, h2 = ic((lp - lA)[up], emps[up], rb)
        print(f"{nom:10} {int(u.sum()):>7} {m1:>+10.5f} [{l1:+.5f},{h1:+.5f}] "
              f"{veredicto(l1, h1):>6}   {m2:+.5f} {veredicto(l2, h2)}")

    # --- varios RUCs concretos ----------------------------------------------------
    print("\n" + "=" * 78)
    print("QUE LE PASA A UNA EMPRESA CONCRETA")
    print("=" * 78)
    vv = v.assign(fin=fin, nivel=nivel_usado, emp=emp_usado,
                  dif_log=p25C - res["seccion"][0])
    vv = vv[vv["fin"]]
    cand = (vv[vv["nivel"] != "mercado/seccion"]
            .groupby("empresa_ruc")
            .agg(cargos=("cargo_norm", "size"), sec=("seccion", "first"),
                 cla=("clase", "first")).query("cargos >= 5")
            .sort_values("cargos", ascending=False))
    for ruc in list(cand.index)[:6]:
        g = vv[vv.empresa_ruc == ruc]
        f = cand.loc[ruc]
        print(f"\n  RUC ...{str(ruc)[-6:]}   CIIU {f['cla']}   seccion {f['sec']}   "
              f"{len(g)} cargos evaluados")
        rr = g.groupby("nivel").size()
        print(f"    niveles usados: {dict(rr)}")
        mov = g[g['nivel'] != 'mercado/seccion']['dif_log']
        if len(mov):
            print(f"    la referencia se mueve: mediana "
                  f"{100*(np.exp(mov.abs().median())-1):.1f}%, "
                  f"maximo {100*(np.exp(mov.abs().max())-1):.1f}%")

    # LOS EXTREMOS DE LA BANDA, no solo el pinball. Un ejecutivo no decide sobre
    # pinball: decide sobre "este cargo esta bajo / dentro / sobre la banda". Sin
    # guardar p25 y p75 esa pregunta no se puede contestar sin volver a correr todo.
    pd.DataFrame({"empresa": v.empresa_ruc, "cargo": v.cargo_norm,
                  "fin": fin, "nivel": nivel_usado, "emp": emp_usado,
                  "y": y,
                  "p25A": res["seccion"][0], "p75A": res["seccion"][1],
                  "p25C": p25C, "p75C": p75C,
                  "empA": res["seccion"][3],
                  "lA": lA, "lC": lC,
                  **{f"uso_{n}": res[n][2] for n, _ in NIVELES},
                  **{f"l_{n}": pinball(y, res[n][0], res[n][1]) for n, _ in NIVELES}}
                 ).to_parquet("research/experimentos/e3_varianza/salidas/"
                              "19_cascada_ciiu.parquet")
    print("\nguardado en salidas/19_cascada_ciiu.parquet")


if __name__ == "__main__":
    main()
