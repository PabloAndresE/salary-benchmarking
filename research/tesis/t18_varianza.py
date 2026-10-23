"""T-018: descomposicion de la varianza del sueldo (voto = mediana de log(sueldo/SBU) por cargo x empresa) entre nivel,
cargo y empresa; R2 dentro y fuera de muestra (registro, T-018).
    GRPC_DNS_RESOLVER=native .venv/bin/python research/tesis/t18_varianza.py      -> salidas/t18_varianza.txt
"""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def efectos(df, factores, iters=50):
    """Efectos fijos aditivos por proyecciones alternadas (media global + un efecto por nivel de cada factor)."""
    mu = df["v"].mean()
    ef = {f: pd.Series(0.0, index=pd.unique(df[f])) for f in factores}
    for _ in range(iters if len(factores) > 1 else 1):
        for f in factores:
            resto = df["v"] - mu - sum(df[g].map(ef[g]) for g in factores if g != f)
            ef[f] = resto.groupby(df[f]).mean()
    return mu, ef


def predecir(df, mu, ef):
    return mu + sum(df[f].map(e) for f, e in ef.items())


def r2(y, p):
    return 1 - np.mean((y - p) ** 2) / np.var(y)


def main():
    e41 = cargar("e41", E2 / "41_base_v16.py")
    e54 = cargar("e54", E2 / "54_pinball.py")
    mk = e41.cargar_marco()
    mk["cargo_norm"] = mk["cargo_norm"].astype(str)
    v = (mk.dropna(subset=["y"]).groupby(["cargo_norm", "empresa_ruc"], sort=False)["y"].median()
           .reset_index().rename(columns={"y": "v"}))
    g = e54.grupos_de_clusters("50_clusters_confiable_cargos.parquet")
    q = pd.read_parquet(E2 / "salidas" / "60_niveles_qwen_v3.parquet")
    niv = {str(t): int(x) for t, x in zip(q["titulo"], q["nivel"]) if 1 <= int(x) <= 5}
    v["cargo"] = v["cargo_norm"].map(g)
    v["nivel"] = v["cargo_norm"].map(niv)
    v["empresa"] = v["empresa_ruc"].astype(str)
    v = v.dropna(subset=["cargo", "nivel"]).reset_index(drop=True)
    v["cargo"] = v["cargo"].astype(int)
    v["nivel"] = v["nivel"].astype(int)
    modelos = [("nivel",), ("cargo",), ("empresa",), ("nivel", "empresa"), ("cargo", "empresa")]
    out = ["T-018 · descomposicion de la varianza del voto (mediana de log(sueldo/SBU) por cargo x empresa), 2024-2025",
           "votos {:,}; cargos {:,}; empresas {:,}; varianza total {:.4f} (desviacion {:.3f})".format(
               len(v), v["cargo"].nunique(), v["empresa"].nunique(), v["v"].var(), v["v"].std()), "",
           "  {:<18} {:>10} {:>12}".format("modelo", "R2 dentro", "R2 fuera")]
    rng = np.random.default_rng(20261023)
    prueba = rng.random(len(v)) < 0.2
    ent, tst = v[~prueba], v[prueba]
    res = {}
    for m in modelos:
        mu, ef = efectos(v, m)
        r_in = r2(v["v"].to_numpy(), predecir(v, mu, ef).to_numpy())
        mu2, ef2 = efectos(ent, m)
        vistos = np.ones(len(tst), bool)
        for f in m:
            vistos &= tst[f].isin(ef2[f].index).to_numpy()
        t_ = tst[vistos]
        r_out = r2(t_["v"].to_numpy(), predecir(t_, mu2, ef2).to_numpy())
        res[m] = (r_in, r_out, int(vistos.sum()))
        out.append("  {:<18} {:>9.1%} {:>11.1%}   (prueba: {:,} votos)".format(" + ".join(m), r_in, r_out, int(vistos.sum())))
    ce, c, e = res[("cargo", "empresa")], res[("cargo",)], res[("empresa",)]
    out += ["", "Lectura (fuera de muestra):",
            "  lo que agrega la EMPRESA una vez conocido el cargo: {:+.1%} de la varianza".format(ce[1] - c[1]),
            "  lo que agrega el CARGO una vez conocida la empresa: {:+.1%}".format(ce[1] - e[1]),
            "  lo que explica el NIVEL solo: {:.1%}; nivel + empresa: {:.1%}".format(res[("nivel",)][1],
                                                                                  res[("nivel", "empresa")][1]),
            "  sin explicar con cargo + empresa: {:.1%}".format(1 - ce[1])]
    (SAL / "t18_varianza.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
