"""D-047 §3: la lista de sinonimos lejanos para que el autor apruebe, como las listas de la capa 0.

Las propuestas de Gemini (`46_propuestas.csv`) que existen en la base, para las anclas con mas
personas, entre clusters que el clustering en la zona confiable dejo separados y sin candado. Se
muestran solo titulos y personas: ni la v3 ni GLM, para no condicionar al autor. Lo aprobado se une
como una regla mas (un diccionario de sinonimos, versionado), igual que las erratas.

    python3 56_lista_sinonimos.py --anclas 100

SALIDA: salidas/56_sinonimos_para_aprobar.csv (ancla, propuesta, personas de cada una, ejemplos de
sus clusters, aprobar)
"""
import argparse
import importlib.util
import json
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
CLUSTERS = "50_clusters_confiable_cargos.parquet"


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(n_anclas):
    e47 = cargar("e47", "47_pares_bi_encoder.py")
    e43, tit, _, per, c0, a2n = e47.nodos_y_capa0()
    lab = pd.read_parquet(SAL / CLUSTERS)["cluster"].to_numpy()
    miembros = pd.Series(np.arange(len(tit))).groupby(lab).apply(list)
    per_cl = pd.Series(per).groupby(lab).sum()
    prop = pd.read_csv(SAL / "46_propuestas.csv", keep_default_na=False)
    filas = []
    for i, r in zip(prop["nodo"].astype(int), prop["respuesta"]):
        for a in {c0.atomo(t) for t in json.loads(r)["titulos"]}:
            j = a2n.get(a)
            if j is not None and j != i and lab[i] != lab[j] and not e43.bloqueado(tit[i], tit[j]):
                filas.append((i, j))
    d = pd.DataFrame(filas, columns=["i", "j"]).drop_duplicates()
    anclas = (pd.Series(per_cl[lab[d["i"]]].to_numpy(), index=d["i"]).groupby(level=0).first()
              .sort_values(ascending=False).index[:n_anclas])
    d = d[d["i"].isin(anclas)].copy()
    # un par por pareja de clusters (si dos anclas del mismo cluster proponen el mismo destino)
    d["ci"], d["cj"] = lab[d["i"]], lab[d["j"]]
    d = d.drop_duplicates(["ci", "cj"])

    def ejemplos(c, sin):
        otros = [str(tit[x]) for x in sorted(miembros[c], key=lambda x: -per[x]) if x != sin][:3]
        return " ; ".join(otros)
    out = pd.DataFrame({
        "ancla": tit[d["i"]], "propuesta": tit[d["j"]],
        "personas_ancla": per_cl[d["ci"]].round().astype(int).to_numpy(),
        "personas_propuesta": per_cl[d["cj"]].round().astype(int).to_numpy(),
        "otros_titulos_ancla": [ejemplos(c, i) for c, i in zip(d["ci"], d["i"])],
        "otros_titulos_propuesta": [ejemplos(c, j) for c, j in zip(d["cj"], d["j"])],
        "aprobar": ""})
    orden = out.groupby("ancla")["personas_ancla"].transform("max")
    out = out.assign(_o=orden).sort_values(["_o", "ancla", "personas_propuesta"],
                                           ascending=[False, True, False]).drop(columns="_o")
    out.to_csv(SAL / "56_sinonimos_para_aprobar.csv", index=False, encoding="utf-8-sig")
    print("{} pares de {} anclas; las anclas cubren {:.1%} de las personas".format(
        len(out), out["ancla"].nunique(), per_cl[lab[anclas]].sum() / per.sum()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--anclas", type=int, default=100)
    main(ap.parse_args().anclas)
