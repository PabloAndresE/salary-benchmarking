"""Segmentar por tamano SOLO donde compense. .Se puede decidir cargo a cargo?

`07` midio que segmentar TODO pierde: el pinball empeora de 0,1255 a 0,1284 porque la banda
apenas se estrecha (28,2% -> 27,5%) y la incertidumbre del centro sube (10,4% -> 12,7%).
Pero el promedio esconde un efecto grande en pocos cargos: la banda entera de un
`GERENTE GENERAL` de empresa PEQUENA ($1.011-$2.330) queda POR DEBAJO de la referencia que
se le da hoy ($3.032), mientras que en `CHOFER` o `AUXILIAR DE LIMPIEZA` los segmentos son
indistinguibles.

LA PREGUNTA. .Se puede decidir cargo a cargo, con los datos de construccion, si segmentar
compensa — y gana eso al agregado?

COMO SE DECIDE, SIN MIRAR LA EVALUACION. Doble particion anidada de EMPRESAS:

    train -> tr (construir)  +  ts (evaluar, intocado hasta el final)
    tr    -> tr_a (ajustar)  +  tr_b (decidir por cargo)

Para cada cargo se ajustan las dos variantes en `tr_a`, se comparan por pinball en `tr_b`, y
se segmenta el cargo si gana. Luego se reajusta TODO sobre `tr` con esa decision y se mide
una sola vez en `ts`. Asi la decision no ve nunca los datos con los que se puntua.

EL PLACEBO, QUE ES LO QUE HACE HONESTA LA MEDICION. Decidir cargo a cargo sobre estimaciones
ruidosas selecciona cargos POR AZAR: con miles de cargos, la mitad "gana" de casualidad y el
agregado no mejora. Se repite todo el procedimiento con las etiquetas de segmento BARAJADAS
dentro de cada cargo. Si la version real no bate claramente al placebo, la seleccion es
ruido con otro nombre.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import pathlib
import sys
from importlib import import_module

import numpy as np
import pandas as pd
from google.cloud import bigquery

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
_s = import_module("07_segmentar_por_tamano")

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits

SEM = 20260805
MIN_EMPRESAS = 3
MIN_PARA_DECIDIR = 20      # empresas del cargo; por debajo, decidir es leer ruido
CASOS = ["GERENTE GENERAL", "CONTADOR", "JEFE DE BODEGA", "ASISTENTE CONTABLE",
         "VENDEDOR", "CHOFER", "AUXILIAR DE LIMPIEZA", "SUPERVISOR DE CAJA"]


def votos(d):
    return (d.dropna(subset=["y"])
             .groupby(["cargo_norm", "empresa_ruc", "_seg"], sort=False)["y"]
             .median().reset_index(name="voto"))


def pinball_por_voto(y, lo, hi):
    """Perdida pinball media de los dos cuantiles, voto a voto."""
    a = np.maximum(0.25 * (y - lo), -0.75 * (y - lo))
    b = np.maximum(0.75 * (y - hi), -0.25 * (y - hi))
    return (a + b) / 2.0


def bandas(mod_fino, mod_cargo, v):
    """Banda jerarquica: celda `cargo | seg` si aguanta, si no el cargo."""
    kf = (v.cargo_norm + " | " + v._seg).to_numpy()
    kc = v.cargo_norm.to_numpy()
    Qf, _, Ff, incf = _s.banda_de(mod_fino, kf)
    Qc, _, Fc, incc = _s.banda_de(mod_cargo, kc)
    fina = Ff >= MIN_EMPRESAS
    return ({q: np.where(fina, Qf[q], Qc[q]) for q in _s.CUANTILES},
            Qc, np.where(fina, incf, incc), fina)


def decidir(tr_a, tr_b):
    """Cargos donde segmentar gana, decidido en `tr_b` con modelos ajustados en `tr_a`."""
    tr_a = tr_a.copy()
    tr_a["_c"] = tr_a.cargo_norm + " | " + tr_a._seg
    fino = _s.construir(tr_a, "_c")
    tr_a["_c"] = tr_a.cargo_norm
    cargo = _s.construir(tr_a, "_c")

    v = votos(tr_b)
    Qf, Qc, _, fina = bandas(fino, cargo, v)
    y = v["voto"].to_numpy(float)
    ok = np.isfinite(Qf[0.25]) & np.isfinite(Qc[0.25]) & fina
    d = pd.DataFrame({"cargo": v.cargo_norm.to_numpy()[ok],
                      "seg": pinball_por_voto(y[ok], Qf[0.25][ok], Qf[0.75][ok]),
                      "sol": pinball_por_voto(y[ok], Qc[0.25][ok], Qc[0.75][ok])})
    g = d.groupby("cargo").agg(n=("seg", "size"), seg=("seg", "mean"), sol=("sol", "mean"))
    n_emp = tr_a.groupby("cargo_norm")["empresa_ruc"].nunique()
    g = g.join(n_emp.rename("emp"))
    elegidos = g[(g["emp"] >= MIN_PARA_DECIDIR) & (g["n"] >= 10) & (g["seg"] < g["sol"])]
    return set(elegidos.index), g


def evaluar(tr, ts, cargos_seg, etiqueta):
    tr = tr.copy()
    tr["_c"] = np.where(tr.cargo_norm.isin(cargos_seg),
                        tr.cargo_norm + " | " + tr._seg, tr.cargo_norm)
    fino = _s.construir(tr, "_c")
    tr["_c"] = tr.cargo_norm
    cargo = _s.construir(tr, "_c")

    v = votos(ts)
    kf = np.where(v.cargo_norm.isin(cargos_seg),
                  v.cargo_norm + " | " + v._seg, v.cargo_norm)
    Qf, _, Ff, incf = _s.banda_de(fino, kf)
    Qc, _, Fc, incc = _s.banda_de(cargo, v.cargo_norm.to_numpy())
    fina = Ff >= MIN_EMPRESAS
    Q = {q: np.where(fina, Qf[q], Qc[q]) for q in _s.CUANTILES}
    inc = np.where(fina, incf, incc)

    y = v["voto"].to_numpy(float)
    ok = np.isfinite(Q[0.25]) & np.isfinite(Q[0.75])
    yy, lo, hi = y[ok], Q[0.25][ok], Q[0.75][ok]
    pin = float(pinball_por_voto(yy, lo, hi).mean())
    print(f"  {etiqueta:<34} {len(cargos_seg):>6,} {float(((yy>=lo)&(yy<=hi)).mean()):>7.1%} "
          f"{float(((yy>=Q[0.10][ok])&(yy<=Q[0.90][ok])).mean()):>7.1%} {pin:>8.4f} "
          f"{float(np.mean(np.exp((hi-lo)/2)-1)):>7.1%} {float(np.nanmean(inc[ok])):>7.1%}")
    return pin


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    train = train.copy()
    train["cargo_norm"] = train.cargo_norm.astype(str)
    train["_seg"] = train["segmento"].astype(str).fillna("NA")

    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train.empresa_ruc.isin(val)].copy()
    ts = train[train.empresa_ruc.isin(val)].copy()
    emp_tr = np.array(sorted(tr.empresa_ruc.unique()))
    val2 = set(rng.choice(emp_tr, len(emp_tr) // 4, replace=False))
    tr_a = tr[~tr.empresa_ruc.isin(val2)].copy()
    tr_b = tr[tr.empresa_ruc.isin(val2)].copy()
    print(f"tr_a {tr_a.empresa_ruc.nunique():,} empresas (ajustar)   "
          f"tr_b {tr_b.empresa_ruc.nunique():,} (decidir)   "
          f"ts {ts.empresa_ruc.nunique():,} (evaluar)")

    # -- decision real --------------------------------------------------------
    elegidos, tabla = decidir(tr_a, tr_b)
    print(f"\ncargos evaluables para decidir: {len(tabla):,}   "
          f"elegidos para segmentar: {len(elegidos):,}")

    # -- placebo: mismo procedimiento con los segmentos BARAJADOS --------------
    rp = np.random.default_rng(99)
    tr_ap = tr_a.copy()
    tr_ap["_seg"] = tr_ap.groupby("cargo_norm")["_seg"].transform(
        lambda v: rp.permutation(v.to_numpy()))
    tr_bp = tr_b.copy()
    tr_bp["_seg"] = tr_bp.groupby("cargo_norm")["_seg"].transform(
        lambda v: rp.permutation(v.to_numpy()))
    elegidos_p, _ = decidir(tr_ap, tr_bp)
    print(f"PLACEBO (segmentos barajados): elegidos {len(elegidos_p):,}")

    print("\n" + "=" * 92)
    print("SOBRE VOTOS DE EMPRESA APARTADOS. pinball menor es mejor")
    print("=" * 92)
    print(f"  {'variante':<34} {'cargos':>6} {'cob50':>7} {'cob80':>7} {'pinball':>8} "
          f"{'ancho':>7} {'incert':>7}")
    todos = set(tr.cargo_norm.unique())
    p_hoy = evaluar(tr, ts, set(), "cargo (hoy)")
    p_all = evaluar(tr, ts, todos, "cargo x tamano SIEMPRE")
    p_sel = evaluar(tr, ts, elegidos, "cargo x tamano SELECTIVO")
    p_pla = evaluar(tr, ts, elegidos_p, "PLACEBO (seleccion al azar)")

    print(f"\n  selectivo contra hoy:     {p_sel - p_hoy:+.4f}")
    print(f"  selectivo contra placebo: {p_sel - p_pla:+.4f}")
    print("  (si selectivo ~ placebo, la seleccion es ruido con otro nombre)")

    print("\n" + "=" * 92)
    print("QUE CARGOS ELIGE, Y LOS CASOS CONOCIDOS")
    print("=" * 92)
    t = tabla.assign(gana=tabla["sol"] - tabla["seg"]).sort_values("gana", ascending=False)
    print("\n  los 10 donde mas gana segmentar:")
    for cg, r in t.head(10).iterrows():
        print(f"    {cg[:44]:<46} {int(r['emp']):>5} emp   gana {r['gana']:+.4f}")
    print("\n  casos conocidos:")
    for cg in CASOS:
        if cg in t.index:
            r = t.loc[cg]
            print(f"    {cg[:30]:<32} {int(r['emp']):>5} emp   gana {r['gana']:+.4f}   "
                  f"{'SEGMENTA' if cg in elegidos else 'no'}")
        else:
            print(f"    {cg[:30]:<32} (no evaluable)")


if __name__ == "__main__":
    main()
