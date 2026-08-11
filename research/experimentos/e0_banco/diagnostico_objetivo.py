"""Diagnostico del objetivo antes de construir nada encima.

Tres preguntas, una consulta:
  1. Que fraccion de `y` esta exactamente en 0 (sueldo == SBU)?
  2. Como se reparte esa masa entre celdas de CARGO?
  3. Cuantas personas y cuantas empresas tiene la celda tipica de CARGO?

Por que va ANTES que todo lo demas. `sueldo_bajo_sbu` esta en cuarentena, asi que
`y = log(sueldo/SBU) >= 0` esta censurada por abajo con masa puntual en cero. Si esa masa
supera el 50% en muchas celdas, la mediana de casi cualquier celda vale 0 —incluida la de
la particion ALEATORIA— y el piso de la escalera sube hasta tocar al arquetipo. El banco
mediria un artefacto de censura y lo llamaria senal.

Si sale alto, hay que decidir el tratamiento AQUI, antes de mirar el test, y sin comparar
cual de las opciones favorece al arquetipo.
"""
import argparse

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anios", default="2024,2025")
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    anios = tuple(int(a) for a in args.anios.split(","))
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=anios), s))

    y = m["y"].to_numpy(float)
    en_cero = np.isclose(y, 0.0, atol=1e-9)
    print(f"filas evaluables      : {len(m):,}")
    print(f"empresas              : {m['empresa_ruc'].nunique():,}")
    print(f"y == 0 (sueldo == SBU): {en_cero.mean():.2%}")
    print(f"y <= 0,05             : {(y <= 0.05).mean():.2%}")
    print(f"cuantiles de y        : "
          f"{np.round(np.percentile(y, [1, 10, 25, 50, 75, 90, 99]), 3).tolist()}")
    print(f"por anio              :")
    print(m.assign(_c=en_cero).groupby("anio_valoracion")["_c"]
           .agg(filas="size", en_cero="mean").round(4).to_string())

    por_celda = m.assign(_c=en_cero).groupby("cargo_norm")["_c"].agg(["mean", "size"])
    grandes = por_celda[por_celda["size"] >= 5]
    print(f"\nceldas de CARGO con >=5 personas : {len(grandes):,}")
    print(f"  ...de ellas, con >50% en el SBU : {(grandes['mean'] > 0.5).mean():.2%}")
    print(f"  ...con >90% en el SBU           : {(grandes['mean'] > 0.9).mean():.2%}")

    tam = m.groupby("cargo_norm").size()
    emp = m.groupby("cargo_norm")["empresa_ruc"].nunique()
    print(f"\netiquetas de CARGO distintas : {len(tam):,}")
    print(f"tamano de celda   mediana={tam.median():.0f}  p90={tam.quantile(.9):.0f}  "
          f"max={tam.max():,}")
    print(f"empresas por celda mediana={emp.median():.0f}  p90={emp.quantile(.9):.0f}")
    print(f"celdas con >=3 empresas : {(emp >= 3).mean():.2%}  "
          f"(personas cubiertas: {tam[emp >= 3].sum() / tam.sum():.2%})")
    print(f"celdas de una sola persona : {(tam == 1).sum():,} "
          f"({(tam == 1).mean():.2%} de las etiquetas)")

    print("\nLECTURA: si mas de la mitad de las celdas grandes tienen mas de la mitad de "
          "su gente en el SBU, la mediana de casi cualquier particion vale 0 y el piso de "
          "la escalera es un artefacto. Decidir el tratamiento AQUI y escribirlo en el "
          "pre-registro.")


if __name__ == "__main__":
    main()
