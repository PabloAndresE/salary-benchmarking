"""Para una lista de cargos: los candidatos que trae el embedding (Vertex, el producto) y lo que dice el juez.

Para cada titulo (como la API: `strip().upper()`): la traduccion si es ingles (capa de idioma con glosario),
los K grupos mas parecidos a lo que se busca (la traduccion, o el titulo si no es ingles), y para cada uno
el coseno, la P del juez, si entra a la zona del juez (coseno >= 0,90), si lo bloquea un candado y si quedo
aprobado (P >= 0,5 en la zona y sin candado). Marca el grupo elegido por el producto.

    GRPC_DNS_RESOLVER=native ../../../.venv/bin/python 70_candidatos_juez.py lista.txt salida.md [K]

La salida va fuera del repo (`demo/`).
"""
import pathlib
import sys

import numpy as np

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.evaluacion import embeddings  # noqa: E402
from benchmarking.producto import idioma  # noqa: E402
from benchmarking.producto.base_referencia import COS_JUEZ, P_JUEZ, BaseReferencia, _vecinos  # noqa: E402
from benchmarking.producto.capa0 import compatibles  # noqa: E402
from benchmarking.producto.juez import cargar as cargar_juez  # noqa: E402
from benchmarking.producto.nivel import seniority_lexica  # noqa: E402


def main(lista, salida, K=10):
    s = cargar_settings()
    base = BaseReferencia.cargar(RAIZ / "demo" / "base_v22.npz", s.get_sbu)
    base.juez = cargar_juez(RAIZ / "modelos" / "juez_v3")
    base.juez_vecinos = True
    base.nivel_por_grupo()
    base.candado_nivel = True
    base.traductor = idioma.cargar(RAIZ / "modelos" / "opus-mt-en-es")
    base.idioma_sueldo = "siempre"
    base.idioma_prima = None                     # como la API: D-055 apagado
    originales = [line.strip() for line in open(lista, encoding="utf-8") if line.strip()]
    titulos = [t.upper() for t in originales]
    trad = base.traductor.traducir([t for t in titulos if idioma.es_ingles(t)])
    buscado = {t: trad.get(t, t) for t in titulos}
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
    emb = {c: base.Z[i] for i, c in enumerate(base.celdas)}
    nuevos = sorted({x for x in list(buscado.values()) + titulos if x and x not in emb})
    emb.update(dict(zip(nuevos, embeddings.embeber(nuevos, cli, s.vertex_embedding_model))))
    elegido = base.resolver_idioma(titulos, emb)
    salida_ref = base.referenciar(titulos, emb).set_index("cargo")
    L = ["# Candidatos del embedding (Vertex) y veredicto del juez", "",
         "Por cada cargo: lo que se buscó (la traducción si está en inglés), los {} grupos más parecidos según "
         "Vertex y la P del juez (cross-encoder v3). **Zona** = coseno ≥ {:.2f} (solo ahí decide el juez). "
         "**Aprobado** = P ≥ {:.1f} en la zona y sin candado. ★ = el grupo que usó el producto.".format(K, COS_JUEZ, P_JUEZ), ""]
    for o, t in zip(originales, titulos):
        q = buscado[t]
        Q = np.asarray(emb[q], float)[None, :]
        Q /= np.linalg.norm(Q)
        vec, sim = _vecinos(Q, base.Z, base.k_busqueda * 4, excluir_propio=False)
        filas, vistos = [], set()
        for j, sj in zip(vec[0], sim[0]):
            g = int(base.grupo[j])
            if g in vistos:
                continue
            vistos.add(g)
            filas.append((int(j), float(sj)))
            if len(filas) == K:
                break
        P = base.juez.P([(q, str(base.celdas[j])) for j, _ in filas])
        r = salida_ref.loc[t]
        usado = r.get("equivalente") or r.get("cargo_base") or ""
        g_usado = int(base.grupo[base.idx[usado]]) if usado in base.idx else None
        L += ["## {}".format(o), "",
              "Se buscó: **{}** · resultado: {} ({}), {} empresas".format(
                  q, usado or "—", r["base"], int(r["empresas"])), "",
              "| # | Grupo (grafía más parecida) | Empresas | Coseno | P juez | Zona | Candado | Aprobado |",
              "|---|---|---|---|---|---|---|---|"]
        for k, ((j, sj), p) in enumerate(zip(filas, P), 1):
            c = str(base.celdas[j])
            na, nb = None, base.nivel[j]
            candado = (seniority_lexica(q) != seniority_lexica(c)) or not compatibles(q, c)
            zona = sj >= COS_JUEZ
            ok = zona and not candado and p >= P_JUEZ
            marca = " ★" if g_usado is not None and int(base.grupo[j]) == g_usado else ""
            L.append("| {} | {}{} | {} | {:.3f} | {:.2f} | {} | {} | {} |".format(
                k, c, marca, int(base.emp[j]), sj, p, "sí" if zona else "no", "sí" if candado else "—",
                "**sí**" if ok else "no"))
        L.append("")
    pathlib.Path(salida).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("listo:", salida)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 10)
