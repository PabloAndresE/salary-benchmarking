"""Exploratorio (D-050, idea del autor): ¿contra que empresas hay que comparar un titulo en ingles?

Para cada voto de las empresas apartadas de `54` con titulo en ingles RESUELTO por su traduccion (64), se
compara el voto con la mediana del grupo en espanol (empresas de entrenamiento) segun el grupo de pares:
todas, mismo tamano (segmento), misma actividad (CIIU nivel 1), ambas, y empresas que titulan en ingles
(>= 20 % de sus titulos). Se reporta el residuo (voto - mediana de pares) y cuantos votos tienen >= 3
empresas pares. Sin criterio: es para disenar la medicion.

    ../../../.venv/bin/python 66_pares_idioma.py

SALIDA: salidas/66_pares_idioma.txt
"""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.evaluacion import splits  # noqa: E402
from benchmarking.producto.idioma import es_ingles  # noqa: E402


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    e41, e54 = cargar("e41", "41_base_v16.py"), cargar("e54", "54_pinball.py")
    mk = e41.cargar_marco()
    mk["cargo_norm"] = mk["cargo_norm"].astype(str)
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    rng = np.random.default_rng(e54.SEM)
    emp0 = np.array(sorted(train["empresa_ruc"].unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train["empresa_ruc"].isin(val)].dropna(subset=["y"])
    ts = train[train["empresa_ruc"].isin(val)].dropna(subset=["y"])
    # titulan en ingles: >= 20 % de sus titulos distintos
    tit_emp = train.groupby("empresa_ruc")["cargo_norm"].unique()
    frac = tit_emp.map(lambda ts_: np.mean([es_ingles(t) for t in ts_]))
    ingl = set(frac[frac >= 0.20].index)
    meta = train.groupby("empresa_ruc")[["segmento", "ciiu_n1"]].first()
    b = np.load(RAIZ / "demo" / "base_v19.npz", allow_pickle=True)
    grupo = dict(zip((str(c) for c in b["celdas"]), b["grupo"].astype(int)))
    tr = tr.assign(g=tr["cargo_norm"].map(grupo))
    por_emp = tr.groupby(["g", "empresa_ruc"])["y"].median().reset_index()
    por_emp = por_emp.join(meta, on="empresa_ruc")
    por_emp["ingl"] = por_emp["empresa_ruc"].isin(ingl)
    r = pd.read_parquet(SAL / "64_idioma_resueltos.parquet")
    dest = dict(zip(r["titulo"], r["destino"]))
    v = ts[ts["cargo_norm"].map(es_ingles)]
    v = v.groupby(["cargo_norm", "empresa_ruc"])["y"].median().reset_index().rename(columns={"y": "voto"})
    v = v[v["cargo_norm"].map(lambda t: bool(dest.get(t)))].join(meta, on="empresa_ruc")
    v["g"] = v["cargo_norm"].map(lambda t: grupo.get(dest[t]))
    pares = {"todas": lambda p, x: p,
             "mismo tamano": lambda p, x: p[p["segmento"] == x["segmento"]],
             "misma actividad": lambda p, x: p[p["ciiu_n1"] == x["ciiu_n1"]],
             "tamano y actividad": lambda p, x: p[(p["segmento"] == x["segmento"]) & (p["ciiu_n1"] == x["ciiu_n1"])],
             "titulan en ingles": lambda p, x: p[p["ingl"]]}
    gp = dict(tuple(por_emp.groupby("g")))
    out = ["66 · ¿CONTRA QUE EMPRESAS COMPARAR UN TITULO EN INGLES? ({:,} votos de {:,} empresas apartadas; "
           "{:,} empresas de entrenamiento titulan en ingles)".format(len(v), v["empresa_ruc"].nunique(), len(ingl)),
           "residuo = voto - mediana de las empresas pares en el grupo de la traduccion (log); 0 = bien centrado"]
    for nombre, f in pares.items():
        res = []
        for x in v.itertuples():
            p = gp.get(x.g)
            if p is None:
                continue
            p = f(p, x._asdict())
            if len(p) >= 3:
                res.append(x.voto - p["y"].median())
        res = np.array(res)
        out.append("   {:<20} con >= 3 pares {:>4} de {} ({:.0%}); residuo mediano {:+.3f} (x{:.2f}); |residuo| mediano {:.3f}".format(
            nombre, len(res), len(v), len(res) / len(v), np.median(res), np.exp(np.median(res)), np.median(np.abs(res))))
    (SAL / "66_pares_idioma.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
