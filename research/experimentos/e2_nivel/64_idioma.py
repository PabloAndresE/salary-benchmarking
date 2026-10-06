"""D-050: los titulos en ingles de `base_v18`, traducidos (opus-mt local) y resueltos en la base.

    armar     traduce, embebe las traducciones (Vertex, como cualquier titulo), resuelve con
              `BaseReferencia.resolver_idioma` (tal cual, capa 0, juez; candados con el original) y
              arma la auditoria ciega de 50 pares (criterio a)
    decidir   lee los juicios del autor

    GRPC_DNS_RESOLVER=native CUDA_VISIBLE_DEVICES=0 ../../../.venv/bin/python 64_idioma.py armar
    ../../../.venv/bin/python 64_idioma.py decidir

SALIDAS: salidas/64_idioma_resueltos.parquet, 64_emb_traducciones.npz, 64_idioma_para_juzgar.csv,
64_idioma_mapa.csv (no abrir antes de juzgar), 64_idioma.txt
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
from benchmarking.producto import idioma  # noqa: E402
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402

SEM = 20261007
TRADUCTOR = RAIZ / "modelos" / "opus-mt-en-es"
JUEZ = RAIZ / "modelos" / "juez_v3"


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def embeber(textos):
    from benchmarking.config.settings import cargar_settings
    from benchmarking.evaluacion import embeddings
    s = cargar_settings()
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
    return embeddings.embeber(textos, cli, s.vertex_embedding_model)


def armar():
    from benchmarking.producto.juez import cargar as cargar_juez
    e41 = cargar("e41", "41_base_v16.py")
    base = BaseReferencia.cargar(RAIZ / "demo" / "base_v18.npz", e41._Ajustes.get_sbu)
    base.juez = cargar_juez(JUEZ)
    base.traductor = idioma.cargar(TRADUCTOR)
    assert base.juez is not None and base.traductor is not None
    ingles = [c for c in base.celdas if idioma.es_ingles(c)]
    print("{:,} titulos en ingles; traduciendo...".format(len(ingles)), flush=True)
    tts = base.traducciones_a_embeber(ingles)
    X = embeber(tts)
    np.savez_compressed(SAL / "64_emb_traducciones.npz", textos=np.array(tts, dtype=object), X=X.astype(np.float32))
    emb = {c: base.Z[i] for i, c in enumerate(base.celdas)} | dict(zip(tts, X))
    r = base.resolver_idioma(ingles, emb)
    trad = base.traductor.traducir(ingles)
    filas = []
    for t in ingles:
        i = base.idx[t]
        j, via, p, _ = r.get(t, (None, "", np.nan, ""))
        filas.append({"titulo": t, "traduccion": trad[t], "destino": base.celdas[j] if j is not None else "",
                      "via": via, "p_juez": p, "personas": float(base.personas[i]), "emp": int(base.emp[i]),
                      "grupo": int(base.grupo[i]), "grupo_destino": int(base.grupo[j]) if j is not None else -1})
    d = pd.DataFrame(filas)
    d["une"] = (d["grupo_destino"] >= 0) & (d["grupo_destino"] != d["grupo"])
    d.to_parquet(SAL / "64_idioma_resueltos.parquet", index=False)
    print("resueltos {:,} de {:,} ({:.0%}); unen a otro grupo {:,} ({:,.0f} personas)".format(
        (d["grupo_destino"] >= 0).sum(), len(d), (d["grupo_destino"] >= 0).mean(), d["une"].sum(),
        d.loc[d["une"], "personas"].sum()))
    print(d["via"].value_counts().to_dict())
    # auditoria ciega: 50 de los que unen, con peso por personas
    u = d[d["une"]].reset_index(drop=True)
    rng = np.random.default_rng(SEM)
    k = rng.choice(len(u), min(50, len(u)), replace=False, p=u["personas"] / u["personas"].sum())
    a = u.iloc[k].reset_index(drop=True)
    miembros = pd.Series(np.arange(len(base.celdas))).groupby(base.grupo).apply(list)

    def ejemplos(g):
        m = sorted(miembros[g], key=lambda x: -base.personas[x])[:4]
        return " ; ".join(base.celdas[x] for x in m)
    a["grupo_es"] = [ejemplos(g) for g in a["grupo_destino"]]
    a["n_ciego"] = np.arange(1, len(a) + 1)
    a[["n_ciego", "titulo", "grupo_es"]].assign(mismo="", nota="").to_csv(
        SAL / "64_idioma_para_juzgar.csv", index=False, encoding="utf-8-sig")
    a.to_csv(SAL / "64_idioma_mapa.csv", index=False, encoding="utf-8")
    print("auditoria: 64_idioma_para_juzgar.csv ({} pares)".format(len(a)))


def decidir():
    e55 = cargar("e55", "55_auditoria_clustering.py")
    j = e55.leer_juicios(SAL / "64_idioma_para_juzgar.csv")
    if not j["mismo"].isin(["si", "no"]).all():
        raise SystemExit("ALTO: faltan {} juicios".format(int((~j["mismo"].isin(["si", "no"])).sum())))
    m = pd.read_csv(SAL / "64_idioma_mapa.csv").merge(j[["n_ciego", "mismo"]], on="n_ciego")
    tasa = (m["mismo"] == "si").mean()
    out = ["64 · AUDITORIA DE LA CAPA DE IDIOMA (D-050 a)",
           "{} pares; el autor dice si en {:.0%} (exigido >= 90 %) -> {}".format(
               len(m), tasa, "CUMPLE" if tasa >= 0.90 else "NO CUMPLE"), "los que separa:"]
    out += ["   {}  ->  {}  (traduccion {}; {})".format(r.titulo, r.grupo_es, r.traduccion, r.via)
            for r in m[m["mismo"] == "no"].itertuples()]
    (SAL / "64_idioma.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    decidir() if sys.argv[1:] == ["decidir"] else armar()
