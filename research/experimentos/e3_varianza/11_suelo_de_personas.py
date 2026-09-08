""".Que suelo de PERSONAS poner, y cuanto cuesta?

`10` midio que el suelo de empresas no basta: 297 celdas directas (5,7%) tienen 3 o 4
personas en total, y la mediana de tres votos de una persona cada uno ES el sueldo de una
de ellas. La regla de dominancia por peso, en cambio, se cumple sola y no hace falta.

El arreglo es un suelo de personas junto al de empresas. Aqui se elige el numero.

COMO SE DECIDE. No por precision —esto es confidencialidad— sino mirando las dos cosas que
cuesta y una que protege:

  protege  cuantas celdas y personas dejan de publicar una mediana reconocible
  cuesta   cuanta gente pasa de "datos directos" a "por analogia"
  cuesta   cuanto empeora la respuesta de ESA gente al pasar a analogia

Lo tercero es lo que decide si el suelo es barato: si contestar por analogia a una celda de
5 personas es igual de bueno que contestar con sus propios datos, el suelo es gratis.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import (MIN_EMPRESAS, MIN_EMPRESAS_BANDA,
                                                   BaseReferencia)

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
UMBRALES = (0, 3, 5, 10, 15, 20, 30)


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    m = m.copy()
    m["cargo_norm"] = m.cargo_norm.astype(str)
    train, _ = splits.partir(m, splits.empresas_test(m))
    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train.empresa_ruc.isin(val)].copy()
    ts = train[train.empresa_ruc.isin(val)].copy()
    print(f"construir {tr.empresa_ruc.nunique():,} empresas   "
          f"evaluar {ts.empresa_ruc.nunique():,}")

    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    cache = embeddings.CacheArchivo(CACHE)
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                    s.vertex_location)
    print(f"embebiendo {len(etiquetas):,} titulos...")
    X = embeddings.embeber(etiquetas, cli, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    emb = dict(zip(etiquetas, X))

    print("construyendo la base sobre tr...")
    b = BaseReferencia.construir(tr, emb, s.get_sbu)
    print(f"base: {len(b.celdas):,} celdas")

    titulos = ts.cargo_norm.tolist()
    y = pd.to_numeric(ts["y"], errors="coerce").to_numpy(float)

    print("\n" + "=" * 88)
    print("EL BARRIDO. Que protege, que cuesta")
    print("=" * 88)
    print(f"  {'suelo':<7} {'celdas dir.':>12} {'cobertura':>10} {'pierde':>8} "
          f"{'MAE':>8} {'personas protegidas':>21}")
    ref = {}
    for u in UMBRALES:
        b.min_personas = u
        r = b.referenciar(titulos, emb)
        directo = (r["base"] == "datos directos").to_numpy()
        ok = np.isfinite(y) & np.isfinite(r["referencia_log"].to_numpy(float))
        mae = float(np.abs(y[ok] - r["referencia_log"].to_numpy(float)[ok]).mean())
        # celdas que quedan directas, y gente de la BASE que deja de publicar
        dir_celda = (b.emp >= MIN_EMPRESAS) & (b.personas >= u)
        prot = int(b.personas[(b.emp >= MIN_EMPRESAS) & (b.personas < u)].sum())
        ref[u] = dict(directo=directo, mae=mae, cob=float(directo.mean()))
        print(f"  {u:<7} {int(dir_celda.sum()):>12,} {float(directo.mean()):>9.1%} "
              f"{ref[0]['cob'] - float(directo.mean()):>7.1%} {mae:>8.4f} "
              f"{prot:>20,}")

    print("\n" + "=" * 88)
    print("LO QUE DE VERDAD DECIDE: .empeora la respuesta de la gente afectada?")
    print("=" * 88)
    print("  Se compara, SOLO sobre las personas que cambian de regimen, el error con")
    print("  datos propios contra el error por analogia. Si es parecido, el suelo es gratis.")
    print()
    print(f"  {'suelo':<7} {'personas':>9} {'MAE directo':>12} {'MAE analogia':>13} "
          f"{'coste':>9}")
    base0 = ref[0]["directo"]
    r0 = b.__class__.referenciar
    b.min_personas = 0
    pred0 = b.referenciar(titulos, emb)["referencia_log"].to_numpy(float)
    for u in UMBRALES[1:]:
        b.min_personas = u
        predu = b.referenciar(titulos, emb)["referencia_log"].to_numpy(float)
        cambia = base0 & ~ref[u]["directo"]
        sel = cambia & np.isfinite(y) & np.isfinite(pred0) & np.isfinite(predu)
        if sel.sum() < 30:
            print(f"  {u:<7} {int(sel.sum()):>9,}  (muy poca gente para medir)")
            continue
        a = float(np.abs(y[sel] - pred0[sel]).mean())
        c = float(np.abs(y[sel] - predu[sel]).mean())
        print(f"  {u:<7} {int(sel.sum()):>9,} {a:>12.4f} {c:>13.4f} {c - a:>+9.4f}")

    print("\n" + "=" * 88)
    print("Y CUANTAS CELDAS SIGUEN PUBLICANDO CUANTILES EMPIRICOS")
    print("=" * 88)
    print("  (son las mas expuestas: cuartiles de datos reales, no un numero de modelo)")
    for u in UMBRALES:
        q = (b.emp >= MIN_EMPRESAS_BANDA) & (b.personas >= u)
        pocos = (b.emp >= MIN_EMPRESAS_BANDA) & (b.personas < u)
        print(f"  suelo {u:<4} con banda empirica: {int(q.sum()):>6,}   "
              f"bloqueadas: {int(pocos.sum()):>5,}")


if __name__ == "__main__":
    main()
