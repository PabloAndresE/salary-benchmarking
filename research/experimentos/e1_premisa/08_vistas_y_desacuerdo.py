"""DOS MEDICIONES SOBRE LA TESIS DE LA OCUPACION LATENTE.

A. LAS VISTAS, BIEN SEPARADAS. En `07` el centro de costo se concateno al texto del cargo y
   se comprimio en las mismas 64 dimensiones: eso diluyo la senal del cargo y salio PEOR que
   el cargo solo (0,2565 frente a 0,3737). Era un artefacto de la representacion, no un
   hallazgo. Aqui cada vista es un bloque aparte.

B. EL DESACUERDO, que es lo que la tesis quiere de verdad. No importa cuanto prediga la
   composicion: importa si **discrepa del titulo cuando el titulo miente** — la "secretaria"
   que en realidad hace de ingeniera comercial senior.

   Diseno, y es no circular por construccion:
     1. Para cada etiqueta con gente suficiente se calcula su PERFIL medio con senales
        SIN TEXTO (composicion + antiguedad). El salario no participa.
     2. Cada persona se compara con el perfil de SU etiqueta y con el de todas las demas.
        Si esta mucho mas cerca del perfil de OTRA etiqueta, se marca como DESACUERDO.
     3. Recien entonces se mira el salario, como VALIDACION EXTERNA: .el sueldo de esa
        persona se parece mas al nivel de su etiqueta, o al de la etiqueta vecina?

   Si los marcados cobran como la etiqueta vecina y no como la propia, el desacuerdo esta
   detectando etiquetas equivocadas. Con los NO marcados como control.
"""
import argparse

import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import GroupKFold

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits

SEM = 20260805
COMP = ["pct_fijo", "pct_comisiones", "pct_extras", "pct_otros"]


