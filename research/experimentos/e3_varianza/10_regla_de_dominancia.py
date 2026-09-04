"""El producto no aplica la regla de dominancia. .A cuanta gente le afecta?

EL HUECO. `evaluacion/referencia.py` define `SUELO_SHARE = 0,80` —la regla de dominancia
del QCEW, D-011— y `aplicar_abstencion` la usa. Pero `producto/base_referencia.py` solo
comprueba `emp >= MIN_EMPRESAS`:

    directo = propio is not None and self.emp[propio] >= MIN_EMPRESAS

Una celda con 3 empresas donde una tiene el 95% de la gente pasa ese filtro. Su mediana
ponderada esta dominada por esa empresa, asi que publicarla es publicar su nomina con otro
nombre. El suelo de 3 empresas existe justamente para que eso no pase, y por si solo no
basta: hace falta que ademas ninguna domine.

Es un hueco de CONFIDENCIALIDAD, no de precision, asi que no se decide por pinball.

QUE SE MIDE
  - cuantas celdas directas estan dominadas, y a cuanta gente contestan
  - con los pesos `w_f` de verdad (que es lo que manda en la mediana ponderada), no solo
    con el reparto de cabezas
  - que cargos concretos son, para ver si el problema es real o teorico

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import (SUELO_SHARE, componentes_varianza,
                                                sigma2_por_celda, tau2_por_celda)
from benchmarking.producto.base_referencia import MIN_EMPRESAS, MIN_EMPRESAS_BANDA


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    m = m.copy()
    m["cargo_norm"] = m.cargo_norm.astype(str)
    train, _ = splits.partir(m, splits.empresas_test(m))
    print(f"train {len(train):,} filas / {train.empresa_ruc.nunique():,} empresas / "
          f"{train.cargo_norm.nunique():,} cargos")

    tau2, sigma2 = componentes_varianza(train, "cargo_norm")
    s2c, _ = sigma2_por_celda(train, "cargo_norm", sigma2_global=sigma2)
    t2c, _ = tau2_por_celda(train, "cargo_norm", s2c, tau2_global=tau2)

    v = (train.dropna(subset=["y"])
              .groupby(["cargo_norm", "empresa_ruc"], sort=False)["y"]
              .agg(n="size").reset_index())
    t = v.cargo_norm.map(t2c).fillna(tau2).to_numpy(float)
    sg = v.cargo_norm.map(s2c).fillna(sigma2).to_numpy(float)
    den = t + sg / v["n"].to_numpy(float)
    v["w"] = np.where(den > 0, 1.0 / np.where(den > 0, den, 1.0), 1.0)

    g = v.groupby("cargo_norm").agg(emp=("n", "size"), personas=("n", "sum"),
                                    n_max=("n", "max"), w_sum=("w", "sum"),
                                    w_max=("w", "max"))
    g["share_pers"] = g.n_max / g.personas
    g["share_peso"] = g.w_max / g.w_sum
    directo = g[g.emp >= MIN_EMPRESAS]
    print(f"\nceldas con datos directos (>= {MIN_EMPRESAS} empresas): {len(directo):,}")

    print("\n" + "=" * 80)
    print(f"A. .CUANTAS ESTAN DOMINADAS?  (regla QCEW: una empresa > {SUELO_SHARE:.0%})")
    print("=" * 80)
    for nom, col in (("por PERSONAS", "share_pers"), ("por PESO en la mediana", "share_peso")):
        dom = directo[directo[col] > SUELO_SHARE]
        print(f"\n  dominancia {nom}")
        print(f"    celdas dominadas   {len(dom):>7,} de {len(directo):,} "
              f"({len(dom)/len(directo):>5.1%})")
        print(f"    personas afectadas {int(dom.personas.sum()):>7,} de "
              f"{int(directo.personas.sum()):,} "
              f"({dom.personas.sum()/directo.personas.sum():>5.1%})")
        # las que ademas publican cuantiles empiricos son las mas expuestas
        dom_q = dom[dom.emp >= MIN_EMPRESAS_BANDA]
        print(f"    de esas, con banda EMPIRICA (>= {MIN_EMPRESAS_BANDA} empresas): "
              f"{len(dom_q):,} celdas, {int(dom_q.personas.sum()):,} personas")

    print("\n" + "=" * 80)
    print("B. REPARTO DEL PESO DE LA EMPRESA MAYOR EN CELDAS DIRECTAS")
    print("=" * 80)
    for q in (0.50, 0.75, 0.90, 0.95, 0.99, 1.00):
        print(f"  p{int(q*100):<3} personas {directo.share_pers.quantile(q):>6.1%}   "
              f"peso {directo.share_peso.quantile(q):>6.1%}")

    print("\n" + "=" * 80)
    print("C. LOS CASOS PEORES: celdas dominadas con mas gente detras")
    print("=" * 80)
    dom = directo[directo.share_peso > SUELO_SHARE].sort_values("personas",
                                                               ascending=False)
    print(f"  {'cargo':<44} {'emp':>4} {'pers':>7} {'mayor':>7} {'peso':>7}")
    for cg, r in dom.head(12).iterrows():
        print(f"  {cg[:43]:<44} {int(r.emp):>4} {int(r.personas):>7,} "
              f"{int(r.n_max):>7,} {r.share_peso:>6.1%}")

    print("\n" + "=" * 80)
    print("D. EL SUELO CUENTA EMPRESAS Y NO DICE NADA DE PERSONAS")
    print("=" * 80)
    print("  `MIN_EMPRESAS = 3` protege contra que una empresa se reconozca en el numero.")
    print("  Pero 3 empresas con una persona cada una son 3 PERSONAS, y la mediana de sus")
    print("  votos ES el sueldo de una de ellas. Eso el suelo de empresas no lo ve.")
    print()
    print(f"  {'personas en la celda':<24} {'celdas':>8} {'%':>7} {'con banda empirica':>20}")
    for lo, hi in ((3, 4), (5, 9), (10, 19), (20, 49), (50, 10 ** 9)):
        sel = directo[(directo.personas >= lo) & (directo.personas <= hi)]
        et = f"{lo}-{hi}" if hi < 10 ** 8 else f"{lo}+"
        print(f"  {et:<24} {len(sel):>8,} {len(sel)/len(directo):>6.1%} "
              f"{int((sel.emp >= MIN_EMPRESAS_BANDA).sum()):>19,}")
    finas = directo[directo.personas < 10]
    print(f"\n  celdas directas con menos de 10 personas: {len(finas):,} "
          f"({len(finas)/len(directo):.1%}), {int(finas.personas.sum()):,} personas")
    print(f"  de esas, con {MIN_EMPRESAS_BANDA}+ empresas y por tanto banda EMPIRICA: "
          f"{int((finas.emp >= MIN_EMPRESAS_BANDA).sum()):,}")

    print("\n" + "=" * 80)
    print("E. QUE PASARIA AL APLICAR LA REGLA DE DOMINANCIA POR PESO")
    print("=" * 80)
    dom = directo[directo.share_peso > SUELO_SHARE]
    print(f"  {len(dom):,} celdas dejarian de contestarse con datos propios y pasarian")
    print(f"  a contestarse por analogia. Eso afecta a {int(dom.personas.sum()):,} personas")
    print(f"  de la base ({dom.personas.sum()/int(directo.personas.sum()):.1%} de las que")
    print(f"  hoy reciben respuesta directa).")
    print()
    print("  No es una perdida de cobertura: se sigue respondiendo. Es que la respuesta")
    print("  deja de ser la nomina de una sola empresa disfrazada de mercado.")


if __name__ == "__main__":
    main()
