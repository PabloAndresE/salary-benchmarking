"""ANCLAR LA REFERENCIA A LA PROPIA EMPRESA DEL CLIENTE.

El banco evalua con leave-company-out: se predice a alguien de una empresa de la que no se
sabe NADA. Bajo ese supuesto el efecto empresa (tau2 = 0,0851, el 64% de la varianza
predictiva) es irreducible.

Pero en produccion ese supuesto es falso: **el cliente entrega su nomina completa**. Se
puede estimar el nivel salarial de ESA empresa con los empleados cuyo puesto si se empareja,
y usarlo para los que no.

  Sin anclaje:  yhat_i = mu_c(i)                     (solo el mercado)
  Con anclaje:  yhat_i = mu_c(i) + k * a_barra_f     (mercado + nivel de su empresa)

donde `a_barra_f` es el residuo medio de sus COMPANEROS —nunca el suyo— y `k` es el
encogimiento de efectos aleatorios, k = n/(n + sigma2/tau2).

QUE NO ES CIRCULAR, y por que:
- `mu_c` se construye SOLO con empresas de train. La empresa de test no participa.
- `a_barra_f` excluye a la persona evaluada (leave-one-person-out dentro de su empresa).
- El agrupamiento sigue sin ver salarios en ningun momento.

Es OTRA TAREA, y hay que reportarla como tal: no "cuanto paga el mercado por este puesto"
sino "dada la forma en que esta empresa paga los puestos que reconozco, cuanto deberia pagar
los que no". Es equidad interna, y es lo que el producto hace de verdad.

OJO: mejora la PRECISION, no la cobertura. Quien no tiene referencia de mercado para su
celda sigue sin tenerla; el anclaje solo corrige el nivel de quien si la tiene.
"""
import argparse

import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import (aplicar_abstencion, componentes_varianza,
                                                predecir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--celda", default="cargo_norm")
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, test = splits.partir(m, splits.empresas_test(m))
    print(f"train {len(train):,} filas / {train.empresa_ruc.nunique():,} empresas")
    print(f"test  {len(test):,} filas / {test.empresa_ruc.nunique():,} empresas")

    tau2, sigma2 = componentes_varianza(train, args.celda)
    print(f"\ntau2 = {tau2:.4f} (sd {np.sqrt(tau2):.4f})   "
          f"sigma2 = {sigma2:.4f} (sd {np.sqrt(sigma2):.4f})")
    print(f"el efecto empresa es el {tau2/(tau2+sigma2):.0%} del ruido irreducible")

    # --- referencia de mercado, construida SOLO con train ---
    pred = predecir(train, test, args.celda, tau2=tau2, sigma2=sigma2)
    t = test.copy()
    t["mercado"] = aplicar_abstencion(pred).to_numpy(float)
    t["y"] = pd.to_numeric(t["y"], errors="coerce")
    t["res"] = t["y"] - t["mercado"]          # NaN donde no hay referencia
    cubierto = t["res"].notna()
    print(f"\ncobertura de la referencia de mercado: {cubierto.mean():.1%} "
          f"({int(cubierto.sum()):,} personas)")

    # --- anclaje: residuo medio de los COMPANEROS, sin la persona ---
    g = t.groupby("empresa_ruc")["res"]
    suma = g.transform("sum")
    cuenta = g.transform("count")
    n_otros = (cuenta - cubierto.astype(int)).clip(lower=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        media_otros = (suma - t["res"].fillna(0.0)) / n_otros.replace(0, np.nan)
    # encogimiento de efectos aleatorios: k = n/(n + sigma2/tau2)
    razon = sigma2 / tau2 if tau2 > 0 else np.inf
    k = n_otros / (n_otros + razon)
    t["ancla"] = (k * media_otros).fillna(0.0)
    t["anclado"] = t["mercado"] + t["ancla"]

    ok = cubierto & t["y"].notna()
    mae_mer = float((t.loc[ok, "y"] - t.loc[ok, "mercado"]).abs().mean())
    mae_anc = float((t.loc[ok, "y"] - t.loc[ok, "anclado"]).abs().mean())
    print(f"\n{'='*64}\nRESULTADO (sobre las {int(ok.sum()):,} personas con referencia)\n{'='*64}")
    print(f"  MAE solo mercado                 = {mae_mer:.4f}")
    print(f"  MAE mercado + ancla de su empresa= {mae_anc:.4f}")
    print(f"  -> MEJORA = {1 - mae_anc/mae_mer:.1%}")
    print(f"\n  (para comparar: el techo por agrupar mejor era 10,9%)")

    print(f"\n=== POR NUMERO DE COMPANEROS CON REFERENCIA ===")
    t["_n"] = n_otros
    cortes = [(0,0),(1,4),(5,19),(20,99),(100,10**9)]
    print(f"{'companeros':>14} {'personas':>10} {'MAE mercado':>12} {'MAE anclado':>12} {'mejora':>8}")
    for a, b in cortes:
        sel = ok & (t["_n"] >= a) & (t["_n"] <= b)
        if sel.sum() < 500:
            continue
        mm = float((t.loc[sel, "y"] - t.loc[sel, "mercado"]).abs().mean())
        ma = float((t.loc[sel, "y"] - t.loc[sel, "anclado"]).abs().mean())
        et = f"{a}-{b}" if b < 10**9 else f"{a}+"
        print(f"{et:>14} {int(sel.sum()):>10,} {mm:>12.4f} {ma:>12.4f} "
              f"{1-ma/mm:>7.1%}")

    print("\n=== SANIDAD ===")
    print(f"  ancla estimada: media={t.loc[ok,'ancla'].mean():+.4f}  "
          f"sd={t.loc[ok,'ancla'].std():.4f}")
    print(f"  sd del efecto empresa real (tau) = {np.sqrt(tau2):.4f}")
    print("  -> si la sd del ancla se acerca a tau, el anclaje esta capturando el efecto")
    print("\nRecordatorio: esto NO mejora la cobertura, solo la precision de quien ya")
    print("tenia referencia. Y es OTRA TAREA — equidad interna, no nivel de mercado.")


if __name__ == "__main__":
    main()
