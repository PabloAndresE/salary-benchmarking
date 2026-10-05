"""D-047: los pares lejanos para entrenar el juez v4, etiquetados por GLM-5.3-Flash con la rubrica v7.

Se arman y se etiquetan MIENTRAS el autor juzga la validacion de `52`: etiquetar no cuesta, y las
etiquetas solo se usan si GLM pasa esa validacion (regla de D-047). Si no pasa, se descartan.

MUESTRA (10.000 pares, semilla fija; todos sin candado, entre nodos que son cargos):
    3.000  pares de representantes dentro de los clusters grandes (21-60 grupos) de la primera corrida
           del clustering: ahi estan los errores que encadenaron
    7.000  candidatos de `50` (con P de la v3), estratificados: 60 % con P >= 0,5 (la zona donde la v3
           dice `si` sin saber) y 40 % con P < 0,5; dentro de cada uno, la mitad con coseno de Vertex
           < 0,80 y la mitad entre 0,80 y 0,90
Fuera: los nodos sin descripcion de Gemini (no son cargos), los pares ya juzgados (auditorias de
D-043 y D-045, 13e, 20, 29, calibra) y los 100 de la validacion de `52`. Ademas, ningun par toca un
nodo de `prueba` ni de `prueba 2` (por titulo), para que la evaluacion de la v4 no se contamine.

ETIQUETA: GLM en los dos ordenes (rubrica v7, sin razonamiento, 8 peticiones a la vez); solo cuentan
los pares coherentes (D-047).

    .venv/bin/python 53_pares_v4.py armar
    .venv/bin/python 53_pares_v4.py etiquetar

SALIDAS (fuera del repo: titulos de clientes): salidas/53_pares_v4.parquet, 53_glm_v4.parquet,
53_pares_v4.txt
"""
import importlib.util
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
SEM = 20261007


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def armar():
    e43, e52 = cargar("e43", "43_perdida_vertex.py"), cargar("e52", "52_validacion_glm.py")
    tit, Zv, _ = e43.nodos()
    desc = pd.read_csv(SAL / "46_descripciones.csv", keep_default_na=False)
    es_cargo = np.zeros(len(tit), bool)
    for k, r in zip(desc["nodo"], desc["respuesta"]):
        es_cargo[int(k)] = bool(json.loads(r)["descripcion"].strip())
    fuera = e52.ya_juzgados()
    v = pd.read_csv(SAL / "52_validacion_mapa.csv")
    fuera |= {frozenset((a, b)) for a, b in zip(v["a"], v["b"])}
    # titulos de `prueba` y `prueba 2`: ningun par de entrenamiento los toca
    prueba = set()
    for f, a, b in (("13e_pares_400.csv", "comun", "raro"), ("20_pares_400.csv", "comun", "raro"),
                    ("29_prueba2_pares.csv", "comun", "raro")):
        d = e52.leer(SAL / f)
        if "particion" in d:
            d = d[d["particion"].isin(["prueba", "prueba2"])]
        prueba |= set(d[a]) | set(d[b])
    rng = np.random.default_rng(SEM)
    usados = set()

    def valido(i, j):
        q = (min(i, j), max(i, j))
        ok = (i != j and q not in usados and es_cargo[i] and es_cargo[j]
              and tit[i] not in prueba and tit[j] not in prueba
              and frozenset((tit[i], tit[j])) not in fuera and not e43.bloqueado(tit[i], tit[j]))
        if ok:
            usados.add(q)
        return ok

    filas = []
    cl = pd.read_parquet(SAL / "50_clusters.parquet")
    tam = cl["cluster"].value_counts()
    grandes = cl[cl["cluster"].isin(tam[(tam >= 21) & (tam <= 60)].index)].groupby("cluster")["nodo"].apply(list)
    intentos = 0
    while sum(f[2] == "cluster grande" for f in filas) < 3000 and intentos < 200_000:
        intentos += 1
        m = grandes.iloc[rng.integers(len(grandes))]
        i, j = (int(x) for x in rng.choice(m, 2, replace=False))
        if valido(i, j):
            filas.append((min(i, j), max(i, j), "cluster grande"))
    d = pd.read_parquet(SAL / "50_candidatos.parquet", columns=["i", "j", "P", "bloqueado"])
    p = pd.concat([pd.read_parquet(SAL / "50_puntajes_{}de3.parquet".format(k)) for k in range(3)])
    d = d.merge(p.rename(columns={"P": "P2"}), on=["i", "j"], how="left")
    d["P"] = d["P"].fillna(d["P2"])
    d = d[d["P"].notna() & ~d["bloqueado"]].copy()
    d["cos"] = np.einsum("ij,ij->i", Zv[d["i"]], Zv[d["j"]])
    cuotas = {("P>=0,5", "cos<0,80"): 2100, ("P>=0,5", "0,80-0,90"): 2100,
              ("P<0,5", "cos<0,80"): 1400, ("P<0,5", "0,80-0,90"): 1400}
    for (pp, cc), n_ in cuotas.items():
        m_p = d["P"] >= 0.5 if pp == "P>=0,5" else d["P"] < 0.5
        m_c = d["cos"] < 0.80 if cc == "cos<0,80" else (d["cos"] >= 0.80) & (d["cos"] < 0.90)
        pool = d[m_p & m_c].sample(frac=1, random_state=SEM)
        k = 0
        for i, j in zip(pool["i"].to_numpy(), pool["j"].to_numpy()):
            if valido(int(i), int(j)):
                filas.append((int(i), int(j), "candidato {} {}".format(pp, cc)))
                k += 1
                if k == n_:
                    break
    t = pd.DataFrame(filas, columns=["i", "j", "estrato"])
    t["a"], t["b"] = tit[t["i"]], tit[t["j"]]
    t["cos"] = np.einsum("ij,ij->i", Zv[t["i"]], Zv[t["j"]])
    t = t.merge(d[["i", "j", "P"]], on=["i", "j"], how="left")
    t.to_parquet(SAL / "53_pares_v4.parquet", index=False)
    print("pares: {:,}".format(len(t)))
    print(t["estrato"].value_counts().to_string())


