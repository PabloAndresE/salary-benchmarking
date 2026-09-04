"""La banda, en dolares y contra la gente de verdad.

No mide nada nuevo: pone lado a lado la banda que el producto entrega y la distribucion
real de sueldos de ese cargo, para poder contar a mano cuanta gente cae dentro. Es la
version legible de lo que `02` reporto como porcentaje de cobertura.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import componentes_varianza

SEM = 20260805
Z50 = 0.6745
CASOS = ["AUXILIAR DE LIMPIEZA", "CONTADOR", "GERENTE GENERAL"]


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))
    tau2_g, sigma2_g = componentes_varianza(train, "cargo_norm")
    sbu = float(s.get_sbu(2025))
    dol = lambda v: np.exp(v) * sbu
    rng = np.random.default_rng(SEM)

    print(f"SBU 2025 = ${sbu:.0f}   tau global = {np.sqrt(tau2_g):.4f}  "
          f"sigma global = {np.sqrt(sigma2_g):.4f}")

    for cargo in CASOS:
        d = train[train.cargo_norm.astype(str) == cargo]
        y = pd.to_numeric(d["y"], errors="coerce").dropna().to_numpy(float)
        if len(y) < 50:
            print(f"\n{cargo}: solo {len(y)} personas, se salta")
            continue

        # el centro que da el producto: mediana de las medianas por empresa
        voto = d.groupby("empresa_ruc")["y"].median().dropna().to_numpy(float)
        mu = float(np.median(voto))

        print("\n" + "=" * 76)
        print(f"{cargo}   —   {len(y):,} personas en {len(voto):,} empresas")
        print("=" * 76)

        print("\n  LO QUE PAGA EL MERCADO DE VERDAD (percentiles reales):")
        for q in (0.05, 0.25, 0.50, 0.75, 0.95):
            print(f"    p{int(q*100):02d}  ${dol(np.quantile(y, q)):>9,.0f}")

        # banda con tau y sigma GLOBALES (lo que hace el producto hoy)
        sd_g = np.sqrt(tau2_g + sigma2_g)
        lo_g, hi_g = dol(mu - Z50 * sd_g), dol(mu + Z50 * sd_g)
        dentro_g = float(((y >= mu - Z50 * sd_g) & (y <= mu + Z50 * sd_g)).mean())

        # banda con tau y sigma DE ESE CARGO
        emp = d.groupby("empresa_ruc")["y"]
        n_f = emp.size().to_numpy(float)
        ssw = float(((d["y"] - d.groupby("empresa_ruc")["y"].transform("mean")) ** 2).sum())
        sigma2_c = ssw / max(1.0, len(y) - len(voto))
        gran = float(np.average(emp.mean().to_numpy(float), weights=n_f))
        ssb = float((n_f * (emp.mean().to_numpy(float) - gran) ** 2).sum())
        n0 = (n_f.sum() - (n_f ** 2).sum() / n_f.sum()) / (len(n_f) - 1)
        tau2_c = max(0.0, (ssb / (len(n_f) - 1) - sigma2_c) / n0)
        sd_c = np.sqrt(tau2_c + sigma2_c)
        lo_c, hi_c = dol(mu - Z50 * sd_c), dol(mu + Z50 * sd_c)
        dentro_c = float(((y >= mu - Z50 * sd_c) & (y <= mu + Z50 * sd_c)).mean())

        print(f"\n  LA BANDA QUE DAMOS HOY (tau y sigma globales):")
        print(f"    ${lo_g:>9,.0f}  —  ${dol(mu):>9,.0f}  —  ${hi_g:>9,.0f}")
        print(f"    decimos que contiene el 50%.  contiene el {dentro_g:.1%}")

        print(f"\n  LA BANDA CON tau Y sigma DE ESTE CARGO "
              f"(tau={np.sqrt(tau2_c):.3f}, sigma={np.sqrt(sigma2_c):.3f}):")
        print(f"    ${lo_c:>9,.0f}  —  ${dol(mu):>9,.0f}  —  ${hi_c:>9,.0f}")
        print(f"    contiene el {dentro_c:.1%}")

        print(f"\n  20 PERSONAS AL AZAR DE ESTE CARGO (dentro/fuera de la banda de hoy):")
        muestra = rng.choice(y, 20, replace=False)
        for v in np.sort(muestra):
            marca = "dentro" if lo_g <= dol(v) <= hi_g else "FUERA"
            print(f"    ${dol(v):>9,.0f}   {marca}")
        print(f"    -> {sum(1 for v in muestra if lo_g <= dol(v) <= hi_g)}/20 dentro "
              f"(deberian ser 10/20)")


if __name__ == "__main__":
    main()
