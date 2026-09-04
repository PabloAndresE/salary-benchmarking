"""De donde sale la referencia de un puesto: la cadena entera, paso a paso.

    python research/herramientas/explicar_puesto.py "GERENTE DE MARKETING DIGITAL"

Responde a la pregunta que hace todo el que lee un informe: *".cuanta gente hay detras de
este numero?"* — y muestra el ensanchamiento que hacen la fusion de grafias y el
vecindario semantico, que es justo lo que no se ve en la salida normal.

Tres tramos, segun donde caiga el titulo:

  1. .Esta el titulo en la base? Si no, se embebe al vuelo (necesita Vertex).
  2. .Con cuantas grafias se fusiono? Cada una era una celda separada y delgada.
  3. Si aun asi no llega al suelo de empresas, .a que vecinos se pregunta y con que peso?
"""
import argparse
import sys

import numpy as np

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import embeddings
from benchmarking.producto.base_referencia import (MIN_EMPRESAS, MIN_EMPRESAS_BANDA,
                                                   VECINOS, BaseReferencia, _vecinos)
from benchmarking.producto.nivel import nivel_lexico


def explicar(b, titulo, emb, sbu, anio=2025):
    t = str(titulo).strip().upper()
    f = float(sbu(anio))
    dol = lambda v: np.exp(v) * f
    propio = b.idx.get(t)

    print("\n" + "=" * 78)
    print(f"  {t}")
    print("=" * 78)

    if propio is None:
        print("\n  1. NO esta en la base. Se coloca por parecido semantico.")
    else:
        print(f"\n  1. Esta en la base.  nivel lexico: {nivel_lexico(t) or '(sin rango)'}")

    # -- 2. la fusion de grafias ------------------------------------------------
    if propio is not None:
        g = int(b.grupo[propio])
        her = np.flatnonzero(b.grupo == g)
        print(f"\n  2. FUSION DE GRAFIAS: su celda son {len(her)} titulo(s)")
        if len(her) > 1:
            for h in her[:8]:
                marca = "  <- el consultado" if h == propio else ""
                print(f"       {b.celdas[h][:52]:<54}{marca}")
            if len(her) > 8:
                print(f"       ... y {len(her) - 8} mas")
        print(f"     -> respaldo del grupo: {int(b.personas[propio]):,} personas en "
              f"{int(b.emp[propio]):,} empresas")

    # -- 3. como se contesta -----------------------------------------------------
    r = b.referenciar([t], emb, anio=anio).iloc[0]
    directo = r["base"] == "datos directos"
    print(f"\n  3. SE CONTESTA {'CON SUS PROPIOS DATOS' if directo else 'POR ANALOGIA'}")

    if not directo:
        Q = np.vstack([emb[t]]).astype(float)
        Q /= np.linalg.norm(Q, axis=1, keepdims=True)
        Zn = b.Z / np.linalg.norm(b.Z, axis=1, keepdims=True)
        vec, sim = _vecinos(Q, Zn, b.k_busqueda, excluir_propio=False)
        j, sm = vec[0], sim[0]
        if propio is not None:
            keep = b.grupo[j] != int(b.grupo[propio])
            if keep.any():
                j, sm = j[keep], sm[keep]
        j, sm = j[:VECINOS], sm[:VECINOS]
        dist = b.lam * (1.0 - sm)
        peso = 1.0 / (1.0 / b.W[j] + dist)
        peso /= peso.sum()
        if propio is None:
            print(f"     (su celda no existe: hace falta el suelo de {MIN_EMPRESAS} "
                  f"empresas)")
        else:
            print(f"     (su celda tiene {int(b.emp[propio])} empresas, por debajo del "
                  f"suelo de {MIN_EMPRESAS})")
        print(f"\n     {'vecino':<44} {'sim':>6} {'peso':>7} {'personas':>9} {'emp':>6}")
        for k in np.argsort(-peso)[:10]:
            print(f"     {b.celdas[j[k]][:43]:<44} {sm[k]:>6.3f} {peso[k]:>6.1%} "
                  f"{int(b.personas[j[k]]):>9,} {int(b.emp[j[k]]):>6}")
        if len(j) > 10:
            print(f"     ... y {len(j) - 10} vecinos mas")
        # sin contar dos veces las grafias del mismo grupo: comparten estadisticos, y
        # sumarlas multiplicaria el respaldo por el numero de formas de teclearlo
        _, uno = np.unique(b.grupo[j], return_index=True)
        print(f"\n     -> respaldo real: {int(b.personas[j[uno]].sum()):,} personas en "
              f"{int(b.emp[j[uno]].sum()):,} empresas   "
              f"({len(j)} vecinos pero {len(uno)} celdas distintas)")

    # -- 4. el resultado ---------------------------------------------------------
    print(f"\n  4. RESULTADO")
    print(f"     referencia   ${r['referencia']:>10,.0f}")
    print(f"     banda 50%    ${r['p25']:>10,.0f}  a  ${r['p75']:>10,.0f}")
    print(f"     banda 80%    ${r['p10']:>10,.0f}  a  ${r['p90']:>10,.0f}")
    print(f"     confianza    {r['confianza']}   (el centro puede moverse "
          f"+/-{r['incert_centro']:.1%})")
    print(f"     respaldo     {int(r['personas']):,} personas, {int(r['empresas']):,} "
          f"empresas")
    if propio is not None and b.emp[propio] >= MIN_EMPRESAS_BANDA:
        print(f"     la banda son CUANTILES EMPIRICOS (>= {MIN_EMPRESAS_BANDA} empresas)")
    else:
        print(f"     la banda sale del MODELO (tau del cargo), no de cuantiles empiricos")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("titulos", nargs="+")
    ap.add_argument("--base", default="demo/base_v4.npz")
    ap.add_argument("--anio", type=int, default=2025)
    ap.add_argument("--cache-embeddings",
                    default="research/experimentos/e1_premisa/emb_cache.npz")
    a = ap.parse_args()

    s = cargar_settings()
    b = BaseReferencia.cargar(a.base, s.get_sbu)
    emb = dict(zip(b.celdas, b.Z))
    nuevos = sorted({str(t).strip().upper() for t in a.titulos} - set(b.celdas))
    if nuevos:
        cache = embeddings.CacheArchivo(a.cache_embeddings)
        cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                        s.vertex_location)
        X = embeddings.embeber(nuevos, cli, s.vertex_embedding_model, cache=cache)
        cache.volcar()
        emb.update(dict(zip(nuevos, X)))
    for t in a.titulos:
        explicar(b, t, emb, s.get_sbu, a.anio)


if __name__ == "__main__":
    sys.exit(main())
