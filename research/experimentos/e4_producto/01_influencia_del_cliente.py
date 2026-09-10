""".Cuanto se mueve el mercado cuando saco al cliente de el?

EL PROBLEMA. El cliente sube su nomina y le decimos donde esta respecto al mercado. Si su
empresa participo en los estudios con los que se construyo la base, se esta comparando
CONTRA SI MISMO: su propio sueldo entra en la mediana que le sirve de referencia. Cuanto
mas pequeno el cargo, mas pesa su voto, y en el limite le diriamos "estas en la mediana"
porque el ES la mediana.

LO QUE NO SE PUEDE HACER, Y POR QUE. El centro de cada celda es una MEDIANA PONDERADA de
los votos por empresa. De una mediana no se puede restar un voto: con `m` y `W` guardados
no hay forma de recuperar `m` sin la empresa f. Haria falta guardar la lista de votos por
celda —el sueldo mediano de CADA empresa en CADA cargo, 161.049 pares—, y eso convierte
el artefacto en una tabla de "que paga la empresa X por el cargo Y". Es exactamente el
dato que los suelos de confidencialidad existen para no publicar. Antes de pagar ese
precio hay que saber que se compra.

LA PREGUNTA MEDIBLE. .Cuanto mueve el centro quitar UNA empresa, comparado con la
incertidumbre que el informe YA declara sobre ese centro?

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
Se compara |m_sin_f - m_con_f| contra `sd(centro) = sqrt(tau2_c + 1/W)`, que es la barra
de error que el informe ya muestra. Esa es la escala honesta: si el desplazamiento cabe
dentro de la imprecision publicada, excluir al cliente esta corrigiendo ruido.

SE CONSTRUYE la exclusion exacta (y se paga el coste de guardar los votos) si y solo si:
    la MEDIANA de |Dm| / sd(centro) supera 0,20 en las celdas que pasan el suelo de banda
    empirica (emp >= 10).

SI NO LO SUPERA, la respuesta correcta de producto es la barata, y se declara asi:
    (a) detectar que el cliente esta en la celda —exacto, con el padron—,
    (b) NEGARSE a leer el cargo si al quitarlo la celda cae por debajo del suelo,
    (c) reportar su influencia `w_cliente / W` en vez de fingir que se le quito.

SECUNDARIO, se reporta y NO decide:
    - .predice `w_f/W` el desplazamiento real? Si la correlacion es alta, reportar la
      influencia es un sustituto defendible de lo que no se puede calcular. Si es baja,
      reportarla es teatro y hay que decirlo.
    - cuantas veces quitar una empresa deja la celda bajo el suelo. Ese es el caso que de
      verdad importa y no necesita esta medicion: sale del padron.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import gc

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import (componentes_varianza,
                                                sigma2_por_celda, tabla_votos,
                                                tau2_por_celda)

SEM = 20260805
COL = "cargo_norm"
CELDAS_POR_TRAMO = 300      # muestreo estratificado: la medicion no necesita las 65.081
TRAMOS = [(3, 5), (5, 10), (10, 20), (20, 50), (50, 200), (200, 10 ** 9)]
UMBRAL = 0.20               # criterio primario, declarado arriba
SUELO_BANDA = 10            # MIN_EMPRESAS_BANDA, el suelo de la banda empirica
MAX_QUITAR = 60             # remociones probadas por celda; ver `loo_de_una_celda`


def mediana_ponderada(v, w):
    """El MISMO estimador que el centro: `cumsum(w) - w/2`, normalizado, interpolado en
    0,5. Reimplementado aqui a proposito —en vez de llamar al vectorizado de
    `referencia.py`— para que la medicion no herede un posible error del codigo que esta
    midiendo."""
    o = np.argsort(v, kind="mergesort")
    v, w = v[o], w[o]
    acum = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(0.5, acum, v))


def loo_de_una_celda(v, w, rng, max_quitar=MAX_QUITAR):
    """|Dm| al quitar cada empresa, una a una. Devuelve (desplazamientos, peso relativo).

    En celdas grandes NO se prueban todas las empresas: el coste es O(n^2) y hay celdas
    con miles. Se sortean `max_quitar` al azar. Cada remocion sigue siendo EXACTA —lo que
    se muestrea es a quien se quita, no como se calcula—, y como el estadistico de interes
    es la distribucion de |Dm| dentro del tramo, muestrear empresas dentro de la celda o
    celdas dentro del tramo da lo mismo. Lo que si haria es sesgar si se eligieran las
    empresas por peso, asi que se eligen uniformes."""
    m0 = mediana_ponderada(v, w)
    total = w.sum()
    n = len(v)
    quienes = (np.arange(n) if n <= max_quitar
               else rng.choice(n, max_quitar, replace=False))
    d = np.empty(len(quienes))
    for i, k in enumerate(quienes):
        keep = np.ones(n, bool)
        keep[k] = False
        d[i] = abs(mediana_ponderada(v[keep], w[keep]) - m0)
    return d, w[quienes] / total


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    # `segmento` y `ciiu_n1` NO se usan aqui, pero `empresas_test` estratifica por ellos
    # y sin ellos el split no es el mismo que el de produccion. Se sueltan despues.
    mk = mk[[c for c in (COL, "empresa_ruc", "y", "segmento", "ciiu_n1")
             if c in mk.columns]].copy()
    mk[COL] = mk[COL].astype(str)
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    train = train[[COL, "empresa_ruc", "y"]]
    del mk
    gc.collect()
    print(f"train: {len(train):,} filas, {train.empresa_ruc.nunique():,} empresas")

    tau2, sigma2 = componentes_varianza(train, COL)
    s2c, _ = sigma2_por_celda(train, COL, sigma2_global=sigma2)
    t2c, _ = tau2_por_celda(train, COL, s2c, tau2_global=tau2)
    v = tabla_votos(train, COL, tau2=tau2, sigma2=sigma2,
                    sigma2_celda=s2c, tau2_celda=t2c)
    print(f"votos: {len(v):,} pares (celda, empresa) sobre {v[COL].nunique():,} celdas")

    emp = v.groupby(COL, sort=False).size()
    rng = np.random.default_rng(SEM)
    filas = []
    for lo, hi in TRAMOS:
        cand = emp[(emp >= lo) & (emp < hi)].index.to_numpy()
        if len(cand) == 0:
            continue
        elegidas = rng.choice(cand, min(CELDAS_POR_TRAMO, len(cand)), replace=False)
        sub = v[v[COL].isin(set(elegidas))]
        etiqueta = f"{lo}-{hi}" if hi < 10 ** 9 else f"{lo}+"
        for celda, g in sub.groupby(COL, sort=False):
            vv = g["voto"].to_numpy(float)
            ww = g["w"].to_numpy(float)
            if len(vv) < 2:
                continue
            d, rel = loo_de_una_celda(vv, ww, rng)
            # La barra de error que el informe YA declara sobre este centro.
            sd = np.sqrt(float(t2c.get(celda, tau2)) + 1.0 / ww.sum())
            filas.append(pd.DataFrame({"tramo": etiqueta, "emp": len(vv),
                                       "dm": d, "sd": sd, "peso_rel": rel}))
        print(f"  tramo {etiqueta}: {len(elegidas):,} celdas")

    r = pd.concat(filas, ignore_index=True)
    r["ratio"] = r["dm"] / r["sd"]

    print("\n" + "=" * 78)
    print("DESPLAZAMIENTO DEL CENTRO AL QUITAR UNA EMPRESA, EN UNIDADES DE sd(centro)")
    print("=" * 78)
    t = (r.groupby("tramo", sort=False)
          .agg(pares=("ratio", "size"), celdas=("emp", "size"),
               ratio_p50=("ratio", "median"),
               ratio_p90=("ratio", lambda x: x.quantile(0.90)),
               dm_p50_log=("dm", "median"),
               peso_p50=("peso_rel", "median"),
               peso_p90=("peso_rel", lambda x: x.quantile(0.90))))
    print(t.round(4).to_string())

    arriba = r[r["emp"] >= SUELO_BANDA]
    p50 = float(arriba["ratio"].median())
    print(f"\nPRIMARIA (celdas con emp >= {SUELO_BANDA}): mediana |Dm|/sd = {p50:.4f}")
    print(f"CRITERIO: se construye la exclusion exacta si > {UMBRAL}")
    print(f"VEREDICTO: {'SE CONSTRUYE' if p50 > UMBRAL else 'NO se construye'}")

    # Secundario: .es `w_f/W` un sustituto util de lo que no se puede calcular?
    sp = arriba[["peso_rel", "ratio"]].corr(method="spearman").iloc[0, 1]
    print(f"\nSECUNDARIO  Spearman(w_f/W, |Dm|/sd) sobre emp>={SUELO_BANDA}: {sp:.3f}")
    print("  alto -> reportar la influencia sustituye a lo que no se puede restar")
    print("  bajo -> reportarla es teatro, y hay que decirlo")

    # Secundario: el caso que de verdad importa, y que no necesita esta medicion
    bajo = float((emp[emp >= SUELO_BANDA] - 1 < SUELO_BANDA).mean())
    print(f"\nSECUNDARIO  celdas con emp>={SUELO_BANDA} que caen BAJO EL SUELO al quitar "
          f"una: {bajo:.1%}")

    r.to_parquet("research/experimentos/e4_producto/01_influencia.parquet")
    print("\nfilas guardadas en 01_influencia.parquet")


if __name__ == "__main__":
    main()
