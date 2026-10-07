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
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "src"))
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
CLUSTERS = "50_clusters_confiable_cargos.parquet"


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(n_anclas, desde=0, salida="56_sinonimos_para_aprobar.csv"):
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
              .sort_values(ascending=False).index[desde:desde + n_anclas])
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
    if desde:                            # ronda 2+: fuera los pares que el autor ya juzgo
        previa = pd.read_csv(SAL / "56_sinonimos_para_aprobar.csv", encoding="utf-8-sig", dtype=str,
                             keep_default_na=False)
        vistos = {frozenset(x) for x in zip(previa["ancla"], previa["propuesta"])}
        out = out[[frozenset(x) not in vistos for x in zip(out["ancla"], out["propuesta"])]]
    out.to_csv(SAL / salida, index=False, encoding="utf-8-sig")
    print("{} pares de {} anclas; las anclas cubren {:.1%} de las personas".format(
        len(out), out["ancla"].nunique(), per_cl[lab[anclas]].sum() / per.sum()))


def aplicar(archivo_clusters=CLUSTERS, salida="50_clusters_confiable_cargos_sinonimos.parquet"):
    """Une los clusters con los sinonimos APROBADOS, con dos protecciones: dos grupos no se juntan si
    entre ellos hay un par que el autor RECHAZO, ni si un candado (nivel de la rubrica, seniority,
    numero de grado) lo impide. Se procesa de mas a menos personas."""
    from benchmarking.producto import capa0 as c0m
    from benchmarking.producto.nivel import nivel_rubrica, seniority_lexica
    e47 = cargar("e47", "47_pares_bi_encoder.py")
    _, tit, _, per, _, _ = e47.nodos_y_capa0()
    cl = pd.read_parquet(SAL / archivo_clusters)
    lab = cl["cluster"].to_numpy()
    idx = {str(t): k for k, t in enumerate(tit)}
    s = pd.read_csv(SAL / "56_sinonimos_para_aprobar.csv", encoding="utf-8-sig", dtype=str,
                    keep_default_na=False)
    s["aprobar"] = s["aprobar"].str.strip().str.lower()
    s["ci"] = [lab[idx[a]] for a in s["ancla"]]
    s["cj"] = [lab[idx[p]] for p in s["propuesta"]]
    rechazos = {frozenset((a, b)) for a, b in zip(s.loc[s["aprobar"] == "no", "ci"], s.loc[s["aprobar"] == "no", "cj"])}
    miembros = {}
    for k, c in enumerate(lab):
        miembros.setdefault(int(c), []).append(k)
    niv = {c: {nivel_rubrica(tit[k]) for k in m} - {None} for c, m in miembros.items()}
    sen = {c: {seniority_lexica(tit[k]) for k in m} for c, m in miembros.items()}
    gra = {c: frozenset().union(*[c0m.grado_numerico(tit[k]) for k in m]) for c, m in miembros.items()}
    padre = {c: c for c in miembros}

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x
    grupo_de = {c: {c} for c in miembros}
    ap = s[s["aprobar"] == "si"].copy()
    ap["p"] = [per[miembros[a]].sum() + per[miembros[b]].sum() for a, b in zip(ap["ci"], ap["cj"])]
    motivo = {"unidos": 0, "ya juntos": 0, "rechazo del autor": 0, "candado": 0}
    aplicadas = []
    for a, b in zip(ap.sort_values("p", ascending=False)["ci"], ap.sort_values("p", ascending=False)["cj"]):
        ra, rb = raiz(int(a)), raiz(int(b))
        if ra == rb:
            motivo["ya juntos"] += 1
            continue
        if any(frozenset((x, y)) in rechazos for x in grupo_de[ra] for y in grupo_de[rb]):
            motivo["rechazo del autor"] += 1
            continue
        if len(niv[ra] | niv[rb]) > 1 or sen[ra] != sen[rb] or (gra[ra] and gra[rb] and gra[ra] != gra[rb]):
            motivo["candado"] += 1
            continue
        padre[rb] = ra
        aplicadas.append((int(a), int(b)))
        grupo_de[ra] |= grupo_de.pop(rb)
        niv[ra] |= niv.pop(rb)
        sen.pop(rb)
        gra[ra] = gra[ra] | gra.pop(rb)
        motivo["unidos"] += 1
    nuevo = np.array([raiz(int(c)) for c in lab])
    cl.assign(cluster=nuevo).to_parquet(SAL / salida, index=False)
    pd.DataFrame(aplicadas, columns=["ci", "cj"]).to_parquet(SAL / "56_uniones_aplicadas.parquet", index=False)
    print("sinonimos aplicados: " + json.dumps(motivo, ensure_ascii=False))
    print("clusters: {:,} -> {:,}".format(len(set(lab.tolist())), len(set(nuevo.tolist()))))
    tam = pd.Series(per).groupby(nuevo).sum().sort_values(ascending=False)
    for c in tam.index[:15]:
        m = [k for k in range(len(tit)) if nuevo[k] == c]
        top = [str(tit[k]) for k in sorted(m, key=lambda k: -per[k])[:8]]
        print("   {:>7,} personas, {:>3} grupos | {}".format(int(tam[c]), len(m), " ; ".join(top)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--anclas", type=int, default=100)
    ap.add_argument("--desde", type=int, default=0, help="ronda 2: las anclas desde esta posicion")
    ap.add_argument("--salida", default="56_sinonimos_para_aprobar.csv")
    ap.add_argument("--aplicar", action="store_true", help="une los clusters con lo aprobado")
    a_ = ap.parse_args()
    aplicar() if a_.aplicar else main(a_.anclas, a_.desde, a_.salida)
