"""El suelo del lado raro es absoluto y a esta escala esta mal planteado.

EL COMENTARIO QUE LO JUSTIFICA dice: "un dedazo no lo teclean tres empresas".

    MAX_EMPRESAS_ERRATA = 2     # el lado raro

Con 6.722 empresas tecleando, eso es falso. Medido sobre `base_v15`, hay 254 pares
a distancia 1 que la regla rechaza SOLO por ese umbral, y no son ambiguos:

    ASISTEMTE CONTABLE        43  ->  ASISTENTE CONTABLE       1698   dif 0%
    ASISTNTE CONTABLE         43  ->  ASISTENTE CONTABLE       1698   dif 0%
    AUXILIAR DI LIMPIEZA      41  ->  AUXILIAR DE LIMPIEZA      446   dif 0%
    GERENTE ADMINISTRATIVA-FIN 49 ->  GERENTE ADMINISTRATIVA F  157   dif 1%
    OPERADOR DE MONTACARGAS   62  ->  OPERADOR DE MONTACARGA     64   dif 8%

`ASISTEMTE CONTABLE` con 43 empresas es un dedazo de uno con 1.698, y pagan lo
mismo. Un dedazo frecuente es frecuente.

POR QUE ESTA BOLSA Y NO OTRA. Dimensionadas todas sobre `base_v15`:

    bolsa                                 pares  personas  % gente  bajo suelo
    clave dura (medida en `11`)              97       816    0,08%    97 de 97
    lado raro con >2 empresas               254    12.508    1,25%     0 de 254
    comun con <8 caracteres                  45     2.400    0,24%    31 de 45
    pasa todos los filtros y no une          37       337    0,03%    37 de 37

`11` salio NO CONCLUYENTE porque sus 97 lados chicos estaban TODOS bajo el suelo:
ya se respondian por analogia, la absorcion cambiaba la rama en 5 votos de 34.435
y el placebo no tenia con que discriminar. Esta bolsa es la contraria —ninguno
esta bajo el suelo, los 254 se responden hoy con datos propios partidos en dos—
asi que el efecto deberia verse y el placebo deberia poder discriminar.

LA RELAJACION. El suelo pasa de absoluto a RELATIVO al tamano del comun:

    hoy         emp[raro] <= 2
    propuesto   emp[raro] <= max(2, frac * emp[comun])

`ASISTEMTE` con 43 contra 1.698 es un 2,5% del comun: errata. Dos grupos de 50 y
60 empresas nunca se tocan, que es donde vive el riesgo de fundir oficios
distintos. Se prueban dos fracciones para ver si el resultado depende de donde se
ponga la raya.

EL RIESGO, y por eso se mide. Aflojar funde oficios distintos, y un falso positivo
contamina la referencia de las DOS celdas. El caso que mas inquieta ya apareció:

    TRABAJADOR_A SOCIAL   35  ->  TRABAJADORA SOCIAL   563   dif 14%

Es el mismo puesto sin discusion, y pagan un 14% distinto. Con 35 empresas eso no
es solo ruido: puede que quien escribe con guion bajo sea sistematicamente otra
cosa —sector publico, por ejemplo—. Fusionarlos MUEVE la referencia, y en la
direccion correcta o no, lo dice el placebo y no la intuicion.

CRITERIO, DECLARADO ANTES DE CORRER — el mismo de `10` y `11`
--------------------------------------------------------------
Metrica: pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste
pareado por empresa apartada.

SE ADOPTA una variante si y solo si:
    1. la cobertura directa SUBE
    2. el IC 95% de la diferencia pareada contra hoy NO queda entero POR ENCIMA de cero
    3. el PLACEBO SI empeora ese guardarrail

Se reporta ANTES de interpretar nada cuantos votos cambian de rama. Con menos de
30, el placebo no discrimina y se declara NO CONCLUYENTE, como paso en `11`.

VARIANTES: hoy / R05 (5%) / R10 (10%) / R05_plac.

MEMORIA: un proceso por variante. Reanudable: si una ya tiene su parquet, no se
repite.

TODO SOBRE TRAIN. El 20% de test no se toca.

RESULTADO (2026-09-23). NO SE ADOPTA. Ver D-032 y su Enmienda 1.

OJO CON EL GUARDARRAIL: esta corrida IMPRIMIO «votos donde R05 CAMBIA la rama: 11
-> POCOS: el placebo no discriminaria. NO CONCLUYENTE». Disparo. Al adjudicarlo
resulta falsa alarma --R05 y su placebo mueven el valor de 33.061 y 33.020 votos,
huella identica, y el placebo hace 30 veces mas dano-- asi que el placebo SI tenia
potencia. El guardarrail cuenta cambios de RAMA, que aproxima mal: mide a cuanta
gente se le cambia la fuente, no a cuanta se le cambia el VALOR. Pendiente
cambiarlo en `11` y `12`.
------------------------------------------------------------------------------
    variante      absorciones   pinball   dif vs hoy (IC95)          cobertura
    hoy                   593   0,13471   -                              55,4%
    R05                   641   0,13481   +0,00004 [-0,00003,+0,00012]   55,5%
    R10                   667   0,13480   +0,00004 [-0,00003,+0,00012]   55,5%
    R05_plac              641   0,13630   +0,00119 [+0,00058,+0,00174]   55,5%

El placebo discrimina con holgura —30 veces el efecto de la regla real— y R05 y R10
coinciden hasta la quinta cifra, que es lo que se le pide a un umbral relativo: que
no dependa de donde se ponga la raya. La medicion es limpia.

NO SE ADOPTA, y la razon no es la medicion. El criterio de D-031 era «demuestra que
no estropea» porque aquello arreglaba un desplegable roto. Esto no sale de ninguna
queja: sale de mirar la regla y notar que un tope fijo es teoricamente feo. Las 48
absorciones que anade son celdas de una o dos empresas, el efecto es indistinguible
de cero y el signo es adverso. Un cambio sin problema que resolver no entra.

Queda ARCHIVADO, no descartado: si aparece una queja que este tope resuelva, la
medicion ya esta hecha y la regla es una linea.
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

SEM = 20260923
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 400
SAL = pathlib.Path("research/experimentos/e2_nivel/salidas")
LINEA = "=" * 78

# (fraccion del comun que puede tener el raro, barajar destinos)
VARIANTES = {
    "hoy":      (None, False),
    "R05":      (0.05, False),
    "R10":      (0.10, False),
    "R05_plac": (0.05, True),
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
    frac, barajar = VARIANTES[nom]
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

    # COPIA EXPLICITA de `_una_pasada_erratas` con UNA linea cambiada, marcada abajo.
    #
    # El primer intento fue pasarle a `max_raro` un objeto que se comparara distinto
    # segun el par. No funciona: el suelo se evalua DESPUES de elegir el comun, pero el
    # objeto nunca se entera de cual es. Antes que un truco fragil que habria que
    # explicar, aqui va la funcion entera: son cuarenta lineas y se ve lo que cambia.
    import benchmarking.producto.base_referencia as BR
    registro = {}

    def pasada_relativa(celdas, grupo, niveles, emp_por_grupo, min_largo, max_raro,
                        min_comun, transposicion, largo_en_comun):
        n = len(celdas)
        idx = BR.defaultdict(list)
        for i, c in enumerate(celdas):
            if not largo_en_comun and len(c) < min_largo:
                continue
            idx[c].append(i)
            for k in range(len(c)):
                idx[c[:k] + c[k + 1:]].append(i)

        destino, vistos, fusiones = {}, set(), 0
        for lista in idx.values():
            if len(lista) < 2:
                continue
            for x in range(len(lista)):
                for y in range(x + 1, len(lista)):
                    i, j = lista[x], lista[y]
                    par = (i, j) if i < j else (j, i)
                    if par in vistos:
                        continue
                    vistos.add(par)
                    gi, gj = int(grupo[par[0]]), int(grupo[par[1]])
                    if gi == gj:
                        continue
                    ni, nj = niveles[par[0]], niveles[par[1]]
                    if np.isfinite(ni) and np.isfinite(nj) and ni != nj:
                        continue
                    a, b = celdas[par[0]], celdas[par[1]]
                    if not BR._distancia1(a, b, transposicion) or not BR._es_errata(a, b):
                        continue
                    ei, ej = emp_por_grupo.get(gi, 0), emp_por_grupo.get(gj, 0)
                    raro, comun = (gi, gj) if ei <= ej else (gj, gi)
                    if largo_en_comun and len(a if comun == gi else b) < min_largo:
                        continue
                    # ---- LA UNICA LINEA QUE CAMBIA -------------------------------
                    tope = (max_raro if frac is None
                            else max(max_raro, frac * emp_por_grupo.get(comun, 0)))
                    if emp_por_grupo.get(raro, 0) > tope:
                        continue
                    # --------------------------------------------------------------
                    if emp_por_grupo.get(comun, 0) < min_comun:
                        continue
                    if raro in destino:
                        continue
                    destino[raro] = comun
                    fusiones += 1

        if not destino:
            return np.asarray(grupo), 0
        nuevo = np.array([destino.get(int(g), int(g)) for g in grupo], dtype=np.int64)
        for raro in destino:
            emp_por_grupo.pop(raro, None)
        return nuevo, fusiones

    original = BR._una_pasada_erratas
    parcheada = pasada_relativa

    # El placebo se aplica sobre el resultado de las pasadas, igual que en `10` y `11`.
    original_fus = BR._fusionar_erratas

    def fus_parcheada(celdas, grupo, niveles, emp_por_grupo, **kw):
        antes = np.asarray(grupo).copy()
        g, n = original_fus(celdas, grupo, niveles, emp_por_grupo, **kw)
        registro["erratas"] = int(n)
        if barajar and n:
            movidos = np.flatnonzero(np.asarray(g) != antes)
            comunes = sorted({int(x) for x in np.asarray(g)[movidos]})
            rp = np.random.default_rng(99)
            g = antes.copy()
            for i in movidos:
                g[i] = rp.choice(comunes)
            registro["absorciones_plac"] = len(movidos)
        return g, n

    BR._una_pasada_erratas = parcheada
    BR._fusionar_erratas = fus_parcheada
    try:
        base = BaseReferencia.construir(tr, emb, s.get_sbu)
    finally:
        BR._una_pasada_erratas = original
        BR._fusionar_erratas = original_fus
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
        SAL / "12_{}.parquet".format(nom))
    (SAL / "12_{}.json".format(nom)).write_text(json.dumps(registro), encoding="utf-8")
    print("  {}   guardado.".format(registro), flush=True)


def juntar():
    # SE UNE POR (empresa, cargo). Cada variante corre en su proceso y consulta BigQuery
    # aparte; BigQuery no garantiza el orden entre consultas, asi que emparejar por
    # posicion compara el voto de una empresa contra el de otra (ver D-030).
    tabla, meta = None, {}
    for nom in VARIANTES:
        d = pd.read_parquet(SAL / "12_{}.parquet".format(nom))
        d = d.rename(columns={"pinball": "p_" + nom, "directa": "d_" + nom})
        tabla = d if tabla is None else tabla.merge(d, on=["empresa", "cargo"],
                                                    how="inner")
        j = SAL / "12_{}.json".format(nom)
        meta[nom] = json.loads(j.read_text(encoding="utf-8")) if j.exists() else {}

    rng = np.random.default_rng(SEM)
    print(LINEA)
    print("SUELO RELATIVO DEL LADO RARO EN LA FUSION POR ERRATA")
    print(LINEA)
    for nom, m in meta.items():
        print("  {:<12} {}".format(nom, m))
    base_n = meta.get("hoy", {}).get("erratas", 0)
    print("\n  absorciones: hoy {}   R05 {}   R10 {}".format(
        base_n, meta.get("R05", {}).get("erratas", 0),
        meta.get("R10", {}).get("erratas", 0)))

    print("\n  votos evaluados (empresa, cargo): {:,}".format(len(tabla)))
    for nom in ("R05", "R10"):
        cambia = int((tabla["d_" + nom] != tabla["d_hoy"]).sum())
        print("  votos donde {} CAMBIA la rama: {:,}".format(nom, cambia))
        if cambia < 30:
            print("    POCOS: el placebo no discriminaria. NO CONCLUYENTE.")

    print("\n  {:<12} {:>12} {:>26} {:>11}".format(
        "variante", "pinball", "dif vs hoy (IC95)", "cobertura"))
    for nom in VARIANTES:
        cob, pin = float(tabla["d_" + nom].mean()), float(tabla["p_" + nom].mean())
        if nom == "hoy":
            print("  {:<12} {:>12.5f} {:>26} {:>10.1f}%".format(nom, pin, "-", 100 * cob))
            continue
        dif = tabla["p_" + nom] - tabla["p_hoy"]
        med, lo, hi = ic(dif.to_numpy(float), tabla["empresa"].to_numpy(), rng)
        print("  {:<12} {:>12.5f} {:>10.5f} [{:+.5f},{:+.5f}] {:>10.1f}%".format(
            nom, pin, med, lo, hi, 100 * cob))

    afecta = tabla["d_R05"] != tabla["d_hoy"]
    if int(afecta.sum()) >= 20:
        print("\n  restringido a los votos donde R05 actua:")
        sub = tabla[afecta]
        for nom in ("R05", "R10", "R05_plac"):
            dif = sub["p_" + nom] - sub["p_hoy"]
            med, lo, hi = ic(dif.to_numpy(float), sub["empresa"].to_numpy(), rng)
            print("  {:<12} {:>12.5f} {:>10.5f} [{:+.5f},{:+.5f}]".format(
                nom, float(sub["p_" + nom].mean()), med, lo, hi))

    print("\n" + LINEA)
    print("LECTURA: se adopta si la cobertura sube, el IC de R05 no queda entero sobre")
    print("cero, y el de R05_plac SI. Si R05 y R10 dan lo mismo, el resultado no depende")
    print("de donde se ponga la raya, que es lo que se quiere de un umbral relativo.")
    print(LINEA)


def main():
    SAL.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] in VARIANTES:
        una_variante(sys.argv[1])
        return
    for nom in VARIANTES:
        if (SAL / "12_{}.parquet".format(nom)).exists():
            print("{:<12} ya estaba.".format(nom), flush=True)
            continue
        print("{:<12} corriendo...".format(nom), flush=True)
        r = subprocess.run([sys.executable, __file__, nom])
        if r.returncode:
            print("  fallo con codigo {}".format(r.returncode))
            return
    juntar()


if __name__ == "__main__":
    main()
