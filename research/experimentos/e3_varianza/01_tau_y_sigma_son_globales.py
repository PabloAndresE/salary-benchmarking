""".Tiene sentido un solo tau y un solo sigma para los 65.081 cargos?

LA OBJECION. `tau` es cuanto difieren dos personas del mismo cargo en empresas distintas,
y `sigma` cuanto difieren dentro de la misma empresa. Parece obvio que eso no puede ser
igual para `AUXILIAR DE LIMPIEZA` —donde el minimo legal comprime todo— que para
`GERENTE GENERAL`, donde el tamano de la empresa manda. Y sin embargo el estimador usa un
`tau` global para todos, y el producto usa ademas un `sigma` global.

El codigo justifica el `tau` global asi: "con el 76,6% de la gente en empresas de >=100,
estimar esto por celda anadiria ruido sin anadir informacion". Eso es un argumento de
varianza del estimador, no una prueba de que el parametro sea constante. Son dos cosas
distintas y aqui se separan.

QUE SE MIDE, EN TRES PASOS

  A. Se estima `tau_c` y `sigma_c` POR CELDA, en las celdas con datos de sobra (>=20
     empresas), con el mismo ANOVA desbalanceado que usa el estimador global.

  B. .Esa dispersion entre celdas es REAL o es ruido de estimacion? Test-retest: se
     parten las empresas de cada celda en dos mitades al azar y se estima en cada una por
     separado. Si `tau_c` fuese el mismo para todas las celdas y lo que vemos fuera ruido,
     las dos mitades NO correlacionarian. Si correlacionan, las celdas difieren de verdad.
     Es la misma logica de test-retest de la Tarea 11.

  C. Si difieren, .cuanto importa? Se traduce a lo unico que le llega al cliente: el suelo
     irreducible `sqrt(tau_c^2 + sigma_c^2)` y el ancho de banda en porcentaje.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits

SEM = 20260805
MIN_EMPRESAS = 20          # para que cada mitad del test-retest quede con >=10
CASOS = ["AUXILIAR DE LIMPIEZA", "CONTADOR", "GERENTE GENERAL", "VENDEDOR",
         "ASISTENTE CONTABLE", "TRABAJADOR AGRICOLA", "GUARDIA DE SEGURIDAD",
         "JEFE DE BODEGA", "CHOFER", "MEDICO OCUPACIONAL"]


def componentes_por_celda(cod_celda, cod_emp, y, n_celdas):
    """(tau2_c, sigma2_c, n_empresas, n_personas) por celda. ANOVA de un factor.

    El mismo modelo que `componentes_varianza`, pero resuelto dentro de cada celda en vez
    de agrupando todas. Vectorizado con bincount: un bucle por celda son miles de
    iteraciones de pandas, y ese error ya costo tres corridas en este proyecto.

        sigma2_c = SSW / (N - F)
        tau2_c   = max(0, (SSB/(F-1) - sigma2_c) / n0)
        n0       = (N - sum(n_f^2)/N) / (F - 1)
    """
    par = cod_celda.astype(np.int64) * (cod_emp.max() + 1) + cod_emp
    uni, pcod = np.unique(par, return_inverse=True)
    n_f = np.bincount(pcod)
    s_f = np.bincount(pcod, weights=y)
    q_f = np.bincount(pcod, weights=y * y)
    celda_de_par = (uni // (cod_emp.max() + 1)).astype(np.int64)

    # SSW: dentro de cada (celda, empresa). Ahi `u_f` es constante y se cancela.
    ssw_par = q_f - s_f ** 2 / n_f
    SSW = np.bincount(celda_de_par, weights=ssw_par, minlength=n_celdas)

    N = np.bincount(celda_de_par, weights=n_f, minlength=n_celdas)
    F = np.bincount(celda_de_par, minlength=n_celdas).astype(float)
    S = np.bincount(celda_de_par, weights=s_f, minlength=n_celdas)
    Q = np.bincount(celda_de_par, weights=s_f ** 2 / n_f, minlength=n_celdas)
    N2 = np.bincount(celda_de_par, weights=n_f ** 2.0, minlength=n_celdas)

    with np.errstate(invalid="ignore", divide="ignore"):
        SSB = Q - S ** 2 / N                       # entre empresas de la misma celda
        sigma2 = np.where(N > F, SSW / (N - F), np.nan)
        n0 = np.where(F > 1, (N - N2 / N) / (F - 1), np.nan)
        tau2 = np.where((F > 1) & (n0 > 0),
                        np.maximum(0.0, (SSB / (F - 1) - sigma2) / n0), np.nan)
    return tau2, sigma2, F, N


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))
    d = train[["cargo_norm", "empresa_ruc", "y"]].dropna(subset=["y"]).copy()
    d["cargo_norm"] = d.cargo_norm.astype(str)
    print(f"train {len(d):,} filas / {d.empresa_ruc.nunique():,} empresas / "
          f"{d.cargo_norm.nunique():,} cargos")

    cc, celdas = pd.factorize(d.cargo_norm, sort=True)
    ce, _ = pd.factorize(d.empresa_ruc, sort=True)
    y = d["y"].to_numpy(float)
    n_c = len(celdas)

    # -- global, como lo calcula el estimador hoy -----------------------------
    from benchmarking.evaluacion.referencia import componentes_varianza
    tau2_g, sigma2_g = componentes_varianza(train, "cargo_norm")
    suelo_g = np.sqrt(tau2_g + sigma2_g)
    anch = lambda sd: np.exp(0.6745 * sd) - 1
    print(f"\nGLOBAL (lo que se usa hoy):  tau={np.sqrt(tau2_g):.4f}  "
          f"sigma={np.sqrt(sigma2_g):.4f}  suelo={suelo_g:.4f}  banda=±{anch(suelo_g):.1%}")

    # -- A. por celda ----------------------------------------------------------
    tau2_c, sigma2_c, F, N = componentes_por_celda(cc, ce, y, n_c)
    ok = (F >= MIN_EMPRESAS) & np.isfinite(tau2_c) & np.isfinite(sigma2_c)
    print(f"\nceldas con >={MIN_EMPRESAS} empresas: {ok.sum():,} de {n_c:,} "
          f"({np.bincount(cc, minlength=n_c)[ok].sum() / len(d):.1%} de la gente)")

    tau_c, sig_c = np.sqrt(tau2_c), np.sqrt(sigma2_c)
    print("\n" + "=" * 74)
    print("A. .VARIA `tau` ENTRE CARGOS?")
    print("=" * 74)
    qs = [0.05, 0.25, 0.50, 0.75, 0.95]
    print(f"  tau por celda   " + "  ".join(f"p{int(q*100):02d}={np.quantile(tau_c[ok], q):.3f}"
                                            for q in qs))
    print(f"  sigma por celda " + "  ".join(f"p{int(q*100):02d}={np.quantile(sig_c[ok], q):.3f}"
                                            for q in qs))
    r = np.quantile(tau_c[ok], 0.95) / np.quantile(tau_c[ok], 0.05)
    print(f"\n  recorrido de tau p05->p95: {r:.2f}x   (global = {np.sqrt(tau2_g):.4f})")

    # -- B. .es real o es ruido? test-retest -----------------------------------
    rng = np.random.default_rng(SEM)
    mitad = rng.integers(0, 2, size=ce.max() + 1)[ce]      # empresa -> A o B, fija
    res = {}
    for lado in (0, 1):
        sel = mitad == lado
        cc2, ce2 = cc[sel], pd.factorize(ce[sel])[0]
        t2, s2, F2, _ = componentes_por_celda(cc2, ce2, y[sel], n_c)
        res[lado] = (np.sqrt(t2), np.sqrt(s2), F2)
    okr = ok & (res[0][2] >= MIN_EMPRESAS // 2) & (res[1][2] >= MIN_EMPRESAS // 2) \
             & np.isfinite(res[0][0]) & np.isfinite(res[1][0])
    print("\n" + "=" * 74)
    print("B. .ES REAL O ES RUIDO DE ESTIMACION? (test-retest entre mitades)")
    print("=" * 74)
    print(f"  celdas comparables: {okr.sum():,}")
    for nom, i in (("tau", 0), ("sigma", 1)):
        a, b = res[0][i][okr], res[1][i][okr]
        pe = np.corrcoef(a, b)[0, 1]
        sp = pd.Series(a).corr(pd.Series(b), method="spearman")
        print(f"  {nom:<6} correlacion entre mitades: Pearson {pe:+.3f}   Spearman {sp:+.3f}")
    print("\n  (si el parametro fuese el mismo para todas las celdas, lo que vemos seria")
    print("   ruido y las dos mitades no correlacionarian: r ~ 0)")

    # -- C. .cuanto le llega al cliente? ---------------------------------------
    suelo_c = np.sqrt(tau2_c + sigma2_c)
    print("\n" + "=" * 74)
    print("C. LO QUE LE LLEGA AL CLIENTE: el suelo y la banda")
    print("=" * 74)
    print(f"  suelo global      {suelo_g:.4f}   ->  banda ±{anch(suelo_g):.1%}")
    for q in qs:
        v = np.quantile(suelo_c[ok], q)
        print(f"  suelo p{int(q*100):02d} por celda {v:.4f}   ->  banda ±{anch(v):.1%}")

    print("\n  cargos concretos:")
    print(f"  {'cargo':<26} {'emp':>5} {'pers':>7} {'tau':>7} {'sigma':>7} {'suelo':>7} {'banda':>8}")
    idx = {c: i for i, c in enumerate(celdas)}
    for c in CASOS:
        i = idx.get(c)
        if i is None or not np.isfinite(suelo_c[i]) or F[i] < 3:
            print(f"  {c[:25]:<26} (sin datos suficientes)")
            continue
        print(f"  {c[:25]:<26} {int(F[i]):>5} {int(N[i]):>7} {tau_c[i]:>7.3f} "
              f"{sig_c[i]:>7.3f} {suelo_c[i]:>7.3f} {anch(suelo_c[i]):>7.1%}")

    # cuantas celdas quedarian FUERA de ALTA si el suelo fuese por celda
    print("\n  si el suelo fuese por celda, .cambiaria la etiqueta de confianza?")
    print("  (hoy el ancho se compara contra el suelo GLOBAL; con suelo por celda,")
    print("   una celda dispersa dejaria de parecer tan precisa)")
    peor = anch(np.quantile(suelo_c[ok], 0.95)) / anch(suelo_g)
    mejor = anch(np.quantile(suelo_c[ok], 0.05)) / anch(suelo_g)
    print(f"    celda del p95 de dispersion: banda {peor:.2f}x la que se le asigna hoy")
    print(f"    celda del p05 de dispersion: banda {mejor:.2f}x la que se le asigna hoy")


if __name__ == "__main__":
    main()
