""".Estrechar la banda segmentando por tamano de empresa? Y .a que precio?

LA IDEA. `GERENTE GENERAL` entrega una banda de $1.516 a $5.766 porque pagar a un gerente
depende brutalmente de la empresa. Pero "la empresa" no es una caja negra: sabemos su
TAMANO (`segmento`), su SECTOR (`ciiu_n1`) y su PROVINCIA. Si el tamano explica parte de
esa dispersion, condicionar por el mueve varianza de "inexplicada" a "explicada" y la banda
se estrecha sin perder nada real.

EL PRECIO, QUE ES LO QUE HAY QUE MEDIR. Partir cada cargo en cuatro segmentos deja cada
celda con la cuarta parte de las empresas. `1/W` sube, la referencia se conoce peor y la
confianza baja. Ademas mas celdas caen por debajo del umbral de cuantiles empiricos y
tienen que volver al modelo. Es un intercambio, no una mejora gratis, y puede salir a
perdida.

DISENO JERARQUICO, que es como se montaria de verdad: se usa la celda `cargo x segmento`
cuando tiene empresas de sobra, y se cae a `cargo` cuando no. Asi la segmentacion solo
actua donde se la puede pagar.

QUE SE MIDE, sobre votos de empresas APARTADAS, igual que `05`:
  - pinball en q=0,25 y q=0,75 (regla propia para cuantiles: la que decide)
  - cobertura del 50% y del 80%
  - ancho medio de la banda        <- lo que se gana
  - `incert_centro` medio          <- lo que se paga
  - cuanta gente cae en la celda segmentada y cuanta vuelve al cargo

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import pathlib
import sys
from importlib import import_module

import numpy as np
import pandas as pd
from google.cloud import bigquery

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
_c = import_module("02_calibracion_por_celda")

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import (componentes_varianza, cuantiles_de_empresa,
                                                sigma2_por_celda, tau2_por_celda)

SEM = 20260805
MIN_EMPRESAS = 3
MIN_BANDA = 10
Z = {0.10: -1.2816, 0.25: -0.6745, 0.75: 0.6745, 0.90: 1.2816}
CUANTILES = (0.10, 0.25, 0.75, 0.90)
CASOS = ["GERENTE GENERAL", "CONTADOR", "JEFE DE BODEGA", "ASISTENTE CONTABLE",
         "VENDEDOR", "CHOFER", "AUXILIAR DE LIMPIEZA"]


def construir(d, colc):
    """Todo lo que hace falta para una definicion de celda: stats, banda y cuantiles."""
    tau2, sigma2 = componentes_varianza(d, colc)
    s2c, _ = sigma2_por_celda(d, colc, sigma2_global=sigma2)
    t2c, _ = tau2_por_celda(d, colc, s2c, tau2_global=tau2)
    v = (d.dropna(subset=["y"]).groupby([colc, "empresa_ruc"], sort=False)["y"]
          .agg(voto="median", n="size").reset_index())
    t = v[colc].map(t2c).fillna(tau2).to_numpy(float)
    sg = v[colc].map(s2c).fillna(sigma2).to_numpy(float)
    den = t + sg / v["n"].to_numpy(float)
    v["w"] = np.where(den > 0, 1.0 / np.where(den > 0, den, 1.0), 1.0)
    g = v.groupby(colc)
    W = g["w"].sum()
    F = g.size()
    m = g.apply(lambda x: float(np.interp(0.5,
                np.cumsum(x.sort_values("voto")["w"]) / x["w"].sum() - 0.5 *
                x.sort_values("voto")["w"] / x["w"].sum(),
                x.sort_values("voto")["voto"])), include_groups=False)
    qs = cuantiles_de_empresa(d, colc, t2c, s2c, CUANTILES)
    return dict(m=m, W=W, F=F, t2=t2c, s2=s2c, q=qs, tau2=tau2, sigma2=sigma2)


def banda_de(mod, claves):
    """Cuantiles para cada clave: empiricos si hay empresas de sobra, si no el modelo."""
    F = mod["F"].reindex(claves).to_numpy(float)
    m = mod["m"].reindex(claves).to_numpy(float)
    W = mod["W"].reindex(claves).to_numpy(float)
    t2 = pd.Series(mod["t2"]).reindex(claves).fillna(mod["tau2"]).to_numpy(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        sd = np.sqrt(t2 + 1.0 / W)
        incert = np.exp(np.sqrt(1.0 / W)) - 1.0
    out = {}
    for q in CUANTILES:
        emp = mod["q"][q].reindex(claves).to_numpy(float) if q in mod["q"] else np.nan
        out[q] = np.where((F >= MIN_BANDA) & np.isfinite(emp), emp, m + Z[q] * sd)
    return out, m, F, incert


def pinball(y, pred, q):
    d = y - pred
    return float(np.mean(np.maximum(q * d, (q - 1.0) * d)))


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    train = train.copy()
    train["cargo_norm"] = train.cargo_norm.astype(str)
    for c in ("segmento", "ciiu_n1", "provincia"):
        train[c] = train[c].astype(str).fillna("NA")
    print("segmentos:", train.segmento.value_counts().to_dict())
    print("sectores :", train.ciiu_n1.nunique(), " provincias:", train.provincia.nunique())

    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train.empresa_ruc.isin(val)].copy()
    ts = train[train.empresa_ruc.isin(val)].copy()
    print(f"construir {len(tr):,} filas / {tr.empresa_ruc.nunique():,} empresas   "
          f"evaluar {len(ts):,} / {ts.empresa_ruc.nunique():,}")

    DEFS = {"cargo (hoy)": None, "cargo x tamano": "segmento",
            "cargo x sector": "ciiu_n1", "cargo x provincia": "provincia"}
    for nom, extra in DEFS.items():
        for d in (tr, ts):
            d["_c"] = (d.cargo_norm if extra is None
                       else d.cargo_norm + " | " + d[extra])
        DEFS[nom] = (extra, construir(tr, "_c"))

    # el nivel de respaldo: siempre el cargo solo
    tr["_c"] = tr.cargo_norm
    base_cargo = construir(tr, "_c")

    # votos de las empresas apartadas, con su clave en cada definicion
    v_ts = (ts.dropna(subset=["y"])
              .groupby(["cargo_norm", "empresa_ruc", "segmento", "ciiu_n1", "provincia"],
                       sort=False)["y"].median().reset_index(name="voto"))
    print(f"evaluando {len(v_ts):,} votos de empresa apartados")

    print("\n" + "=" * 92)
    print("SEGMENTAR: LO QUE SE GANA EN BANDA CONTRA LO QUE SE PAGA EN CONFIANZA")
    print("=" * 92)
    print(f"  {'definicion':<20} {'cob50':>7} {'cob80':>7} {'pin.med':>8} {'ancho':>8} "
          f"{'incert':>8} {'usa celda fina':>15}")
    filas = {}
    for nom, (extra, mod) in DEFS.items():
        claves = (v_ts.cargo_norm if extra is None
                  else v_ts.cargo_norm + " | " + v_ts[extra]).to_numpy()
        Qf, mf, Ff, inf_ = banda_de(mod, claves)
        Qc, mc, Fc, inc_ = banda_de(base_cargo, v_ts.cargo_norm.to_numpy())
        # jerarquico: celda fina si tiene empresas de sobra, si no el cargo
        fina = Ff >= MIN_EMPRESAS
        Q = {q: np.where(fina, Qf[q], Qc[q]) for q in CUANTILES}
        incert = np.where(fina, inf_, inc_)
        ok = np.isfinite(Q[0.25]) & np.isfinite(Q[0.75])
        y = v_ts["voto"].to_numpy(float)
        lo, hi = Q[0.25][ok], Q[0.75][ok]
        yy = y[ok]
        p25, p75 = pinball(yy, lo, 0.25), pinball(yy, hi, 0.75)
        filas[nom] = dict(Q=Q, ok=ok, fina=fina, incert=incert, pin=(p25 + p75) / 2)
        print(f"  {nom:<20} {float(((yy>=lo)&(yy<=hi)).mean()):>6.1%} "
              f"{float(((yy>=Q[0.10][ok])&(yy<=Q[0.90][ok])).mean()):>6.1%} "
              f"{(p25+p75)/2:>8.4f} "
              f"{float(np.mean(np.exp((hi-lo)/2)-1)):>7.1%} "
              f"{float(np.nanmean(incert[ok])):>7.1%} {float(fina.mean()):>14.1%}")

    mejor = min(filas, key=lambda k: filas[k]["pin"])
    print(f"\n  MEJOR PINBALL: {mejor}")

    print("\n" + "=" * 92)
    print("CARGOS CONCRETOS: banda en dolares por tamano de empresa")
    print("=" * 92)
    sbu = float(s.get_sbu(2025))
    extra, mod = DEFS["cargo x tamano"]
    segs = sorted(tr.segmento.unique())
    for cg in CASOS:
        claves = np.array([cg] + [f"{cg} | {g}" for g in segs])
        Q, m, F, inc = banda_de(mod if True else mod, claves)
        Qc, mc, Fc, incc = banda_de(base_cargo, np.array([cg]))
        if not np.isfinite(Qc[0.25][0]):
            continue
        print(f"\n  {cg}")
        print(f"    {'TODOS (hoy)':<22} {int(Fc[0]):>5} emp  "
              f"${np.exp(Qc[0.25][0])*sbu:>8,.0f} — ${np.exp(Qc[0.75][0])*sbu:>8,.0f}"
              f"   incert {incc[0]:>6.1%}")
        for k, g in enumerate(segs, start=1):
            if not np.isfinite(F[k]) or F[k] < MIN_EMPRESAS:
                continue
            print(f"    {g[:21]:<22} {int(F[k]):>5} emp  "
                  f"${np.exp(Q[0.25][k])*sbu:>8,.0f} — ${np.exp(Q[0.75][k])*sbu:>8,.0f}"
                  f"   incert {inc[k]:>6.1%}")


if __name__ == "__main__":
    main()
