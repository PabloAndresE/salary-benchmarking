"""Cuarta pasada de consolidacion: la clave dura, o sea el titulo sin puntuacion.

DE DONDE VIENE. Auditando la consolidacion con `benchmarking grafias` sobre una
nomina de cinco cargos aparecio que `Contador.` no encuentra a `CONTADOR`. Mirando
por que, se vio algo mas gordo que un problema de consulta:

    clave GERENTEGENERAL
       grupo 34198   GERENTE GENERAL      774 empresas
       grupo 33253   GERENTE_GENERAL        3 empresas

    clave AUXILIARDEBODEGA
       grupo 13465   AUXILIAR DE BODEGA   499 empresas
       grupo 13532   AUXILIAR_DE_BODEGA     2 empresas

El embedding trata el guion bajo como si cambiara el significado, y la pasada de
erratas no los alcanza porque la distancia de edicion entre `GERENTE GENERAL` y
`GERENTE_GENERAL` es 1 pero la de `AUXILIAR DE BODEGA` a `AUXILIAR_DE_BODEGA` es 2.
Resultado: puestos reales partidos en dos, cada mitad estimando su centro con menos
empresas de las que tiene.

MEDIDO ANTES DE ESCRIBIR ESTO, sobre `base_v15`:

    claves duras distintas           63.051 de 65.181 titulos
    claves que apuntan a >1 grupo        462   (0,73%)
    personas en el lado chico         14.565   (1,46%)
    de esos grupos, sin llegar al suelo de 3 empresas:  329 de 462 (71%)

Y la diferencia de sueldo entre los dos grupos que comparten clave se desploma al
exigir respaldo, que es lo que dice que son el mismo puesto y no dos:

    lado chico sin exigir nada   mediana 20,3%   (contaminado: 1-2 empresas)
    lado chico con >=10 empresas mediana  8,6%
    lado chico con >=20 empresas mediana  4,0%

Los peores casos —`ASIS PRODUCCION` contra `ASIS.PRODUCCION`, un 916%— tienen UNA
empresa de un lado: la mediana es el sueldo de una persona, no un puesto distinto.

EL RIESGO, y por eso se mide. La clave dura borra separadores, y un separador a
veces SI cambia el puesto: `ASISTENTE / ADMINISTRATIVO` puede ser un rol combinado
y no un `ASISTENTE ADMINISTRATIVO`. Un falso positivo aqui contamina las dos celdas.

CRITERIO, DECLARADO ANTES DE CORRER — el mismo de `10`
--------------------------------------------------------
Metrica: pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste
pareado por empresa apartada, restringido a los votos donde la absorcion ACTUA.

SE ADOPTA si y solo si:
    1. la cobertura directa SUBE sobre los titulos afectados
    2. el IC 95% de la diferencia pareada contra hoy NO queda entero POR ENCIMA de cero
    3. el PLACEBO SI empeora ese guardarrail

El placebo absorbe los MISMOS grupos raros hacia destinos AL AZAR. Si la clave dura
acierta, el real deja el pinball donde estaba y el placebo lo estropea. Si los dos lo
dejan igual, da lo mismo donde caiga la gente y la regla no aporta.

Con pocas absorciones el placebo no puede discriminar, asi que se reporta cuantas hay
ANTES de interpretar nada y, si son pocas, se declara NO CONCLUYENTE en vez de aprobado.

VARIANTES: hoy / D_dura / D_dura_plac.

MEMORIA: un proceso por variante, como en `10`. Cada uno construye, evalua, guarda su
vector y muere. Reanudable: si una variante ya tiene su parquet, no se repite.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import gc
import json
import pathlib
import subprocess
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import (MAX_EMPRESAS_ERRATA,
                                                   MIN_EMPRESAS_ABSORBE,
                                                   BaseReferencia)

SEM = 20260923
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 400
SAL = pathlib.Path("research/experimentos/e2_nivel/salidas")
LINEA = "=" * 78

# (aplicar clave dura, barajar destinos)
VARIANTES = {
    "hoy":         (False, False),
    "D_dura":      (True,  False),
    "D_dura_plac": (True,  True),
}


def clave_dura(t):
    """El titulo sin nada que no sea letra o digito."""
    return "".join(ch for ch in t if ch.isalnum())


def fusionar_clave_dura(celdas, grupo, niveles, emp_por_grupo,
                        max_raro=MAX_EMPRESAS_ERRATA, min_comun=MIN_EMPRESAS_ABSORBE):
    """Absorbe el grupo raro dentro del comun cuando comparten clave dura.

    MISMAS REGLAS QUE LA PASADA DE ERRATAS, a proposito:

      - UNIDIRECCIONAL: lo raro entra en lo comun y nunca al reves. Asi no encadena,
        porque el destino no puede ser absorbido: para serlo tendria que tener
        `max_raro` empresas y acaba de exigirsele `min_comun`.
      - CANDADO DE ESCALON: dos titulos de nivel jerarquico distinto no se juntan.
      - UNA SOLA VUELTA. La clave dura es una relacion de equivalencia —o comparten
        clave o no—, asi que no hay erratas de erratas que perseguir.
    """
    grupo = np.asarray(grupo).copy()
    por_clave = defaultdict(set)
    nivel_de = {}
    for i, c in enumerate(celdas):
        g = int(grupo[i])
        por_clave[clave_dura(c)].add(g)
        if np.isfinite(niveles[i]):
            nivel_de.setdefault(g, int(niveles[i]))

    destino = {}
    for grupos in por_clave.values():
        if len(grupos) < 2:
            continue
        orden = sorted(grupos, key=lambda g: -emp_por_grupo.get(g, 0))
        comun = orden[0]
        if emp_por_grupo.get(comun, 0) < min_comun:
            continue
        for raro in orden[1:]:
            if emp_por_grupo.get(raro, 0) > max_raro:
                continue
            na, nb = nivel_de.get(raro), nivel_de.get(comun)
            if na is not None and nb is not None and na != nb:
                continue
            if raro in destino:                 # ya absorbido por otro comun
                continue
            destino[raro] = comun

    if not destino:
        return grupo, 0
    nuevo = np.array([destino.get(int(g), int(g)) for g in grupo], dtype=np.int64)
    for raro in destino:
        emp_por_grupo.pop(raro, None)
    return nuevo, len(destino)


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
    aplicar, barajar = VARIANTES[nom]
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

    # La cuarta pasada se engancha DESPUES de la de erratas, que es su sitio: necesita
    # los conteos de empresa ya consolidados por las tres anteriores. Se parchea
    # `_fusionar_erratas` porque `construir` no expone un punto de extension, y no se le
    # anade uno al producto hasta que la medicion diga algo.
    import benchmarking.producto.base_referencia as BR
    original = BR._fusionar_erratas
    registro = {}

    def parcheada(celdas, grupo, niveles, emp_por_grupo, **kw):
        g, n = original(celdas, grupo, niveles, emp_por_grupo, **kw)
        registro["erratas"] = int(n)
        if not aplicar:
            return g, n
        antes = np.asarray(g).copy()
        g, n_dura = fusionar_clave_dura(celdas, g, niveles, emp_por_grupo)
        registro["clave_dura"] = int(n_dura)
        if barajar and n_dura:
            # PLACEBO: los MISMOS raros, a destinos al azar entre los comunes elegidos
            movidos = np.flatnonzero(g != antes)
            comunes = sorted({int(x) for x in g[movidos]})
            rp = np.random.default_rng(99)
            g = antes.copy()
            for i in movidos:
                g[i] = rp.choice(comunes)
            registro["absorciones_plac"] = len(movidos)
        return g, n

    BR._fusionar_erratas = parcheada
    try:
        base = BaseReferencia.construir(tr, emb, s.get_sbu)
    finally:
        BR._fusionar_erratas = original
    del tr
    gc.collect()

    out = base.referenciar(cargos, emb).set_index("cargo")
    perdida = pinball(y,
                      out["p25_log"].reindex(v.cargo_norm).to_numpy(float),
                      out["p75_log"].reindex(v.cargo_norm).to_numpy(float))
    directa = (out["base"].reindex(v.cargo_norm) == "datos directos").to_numpy()
    del base, out, emb, X
    gc.collect()

    pd.DataFrame({"empresa": emps, "cargo": v.cargo_norm,
                  "pinball": perdida, "directa": directa}).to_parquet(
        SAL / "11_{}.parquet".format(nom))
    (SAL / "11_{}.json".format(nom)).write_text(json.dumps(registro), encoding="utf-8")
    print("  {}   guardado.".format(registro), flush=True)


def juntar():
    # SE UNE POR (empresa, cargo). Cada variante corre en su proceso y consulta BigQuery
    # aparte; BigQuery no garantiza el orden de las filas entre consultas, asi que
    # emparejar por posicion compara el voto de una empresa contra el de otra (ver D-030).
    tabla, meta = None, {}
    for nom in VARIANTES:
        d = pd.read_parquet(SAL / "11_{}.parquet".format(nom))
        d = d.rename(columns={"pinball": "p_" + nom, "directa": "d_" + nom})
        tabla = d if tabla is None else tabla.merge(d, on=["empresa", "cargo"],
                                                    how="inner")
        j = SAL / "11_{}.json".format(nom)
        meta[nom] = json.loads(j.read_text(encoding="utf-8")) if j.exists() else {}

    rng = np.random.default_rng(SEM)
    print(LINEA)
    print("CUARTA PASADA: CLAVE DURA (titulo sin puntuacion)")
    print(LINEA)
    for nom, m in meta.items():
        print("  {:<14} {}".format(nom, m))
    n_dura = meta.get("D_dura", {}).get("clave_dura", 0)
    print("\n  absorciones nuevas por clave dura: {}".format(n_dura))
    if n_dura < 30:
        print("  POCAS: el placebo no puede discriminar. Se declara NO CONCLUYENTE.")

    print("\n  votos evaluados (empresa, cargo): {:,}".format(len(tabla)))
    afecta = tabla["d_D_dura"] != tabla["d_hoy"]
    print("  votos donde la absorcion CAMBIA la rama: {:,}".format(int(afecta.sum())))

    print("\n  {:<14} {:>12} {:>24} {:>12}".format(
        "variante", "pinball", "dif vs hoy (IC95)", "cobertura"))
    for nom in VARIANTES:
        cob = float(tabla["d_" + nom].mean())
        pin = float(tabla["p_" + nom].mean())
        if nom == "hoy":
            print("  {:<14} {:>12.5f} {:>24} {:>11.1f}%".format(
                nom, pin, "-", 100 * cob))
            continue
        dif = tabla["p_" + nom] - tabla["p_hoy"]
        med, lo, hi = ic(dif.to_numpy(float), tabla["empresa"].to_numpy(), rng)
        print("  {:<14} {:>12.5f} {:>9.5f} [{:+.5f},{:+.5f}] {:>11.1f}%".format(
            nom, pin, med, lo, hi, 100 * cob))

    # SOBRE LOS VOTOS AFECTADOS, que es donde la regla actua. El global los diluye.
    if int(afecta.sum()) >= 20:
        print("\n  restringido a los votos donde la absorcion actua:")
        sub = tabla[afecta]
        for nom in ("D_dura", "D_dura_plac"):
            dif = sub["p_" + nom] - sub["p_hoy"]
            med, lo, hi = ic(dif.to_numpy(float), sub["empresa"].to_numpy(), rng)
            print("  {:<14} {:>12.5f} {:>9.5f} [{:+.5f},{:+.5f}]".format(
                nom, float(sub["p_" + nom].mean()), med, lo, hi))

    print("\n" + LINEA)
    print("LECTURA: se adopta si la cobertura sube, el IC de D_dura no queda entero")
    print("sobre cero, y el de D_dura_plac SI. Si los dos quedan igual, la regla no")
    print("aporta: daria lo mismo donde caiga la gente.")
    print(LINEA)


def main():
    SAL.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] in VARIANTES:
        una_variante(sys.argv[1])
        return
    for nom in VARIANTES:
        if (SAL / "11_{}.parquet".format(nom)).exists():
            print("{:<14} ya estaba.".format(nom), flush=True)
            continue
        print("{:<14} corriendo...".format(nom), flush=True)
        r = subprocess.run([sys.executable, __file__, nom])
        if r.returncode:
            print("  fallo con codigo {}".format(r.returncode))
            return
    juntar()


if __name__ == "__main__":
    main()
