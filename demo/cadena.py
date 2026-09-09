"""La cadena concreta que el enlace SIMPLE recorre entre dos cargos sin relacion.

`e2_nivel/06` midio que union-find a 0,95 produce un grupo de 1.758 titulos con
`ASISTENTE CONTABLE` y `AUXILIAR DE LIMPIEZA` dentro. Eso suena imposible: no se parecen
en nada. Este script saca los saltos que los unen, uno a uno, para que se vea que cada
eslabon es razonable y la cadena entera no.

Reproduce el grafo del enlace simple —aristas del 10-NN que superan el umbral y no cruzan
escalon lexico— y busca el camino mas corto entre los dos.
"""
import numpy as np
from benchmarking.config.settings import cargar_settings
from benchmarking.producto.base_referencia import (UMBRAL_FUSION, VECINOS_FUSION,
                                                   BaseReferencia, _vecinos)
from benchmarking.producto.nivel import nivel_lexico

A, B = "ASISTENTE CONTABLE", "AUXILIAR DE LIMPIEZA"


def main():
    s = cargar_settings()
    b = BaseReferencia.cargar("demo/base_v6.npz", s.get_sbu)
    Z = b.Z / np.linalg.norm(b.Z, axis=1, keepdims=True)
    niv = b.nivel
    ia, ib = b.idx[A], b.idx[B]
    print(f"{A}  vs  {B}")
    print(f"  similitud DIRECTA entre los dos extremos: {float(Z[ia] @ Z[ib]):.4f}")
    print(f"  umbral de fusion: {UMBRAL_FUSION}   -> jamas se fusionarian por parecerse\n")

    print(f"construyendo el grafo de enlace simple sobre {len(b.celdas):,} titulos...")
    vec, sim = _vecinos(Z, Z, VECINOS_FUSION, excluir_propio=True)

    ady = [[] for _ in range(len(b.celdas))]
    aristas = 0
    for i in range(len(b.celdas)):
        for j, sj in zip(vec[i], sim[i]):
            if sj < UMBRAL_FUSION:
                break
            j = int(j)
            ni, nj = niv[i], niv[j]
            if np.isfinite(ni) and np.isfinite(nj) and ni != nj:
                continue
            ady[i].append((j, float(sj)))
            ady[j].append((i, float(sj)))
            aristas += 1
    print(f"aristas que superan {UMBRAL_FUSION}: {aristas:,}\n")

    # camino mas corto por anchura
    from collections import deque
    padre = {ia: None}
    q = deque([ia])
    while q and ib not in padre:
        u = q.popleft()
        for v, sv in ady[u]:
            if v not in padre:
                padre[v] = (u, sv)
                q.append(v)
    if ib not in padre:
        print("no hay camino: el enlace simple NO los uniria")
        return

    camino = []
    cur = ib
    while padre[cur] is not None:
        u, sv = padre[cur]
        camino.append((u, cur, sv))
        cur = u
    camino.reverse()

    print(f"LA CADENA: {len(camino)} saltos, y cada uno supera {UMBRAL_FUSION}")
    print(f"  {'':<48} {'sim con el anterior':>20}")
    print(f"  {b.celdas[camino[0][0]][:47]:<48}")
    for u, v, sv in camino:
        print(f"  {b.celdas[v][:47]:<48} {sv:>20.4f}")

    print(f"\n  extremo a extremo: {float(Z[ia] @ Z[ib]):.4f}  "
          f"<- muy por debajo del umbral, y aun asi acaban en el mismo grupo")

    # tamano de la componente conexa
    visto = {ia}
    q = deque([ia])
    while q:
        u = q.popleft()
        for v, _ in ady[u]:
            if v not in visto:
                visto.add(v)
                q.append(v)
    print(f"\n  la componente conexa entera: {len(visto):,} titulos, "
          f"{int(b.personas[sorted(visto)].sum()):,} personas")


if __name__ == "__main__":
    main()
