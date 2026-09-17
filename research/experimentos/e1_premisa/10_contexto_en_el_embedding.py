""".Y si al modelo le damos el titulo con contexto en vez de desnudo?

DE DONDE VIENE. Buscar `TECNICO DE DIALISIS` sugeria `ASISTENTE EN DISENO`. Medido sobre
los 65.181 titulos, dos cargos SIN NINGUNA RELACION llegan a 0,78 de coseno en el
percentil 99, y el 8,6% de los pares al azar pasan de 0,70. Los candidatos malos puntuan
0,74-0,79: estan dentro del rango del azar. Con titulos de una a tres palabras en espanol,
`text-multilingual-embedding-002` no separa el sinonimo de la rima.

LA PISTA. Embebiendo el mismo titulo dentro de una frase, sobre cinco pares conocidos:

    consulta             buena         mala          desnudo         con contexto
    DENTISTA             ODONTOLOGA    HIGIENISTA    0,763/0,784 MAL 0,943/0,870 OK
    AI DEVELOPER         IA DEVELOPER  AI TRAINER    0,765/0,772 MAL 0,922/0,890 OK
    TECNICO DE DIALISIS  HEMODIALISIS  T. DE DISENO  0,800/0,778 OK  0,870/0,847 OK
    DENTISTA             ODONTOLOGA    TELEFONISTA   0,763/0,752 OK  0,943/0,835 OK
    CHOFER               CONDUCTOR     CHEF          0,588/0,672 MAL 0,790/0,833 MAL

Tres de cinco pasaban de fallar a acertar, y la separacion crece: `DENTISTA`-`ODONTOLOGA`
va de 0,763 —dentro del ruido— a 0,943. Pero son CINCO ANECDOTAS, tres traidas por el
usuario y dos elegidas por mi, que es el peor muestreo posible. Esto lo mide en serio.

EL CONFUNDIDO QUE HAY QUE NEUTRALIZAR, y es el motivo de la mitad de este script: con
contexto TODOS los cosenos suben. `UMBRAL_FUSION = 0,95` deja de significar lo mismo y la
variante nueva fusionaria muchisimo mas. Comparar asi mediria la agresividad de la fusion,
no la calidad del embedding. Se iguala por CUANTIL: el umbral de cada variante es el que
ocupa la misma posicion en su propia distribucion de similitudes vecinas que 0,95 en la
desnuda. Se reporta el umbral resultante y el numero de grupos.

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
PRIMARIA — es un cambio del MODELO, asi que la barra es la de siempre: mejorar.
Pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste pareado por
empresa apartada.

    SE ADOPTA una plantilla si el IC 95% de (plantilla - desnudo) queda ENTERO bajo cero.

SE DECLARAN DOS PLANTILLAS Y SE REPORTAN LAS DOS. Elegir la ganadora despues de ver los
resultados seria ajustar a ruido, que es el error que este experimento existe para no
cometer:

    T1 "larga"  la que se probo a mano, con funciones y responsabilidad
    T2 "corta"  solo "Cargo: {}", como CONTROL: si T2 rinde igual que T1, lo que ayuda es
                tener CUALQUIER contexto y no la redaccion concreta. Si T2 no hace nada,
                el efecto depende de la frase y hay que desconfiar mas.

SECUNDARIA, se reporta y NO decide: acierto en los cinco pares sinonimo/rima. Son pocos y
elegidos a dedo; sirven para ver la direccion, no para decidir.

MEMORIA: UN PROCESO POR VARIANTE. La maquina tiene 31,5 GB y solo ~7 libres, y el resto no
es de este proyecto. Dos versiones anteriores murieron: la primera guardaba las tres
variantes a la vez; la segunda las soltaba dentro del mismo proceso, y aun asi murio,
porque Python devuelve la memoria al asignador y no al sistema, de modo que los picos se
acumulan.

Aqui cada variante corre en su PROPIO proceso (`--variante X`), escribe su vector de
pinball a disco y muere. El padre solo junta los parquet. Es ademas REANUDABLE: si una
variante ya tiene su fichero, no se repite — importante cuando embeber 58.000 titulos
cuesta lo que cuesta.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import gc
import json
import pathlib
import subprocess
import sys

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import (UMBRAL_FUSION, VECINOS_FUSION,
                                                   BaseReferencia, _vecinos)

SEM = 20260917
CACHE_DESNUDO = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 400
SAL = pathlib.Path("research/experimentos/e1_premisa/salidas")
REF_Z = SAL / "10_Zref.npy"

PLANTILLAS = {
    "desnudo": "{}",
    "T1_larga": ("Puesto de trabajo en una empresa: {}. Describe las funciones y el "
                 "nivel de responsabilidad del cargo."),
    "T2_corta": "Cargo: {}",
}

PARES = [  # (consulta, sinonimo correcto, distractor que rima o comparte estructura)
    ("DENTISTA", "ODONTOLOGA", "TELEFONISTA"),
    ("DENTISTA", "ODONTOLOGA", "HIGIENISTA"),
    ("TECNICO DE DIALISIS", "TECNICO EN HEMODIALISIS", "TECNICO DE DISENO"),
    ("AI DEVELOPER", "IA DEVELOPER", "AI TRAINER"),
    ("CHOFER", "CONDUCTOR", "CHEF"),
]

LINEA = "=" * 78


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


def umbral_igualado(Z_ref, Z_var, umbral_ref=UMBRAL_FUSION, muestra=4000, sem=1):
    """El umbral de `Z_var` que ocupa el mismo CUANTIL que `umbral_ref` en `Z_ref`.

    Sin esto la comparacion esta viciada: con contexto todos los cosenos suben, asi que
    0,95 fusionaria mucho mas y se estaria midiendo la agresividad de la fusion en vez
    de la calidad del embedding.
    """
    rng = np.random.default_rng(sem)
    idx = rng.choice(Z_ref.shape[0], min(muestra, Z_ref.shape[0]), replace=False)
    _, s_ref = _vecinos(Z_ref[idx], Z_ref, VECINOS_FUSION, excluir_propio=True)
    _, s_var = _vecinos(Z_var[idx], Z_var, VECINOS_FUSION, excluir_propio=True)
    q = float((s_ref.ravel() < umbral_ref).mean())      # cuantil que ocupa 0,95
    return float(np.quantile(s_var.ravel(), q)), q


def una_variante(nom):
    """Embebe, construye, evalua y guarda UNA variante. Este proceso muere despues."""
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    mk = mk[[c for c in ("cargo_norm", "empresa_ruc", "y", "segmento", "ciiu_n1")
             if c in mk.columns]].copy()
    mk["cargo_norm"] = mk.cargo_norm.astype(str)
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
    print("construir {:,}   evaluar {:,}".format(
        tr.empresa_ruc.nunique(), ts.empresa_ruc.nunique()), flush=True)

    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    extra = sorted({x for p in PARES for x in p} - set(etiquetas))
    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc"], sort=False)["y"]
           .median().reset_index().rename(columns={"y": "voto"}))
    del ts
    gc.collect()
    y = v["voto"].to_numpy(float)
    emps = v["empresa_ruc"].to_numpy()
    cargos = sorted(set(v.cargo_norm))

    ruta = (CACHE_DESNUDO if nom == "desnudo"
            else "research/experimentos/e1_premisa/emb_{}.npz".format(nom))
    cache = embeddings.CacheArchivo(ruta)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print("embebiendo {:,} titulos [{}]...".format(len(etiquetas) + len(extra), nom),
          flush=True)
    X = embeddings.embeber([PLANTILLAS[nom].format(t) for t in etiquetas + extra],
                           cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    del cache, cli
    X = np.asarray(X, dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    gc.collect()

    emb_var = dict(zip(etiquetas + extra, X))
    pares = {"|".join(c): (float(emb_var[c[0]] @ emb_var[c[1]]),
                           float(emb_var[c[0]] @ emb_var[c[2]])) for c in PARES}
    Zv = X[:len(etiquetas)]
    if nom == "desnudo":
        u, q_ = UMBRAL_FUSION, None
        np.save(REF_Z, Zv)          # para que las otras igualen su umbral por cuantil
    else:
        Zref = np.asarray(np.load(REF_Z, mmap_mode="r"))
        u, q_ = umbral_igualado(Zref, Zv)
        del Zref
        gc.collect()
    extra_msg = ("  (mismo cuantil {:.4f} que 0,95 en desnudo)".format(q_) if q_ else "")
    print("  umbral de fusion {:.4f}{}".format(u, extra_msg), flush=True)

    base = BaseReferencia.construir(tr, {t: emb_var[t] for t in etiquetas},
                                    s.get_sbu, umbral_fusion=u)
    n_grupos = len(set(base.grupo.tolist()))
    print("  grupos de fusion: {:,}".format(n_grupos), flush=True)
    del tr
    gc.collect()
    out = base.referenciar(cargos, emb_var).set_index("cargo")
    perdida = pinball(y,
                      out["p25_log"].reindex(v.cargo_norm).to_numpy(float),
                      out["p75_log"].reindex(v.cargo_norm).to_numpy(float))
    del base, out, emb_var, X, Zv
    gc.collect()

    pd.DataFrame({"empresa": emps, "cargo": v.cargo_norm,
                  "pinball": perdida}).to_parquet(
        SAL / "pinball_{}.parquet".format(nom))
    (SAL / "meta_{}.json".format(nom)).write_text(
        json.dumps({"umbral": u, "grupos": n_grupos, "pares": pares}), encoding="utf-8")
    print("  guardado.", flush=True)


def juntar():
    """Junta lo que dejo cada proceso y aplica el criterio."""
    # SE UNE POR (empresa, cargo), NO POR POSICION. Cada variante corre en su propio
    # proceso y cada proceso consulta BigQuery por su cuenta; BigQuery NO garantiza el
    # orden de las filas entre consultas. Emparejar por posicion compara el voto de una
    # empresa contra el de otra y el resultado sale con el SIGNO CAMBIADO: la primera
    # version de esta funcion daba "T1 PEOR +0,00641" donde la union correcta da
    # "sin diferencia -0,00057".
    meta, tabla = {}, None
    for nom in PLANTILLAS:
        d = pd.read_parquet(SAL / "pinball_{}.parquet".format(nom))
        d = d.rename(columns={"pinball": nom})
        tabla = d if tabla is None else tabla.merge(d, on=["empresa", "cargo"],
                                                    how="inner")
        meta[nom] = json.loads(
            (SAL / "meta_{}.json".format(nom)).read_text(encoding="utf-8"))
    perd = {n: tabla[n].to_numpy() for n in PLANTILLAS}
    emps = tabla["empresa"].to_numpy()
    print("votos emparejados por (empresa, cargo): {:,}".format(len(tabla)))

    print("")
    print(LINEA)
    print("SECUNDARIA (no decide)  pares sinonimo / rima")
    print(LINEA)
    print("{:21} {:23} {:19}".format("consulta", "buena", "mala")
          + "".join("{:>18}".format(n) for n in PLANTILLAS))
    aciertos = {n: 0 for n in PLANTILLAS}
    for c in PARES:
        cel = []
        for n in PLANTILLAS:
            sb, sm = meta[n]["pares"]["|".join(c)]
            aciertos[n] += sb > sm
            cel.append("{:.3f}/{:.3f} {}".format(sb, sm, "OK " if sb > sm else "MAL"))
        print("{:21} {:23} {:19}".format(c[0][:21], c[1][:23], c[2][:19])
              + "".join("{:>18}".format(x) for x in cel))
    print("  aciertos: " + str({n: "{}/{}".format(x, len(PARES))
                                for n, x in aciertos.items()}))

    fin = np.ones(len(tabla), bool)
    for n in PLANTILLAS:
        fin &= np.isfinite(perd[n])
    rb = np.random.default_rng(11)
    d0 = perd["desnudo"]
    print("")
    print(LINEA)
    print("PRIMARIA  cada plantilla contra el titulo DESNUDO")
    print(LINEA)
    print("  votos comparables: {:,}".format(int(fin.sum())))
    print("  pinball desnudo:   {:.5f}".format(d0[fin].mean()))
    print("  umbral y grupos:   " + str({n: (round(meta[n]["umbral"], 4),
                                             meta[n]["grupos"]) for n in PLANTILLAS}))
    print("")
    for n in PLANTILLAS:
        if n == "desnudo":
            continue
        dn = perd[n]
        m_, lo, hi = ic((dn - d0)[fin], emps[fin], rb)
        veredicto = ("MEJORA, se adopta" if hi < 0 else
                     "PEOR" if lo > 0 else "sin diferencia")
        print("  {:10} pinball {:.5f}   dif {:+.5f}  IC95 [{:+.5f}, {:+.5f}]   {}".format(
            n, dn[fin].mean(), m_, lo, hi, veredicto))
    print("")
    print("  CRITERIO: se adopta si el IC queda ENTERO bajo cero")


if __name__ == "__main__":
    SAL.mkdir(parents=True, exist_ok=True)
    if "--variante" in sys.argv:
        una_variante(sys.argv[sys.argv.index("--variante") + 1])
    elif "--juntar" in sys.argv:
        juntar()
    else:
        # PADRE: un proceso por variante, y luego juntar. Reanudable.
        for nombre in PLANTILLAS:
            if (SAL / "pinball_{}.parquet".format(nombre)).exists():
                print("[padre] {} ya estaba hecha".format(nombre), flush=True)
                continue
            print("[padre] lanzando {}".format(nombre), flush=True)
            r = subprocess.run([sys.executable, __file__, "--variante", nombre])
            if r.returncode != 0:
                print("[padre] {} fallo con codigo {}".format(nombre, r.returncode))
                sys.exit(r.returncode)
        juntar()
