"""Pasa las filas APROBADAS de las listas de `36` a los diccionarios de la capa 0. D-040.

El autor revisa `36_aprobar_erratas.csv`, `36_aprobar_abreviaturas.csv` y
`36_aprobar_genero.csv` (columna `aprobar` = si / no) hasta el 95 % de las personas. Solo las
filas con `si` pasan a `src/benchmarking/producto/datos/capa0_<version>/`; lo vacio y lo `no`
no se aplica. Se niega a escribir si hay valores raros en `aprobar`.

USO
    python 37_exportar_capa0.py            (version v1)
"""
import pathlib
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
VERSION = sys.argv[1] if len(sys.argv) > 1 else "v1"
DESTINO = RAIZ / "src" / "benchmarking" / "producto" / "datos" / "capa0_{}".format(VERSION)
LISTAS = [("36_aprobar_erratas.csv", "erratas.csv", ["rara", "corregida"]),
          ("36_aprobar_abreviaturas.csv", "abreviaturas.csv", ["abreviatura", "expansion"]),
          ("36_aprobar_genero.csv", "genero.csv", ["femenino", "masculino"])]


def main():
    DESTINO.mkdir(parents=True, exist_ok=True)
    for origen, destino, cols in LISTAS:
        d = pd.read_csv(SAL / origen, dtype=str, keep_default_na=False)
        a = d["aprobar"].str.strip().str.lower()
        raros = sorted(set(a) - {"", "si", "no"})
        if raros:
            raise SystemExit("ALTO: `aprobar` en {} solo admite si / no / vacio: {}".format(
                origen, raros))
        ok = d[a == "si"][cols]
        ok.to_csv(DESTINO / destino, index=False, encoding="utf-8")
        p = pd.to_numeric(d["personas_estimadas"], errors="coerce")
        print("{:<30} revisadas {:>4} de {:>4}  aprobadas {:>4}  personas cubiertas por lo "
              "revisado {:.0%}".format(origen, int((a != "").sum()), len(d), len(ok),
                                      p[a != ""].sum() / p.sum()))
    print("-> {}".format(DESTINO))


if __name__ == "__main__":
    main()
