"""Tres huecos de la fusion por errata: transposicion, suelo de largo y encadenado.

DE DONDE VIENE. En el desplegable del front, escribir `Vendedo` ofrecia esto:

    VENDEDRO   1 empresa      VENEDOR    1 empresa
    VENDEROA   1 empresa      VENDEDOR   767 empresas
    VEDEDOR    2 empresas

Cinco grafias del mismo puesto como celdas separadas, y las erratas ARRIBA de la buena.
La fusion por errata (D-025) no las caza, y el diagnostico da TRES causas distintas:

    grafia      emp  largo  lev  damerau   por que se escapo
    VENDEDRO      1      8    2        1   TRANSPOSICION: lev la ve como 2
    VEDEDOR       2      7    1        1   largo 7 < 8
    VENEDOR       1      7    1        1   largo 7 < 8
    VENDEROA      1      8    2        2   es errata DE UNA ERRATA (VENDERORA), y la
                                         fusion no encadena: queda huerfana por orden

TRES RELAJACIONES, medidas por separado y juntas:

  A) TRANSPOSICION (distancia de Damerau). Intercambiar dos letras contiguas es el dedazo
     mas comun al teclear y Levenshtein lo cuenta como dos errores.

  C) VARIAS PASADAS, para la errata DE una errata. `VENDEROA` viene de `VENDERORA`, que
     viene de `VENDEDORA`. En una sola pasada, el par (VENDERORA, VENDEROA) se evalua
     leyendo el grupo ORIGINAL de VENDERORA —su grupito de una empresa—, falla el suelo
     de 10 del lado comun, y cuando VENDERORA se absorbe ya es tarde. Queda huerfana por
     orden de ejecucion, no por la regla. NO es encadenar a ciegas: el destino sigue
     exigiendo 10 empresas EN CADA VUELTA, asi que nunca se pasa por un grupo raro.

     Lo importante de este caso: ninguna de esas grafias llega al umbral SEMANTICO.
     `VENDEROR` contra `VENDEDOR` puntua 0,7177 — el embedding no reconoce una errata de
     una letra. Todo ese grupo lo armo la fusion por errata, no el modelo.

  B) EL SUELO DE LARGO SOBRE LA GRAFIA COMUN, no sobre la rara. El suelo de 8 existe
     porque con palabras cortas un caracter cambia el significado (`SUB`/`SUR`). Pero
     aplicarselo a la RARA descarta pares seguros: `VEDEDOR` tiene 7 letras y 2 empresas,
     y su comun `VENDEDOR` tiene 8 y 767. El riesgo esta en que las DOS sean cortas y
     frecuentes, y de eso ya se ocupa el suelo de 10 empresas del lado que absorbe.

EL RIESGO, y por eso esto se mide y no se monta a ojo: aflojar la regla funde oficios
distintos. Un falso positivo aqui contamina la referencia de las dos celdas.

CRITERIO, DECLARADO ANTES DE CORRER — el mismo de D-025
--------------------------------------------------------
Metrica: pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste pareado
por empresa apartada, restringido a los votos donde la absorcion ACTUA.

SE ADOPTA una variante si y solo si:
    1. la cobertura directa SUBE sobre los titulos afectados
    2. el guardarrail NO empeora: el IC 95% de la diferencia pareada contra la regla de
       hoy no queda entero POR ENCIMA de cero
    3. el PLACEBO SI empeora ese guardarrail

EL PLACEBO ES LA PIEZA QUE DISCRIMINA, y es la leccion de D-025: la cobertura sube por
construccion en cualquier absorcion, real o barajada, asi que la cobertura sola no prueba
nada. El placebo absorbe los MISMOS grupos raros hacia destinos AL AZAR. Si la regla
acierta, el real deja el pinball donde estaba y el placebo lo estropea. Si los dos lo
dejan igual, da lo mismo donde caiga la gente y la regla no aporta.

D-025 SE CERRO SIN POTENCIA en ese placebo —"no validada, solo no contradicha"—, asi que
aqui se reporta cuantas absorciones nuevas hay ANTES de interpretar nada: con pocas, el
placebo no puede discriminar y el resultado se declara no concluyente en vez de aprobado.

VARIANTES: hoy / A / B / C / A+B+C, y el placebo de A+B+C.

MEMORIA: UN PROCESO POR VARIANTE, como en `e1_premisa/10`. La maquina tiene ~7 GB libres
y cinco bases no caben. Cada proceso construye, evalua, guarda su vector y muere. Es
reanudable: si una variante ya tiene su parquet, no se repite.

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

SEM = 20260917
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 400
SAL = pathlib.Path("research/experimentos/e2_nivel/salidas")
LINEA = "=" * 78

# (transposicion, largo_en_comun, pasadas, barajar_destinos)
VARIANTES = {
    "hoy":       (False, False, 1, False),
    "A_transp":  (True,  False, 1, False),
    "B_largo":   (False, True,  1, False),
    "C_cadena":  (False, False, 5, False),
    "ABC":       (True,  True,  5, False),
    "ABC_plac":  (True,  True,  5, True),
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
    transp, largo_comun, pasadas, barajar = VARIANTES[nom]
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

    # El parcheo de `_fusionar_erratas` se hace por variable de modulo, porque
    # `construir` no expone estas opciones — y no se le anaden al producto hasta que la
    # medicion diga algo.
    import benchmarking.producto.base_referencia as BR
    original = BR._fusionar_erratas

    registro = {}

    def parcheada(celdas, grupo, niveles, emp_por_grupo, **kw):
        g, n = original(celdas, grupo, niveles, emp_por_grupo,
                        transposicion=transp, largo_en_comun=largo_comun,
                        pasadas=pasadas, **kw)
        registro["absorciones"] = int(n)
        if barajar and n:
            # PLACEBO: los MISMOS raros, a destinos al azar entre los comunes elegibles
            movidos = np.flatnonzero(g != np.asarray(grupo))
            comunes = sorted({int(x) for x in g[movidos]})
            rp = np.random.default_rng(99)
            g = np.asarray(grupo).copy()
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
        SAL / "10_{}.parquet".format(nom))
    (SAL / "10_{}.json".format(nom)).write_text(json.dumps(registro), encoding="utf-8")
    print("  absorciones: {}   guardado.".format(registro), flush=True)


def juntar():
    # SE UNE POR (empresa, cargo). Cada variante corre en su proceso y consulta BigQuery
    # aparte; BigQuery no garantiza el orden de las filas entre consultas. Emparejar por
    # posicion compara el voto de una empresa contra el de otra (ver D-030).
    tabla, meta = None, {}
    for nom in VARIANTES:
        d = pd.read_parquet(SAL / "10_{}.parquet".format(nom))
        d = d.rename(columns={"pinball": "p_" + nom, "directa": "d_" + nom})
        tabla = d if tabla is None else tabla.merge(d, on=["empresa", "cargo"],
                                                    how="inner")
        meta[nom] = json.loads(
            (SAL / "10_{}.json".format(nom)).read_text(encoding="utf-8"))
    print("votos emparejados: {:,}".format(len(tabla)))
    print("absorciones por variante: " + str({n: meta[n] for n in VARIANTES}))

    emps = tabla["empresa"].to_numpy()
    p0 = tabla["p_hoy"].to_numpy()
    rb = np.random.default_rng(11)
    print("")
    print(LINEA)
    print("COBERTURA DIRECTA y GUARDARRAIL, contra la regla de hoy")
    print(LINEA)
    base_dir = tabla["d_hoy"].mean()
    print("  cobertura directa hoy: {:.4%}".format(base_dir))
    print("")
    for nom in VARIANTES:
        if nom == "hoy":
            continue
        pn = tabla["p_" + nom].to_numpy()
        cambia = tabla["d_" + nom].to_numpy() != tabla["d_hoy"].to_numpy()
        # el guardarrail se mide donde la absorcion ACTUA
        act = cambia | (np.abs(pn - p0) > 1e-12)
        m_, lo, hi = ic((pn - p0)[act], emps[act], rb)
        cob = tabla["d_" + nom].mean()
        print("  {:9} cobertura {:.4%} ({:+.4%})   votos donde actua {:>6,}".format(
            nom, cob, cob - base_dir, int(act.sum())))
        print("            pinball {:+.5f}  IC95 [{:+.5f}, {:+.5f}]   {}".format(
            m_, lo, hi, "EMPEORA" if lo > 0 else "no empeora"))
    print("")
    print("  CRITERIO: sube cobertura + no empeora + el PLACEBO si empeora")


if __name__ == "__main__":
    SAL.mkdir(parents=True, exist_ok=True)
    if "--variante" in sys.argv:
        una_variante(sys.argv[sys.argv.index("--variante") + 1])
    elif "--juntar" in sys.argv:
        juntar()
    else:
        for nombre in VARIANTES:
            if (SAL / "10_{}.parquet".format(nombre)).exists():
                print("[padre] {} ya estaba hecha".format(nombre), flush=True)
                continue
            print("[padre] lanzando {}".format(nombre), flush=True)
            r = subprocess.run([sys.executable, __file__, "--variante", nombre])
            if r.returncode != 0:
                print("[padre] {} fallo ({})".format(nombre, r.returncode))
                sys.exit(r.returncode)
        juntar()
