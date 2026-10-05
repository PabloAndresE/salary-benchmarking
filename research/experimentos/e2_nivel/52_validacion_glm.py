"""D-047: validacion limpia de GLM-5.3-Flash como etiquetador, con 100 pares lejanos NUEVOS.

Registrado antes (D-047, commit 6a3b1d6). Los pares salen de la misma zona de donde saldran los
datos de entrenamiento del juez v4, y no se usaron para escribir la rubrica v7:
    30  pares de representantes dentro de los clusters grandes (21-60 grupos) de la primera corrida
        del clustering (`50_clusters.parquet`): ahi estan los errores que encadenaron
    35  candidatos de `50` con P de la v3 >= 0,5
    35  candidatos de `50` con P de la v3 < 0,5
Todos con coseno de Vertex < 0,85 y sin candado. Fuera: los nodos sin descripcion de Gemini (no son
cargos), y cualquier par ya juzgado (auditorias de D-043 y D-045, 13e, 20, 29, calibra).

    python3 52_validacion_glm.py armar       arma la auditoria ciega
    .venv/bin/python 52_validacion_glm.py medir   (despues de juzgar) GLM y el criterio

CRITERIO (D-047): se usa GLM si, en los pares en que es coherente en los dos ordenes, coincide con
el autor >= 90 %, y es coherente en >= 85 % de los pares.

SALIDAS: salidas/52_validacion_para_juzgar.csv (n_ciego, a, b, mismo, nota), 52_validacion_mapa.csv
(no abrir antes de juzgar), 52_glm.csv, 52_validacion_glm.txt
"""
import importlib.util
import json
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
SEM = 20261006


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def leer(p):
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                       keep_default_na=False)


def ya_juzgados():
    t = set()
    for f, a, b in (("43_auditoria_para_juzgar.csv", "a", "b"), ("45_auditoria_para_juzgar.csv", "a", "b"),
                    ("13e_para_juzgar.csv", "comun", "raro"), ("20_para_juzgar.csv", "comun", "raro"),
                    ("29_prueba2_para_juzgar.csv", "comun", "raro")):
        d = leer(SAL / f)
        t |= {frozenset((x, y)) for x, y in zip(d[a], d[b])}
    c = pd.read_csv(SAL / "21_paquete_v6" / "calibra.csv", dtype=str, keep_default_na=False)
    return t | {frozenset((x, y)) for x, y in zip(c["comun"], c["raro"])}


def armar():
    e43 = cargar("e43", "43_perdida_vertex.py")
    tit, Zv, _ = e43.nodos()
    desc = pd.read_csv(SAL / "46_descripciones.csv", keep_default_na=False)
    es_cargo = np.zeros(len(tit), bool)
    for k, r in zip(desc["nodo"], desc["respuesta"]):
        es_cargo[int(k)] = bool(json.loads(r)["descripcion"].strip())
    juzgados = ya_juzgados()
    rng = np.random.default_rng(SEM)

    def valido(i, j):
        return (i != j and es_cargo[i] and es_cargo[j] and float(Zv[i] @ Zv[j]) < 0.85
                and frozenset((tit[i], tit[j])) not in juzgados and not e43.bloqueado(tit[i], tit[j]))

    # 30 de dentro de los clusters grandes de la primera corrida
    cl = pd.read_parquet(SAL / "50_clusters.parquet")
    tam = cl["cluster"].value_counts()
    grandes = cl[cl["cluster"].isin(tam[(tam >= 21) & (tam <= 60)].index)].groupby("cluster")["nodo"].apply(list)
    a = []
    while len(a) < 30:
        m = grandes.iloc[rng.integers(len(grandes))]
        i, j = (int(x) for x in rng.choice(m, 2, replace=False))
        if valido(i, j) and (min(i, j), max(i, j)) not in {(p, q) for p, q, _ in a}:
            a.append((min(i, j), max(i, j), "dentro de cluster grande"))
    # 35 + 35 de los candidatos de 50, por la P de la v3
    d = pd.read_parquet(SAL / "50_candidatos.parquet", columns=["i", "j", "P", "bloqueado"])
    p = pd.concat([pd.read_parquet(SAL / "50_puntajes_{}de3.parquet".format(k)) for k in range(3)])
    d = d.merge(p.rename(columns={"P": "P2"}), on=["i", "j"], how="left")
    d["P"] = d["P"].fillna(d["P2"])
    d = d[d["P"].notna() & ~d["bloqueado"]]
    for nombre, mascara in (("candidato, v3 P >= 0,5", d["P"] >= 0.5), ("candidato, v3 P < 0,5", d["P"] < 0.5)):
        pool = d[mascara].sample(frac=1, random_state=SEM)
        k = 0
        for i, j in zip(pool["i"], pool["j"]):
            if valido(int(i), int(j)):
                a.append((int(i), int(j), nombre))
                k += 1
                if k == 35:
                    break
    t = pd.DataFrame(a, columns=["i", "j", "grupo"]).sample(frac=1, random_state=SEM).reset_index(drop=True)
    t["n_ciego"] = np.arange(1, len(t) + 1)
    gira = rng.random(len(t)) < 0.5
    t["a"] = np.where(gira, tit[t["j"]], tit[t["i"]])
    t["b"] = np.where(gira, tit[t["i"]], tit[t["j"]])
    t["coseno"] = [float(Zv[i] @ Zv[j]) for i, j in zip(t["i"], t["j"])]
    t[["n_ciego", "a", "b"]].assign(mismo="", nota="").to_csv(
        SAL / "52_validacion_para_juzgar.csv", index=False, encoding="utf-8-sig")
    t.to_csv(SAL / "52_validacion_mapa.csv", index=False, encoding="utf-8")
    print("{} pares: {}".format(len(t), t["grupo"].value_counts().to_dict()))
    print("coseno: mediana {:.2f}, minimo {:.2f}".format(t["coseno"].median(), t["coseno"].min()))