def etiquetar():
    sys.modules["vllm"] = None
    e51 = cargar("e51", "51_etiquetador_local.py")
    t = pd.read_parquet(SAL / "53_pares_v4.parquet")
    sis, sha = e51.sistema()
    filas = [(k, o, a, b) for k, (x, y) in enumerate(zip(t["a"], t["b"]))
             for o, a, b in (("ab", x, y), ("ba", y, x))]
    t0 = time.time()
    textos = e51.correr_api("glm-5.3-flash", filas, sis)
    out = []
    for (k, o, a, b), s in zip(filas, textos):
        try:
            r = json.loads(s)
            out.append((k, o, r["mismo"], r["paso"], r["razon"]))
        except (ValueError, KeyError, TypeError):
            out.append((k, o, "", "", str(s)[:200]))
    r = pd.DataFrame(out, columns=["k", "orden", "mismo", "paso", "razon"])
    w = r.pivot_table(index="k", columns="orden", values="mismo", aggfunc="first")
    t["glm_ab"], t["glm_ba"] = w["ab"].reindex(t.index).to_numpy(), w["ba"].reindex(t.index).to_numpy()
    t["coherente"] = (t["glm_ab"] == t["glm_ba"]) & t["glm_ab"].isin(["si", "no"])
    t["etiqueta"] = np.where(t["coherente"], (t["glm_ab"] == "si").astype(float), np.nan)
    t["rubrica_sha"], t["modelo"] = sha, "zai-org/GLM-5.3-Flash"
    t.to_parquet(SAL / "53_glm_v4.parquet", index=False)
    r.to_parquet(SAL / "53_glm_v4_respuestas.parquet", index=False)
    lineas = ["53 · PARES LEJANOS PARA LA v4, etiquetados por GLM (rubrica v7, sha {})".format(sha),
              "{:,} pares en {:.0f} min; coherentes {:.1%}".format(len(t), (time.time() - t0) / 60,
                                                                 t["coherente"].mean())]
    for e_, g in t.groupby("estrato"):
        c = g[g["coherente"]]
        lineas.append("   {:<32} n={:>5}  coherentes {:.0%}  `si` de GLM {:.0%}  (v3 P>=0,5: {:.0%})".format(
            e_, len(g), g["coherente"].mean(), c["etiqueta"].mean(), (c["P"] >= 0.5).mean()))
    (SAL / "53_pares_v4.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))


if __name__ == "__main__":
    etiquetar() if sys.argv[1:] == ["etiquetar"] else armar()
