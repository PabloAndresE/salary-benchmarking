""".Y si la escalera de escalones esta medida con el estimador equivocado?

EL DEFECTO. `efecto_nivel` estima cuanto paga cada escalon con PROMEDIOS —centra por la
media de la empresa, luego por la media del area, y promedia por nivel— y ese numero se
suma a `m`, que es una MEDIANA ponderada:

    aj = efecto[mi_nivel] - efecto[nivel_del_vecino]      <- diferencia de PROMEDIOS
    mu = suma(peso * (m[j] + aj))                          <- sumada a una MEDIANA

Una diferencia-de-promedios solo coincide con una diferencia-de-medianas si las dos
distribuciones tienen la MISMA FORMA. Aqui no la tienen, y esta a la vista: `GERENTE
GENERAL` va de $500 a $13.712 y `AUXILIAR DE LIMPIEZA` de $475 a $485. Con mas asimetria a
la derecha el promedio se separa mas de su mediana, luego

    E[nivel 5] - E[nivel 1]   >   med[nivel 5] - med[nivel 1]

y el ajuste esta SOBREDIMENSIONADO. Alcance: solo la rama de analogia, o sea el 35,9% de
la gente. En la rama directa no se toca.

Es ademas el mismo error que ya se cometio dos veces en este proyecto: `tau` global,
`sigma` global. Un estimador elegido por comodidad y aplicado donde su supuesto no se
cumple.

CRITERIO, DECLARADO ANTES DE CORRER
-----------------------------------
PRIMARIA:   pinball medio en q=0,25 y q=0,75 sobre la banda de EMPRESAS, contraste pareado
            sobre empresas apartadas, restringido a los votos donde el ajuste ACTUA — rama
            de analogia y `aj != 0`. En el resto las variantes son identicas por
            construccion y meterlas solo diluye.

SE ADOPTA la mediana si y solo si:
    1. el IC 95% de la diferencia pareada (mediana - media) queda ENTERO por debajo de cero
    2. el PLACEBO —niveles barajados entre celdas— no reproduce la mejora

SECUNDARIO, se reporta y NO decide: los cinco efectos y el recorrido 1->5 con cada
estimador. Es la magnitud del problema, no la prueba de que cambiarlo mejore.

TERCERA VARIANTE, de referencia: SIN ajuste de nivel. Sirve de suelo — si `sin ajuste`
empata con las otras dos, la discusion media-vs-mediana es irrelevante porque el ajuste
entero no esta haciendo nada.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.producto.base_referencia import BaseReferencia
from benchmarking.producto.nivel import efecto_nivel

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
N_REPLICAS = 300


def pinball(y, lo, hi):
    a = np.maximum(0.25 * (y - lo), -0.75 * (y - lo))
    b = np.maximum(0.75 * (y - hi), -0.25 * (y - hi))
    return (a + b) / 2.0


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    mk = mk.copy()
    mk["cargo_norm"] = mk.cargo_norm.astype(str)
    train, _ = splits.partir(mk, splits.empresas_test(mk))
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
    # UNA SOLA BASE. `efecto` solo entra al CONSULTAR, asi que las variantes se hacen
    # intercambiando `b.efecto` — mismo vecindario, mismos pesos, misma todo. Construir
    # dos bases meteria el ruido de dos fusiones distintas en una comparacion que no va
    # de eso.
    b = BaseReferencia.construir(tr, emb, s.get_sbu)

    ef_media = efecto_nivel(tr, col="cargo_norm", estimador="media")
    ef_mediana = efecto_nivel(tr, col="cargo_norm", estimador="mediana")

    print("\n" + "=" * 78)
    print("A. SECUNDARIO (no decide): .cuanto se separan los dos estimadores?")
    print("=" * 78)
    print(f"  {'nivel':<8} {'promedio':>12} {'mediana':>12} {'dif':>10}")
    for k in sorted(set(ef_media) | set(ef_mediana)):
        a, m = ef_media.get(k, np.nan), ef_mediana.get(k, np.nan)
        print(f"  {k:<8} {a:>+12.4f} {m:>+12.4f} {m - a:>+10.4f}")
    for nom, ef in (("promedio", ef_media), ("mediana", ef_mediana)):
        if len(ef) >= 2:
            ks = sorted(ef)
            r = float(np.exp(ef[ks[-1]] - ef[ks[0]]))
            print(f"  recorrido {ks[0]}->{ks[-1]} con {nom:<9}: {r:.3f}x")

    # -- votos de las empresas apartadas ---------------------------------------
    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc"], sort=False)["y"]
           .median().rename("voto").reset_index())
    titulos = sorted(set(v.cargo_norm))

    # PLACEBO: los niveles barajados ENTRE CELDAS. Rompe la correspondencia
    # escalon->paga conservando la distribucion de escalones y el vecindario.
    rp = np.random.default_rng(99)
    niv_real = b.nivel.copy()
    finitos = np.flatnonzero(np.isfinite(niv_real))
    niv_plac = niv_real.copy()
    niv_plac[finitos] = rp.permutation(niv_real[finitos])

    def referencia(ef, niveles=None):
        guarda_ef, guarda_niv = b.efecto, b.nivel
        b.efecto = ef
        if niveles is not None:
            b.nivel = niveles
        try:
            return b.referenciar(titulos, emb).set_index("cargo")
        finally:
            b.efecto, b.nivel = guarda_ef, guarda_niv

    variantes = {
        "media (hoy)": referencia(ef_media),
        "mediana": referencia(ef_mediana),
        "sin ajuste": referencia({}),
        "PLACEBO": referencia(ef_media, niv_plac),
    }
    col = {n: {c: r[c].reindex(v.cargo_norm).to_numpy(float)
               for c in ("referencia_log", "p25_log", "p75_log")}
           for n, r in variantes.items()}
    base_col = list(variantes["media (hoy)"]["base"].reindex(v.cargo_norm))

    y = v["voto"].to_numpy(float)
    analogia = np.array([str(x) == "por analogia" for x in base_col])
    difiere = col["media (hoy)"]["referencia_log"] != col["mediana"]["referencia_log"]
    ok = analogia & difiere & np.isfinite(y)
    for n in col:
        ok &= np.isfinite(col[n]["p25_log"]) & np.isfinite(col[n]["p75_log"])
    print(f"\nvotos por analogia: {int(analogia.sum()):,} de {len(v):,}")
    print(f"...y donde el ajuste ACTUA (las dos variantes difieren): {int(ok.sum()):,}")
    if ok.sum() < 100:
        print("MUY POCOS votos corregibles: la comparacion no seria concluyente.")
        return

    print("\n" + "=" * 78)
    print("B. PRIMARIA: pinball sobre los votos donde el ajuste actua")
    print("=" * 78)
    print(f"  {'variante':<16} {'PINBALL':>9} {'|sesgo|':>9} {'cob 50%':>9}")
    for n, c in col.items():
        pb = pinball(y[ok], c["p25_log"][ok], c["p75_log"][ok]).mean()
        sg = float(np.mean(y[ok] - c["referencia_log"][ok]))
        cb = float(((y[ok] >= c["p25_log"][ok]) & (y[ok] <= c["p75_log"][ok])).mean())
        print(f"  {n:<16} {pb:>9.4f} {abs(np.exp(sg) - 1):>8.1%} {cb:>8.1%}")

    print(f"\n  contraste pareado ({N_REPLICAS} replicas de empresas apartadas)")
    emp = v.empresa_ruc.to_numpy()
    unicas = np.array(sorted(set(emp[ok])))
    pos = {e: np.flatnonzero((emp == e) & ok) for e in unicas}
    rb = np.random.default_rng(13)
    idxs = [i for i in (np.concatenate([pos[e] for e in rb.choice(unicas, len(unicas))])
                        for _ in range(N_REPLICAS)) if len(i) >= 50]
    g = col["media (hoy)"]
    for n in ("mediana", "sin ajuste", "PLACEBO"):
        c = col[n]
        d = np.array([float(pinball(y[i], c["p25_log"][i], c["p75_log"][i]).mean())
                      - float(pinball(y[i], g["p25_log"][i], g["p75_log"][i]).mean())
                      for i in idxs])
        lo, hi = np.quantile(d, [.025, .975])
        vv = "MEJORA" if hi < 0 else ("sin efecto" if lo < 0 < hi else "EMPEORA")
        print(f"    {n:<14} - media = {d.mean():+.5f}  "
              f"IC 95% [{lo:+.5f}, {hi:+.5f}]  {vv}")

    print("\n" + "=" * 78)
    print("C. .DONDE cambia? por escalon del puesto preguntado")
    print("=" * 78)
    niv_q = np.array([b.nivel[b.idx[c]] if c in b.idx else np.nan for c in v.cargo_norm])
    print(f"  {'nivel':<8} {'votos':>7} {'media':>10} {'mediana':>10} {'dif':>10}")
    for k in (1, 2, 3, 4, 5):
        sel = ok & (niv_q == k)
        if sel.sum() < 40:
            continue
        pa = pinball(y[sel], g["p25_log"][sel], g["p75_log"][sel]).mean()
        pm = pinball(y[sel], col["mediana"]["p25_log"][sel],
                     col["mediana"]["p75_log"][sel]).mean()
        print(f"  {k:<8} {int(sel.sum()):>7,} {pa:>10.4f} {pm:>10.4f} {pm - pa:>+10.4f}")


if __name__ == "__main__":
    main()
