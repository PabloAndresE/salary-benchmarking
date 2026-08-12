"""LA PREMISA CENTRAL DE LA TESIS, medida por fin.

El EDA se hizo con la composicion al 2,7%: no habia con que analizarla. Despues se
recupero hasta el 80% y se midio que es ESTABLE entre anios (test-retest 0,88 en
comisiones) y cuanto de ella explica el empleador. Pero nunca se midio lo unico que
sostiene la tesis:

    .LA COMPOSICION DEL PAGO EXPLICA LA DISPERSION SALARIAL QUE `CARGO` NO EXPLICA?

Si la respuesta es que no, la hipotesis se cae y hay que saberlo AHORA, no en la semana 12.

DISENO

Se descuenta en cadena lo que ya sabemos que explica el salario, y se pregunta que queda:

    r1 = y  - media(y | empresa)          quita el nivel del empleador (eta2 = 0,388)
    r2 = r1 - media(r1 | cargo_norm)      quita lo que la etiqueta SI captura

Sobre `r2` —lo que ni el empleador ni la etiqueta explican— se compara el omega2 de:

    composicion   k-means sobre las 4 proporciones del pago
    antiguedad    quintiles, como segunda variable candidata
    PLACEBO       particion aleatoria de la MISMA cardinalidad

El placebo no es opcional. Cualquier particion de 25 celdas explica algo por azar, y sin
el numero de referencia el resultado no se puede leer. omega2 y no eta2 porque descuenta
los grados de libertad.

DOS CUIDADOS

1. **Solo sobre el 80% de train.** Mirarlo en todo el marco quemaria el conjunto de prueba.
2. Esto es DESCRIPTIVO, y adelanta de forma barata la misma pregunta que el experimento E0
   formaliza (baseline con composicion frente a baseline sin ella). No sustituye a E0: E0
   la contesta con el banco completo y en validacion cruzada.
"""
import argparse

import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.cluster import MiniBatchKMeans

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.metricas import omega2_intra_empresa

SEMILLA = 20260805
_COMP = ["pct_fijo", "pct_comisiones", "pct_extras", "pct_otros"]


