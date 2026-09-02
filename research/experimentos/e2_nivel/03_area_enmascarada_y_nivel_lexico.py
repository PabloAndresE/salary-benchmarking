"""Area del titulo enmascarado x nivel del lexico: .funciona la descomposicion?

`02` midio que el nivel NO es recuperable de los titulos que no lo declaran: entrenando
sobre el titulo enmascarado la escalera sale 1,43x y no monotona. El nivel esta en la
palabra de rango o no esta.

Pero eso no cierra la puerta, la reordena. En vez de PREDECIR el nivel, se puede usar
donde SI esta escrito, y separar los dos ejes limpiamente:

    area   <- del titulo ENMASCARADO   (`PUESTO DE CAJA`), sin contaminacion de rango
    nivel  <- del LEXICO               (`AUXILIAR` -> 1, `SUPERVISOR` -> 3)

El enmascarado hace que `AUXILIAR DE CAJA` y `SUPERVISOR DE CAJA` sean el MISMO punto, asi
que el vecindario de area agrupa todos los rangos del mismo oficio y el lexico los separa
despues. Es la estructura rol-familia x nivel, construida con un diccionario en vez de con
clustering.

LA MEDICION QUE LO DECIDE. Los titulos que colapsan al enmascarar son **pares
controlados**: `PUESTO DE CAJA` existe como auxiliar y como supervisor, misma area exacta,
solo cambia el rango. Comparar su pago es un contraste sin confusion. Si dentro de la
misma area enmascarada el nivel ordena el pago, la descomposicion funciona; si no, el
lexico tampoco sirve y el eje de nivel se cae del todo.

Se mide ademas contra un PLACEBO que reasigna los niveles al azar dentro de cada area,
para descontar el efecto de partir en mas grupos.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.producto.nivel import enmascarar, nivel_lexico

SEM = 20260805


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))

    etiquetas = sorted(set(train.cargo_norm.astype(str)))
    area = {e: enmascarar(e) for e in etiquetas}
    nivel = {e: nivel_lexico(e) for e in etiquetas}
    d = train.copy()
    d["area"] = d.cargo_norm.map(area)
    d["nivel"] = d.cargo_norm.map(nivel)
    # dentro de empresa: el efecto empleador es el 81% del ruido y taparia todo
    d["r"] = d["y"] - d.groupby("empresa_ruc")["y"].transform("mean")

    con = d["nivel"].notna()
    print(f"train {len(d):,} filas   areas enmascaradas {d.area.nunique():,}")
    print(f"con nivel lexico: {con.mean():.1%} de las personas")

    # ---- areas que contienen VARIOS niveles: el contraste controlado ---------
    dd = d[con].copy()
    porarea = dd.groupby("area")["nivel"].nunique()
    mixtas = porarea[porarea >= 2].index
    sub = dd[dd.area.isin(mixtas)].copy()
    print(f"\nareas con 2+ niveles distintos: {len(mixtas):,}  "
          f"({len(sub):,} personas, {sub.cargo_norm.nunique():,} etiquetas)")

    print("\n" + "=" * 74)
    print("A. DENTRO DE LA MISMA AREA ENMASCARADA, .ORDENA EL NIVEL EL PAGO?")
    print("=" * 74)
    # se centra por area para que el contraste sea intra-area puro
    sub["r_area"] = sub["r"] - sub.groupby("area")["r"].transform("mean")
    g = sub.groupby("nivel")["r_area"].agg(["mean", "median", "size"])
    print(f"  {'nivel':<8} {'media':>9} {'mediana':>9} {'personas':>10}")
    for k, r in g.iterrows():
        print(f"  {int(k):<8} {r['mean']:>+9.4f} {r['median']:>+9.4f} {int(r['size']):>10,}")
    mono = bool(g["mean"].is_monotonic_increasing)
    recorrido = float(np.exp(g["mean"].iloc[-1] - g["mean"].iloc[0]))
    print(f"\n  monotona: {mono}    recorrido nivel 1 -> 5: {recorrido:.2f}x")

    # ---- cuanta varianza explica, con placebo -------------------------------
    def omega2(y, grupo):
        y = np.asarray(y, float)
        g2 = pd.DataFrame({"y": y, "g": np.asarray(grupo)}).dropna()
        k, n = g2.g.nunique(), len(g2)
        if k < 2 or n <= k:
            return float("nan")
        gran = g2.y.mean()
        agg = g2.groupby("g")["y"].agg(["mean", "size"])
        ss_e = float((agg["size"] * (agg["mean"] - gran) ** 2).sum())
        ss_t = float(((g2.y - gran) ** 2).sum())
        ms_d = (ss_t - ss_e) / (n - k)
        den = ss_t + ms_d
        return float((ss_e - (k - 1) * ms_d) / den) if den > 0 else float("nan")

    rng = np.random.default_rng(SEM)
    # placebo: reasigna el nivel AL AZAR dentro de cada area, conservando el reparto.
    # Descuenta el efecto de partir en mas grupos, que sube omega2 por si solo.
    sub["placebo"] = sub.groupby("area")["nivel"].transform(
        lambda v: rng.permutation(v.to_numpy()))
    print("\n" + "=" * 74)
    print("B. CUANTA VARIANZA INTRA-AREA EXPLICA EL NIVEL (con placebo)")
    print("=" * 74)
    w_real = omega2(sub["r_area"], sub["nivel"])
    w_plac = omega2(sub["r_area"], sub["placebo"])
    print(f"  nivel lexico   omega2 = {w_real:+.4f}   reduce la sd un "
          f"{1 - np.sqrt(max(0.0, 1 - w_real)):.1%}")
    print(f"  PLACEBO        omega2 = {w_plac:+.4f}")

    # ---- .y cuanto queda por area, para comparar los dos ejes? --------------
    print("\n" + "=" * 74)
    print("C. LOS DOS EJES, LADO A LADO (sobre las areas mixtas)")
    print("=" * 74)
    print(f"  area sola            omega2 = {omega2(sub['r'], sub['area']):+.4f}")
    print(f"  nivel solo           omega2 = {omega2(sub['r'], sub['nivel']):+.4f}")
    print(f"  area x nivel         omega2 = "
          f"{omega2(sub['r'], sub['area'].astype(str) + '|' + sub['nivel'].astype(str)):+.4f}")
    print(f"  etiqueta original    omega2 = {omega2(sub['r'], sub['cargo_norm']):+.4f}")
    print("\n  (si `area x nivel` se acerca a `etiqueta original` con muchas menos celdas,")
    print("   la descomposicion recupera lo que la etiqueta sabe, y de forma reutilizable)")

    # ---- ejemplos concretos --------------------------------------------------
    print("\n" + "=" * 74)
    print("D. EJEMPLOS: la misma area con dos rangos")
    print("=" * 74)
    grandes = (sub.groupby("area").agg(n=("y", "size"), niveles=("nivel", "nunique"))
                  .query("n >= 300 and niveles >= 2").sort_values("n", ascending=False))
    for a in grandes.head(6).index:
        t = sub[sub.area == a]
        print(f"\n  {a[:60]}")
        for k, r in t.groupby("nivel")["y"].agg(["median", "size"]).iterrows():
            ej = t[t.nivel == k].cargo_norm.mode()
            print(f"    nivel {int(k)}  mediana {r['median']:>6.3f}  "
                  f"{int(r['size']):>6,} pers.  ej: {ej.iloc[0][:34] if len(ej) else ''}")


if __name__ == "__main__":
    main()