def _texto_svd(serie, n, semilla=SEM):
    tf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=5,
                         max_features=60000)
    return TruncatedSVD(n, random_state=semilla).fit_transform(
        tf.fit_transform(serie.fillna("").astype(str)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", type=int, default=150000)
    ap.add_argument("--min-etiqueta", type=int, default=100)
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))
    d = train[train["tiene_composicion"]].dropna(subset=COMP + ["y"]).copy()

    rng = np.random.default_rng(SEM)
    emp = np.array(sorted(d.empresa_ruc.unique())); rng.shuffle(emp)
    acum, elegidas = 0, []
    for e in emp:
        n = int((d.empresa_ruc == e).sum())
        if acum + n > args.muestra:
            break
        elegidas.append(e); acum += n
    d = d[d.empresa_ruc.isin(elegidas)].reset_index(drop=True)
    print(f"muestra {len(d):,} personas / {d.empresa_ruc.nunique():,} empresas")

    # dentro de empresa: el empleador es el 81% del ruido y taparia todo
    d["r"] = d["y"] - d.groupby("empresa_ruc")["y"].transform("mean")
    y = d["r"].to_numpy(float)
    g = d["empresa_ruc"].to_numpy()
    ant = d[["antiguedad_total"]].fillna(d.antiguedad_total.median()).to_numpy(float)
    comp = d[COMP].to_numpy(float)
    sin_texto = np.hstack([comp, ant])

    # ============ A. LAS VISTAS, BIEN SEPARADAS ============
    print("\n" + "=" * 76)
    print("A. PODER MARGINAL DE CADA VISTA — cada bloque por separado")
    print("=" * 76)

    def r2(X, et):
        X = np.asarray(X, float); pred = np.zeros(len(y))
        for a, b in GroupKFold(n_splits=4).split(X, groups=g):
            mo = HistGradientBoostingRegressor(random_state=SEM, max_iter=200)
            mo.fit(X[a], y[a]); pred[b] = mo.predict(X[b])
        v = 1 - float(((y - pred) ** 2).sum()) / float(((y - y.mean()) ** 2).sum())
        print(f"  {et:48s} R2 = {v:+.4f}   sd -{1-np.sqrt(max(1-v,0)):.1%}")
        return v

    Xc = _texto_svd(d["cargo_norm"], 64)
    Xk = _texto_svd(d["centro_de_costo"], 32)

    r2(rng.normal(0, 1, (len(d), 4)), "PLACEBO")
    r_txt = r2(Xc, "cargo (texto)")
    r_cen = r2(Xk, "centro de costo (texto), BLOQUE APARTE")
    r_sin = r2(sin_texto, "sin texto (composicion + antiguedad)")
    r_tc = r2(np.hstack([Xc, Xk]), "cargo + centro, bloques separados")
    r_todo = r2(np.hstack([Xc, Xk, sin_texto]), "TODAS LAS VISTAS")

    print(f"\n  la vista sin texto alcanza el {r_sin/r_txt:.0%} del cargo")
    print(f"  el centro de costo solo alcanza el {r_cen/r_txt:.0%} del cargo")
    print(f"  las vistas sin cargo (centro + sin texto) frente al cargo:")
    r_nocargo = r2(np.hstack([Xk, sin_texto]), "  TODO MENOS EL CARGO")
    print(f"\n  lo que TODO anade sobre el cargo solo: {r_todo - r_txt:+.4f}")
    print(f"  redundancia de la vista sin texto: "
          f"{max(0, 1 - (r_todo - r_tc)/r_sin):.0%} ya esta en el texto")

    # ============ B. EL DESACUERDO ============
    print("\n" + "=" * 76)
    print("B. .DETECTA LA VISTA SIN TEXTO QUE UNA ETIQUETA ESTA MAL?")
    print("=" * 76)

    grandes = d.groupby("cargo_norm").filter(lambda x: len(x) >= args.min_etiqueta)
    print(f"etiquetas con >={args.min_etiqueta} personas: "
          f"{grandes.cargo_norm.nunique():,}  ({len(grandes):,} personas)")

    P = grandes[COMP + ["antiguedad_total"]].copy()
    P["antiguedad_total"] = P["antiguedad_total"].fillna(P["antiguedad_total"].median())
    Z = (P - P.mean()) / P.std().replace(0, 1)          # perfil estandarizado, SIN salario
    Z["_lab"] = grandes["cargo_norm"].to_numpy()
    cent = Z.groupby("_lab").mean()
    nivel = grandes.groupby("cargo_norm")["r"].median()  # nivel salarial de cada etiqueta

    A = Z.drop(columns="_lab").to_numpy(float)
    C = cent.to_numpy(float)
    labs = np.array(cent.index)
    idx_prop = pd.Index(labs).get_indexer(grandes["cargo_norm"])

    # distancia a todos los perfiles, en bloques para no reventar la memoria
    d_prop = np.empty(len(A)); d_mej = np.empty(len(A)); i_mej = np.empty(len(A), int)
    for ini in range(0, len(A), 20000):
        fin = min(ini + 20000, len(A))
        D = ((A[ini:fin, None, :] - C[None, :, :]) ** 2).sum(-1)
        fila = np.arange(fin - ini)
        d_prop[ini:fin] = D[fila, idx_prop[ini:fin]]
        D[fila, idx_prop[ini:fin]] = np.inf
        i_mej[ini:fin] = D.argmin(1)
        d_mej[ini:fin] = D[fila, i_mej[ini:fin]]

    razon = d_mej / np.maximum(d_prop, 1e-9)
    marcado = razon < 0.5          # el perfil de OTRA etiqueta le queda el doble de cerca
    print(f"marcados como DESACUERDO: {int(marcado.sum()):,} ({marcado.mean():.1%})")

    r_pers = grandes["r"].to_numpy(float)
    n_prop = nivel.reindex(labs).to_numpy()[idx_prop]
    n_vec = nivel.reindex(labs).to_numpy()[i_mej]
    err_prop = np.abs(r_pers - n_prop)
    err_vec = np.abs(r_pers - n_vec)

    print(f"\n{'grupo':>14} {'personas':>10} {'|y - su etiqueta|':>19} "
          f"{'|y - etiqueta vecina|':>22} {'gana':>10}")
    for et, sel in (("marcados", marcado), ("control", ~marcado)):
        if sel.sum() < 100:
            continue
        a, b = err_prop[sel].mean(), err_vec[sel].mean()
        print(f"{et:>14} {int(sel.sum()):>10,} {a:>19.4f} {b:>22.4f} "
              f"{'VECINA' if b < a else 'la suya':>10}")

    print("\n  Si en los MARCADOS gana la etiqueta vecina y en el CONTROL gana la suya,")
    print("  la vista sin texto esta detectando etiquetas equivocadas sin mirar el sueldo.")

    print("\n=== 12 desacuerdos mas frecuentes (etiqueta -> perfil al que se parece) ===")
    pares = pd.Series(list(zip(grandes["cargo_norm"].to_numpy()[marcado],
                               labs[i_mej[marcado]]))).value_counts()
    for (a, b), n in pares.head(12).items():
        print(f"  {n:>4}  {a[:38]:38s} -> {b[:38]}")


if __name__ == "__main__":
    main()
