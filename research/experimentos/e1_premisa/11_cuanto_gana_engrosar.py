"""CUANTO SE GANA ENGROSANDO LAS CELDAS? El barrido de granularidad.

La pregunta del director, y es la pregunta central de la tesis puesta en su forma mas
simple: `CARGO` tiene 65.081 etiquetas con una mediana de 2 personas y 1 empresa. Si se
agrupan por significado en celdas mas gruesas, hay mas gente por celda y la mediana se
estima mejor. .Cuanto se gana con eso, y donde esta el punto optimo?

POR QUE ESTE EXPERIMENTO Y NO EL TECHO DE `04`. El techo del 10,9% de `04` mide una sola
cosa: dejar las celdas de `CARGO` como estan y arreglar SOLO la estimacion. Sus tau y
sigma se estiman DENTRO de las celdas de `CARGO`, asi que da por fijo el suelo que una
particion distinta puede mover. Y no dice nada de la COBERTURA, que es donde `CARGO` mas
falla: solo puede responder para el 66,6% de la gente.

Aqui se miden las tres cosas a la vez, barriendo k:

  - error entre los que reciben respuesta (MAE),
  - cobertura (que fraccion la recibe),
  - riesgo generalizado, que es el unico numero que las combina con denominador comun.

El barrido va de k=50 hasta la propia `CARGO` (65.081 celdas). Si la intuicion es
correcta, deberia verse una U: demasiado grueso mezcla puestos distintos, demasiado fino
deja las celdas vacias, y en medio esta el optimo.

TODO SOBRE TRAIN. El 20% de test no se toca: se parte el train en dos por empresa.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.cluster import MiniBatchKMeans

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.evaluacion.metricas import augrc, curva_riesgo, error_y_cobertura
from benchmarking.evaluacion.referencia import aplicar_abstencion, predecir

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
REJILLA = (50, 200, 1000, 5000, 20000)
MUESTRA_EMPRESAS = 1200


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))

    rng = np.random.default_rng(SEM)
    emp = np.array(sorted(train.empresa_ruc.unique()))
    if len(emp) > MUESTRA_EMPRESAS:
        emp = rng.choice(emp, MUESTRA_EMPRESAS, replace=False)
    d = train[train.empresa_ruc.isin(emp)].reset_index(drop=True)

    # segunda particion por empresa DENTRO del train: fuera de muestra de verdad
    val = set(rng.choice(emp, max(1, len(emp) // 4), replace=False))
    tr = d[~d.empresa_ruc.isin(val)].reset_index(drop=True)
    ts = d[d.empresa_ruc.isin(val)].reset_index(drop=True)
    print(f"train {len(tr):,} filas / {tr.empresa_ruc.nunique()} empresas")
    print(f"eval  {len(ts):,} filas / {ts.empresa_ruc.nunique()} empresas")
    print(f"etiquetas de CARGO en train: {tr.cargo_norm.nunique():,}")

    cache = embeddings.CacheArchivo(s.gcs_cache_embeddings or CACHE)
    cliente = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                        s.vertex_location)
    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    print(f"embebiendo {len(etiquetas):,} etiquetas unicas...")
    E = embeddings.embeber(etiquetas, cliente, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    pos = {e: i for i, e in enumerate(etiquetas)}

    def evaluar(nombre, col_tr, col_ts, n_celdas):
        t = tr.assign(_c=np.asarray(col_tr, dtype=str))
        v = ts.assign(_c=np.asarray(col_ts, dtype=str))
        p = predecir(t, v, "_c")
        r = error_y_cobertura(v, aplicar_abstencion(p))
        a = augrc(curva_riesgo(v, p))
        # CUIDADO: `mae * cobertura` es el riesgo generalizado con COSTE CERO por
        # callarse, y por tanto PREMIA abstenerse: quien no responde no paga nada.
        # Con esa cuenta CARGO "gana" por el mero hecho de callarse para el 46% de
        # la gente. Lo comparable es el riesgo a un coste c > 0, y el numero que
        # decide es el c donde se cruzan las curvas: la frontera A/B de D-004.
        print(
              f"{nombre:<26} {n_celdas:>8,} {r['cobertura']:>9.1%} "
              f"{r['mae']:>9.4f} {a:>9.4f}")
        return {"metodo": nombre, "celdas": n_celdas, "cobertura": r["cobertura"],
                "mae": r["mae"], "augrc": a}

    print("\n" + "=" * 78)
    print("BARRIDO DE GRANULARIDAD")
    print("=" * 78)
    print(f"{'metodo':<26} {'celdas':>8} {'cobertura':>9} {'MAE':>9} {'AUGRC':>9}")
    print("-" * 78)

    filas = [evaluar("CARGO crudo (baseline)", tr.cargo_norm, ts.cargo_norm,
                     tr.cargo_norm.nunique())]

    X = E[[pos[e] for e in etiquetas]]
    for k in REJILLA:
        if k >= len(etiquetas):
            continue
        km = MiniBatchKMeans(n_clusters=k, random_state=SEM, n_init=3,
                             batch_size=4096).fit(X)
        mapa = {e: str(c) for e, c in zip(etiquetas, km.labels_)}
        filas.append(evaluar(f"texto agrupado k={k}", tr.cargo_norm.map(mapa),
                             ts.cargo_norm.map(mapa), k))

    f = pd.DataFrame(filas)
    base = f.iloc[0]
    print("\n" + "=" * 78)
    print("FRENTE AL BASELINE `CARGO CRUDO`")
    print("=" * 78)
    for _, r in f.iloc[1:].iterrows():
        print(f"  {r.metodo:<24} MAE {r.mae/base.mae-1:+7.1%}   "
              f"cobertura {r.cobertura-base.cobertura:+6.1%} pts")

    print()
    print("=" * 78)
    print("LA FRONTERA: a partir de que coste de NO RESPONDER gana engrosar?")
    print("=" * 78)
    print("  Riesgo(c) = MAE*cobertura + c*(1-cobertura), denominador N para todos.")
    print("  El c del cruce se lee en dolares: exp(c)-1 es el desvio equivalente de")
    print("  la respuesta que se acepta a cambio de no callarse.")
    print()
    print(f"  {'metodo':<24} {'c* del cruce':>13} {'en dolares':>12}")
    print("  " + "-" * 52)
    for _, r in f.iloc[1:].iterrows():
        den = r.cobertura - base.cobertura
        if den <= 0:
            continue
        c = (r.mae * r.cobertura - base.mae * base.cobertura) / den
        print(f"  {r.metodo:<24} {c:>13.4f} {np.exp(c)-1:>11.1%}")
    print()
    print("COMO SE LEE")
    print("  1. Engrosar NO mejora la precision: el MAE sube en todos los puntos.")
    print("     Mas gente por celda estima mejor la mediana, pero la celda gruesa")
    print("     mezcla puestos que pagan distinto, y gana el segundo efecto.")
    print("  2. Lo que compra engrosar es COBERTURA, y tiene un precio exacto: c*.")
    print("  3. El MAE a secas no decide, porque quien se calla mas acierta mas")
    print("     entre los que responde. Y MAE*cobertura tampoco: premia callarse.")
    print()
    print("AVISO DE MUESTRA: con 1.200 empresas CARGO cubre menos que sobre el")
    print("train completo (53,8% aqui frente a 66,6% real), asi que este barrido")
    print("FAVORECE a los metodos gruesos. Aun asi pierden en precision.")


if __name__ == "__main__":
    main()
