"""D-046 criterio a: auditoria ciega del clustering en la zona confiable (rubrica v7).

100 pares de representantes que el clustering JUNTO (de grupos distintos de la capa 0), sorteados con
peso por las personas del cluster, mezclados con 100 candidatos cercanos (coseno de Vertex >= 0,85)
que NO junto. Se exige >= 90 % de `si` en los juntados. Los no juntados son descriptivos (cuanto deja
sin unir que si es el mismo cargo). Fuera: cualquier par ya juzgado.

    python3 55_auditoria_clustering.py armar
    python3 55_auditoria_clustering.py decidir

SALIDAS: salidas/55_auditoria_para_juzgar.csv, 55_auditoria_mapa.csv (no abrir antes de juzgar),
55_auditoria_clustering.txt
"""
import importlib.util
import pathlib
import sys
import zipfile

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
SEM = 20261008
CLUSTERS = "50_clusters_confiable_cargos.parquet"


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def armar():
    e43, e52 = cargar("e43", "43_perdida_vertex.py"), cargar("e52", "52_validacion_glm.py")
    tit, Zv, per = e43.nodos()
    fuera = e52.ya_juzgados()
    for f in ("52_validacion_mapa.csv",):
        v = pd.read_csv(SAL / f)
        fuera |= {frozenset((a, b)) for a, b in zip(v["a"], v["b"])}
    cl = pd.read_parquet(SAL / CLUSTERS)
    lab = cl["cluster"].to_numpy()
    rng = np.random.default_rng(SEM)
    grupos = cl.groupby("cluster")["nodo"].apply(list)
    grupos = grupos[grupos.str.len() >= 2]
    peso = np.array([per[m].sum() for m in grupos], dtype=float)
    peso /= peso.sum()
    juntos, vistos = [], set()
    while len(juntos) < 100:
        m = grupos.iloc[rng.choice(len(grupos), p=peso)]
        i, j = (int(x) for x in rng.choice(m, 2, replace=False))
        q = (min(i, j), max(i, j))
        if q in vistos or frozenset((tit[i], tit[j])) in fuera:
            continue
        vistos.add(q)
        juntos.append((q[0], q[1], "juntado"))
    d = pd.read_parquet(SAL / "50_candidatos.parquet", columns=["i", "j", "bloqueado"])
    d = d[~d["bloqueado"] & (lab[d["i"]] != lab[d["j"]])]
    d = d.assign(cos=np.einsum("ij,ij->i", Zv[d["i"]], Zv[d["j"]]))
    d = d[d["cos"] >= 0.85].sample(frac=1, random_state=SEM)
    separados = []
    for i, j in zip(d["i"].to_numpy(), d["j"].to_numpy()):
        if frozenset((tit[i], tit[j])) not in fuera:
            separados.append((int(i), int(j), "no juntado"))
        if len(separados) == 100:
            break
    t = pd.DataFrame(juntos + separados, columns=["i", "j", "grupo"]).sample(frac=1, random_state=SEM)
    t = t.reset_index(drop=True)
    t["n_ciego"] = np.arange(1, len(t) + 1)
    gira = rng.random(len(t)) < 0.5
    t["a"] = np.where(gira, tit[t["j"]], tit[t["i"]])
    t["b"] = np.where(gira, tit[t["i"]], tit[t["j"]])
    t["cos"] = np.einsum("ij,ij->i", Zv[t["i"]], Zv[t["j"]])
    t[["n_ciego", "a", "b"]].assign(mismo="", nota="").to_csv(
        SAL / "55_auditoria_para_juzgar.csv", index=False, encoding="utf-8-sig")
    t.to_csv(SAL / "55_auditoria_mapa.csv", index=False, encoding="utf-8")
    print(t["grupo"].value_counts().to_dict(), "coseno mediano {:.2f}".format(t["cos"].median()))


def leer_juicios(f):
    try:
        j = pd.read_excel(f, engine="openpyxl", dtype=str).fillna("")       # Excel lo guarda en .xlsx
    except (zipfile.BadZipFile, ValueError, ImportError):
        j = pd.read_csv(f, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                        keep_default_na=False)
    j["n_ciego"] = j["n_ciego"].astype(str).str.replace(r"\.0$", "", regex=True).astype(int)
    j["mismo"] = j["mismo"].str.strip().str.lower()
    return j


def decidir():
    j = leer_juicios(SAL / "55_auditoria_para_juzgar.csv")
    if not j["mismo"].isin(["si", "no"]).all():
        raise SystemExit("ALTO: faltan {} juicios".format(int((~j["mismo"].isin(["si", "no"])).sum())))
    m = pd.read_csv(SAL / "55_auditoria_mapa.csv").merge(j[["n_ciego", "mismo"]], on="n_ciego")
    jun = m[m["grupo"] == "juntado"]
    sep = m[m["grupo"] == "no juntado"]
    tasa = (jun["mismo"] == "si").mean()
    out = ["55 · AUDITORIA DEL CLUSTERING EN LA ZONA CONFIABLE (D-046 a, rubrica v7)",
           "juntados: {} pares; el autor dice si en {:.0%} (exigido >= 90 %)".format(len(jun), tasa),
           "no juntados (coseno >= 0,85): {} pares; el autor dice si en {:.0%} (descriptivo)".format(
               len(sep), (sep["mismo"] == "si").mean()),
           "\n>>> CRITERIO D-046 a: {} <<<".format("CUMPLE" if tasa >= 0.90 else "NO CUMPLE"),
           "\njuntados que el autor separa:"]
    out += ["   {} / {}".format(a, b) for a, b in zip(jun.loc[jun["mismo"] == "no", "a"], jun.loc[jun["mismo"] == "no", "b"])]
    (SAL / "55_auditoria_clustering.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    decidir() if sys.argv[1:] == ["decidir"] else armar()
