"""D-065: votos atipicos (cargo x empresa) que no son un precio de mercado del cargo.

Un voto es la mediana de `y = log(sueldo / SBU)` de una empresa en un grupo de cargos. Dos reglas:

- **(a) Sueldo de dueno:** grupo de nivel 4-5 (jefaturas y gerencias) y voto < `piso` SBU (1,25). En esos niveles
  hay un pico en el minimo: el 10 % de los `GERENTE GENERAL` figura con $470-$600, lo mas probable un dueno que se
  pone el SBU en la nomina.
- **(b) Extremo:** en grupos con >= `min_emp` empresas, voto mas de `factor` veces (6) por encima o por debajo de
  la mediana del grupo: errores de digitacion o titulos mal puestos.

Una regla simetrica por MAD NO sirve: muchos grupos de nivel 1 estan pegados al SBU, su MAD es casi 0 y se
cortarian los sueldos altos, que son reales.
"""
import numpy as np
import pandas as pd

PISO_DUENO = 1.25
FACTOR_EXTREMO = 6.0
MIN_EMPRESAS = 5


def votos(marco, base, col="cargo_norm"):
    """(grupo, empresa) -> voto, con el nivel del grupo. Solo titulos que estan en la base."""
    d = marco[[col, "empresa_ruc", "y"]].dropna(subset=["y"]).copy()
    i = d[col].astype(str).map(base.idx)
    d = d[i.notna()].copy()
    j = i[i.notna()].astype(int).to_numpy()
    d["g"], d["L"] = base.grupo[j], base.nivel[j]
    return d.groupby(["g", "empresa_ruc"], sort=False).agg(voto=("y", "median"), L=("L", "first")).reset_index()


def marcar(v, ref=None, piso=PISO_DUENO, factor=FACTOR_EXTREMO, min_emp=MIN_EMPRESAS):
    """Columna `regla` ('dueno', 'extremo' o '') para los votos `v`. La mediana y el numero de empresas de cada
    grupo salen de `ref` (los votos de entrenamiento; por defecto, los mismos `v`)."""
    ref = v if ref is None else ref
    est = ref.groupby("g")["voto"].agg(["median", "size"])
    med, n = v["g"].map(est["median"]), v["g"].map(est["size"]).fillna(0)
    dueno = v["L"].isin([4.0, 5.0]) & (np.exp(v["voto"]) < piso)
    extremo = (n >= min_emp) & ((v["voto"] - med).abs() > np.log(factor))
    return np.where(dueno, "dueno", np.where(extremo, "extremo", ""))


def placebo(v, regla, semilla=17):
    """Mismo numero de votos que la regla, al azar y del mismo nivel."""
    rng = np.random.default_rng(semilla)
    out = np.array([""] * len(v), dtype=object)
    for lv, k in pd.Series(v["L"].to_numpy()[regla != ""]).value_counts(dropna=False).items():
        pool = np.flatnonzero((v["L"].to_numpy() == lv) if pd.notna(lv) else v["L"].isna().to_numpy())
        out[rng.choice(pool, min(int(k), len(pool)), replace=False)] = "placebo"
    return out


def quitar(marco, base, v, regla, col="cargo_norm"):
    """El marco sin las filas de los pares (grupo, empresa) marcados."""
    malos = set(zip(v["g"].to_numpy()[regla != ""], v["empresa_ruc"].to_numpy()[regla != ""]))
    i = marco[col].astype(str).map(base.idx)
    g = np.where(i.notna(), base.grupo[i.fillna(0).astype(int).to_numpy()], -1)
    fuera = np.array([(gg, e) in malos for gg, e in zip(g, marco["empresa_ruc"].to_numpy())])
    return marco[~fuera].copy()
