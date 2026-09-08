""".Cambia la banda de un puesto segun como se parta el mercado?

    python research/herramientas/banda_por_tamano.py "LABORATORISTA"
    python research/herramientas/banda_por_tamano.py "CONTADOR" --por sector

Tres dimensiones, y las tres estan medidas con resultados DISTINTOS. Conviene saberlo
antes de leer la salida:

  --por tamano     `e3_varianza/09`: sesga MUCHO en los cargos altos (GERENTE GENERAL:
                   -56% en pequenas contra +82% en grandes) y NADA en los de base
                   (CHOFER, AUXILIAR DE LIMPIEZA). Montado como correccion del CENTRO
                   en cargos de escalon >=4 (D-018).
  --por sector     `07` y `16`: pierde para la banda e indistinguible de un placebo para
                   el centro (D-022). Montado solo como LENTE opcional (D-023). El sector
                   ya esta en el titulo donde importa: una petrolera tiene `PERFORADOR`
                   y una textilera `OPERARIO TEXTIL`, y lo que comparten —`CONTADOR`,
                   `CHOFER`— paga casi igual.
  --por provincia  sin medir.

Esta herramienta contesta la pregunta para un puesto concreto, en vez de fiarse del
patron general. Y el aviso que vale para las tres: **un desvio grande con pocas empresas
detras es ruido**, no senal — mirar siempre la columna `empresas` antes que el porcentaje.

Consulta acotada al cargo: no baja el millon de filas, solo las suyas.

La unidad es la EMPRESA, como en el producto: cada empresa vota con la mediana de su gente
y los cuantiles se calculan sobre esos votos. Una nomina de 400 laboratoristas cuenta una
vez.
"""
import argparse
import sys

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos

SQL = """
SELECT id_hash, empresa_ruc, numero_proceso, anio_valoracion,
       cargo_norm, centro_de_costo, sueldo, total,
       pct_fijo, pct_comisiones, pct_extras, pct_otros,
       antiguedad_total, tiene_composicion, en_clean,
       segmento, ciiu_n1, provincia, sexo
FROM `{proyecto}.{dataset}.nomina_features`
WHERE en_clean AND anio_valoracion IN (2024, 2025)
  AND UPPER(TRIM(cargo_norm)) IN ({cargos})
"""
ORDEN = ["MICROEMPRESA", "PEQUEÑA", "MEDIANA", "GRANDE", "NA"]
MIN_EMPRESAS = 3
DIMENSIONES = {"tamano": ("segmento", ORDEN),
               "sector": ("ciiu_n1", None),
               "provincia": ("provincia", None)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cargos", nargs="+")
    ap.add_argument("--anio", type=int, default=2025)
    ap.add_argument("--por", default="tamano", choices=sorted(DIMENSIONES),
                    help="dimension por la que partir el mercado")
    a = ap.parse_args()
    columna, orden_fijo = DIMENSIONES[a.por]

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    lista = ", ".join("'" + str(c).strip().upper().replace("'", "''") + "'"
                      for c in a.cargos)
    df = cl.query(SQL.format(proyecto=s.bq_project, dataset=s.bq_dataset,
                             cargos=lista)).to_dataframe()
    m = datos.marco_evaluable(datos.agregar_objetivo(df, s))
    if m.empty:
        print("sin filas evaluables")
        return 1
    m = m.copy()
    m["cargo_norm"] = m.cargo_norm.astype(str).str.upper().str.strip()
    m["_seg"] = m[columna].astype(str).fillna("NA")
    orden = orden_fijo or (sorted(x for x in m["_seg"].unique() if x != "NA") + ["NA"])
    f = float(s.get_sbu(a.anio))
    dol = lambda v: float(np.exp(v)) * f

    for cg in [str(c).strip().upper() for c in a.cargos]:
        d = m[m.cargo_norm == cg]
        if d.empty:
            print(f"\n{cg}: sin datos")
            continue
        # un voto por empresa: la mediana de su gente en ese cargo
        v = d.groupby(["empresa_ruc", "_seg"])["y"].agg(voto="median",
                                                        n="size").reset_index()
        print("\n" + "=" * 82)
        print(f"  {cg}  por {a.por.upper()}   -   {len(d):,} personas en {v.empresa_ruc.nunique():,} empresas")
        print("=" * 82)
        print(f"\n  {a.por:<14} {'empresas':>9} {'personas':>9} {'p25':>9} "
              f"{'mediana':>9} {'p75':>9} {'ancho':>8}")
        tot = v["voto"]
        pt = np.quantile(tot, [0.25, 0.5, 0.75])
        for g in orden:
            vg = v[v._seg == g]
            if len(vg) < MIN_EMPRESAS:
                continue
            q = np.quantile(vg["voto"], [0.25, 0.5, 0.75])
            ng = int(d[d._seg == g].shape[0])
            print(f"  {g:<14} {len(vg):>9,} {ng:>9,} ${dol(q[0]):>8,.0f} "
                  f"${dol(q[1]):>8,.0f} ${dol(q[2]):>8,.0f} "
                  f"{dol(q[2])/dol(q[0]):>7.2f}x")
        print(f"  {'TODOS (hoy)':<14} {len(v):>9,} {len(d):>9,} ${dol(pt[0]):>8,.0f} "
              f"${dol(pt[1]):>8,.0f} ${dol(pt[2]):>8,.0f} "
              f"{dol(pt[2])/dol(pt[0]):>7.2f}x")

        # .cuanto se desvia la mediana de cada grupo de la global?
        print(f"\n  desvio de la mediana de cada {a.por} contra la referencia global:")
        hay = False
        for g in orden:
            vg = v[v._seg == g]
            if len(vg) < MIN_EMPRESAS:
                continue
            hay = True
            dev = float(np.median(vg["voto"])) - float(pt[1])
            print(f"    {g:<14} {np.exp(dev) - 1:>+8.1%}")
        if hay:
            # `NA` FUERA DEL RECORRIDO: no es un valor de la dimension, es dato
            # faltante. Meterlo inventa una diferencia entre "empresas sin dato" y las
            # demas que no significa nada sobre la dimension.
            meds = [float(np.median(v[v._seg == g]["voto"])) for g in orden[:-1]
                    if len(v[v._seg == g]) >= MIN_EMPRESAS]
            if len(meds) > 1:
                print(f"    {'recorrido':<14} {np.exp(max(meds) - min(meds)) - 1:>8.1%}"
                      f"   (sin contar NA, que es dato faltante)")
            else:
                print(f"    {'recorrido':<14} {'-':>8}   (menos de dos grupos con "
                      f"{MIN_EMPRESAS}+ empresas: no se puede segmentar este puesto)")
            print(f"\n  (si el recorrido es pequeno, partir por {a.por} no cambia nada")
            print("   para este puesto; si es grande, la referencia global miente a los")
            print("   extremos. OJO: un desvio grande con POCAS EMPRESAS detras es ruido,")
            print("   no senal — mirar la columna `empresas` antes que el porcentaje)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
