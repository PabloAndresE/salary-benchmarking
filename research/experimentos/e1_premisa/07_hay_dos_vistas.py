"""HAY DOS VISTAS DE LA OCUPACION, O SOLO UNA?

La tesis que el director quiere: inferir la ocupacion REAL desde varias senales ruidosas,
porque el titulo del cargo miente (la "secretaria" que era ingeniera comercial senior). Eso
es un modelo de variable latente con varias vistas:

    ocupacion latente
      |- titulo del cargo        <- medida ruidosa, y a veces falsa
      |- composicion del pago    <- medida ruidosa
      |- centro de costo         <- medida ruidosa
      |- antiguedad              <- medida ruidosa

Para que eso tenga material hacen falta AL MENOS DOS vistas informativas. Si solo el texto
informa, no hay nada que triangular.

POR QUE ESTA MEDICION Y NO LA ANTERIOR. En `03_premisa_continua...` se midio cuanto anade la
composicion MAS ALLA de `cargo_norm`: 0,21%. Se concluyo que no informa. **Era la pregunta
equivocada para esta tesis.** Si composicion y cargo son dos medidas ruidosas de LO MISMO,
la composicion aporta poco condicionada al cargo justamente PORQUE es redundante — no
porque sea inutil. Aqui se mide el poder MARGINAL de cada vista, sin condicionar a la otra.

Todo dentro de empresa (se descuenta el nivel del empleador) y fuera de muestra, con
validacion cruzada agrupada por empresa. El texto entra como embeddings ya cacheados.
"""
import argparse

import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits

SEM = 20260805
COMP = ["pct_fijo", "pct_comisiones", "pct_extras", "pct_otros"]


def r2_fuera_de_muestra(X, y, grupos, etiqueta, n_splits=4):
    """R2 fuera de muestra con CV agrupada por empresa. Un R2 en muestra no dice nada."""
    X = np.asarray(X, dtype=float)
    pred = np.zeros(len(y))
    for i_tr, i_va in GroupKFold(n_splits=n_splits).split(X, groups=grupos):
        mo = HistGradientBoostingRegressor(random_state=SEM, max_iter=200)
        mo.fit(X[i_tr], y[i_tr])
        pred[i_va] = mo.predict(X[i_va])
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot
    print(f"  {etiqueta:44s} R2 = {r2:+.4f}   reduce la sd un {1-np.sqrt(max(1-r2,0)):.1%}")
    return r2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", type=int, default=120000,
                    help="submuestra de personas; el texto obliga a embeber")
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))
    d = train[train["tiene_composicion"]].dropna(subset=COMP + ["y"]).copy()

    # submuestra por EMPRESA, no por fila: hay que conservar los grupos completos
    if len(d) > args.muestra:
        rng = np.random.default_rng(SEM)
        emp = np.array(sorted(d["empresa_ruc"].unique()))
        rng.shuffle(emp)
        acum, elegidas = 0, []
        for e in emp:
            n = int((d["empresa_ruc"] == e).sum())
            if acum + n > args.muestra:
                break
            elegidas.append(e); acum += n
        d = d[d["empresa_ruc"].isin(elegidas)].copy()
    d = d.reset_index(drop=True)
    print(f"muestra: {len(d):,} personas de {d.empresa_ruc.nunique():,} empresas")

    # DENTRO DE EMPRESA: se descuenta el nivel del empleador, que es el 81% del ruido
    y = (d["y"] - d.groupby("empresa_ruc")["y"].transform("mean")).to_numpy(float)
    grupos = d["empresa_ruc"].to_numpy()
    print(f"objetivo: y dentro de empresa, var = {y.var():.4f} (sd {np.sqrt(y.var()):.4f})")

    # --- vista 1: el TEXTO ---
    cache = embeddings.CacheArchivo(s.gcs_cache_embeddings or
                                    "research/experimentos/e1_premisa/emb_cache.npz")
    cliente = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                        s.vertex_location)
    texto = (d["cargo_norm"].astype(str) + " " +
             d["centro_de_costo"].fillna("").astype(str)).tolist()
    solo_cargo = d["cargo_norm"].astype(str).tolist()
    print(f"\nembebiendo {len(set(solo_cargo)):,} cargos unicos...")
    E_cargo = embeddings.embeber(solo_cargo, cliente, s.vertex_embedding_model, cache=cache)
    print(f"embebiendo {len(set(texto)):,} combinaciones cargo+centro...")
    E_todo = embeddings.embeber(texto, cliente, s.vertex_embedding_model, cache=cache)
    cache.volcar()

    # reducir el texto para que no aplaste al GBM por numero de columnas
    from sklearn.decomposition import PCA
    Ec = PCA(n_components=48, random_state=SEM).fit_transform(E_cargo)
    Et = PCA(n_components=48, random_state=SEM).fit_transform(E_todo)

    # --- vista 2: senales SIN texto ---
    ant = d[["antiguedad_total"]].fillna(d["antiguedad_total"].median()).to_numpy(float)
    comp = d[COMP].to_numpy(float)
    sin_texto = np.hstack([comp, ant])

    print("\n" + "=" * 74)
    print("PODER PREDICTIVO MARGINAL DE CADA VISTA (dentro de empresa, fuera de muestra)")
    print("=" * 74)
    rng = np.random.default_rng(SEM)
    r2_fuera_de_muestra(rng.normal(0, 1, (len(d), 4)), y, grupos, "PLACEBO (ruido puro)")
    r_comp = r2_fuera_de_muestra(comp, y, grupos, "composicion sola (4 proporciones)")
    r_ant = r2_fuera_de_muestra(ant, y, grupos, "antiguedad sola")
    r_sin = r2_fuera_de_muestra(sin_texto, y, grupos, "VISTA SIN TEXTO (composicion+antig.)")
    r_txt = r2_fuera_de_muestra(Ec, y, grupos, "VISTA TEXTO (embedding del cargo)")
    r_tc = r2_fuera_de_muestra(Et, y, grupos, "texto: cargo + centro de costo")
    r_todo = r2_fuera_de_muestra(np.hstack([Et, sin_texto]), y, grupos, "LAS DOS VISTAS")

    print("\n" + "=" * 74)
    print("LECTURA")
    print("=" * 74)
    if r_txt > 0:
        print(f"  la vista sin texto alcanza el {r_sin/r_txt:.0%} de lo que alcanza el texto")
    print(f"  juntas suman {r_todo:+.4f}; por separado {r_txt:+.4f} y {r_sin:+.4f}")
    extra = r_todo - max(r_txt, r_tc)
    print(f"  lo que la vista sin texto ANADE sobre el texto: {extra:+.4f}")
    print(f"  redundancia: {1 - extra/r_sin:.0%} de la vista sin texto ya esta en el texto"
          if r_sin > 0 else "")
    print("\n  Si la vista sin texto alcanza una fraccion apreciable del texto POR SI SOLA,")
    print("  hay dos vistas de la ocupacion y el modelo latente tiene material.")
    print("  Si da casi cero sola, solo hay una vista y hay que replantear.")


if __name__ == "__main__":
    main()
