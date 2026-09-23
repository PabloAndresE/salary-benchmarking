"""Segundo candado en la fusion semantica: la marca de seniority.

DE DONDE VIENE. 48 pares de la banda 0,93-0,97 juzgados a mano (ver `13a`). De los
12 que se juzgaron como puestos DISTINTOS, el motivo era casi siempre una marca de
seniority que el lexico de rango no ve:

    SUPERVISOR CALIDAD       | SUPERVISOR DE CALIDAD SR      <- SR
    ANALISTA INTELIGENCIA    | ANALISTA JUNIOR - INTELIG.    <- JUNIOR
    CHEF DE COCINA           | SOUS CHEF DE COCINA           <- SOUS
    GERENTE DE INGENIERIA    | GERENTE CORPORATIVO DE ING.   <- CORPORATIVO

`SR` no es un escalon: un `SUPERVISOR DE CALIDAD SR` sigue siendo supervisor.
Meterlo en `RANGOS` romperia la escalera —medida sobre cinco escalones— y el
`lambda` por nivel. Va aparte, y solo sirve para impedir la fusion.

VALIDADO CONTRA LOS 48, antes de escribir el candado. Se probaron cinco conjuntos:

    solo SR/JR                  caza 2 de 12   rompe 1 de 36
    + SOUS                      caza 3         rompe 1
    + CORPORATIVO               caza 5         rompe 1   <- el elegido
    + GENERAL                   caza 5         rompe 3
    + numeros y letras romanas  caza 5         rompe 4

`GENERAL` fuera: `SUPERVISOR DE ETIQUETADO` y `SUPERVISOR GENERAL DE ETIQUETADO` se
juzgaron como el mismo puesto. Los numeros tampoco: `TECNICO MECANICO A` y `TECNICO
MECANICO I` tambien, y de los escalones por digito ya se ocupa `_es_errata`.

Sumado al candado de escalon que ya existe, los dos cubren 8 de los 12 `no` con 2
falsos positivos sobre los 36 `si` —los dos del candado viejo, ninguno de este.

EL RIESGO. Un candado SEPARA, asi que su fallo es el contrario del de una fusion:
no contamina una celda, la deja delgada. `TECNICO ESPECIALISTA EN MANTENIMIENTO` y
`TECNICO DE MANTENIMIENTO SR.` se juzgaron iguales y este candado los separa. Es el
unico falso positivo medido, y se paga a cambio de cinco aciertos.

CRITERIO, DECLARADO ANTES DE CORRER
--------------------------------------------------------------
Metrica: pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste
pareado por empresa apartada.

SE ADOPTA si y solo si:
    1. el IC 95% de la diferencia pareada contra hoy NO queda entero POR ENCIMA de cero
    2. la cobertura directa NO cae mas de 0,5 puntos

NO HAY PLACEBO, y hay que decir por que. El placebo de permutacion prueba que una
FUSION eligio bien el destino: manda las mismas absorciones a destinos al azar. Un
candado no tiene destino —solo impide uniones— asi que no hay nada que barajar. El
contraste que si tiene sentido es el conjunto `GENERAL`, que segun los 48 juicios
rompe mas de lo que caza: si el candado bueno y ese dan lo mismo, el criterio de
seleccion no estaba aportando.

VARIANTES: hoy / candado / candado_general (el contraste).

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
from benchmarking.producto.base_referencia import BaseReferencia
from benchmarking.producto.nivel import SENIORIDAD, seniority_lexica

SEM = 20260923
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 400
SAL = pathlib.Path("research/experimentos/e2_nivel/salidas")
LINEA = "=" * 78

CON_GENERAL = dict(SENIORIDAD, GENERAL=3)

VARIANTES = {
    "hoy": None,
    "candado": SENIORIDAD,
    "candado_general": CON_GENERAL,
}


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


def una_variante(nom):
    tabla = VARIANTES[nom]
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

    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc"], sort=False)["y"]
           .median().reset_index().rename(columns={"y": "voto"}))
    del ts
    gc.collect()
    y = v["voto"].to_numpy(float)
    emps = v["empresa_ruc"].to_numpy()
    cargos = sorted(set(v.cargo_norm))

    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    X = embeddings.embeber(etiquetas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    del cache, cli
    X = np.asarray(X, dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    emb = dict(zip(etiquetas, X))
    gc.collect()

    # `_fusionar` ya acepta `senior`, desactivado por defecto. Aqui se le da el array
    # que toca; el resto del producto no se entera.
    import benchmarking.producto.base_referencia as BR
    original = BR._fusionar
    registro = {}

    def parcheada(Z, niveles, umbral=BR.UMBRAL_FUSION, tope=BR.TOPE_GRUPO, senior=None):
        if tabla is None:
            return original(Z, niveles, umbral, tope, None)
        # `seniority_lexica` lee de `SENIORIDAD`; para la variante de contraste se
        # sustituye el diccionario del modulo durante la llamada.
        import benchmarking.producto.nivel as NV
        viejo, viejo_pat = NV.SENIORIDAD, NV._PATRON_SEN
        import re as _re
        NV.SENIORIDAD = tabla
        NV._PATRON_SEN = _re.compile(
            r"\b(" + "|".join(sorted(tabla, key=len, reverse=True)) + r")\b\.?")
        try:
            sen = np.array([NV.seniority_lexica(c) for c in parcheada.celdas])
        finally:
            NV.SENIORIDAD, NV._PATRON_SEN = viejo, viejo_pat
        registro["con_marca"] = int((sen != 0).sum())
        return original(Z, niveles, umbral, tope, sen)

    # `_fusionar` recibe `Z` y no las etiquetas, asi que hay que pasarselas aparte.
    parcheada.celdas = sorted(set(tr.cargo_norm))

    BR._fusionar = parcheada
    try:
        base = BaseReferencia.construir(tr, emb, s.get_sbu)
    finally:
        BR._fusionar = original
    del tr
    gc.collect()

    registro["grupos"] = int(len(set(base.grupo.tolist())))
    out = base.referenciar(cargos, emb).set_index("cargo")
    perdida = pinball(y,
                      out["p25_log"].reindex(v.cargo_norm).to_numpy(float),
                      out["p75_log"].reindex(v.cargo_norm).to_numpy(float))
    directa = (out["base"].reindex(v.cargo_norm) == "datos directos").to_numpy()
    del base, out, emb, X
    gc.collect()

    pd.DataFrame({"empresa": emps, "cargo": v.cargo_norm,
                  "pinball": perdida, "directa": directa}).to_parquet(
        SAL / "14_{}.parquet".format(nom))
    (SAL / "14_{}.json".format(nom)).write_text(json.dumps(registro), encoding="utf-8")
    print("  {}   guardado.".format(registro), flush=True)


def juntar():
    # SE UNE POR (empresa, cargo): BigQuery no garantiza el orden entre consultas.
    tabla, meta = None, {}
    for nom in VARIANTES:
        d = pd.read_parquet(SAL / "14_{}.parquet".format(nom))
        d = d.rename(columns={"pinball": "p_" + nom, "directa": "d_" + nom})
        tabla = d if tabla is None else tabla.merge(d, on=["empresa", "cargo"],
                                                    how="inner")
        j = SAL / "14_{}.json".format(nom)
        meta[nom] = json.loads(j.read_text(encoding="utf-8")) if j.exists() else {}

    rng = np.random.default_rng(SEM)
    print(LINEA)
    print("CANDADO DE SENIORITY EN LA FUSION SEMANTICA")
    print(LINEA)
    for nom, m in meta.items():
        print("  {:<18} {}".format(nom, m))

    print("\n  votos evaluados (empresa, cargo): {:,}".format(len(tabla)))
    for nom in ("candado", "candado_general"):
        print("  votos donde {} CAMBIA la rama: {:,}".format(
            nom, int((tabla["d_" + nom] != tabla["d_hoy"]).sum())))

    print("\n  {:<18} {:>12} {:>26} {:>11}".format(
        "variante", "pinball", "dif vs hoy (IC95)", "cobertura"))
    for nom in VARIANTES:
        cob, pin = float(tabla["d_" + nom].mean()), float(tabla["p_" + nom].mean())
        if nom == "hoy":
            print("  {:<18} {:>12.5f} {:>26} {:>10.1f}%".format(nom, pin, "-", 100 * cob))
            continue
        dif = tabla["p_" + nom] - tabla["p_hoy"]
        med, lo, hi = ic(dif.to_numpy(float), tabla["empresa"].to_numpy(), rng)
        print("  {:<18} {:>12.5f} {:>10.5f} [{:+.5f},{:+.5f}] {:>10.1f}%".format(
            nom, pin, med, lo, hi, 100 * cob))

    print("\n" + LINEA)
    print("LECTURA: se adopta si el IC de `candado` no queda entero sobre cero y la")
    print("cobertura no cae mas de 0,5 puntos. Si `candado` y `candado_general` dan lo")
    print("mismo, el criterio de que palabras entran no estaba aportando: seria una")
    print("senal de que el candado funciona por separar, no por separar BIEN.")
    print(LINEA)


def main():
    SAL.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] in VARIANTES:
        una_variante(sys.argv[1])
        return
    for nom in VARIANTES:
        if (SAL / "14_{}.parquet".format(nom)).exists():
            print("{:<18} ya estaba.".format(nom), flush=True)
            continue
        print("{:<18} corriendo...".format(nom), flush=True)
        r = subprocess.run([sys.executable, __file__, nom])
        if r.returncode:
            print("  fallo con codigo {}".format(r.returncode))
            return
    juntar()


if __name__ == "__main__":
    main()