def _omega2(r, celda):
    """omega2 de `celda` sobre el residuo `r`. Descuenta grados de libertad."""
    d = pd.DataFrame({"r": np.asarray(r, float), "c": np.asarray(celda)}).dropna()
    k, n = d["c"].nunique(), len(d)
    if k < 2 or n <= k:
        return float("nan")
    gran = d["r"].mean()
    g = d.groupby("c")["r"].agg(["mean", "size"])
    ss_entre = float((g["size"] * (g["mean"] - gran) ** 2).sum())
    ss_total = float(((d["r"] - gran) ** 2).sum())
    ms_dentro = (ss_total - ss_entre) / (n - k)
    denom = ss_total + ms_dentro
    return float((ss_entre - (k - 1) * ms_dentro) / denom) if denom > 0 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=25)
    ap.add_argument("--anios", default="2024,2025")
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    anios = tuple(int(a) for a in args.anios.split(","))
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=anios), s))

    # SOLO TRAIN. El 20% de test no se toca aqui.
    train, _ = splits.partir(m, splits.empresas_test(m))
    d = train[train["tiene_composicion"]].dropna(subset=_COMP + ["y"]).copy()
    print(f"marco evaluable      : {len(m):,} filas")
    print(f"train                : {len(train):,} filas, "
          f"{train.empresa_ruc.nunique():,} empresas")
    print(f"train CON composicion: {len(d):,} filas, {d.empresa_ruc.nunique():,} empresas")
    print(f"(el 20% de test NO se toca en este analisis)")

    # --- cuanta dispersion hay, y cuanta queda tras descontar empresa y CARGO ---
    y = d["y"].to_numpy(float)
    d["r1"] = y - d.groupby("empresa_ruc")["y"].transform("mean")
    d["r2"] = d["r1"] - d.groupby("cargo_norm")["r1"].transform("mean")
    v0, v1, v2 = y.var(), d["r1"].var(), d["r2"].var()
    print("\n=== CUANTA DISPERSION QUEDA POR EXPLICAR ===")
    print(f"var(y)                        = {v0:.4f}   sd = {np.sqrt(v0):.4f}")
    print(f"var tras quitar EMPRESA       = {v1:.4f}   queda {v1/v0:.1%}")
    print(f"var tras quitar EMPRESA+CARGO = {v2:.4f}   queda {v2/v0:.1%}")
    print(f"-> la etiqueta explica {1 - v2/v1:.1%} de lo que sobra tras la empresa")

    # --- particiones candidatas, todas de la misma cardinalidad ---
    rng = np.random.default_rng(SEMILLA)
    X = d[_COMP].to_numpy(float)
    d["p_comp"] = MiniBatchKMeans(n_clusters=args.k, random_state=SEMILLA,
                                  n_init=10).fit_predict(X).astype(str)
    d["p_ant"] = pd.qcut(d["antiguedad_total"].fillna(-1).rank(method="first"),
                         args.k, labels=False).astype(str)
    d["p_azar"] = rng.integers(0, args.k, len(d)).astype(str)
    # control adicional: solo comisiones, que es la componente menos dependiente de la
    # politica interna (extras es en buena parte horas extra: eta2_empresa 0,498)
    d["p_com"] = pd.qcut(d["pct_comisiones"].rank(method="first"), args.k,
                         labels=False).astype(str)

    print(f"\n=== omega2 SOBRE r2 (lo que ni empresa ni CARGO explican), k={args.k} ===")
    filas = []
    for nombre, col in (("composicion (4 proporciones)", "p_comp"),
                        ("solo comisiones", "p_com"),
                        ("antiguedad", "p_ant"),
                        ("PLACEBO aleatorio", "p_azar")):
        o2 = _omega2(d["r2"], d[col])
        filas.append((nombre, o2))
        print(f"  {nombre:30s} {o2:+.4f}")

    placebo = filas[-1][1]
    print(f"\n=== LECTURA ===")
    for nombre, o2 in filas[:-1]:
        veces = o2 / placebo if placebo not in (0, None) and abs(placebo) > 1e-9 else np.inf
        print(f"  {nombre:30s} {o2 - placebo:+.4f} sobre el placebo"
              f"   ({veces:.0f}x)" if np.isfinite(veces) else "")

    comp = filas[0][1]
    if comp - placebo < 0.005:
        print("\n  LA PREMISA NO SE SOSTIENE. La composicion no explica la dispersion que")
        print("  CARGO deja sin explicar. Hay que replantear la hipotesis central antes de")
        print("  construir el sub-proyecto 2.")
    else:
        print(f"\n  La composicion explica un {comp:.1%} de la dispersion residual, frente")
        print(f"  al {placebo:.1%} del placebo. La premisa se sostiene; cuanto vale eso en")
        print("  error de prediccion lo contesta el banco (E0).")

    # --- dentro de las etiquetas ROTAS, que es donde la tesis promete servir ---
    print("\n=== SOLO EN LAS ETIQUETAS MAS DISPERSAS ===")
    tam = d.groupby("cargo_norm")["y"].agg(["size", "std"])
    grandes = tam[(tam["size"] >= 50)].sort_values("std", ascending=False)
    rotas = set(grandes.head(50).index)
    sub = d[d["cargo_norm"].isin(rotas)]
    print(f"50 etiquetas con >=50 personas y mas dispersion: {len(sub):,} filas")
    for nombre, col in (("composicion", "p_comp"), ("PLACEBO", "p_azar")):
        print(f"  omega2 {nombre:12s} = {_omega2(sub['r2'], sub[col]):+.4f}")
    print("\n  Si aqui la composicion separa mas que en el agregado, la tesis funciona")
    print("  precisamente donde promete: en las etiquetas que estan rotas.")


if __name__ == "__main__":
    main()
