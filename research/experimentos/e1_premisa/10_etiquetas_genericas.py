"""LAS ETIQUETAS GENERICAS: .cuanta gente, cuanto error, y las parte el sector?

La etiqueta falla de DOS formas opuestas y solo hemos atacado una:

  FRAGMENTADA  el mismo trabajo escrito de 50 maneras. 34% de la gente en celdas de 1-2
               empresas. Se arregla FUSIONANDO — y eso ya esta resuelto.
  GENERICA     `TRABAJADOR EN GENERAL`, `EMPLEADO`, `OBRERO`. Una etiqueta con muchos
               trabajos dentro. Se arregla PARTIENDO, y fusionar la empeora.

Los propios datos ya lo decian y se leyo mal: las celdas de 101+ empresas tienen sd
predictiva 0,3359 frente a 0,3249 de las de 21-100. Estan bien estimadas y son
internamente HETEROGENEAS.

Este script mide:
  1. cuanta gente vive en etiquetas genericas
  2. cuanto de su dispersion es intra-etiqueta (lo que una particion podria recuperar)
  3. si SECTOR y TAMANO las parten — que es la mitigacion que ya esta en el diseno y no
     necesita informacion nueva
  4. y cuanto queda irreducible despues de eso
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits

MIN_PERSONAS = 300      # una etiqueta "grande" para este analisis


def omega2(r, celda):
    d = pd.DataFrame({"r": np.asarray(r, float), "c": np.asarray(celda)}).dropna()
    k, n = d["c"].nunique(), len(d)
    if k < 2 or n <= k:
        return float("nan")
    gran = d["r"].mean()
    g = d.groupby("c")["r"].agg(["mean", "size"])
    sse = float((g["size"] * (g["mean"] - gran) ** 2).sum())
    sst = float(((d["r"] - gran) ** 2).sum())
    msd = (sst - sse) / (n - k)
    return float((sse - (k - 1) * msd) / (sst + msd)) if sst + msd > 0 else float("nan")


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))
    d = train.dropna(subset=["y"]).copy()
    print(f"train: {len(d):,} filas, {d.cargo_norm.nunique():,} etiquetas")

    # dentro de empresa: el empleador es el 81% del ruido irreducible
    d["r"] = d["y"] - d.groupby("empresa_ruc")["y"].transform("mean")
    var_global = d["r"].var()
    print(f"var dentro de empresa: {var_global:.4f} (sd {np.sqrt(var_global):.4f})\n")

    tam = d.groupby("cargo_norm").size()
    grandes = tam[tam >= MIN_PERSONAS].sort_values(ascending=False)
    print("=" * 84)
    print(f"1. LAS {len(grandes)} ETIQUETAS CON >= {MIN_PERSONAS} PERSONAS")
    print("=" * 84)
    cubre = tam[tam >= MIN_PERSONAS].sum() / len(d)
    print(f"  cubren el {cubre:.1%} de la gente ({grandes.sum():,} personas)")

    # dispersion INTRA-etiqueta de cada etiqueta grande, y cuanto la parten los controles
    print(f"\n{'etiqueta':<40} {'personas':>9} {'sd intra':>9} "
          f"{'w2 sector':>10} {'w2 ciiu+tam':>12}")
    print("-" * 84)
    filas = []
    for et in grandes.head(25).index:
        sub = d[d.cargo_norm == et]
        if sub.empresa_ruc.nunique() < 5:
            continue
        sd = float(sub["r"].std())
        w_ciiu = omega2(sub["r"], sub["ciiu_n1"].astype(str))
        w_ct = omega2(sub["r"], sub["ciiu_n1"].astype(str) + "|" + sub["segmento"].astype(str))
        filas.append({"et": et, "n": len(sub), "sd": sd, "w_ciiu": w_ciiu, "w_ct": w_ct})
        print(f"{et[:38]:<40} {len(sub):>9,} {sd:>9.4f} "
              f"{w_ciiu:>10.4f} {w_ct:>12.4f}")

    f = pd.DataFrame(filas)
    print("-" * 84)
    print(f"\n  sd intra media (ponderada por personas): "
          f"{np.average(f.sd, weights=f.n):.4f}   frente a {np.sqrt(var_global):.4f} global")
    print(f"  omega2 medio de sector           : {np.average(f.w_ciiu.fillna(0), weights=f.n):+.4f}")
    print(f"  omega2 medio de sector x tamano  : {np.average(f.w_ct.fillna(0), weights=f.n):+.4f}")

    print("\n" + "=" * 84)
    print("2. .PARTE EL SECTOR LAS GENERICAS? (placebo al lado)")
    print("=" * 84)
    rng = np.random.default_rng(20260805)
    sub = d[d.cargo_norm.isin(grandes.index)].copy()
    sub["placebo"] = rng.integers(0, sub.ciiu_n1.nunique(), len(sub)).astype(str)
    sub["sec"] = sub.ciiu_n1.astype(str)
    sub["sect"] = sub.sec + "|" + sub.segmento.astype(str)

    # La pregunta es una INTERACCION, no un efecto principal. Un omega2 de sector
    # agrupando las 381 etiquetas mide "hay un efecto de sector IGUAL para todas", y da
    # 0,019: casi nada. Pero la pregunta util es "cuando comparo un VENDEDOR, .ayuda saber
    # su sector?", y eso se responde partiendo cada etiqueta por su cuenta. Medido asi da
    # 13,2% de sd. Un OBRERO es otra cosa segun el sector (omega2 0,43) y un TRABAJADOR
    # AGRICOLA es el mismo en todas partes (0,02): promediar ese efecto entre etiquetas lo
    # borra. El placebo lleva la misma cantidad de celdas, asi que descuenta el artefacto
    # de grados de libertad.
    def var_resid(cols):
        return float((sub["r"] - sub.groupby(cols)["r"].transform("mean")).var())

    base = var_resid(["cargo_norm"])
    print(f"  varianza residual tras la etiqueta sola: {base:.5f}")
    for nom, col in (("etiqueta x sector", "sec"),
                     ("etiqueta x sector x tamano", "sect"),
                     ("etiqueta x PLACEBO", "placebo")):
        v = var_resid(["cargo_norm", col])
        print(f"  + {nom:<28} -> {v:.5f}   var -{1-v/base:6.2%}   sd -{1-np.sqrt(v/base):5.2%}")

    print()
    print("  .a cuanta gente le aplica? (reduccion dentro de su etiqueta)")
    filas2 = []
    for et, g in sub.groupby("cargo_norm"):
        if g.empresa_ruc.nunique() < 5:
            continue
        v0 = float(g["r"].var())
        if v0 > 0:
            filas2.append((len(g), 1 - float((g["r"] - g.groupby("sec")["r"]
                                              .transform("mean")).var()) / v0))
    f2 = pd.DataFrame(filas2, columns=["n", "red"]).dropna()
    for u in (0.10, 0.20, 0.30):
        sel = f2.red > u
        print(f"    el sector recorta >{u:.0%} de su varianza en {sel.sum():>3} de "
              f"{len(f2)} etiquetas  ({f2.loc[sel, 'n'].sum() / f2.n.sum():5.1%} de la gente)")

    print("\n" + "=" * 84)
    print("3. EL REPARTO DEL ERROR: fragmentadas frente a genericas")
    print("=" * 84)
    n_emp = d.groupby("cargo_norm")["empresa_ruc"].nunique()
    d["_emp"] = d.cargo_norm.map(n_emp)
    d["_tam"] = d.cargo_norm.map(tam)
    grupos = [("genericas (>=300 pers.)", d._tam >= MIN_PERSONAS),
              ("medianas", (d._tam < MIN_PERSONAS) & (d._emp >= 3)),
              ("fragmentadas (<3 empresas)", d._emp < 3)]
    print(f"{'grupo':<28} {'personas':>10} {'% gente':>9} {'sd intra':>9} {'% de la var':>12}")
    print("-" * 72)
    total_ss = float(((d["r"] - d["r"].mean()) ** 2).sum())
    for nom, sel in grupos:
        if sel.sum() == 0:
            continue
        rr = d.loc[sel, "r"]
        ss = float(((rr - rr.mean()) ** 2).sum())
        print(f"{nom:<28} {int(sel.sum()):>10,} {sel.mean():>8.1%} "
              f"{rr.std():>9.4f} {ss/total_ss:>11.1%}")

    print()
    print("LECTURA: el sector SI parte las genericas —13,2% de sd frente a 0,9%")
    print("del placebo—, y es el mismo orden que el eje de nivel. Es un SEGUNDO EJE,")
    print("no un control: la referencia debe condicionar por sector dentro de las")
    print("etiquetas anchas.")
    print()
    print("CUIDADO: esto es descomposicion de varianza, no R2 fuera de muestra. El")
    print("placebo descuenta el artefacto de grados de libertad, pero no sustituye a")
    print("una validacion held-out como la de `03`.")


if __name__ == "__main__":
    main()