def medir():
    import sys as _s
    _s.modules["vllm"] = None
    e51 = cargar("e51", "51_etiquetador_local.py")
    j = leer(SAL / "52_validacion_para_juzgar.csv")
    j["mismo"] = j["mismo"].str.strip().str.lower()
    if not j["mismo"].isin(["si", "no"]).all():
        raise SystemExit("ALTO: faltan {} juicios".format(int((~j["mismo"].isin(["si", "no"])).sum())))
    m = pd.read_csv(SAL / "52_validacion_mapa.csv").merge(
        j[["n_ciego", "mismo"]].astype({"n_ciego": int}), on="n_ciego")
    sis, sha = e51.sistema()
    filas = [(r.n_ciego, o, a, b) for r in m.itertuples() for o, a, b in (("ab", r.a, r.b), ("ba", r.b, r.a))]
    textos = e51.correr_api("glm-5.3-flash", filas, sis)
    out = []
    for (n, o, a, b), t in zip(filas, textos):
        try:
            v = json.loads(t)["mismo"]
        except (ValueError, KeyError, TypeError):
            v = ""
        out.append((n, o, v))
    r = pd.DataFrame(out, columns=["n_ciego", "orden", "glm"])
    r.to_csv(SAL / "52_glm.csv", index=False, encoding="utf-8")
    w = r.pivot_table(index="n_ciego", columns="orden", values="glm", aggfunc="first")
    x = m.set_index("n_ciego").join(w)
    coh = (x["ab"] == x["ba"]) & x["ab"].isin(["si", "no"])
    acierto = (x.loc[coh, "ab"] == x.loc[coh, "mismo"]).mean()
    lineas = ["52 · VALIDACION LIMPIA DE GLM-5.3-Flash (rubrica v7, sha {})".format(sha),
              "pares {}; el autor dice si en {:.0%}".format(len(x), (x["mismo"] == "si").mean()),
              "coherente en los dos ordenes: {:.1%} (exigido >= 85 %)".format(coh.mean()),
              "acierto en los coherentes: {:.1%} (exigido >= 90 %)".format(acierto)]
    for g, gx in x.groupby("grupo"):
        c = (gx["ab"] == gx["ba"]) & gx["ab"].isin(["si", "no"])
        lineas.append("   {:<28} n={:>3}  coherente {:.0%}  acierto {:.0%}  autor si {:.0%}".format(
            g, len(gx), c.mean(), (gx.loc[c, "ab"] == gx.loc[c, "mismo"]).mean(), (gx["mismo"] == "si").mean()))
    pasa = coh.mean() >= 0.85 and acierto >= 0.90
    lineas.append("\n>>> CRITERIO D-047: {} <<<".format("SE USA GLM como etiquetador" if pasa else "NO se usa GLM"))
    lineas.append("\ndesacuerdos (coherentes):")
    for n, f in x[coh & (x["ab"] != x["mismo"])].iterrows():
        lineas.append("   autor {:<2} GLM {:<2} | {} / {}".format(f["mismo"], f["ab"], f["a"], f["b"]))
    (SAL / "52_validacion_glm.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))


if __name__ == "__main__":
    medir() if sys.argv[1:] == ["medir"] else armar()
