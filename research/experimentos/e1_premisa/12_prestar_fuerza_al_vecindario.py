"""PRESTAR FUERZA EN VEZ DE FUSIONAR: estimacion en areas pequenas sobre CARGO.

`11` midio que engrosar las celdas NO mejora la precision: mas gente por celda estima
mejor la mediana, pero la celda gruesa mezcla puestos que pagan distinto, y gana el
segundo efecto. Lo unico que compra engrosar es cobertura, a un precio de c* = 0,304.

Aqui se prueba la otra via para lo mismo, y es la que D-013 senalo sin que la usaramos:
**no fusionar las celdas, dejarlas donde estan y prestarles fuerza de sus vecinas.**
`ASESOR COMERCIAL` no se convierte en `VENDEDOR`; conserva su identidad y su nivel, pero
cuando tiene dos personas toma prestada informacion de los puestos que se le parecen.

Eso es Fay-Herriot (1979), el estimador clasico de areas pequenas:

    mu_c = gamma_c * (estimacion propia) + (1 - gamma_c) * (sintetico del vecindario)
    gamma_c = sigma_u^2 / (sigma_u^2 + v_c)

`v_c` es la varianza de muestreo de la celda —que el banco YA calcula, es el 1/suma(w)
de la anchura predictiva— y `sigma_u^2` es cuanto varian las celdas de verdad alrededor
de su vecindario. Las celdas gordas tienen `v_c` pequeno, `gamma` cerca de 1 y se quedan
como estan; las delgadas se van hacia el vecindario. **Sin parametros libres:**
`sigma_u^2` sale por momentos.

POR QUE NO ES CIRCULAR. El vecindario se define con el TEXTO del cargo, sin mirar
salarios. El prestamo usa salarios de OTRAS celdas, que es exactamente lo que hace
cualquier estimador de area pequena desde 1979 y lo que el BLS hace con sus donantes.
El salario nunca entra en la definicion de quien se parece a quien.

POR QUE ES EL BLANCO CORRECTO. Medido en `04`: el 34% de la gente esta en celdas de 1-2
empresas y el **44,6% de su error es error de estimacion**, no de agrupamiento. Es el
trozo mas grande y el unico que ni engrosar ni etiquetar mejor puede tocar.

Y es lo que el BLS y Eurostat NO hicieron: ellos engrosaron.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.evaluacion.metricas import error_y_cobertura
from benchmarking.evaluacion.referencia import (SUELO_EMPRESAS, SUELO_SHARE,
                                                componentes_varianza, tabla_votos)

SEM = 20260805
CACHE = "research/experimentos/e1_premisa/emb_cache.npz"
MUESTRA_EMPRESAS = 1200
VECINOS = (25, 50, 100)


def tabla_celdas(votos, col):
    """Estimacion directa de cada celda y su varianza de muestreo v_c = 1/suma(w)."""
    g = votos.groupby(col)
    filas = []
    for celda, sub in g:
        w = sub["w"].to_numpy(float)
        v = sub["voto"].to_numpy(float)
        n = sub["n"].to_numpy(float)
        o = np.argsort(v, kind="mergesort")
        v, w2, n = v[o], w[o], n[o]
        acum = (np.cumsum(w2) - 0.5 * w2) / w2.sum()
        filas.append({col: celda, "m": float(np.interp(0.5, acum, v)),
                      "W": float(w2.sum()), "empresas": int(len(v)),
                      "personas": int(n.sum()),
                      "share": float(n.max() / n.sum())})
    t = pd.DataFrame(filas).set_index(col)
    t["v"] = 1.0 / t["W"]
    return t


def sintetico(t, X, pos, k, objetivo=None):
    """Estimacion sintetica desde los k vecinos mas parecidos POR TEXTO.

    `objetivo=None` la calcula para las propias celdas de train (para el encogimiento).
    Con una lista de etiquetas la calcula para ELLAS, aunque no aparezcan en train:
    ese es el mecanismo que de verdad importa. El 46% de la gente que `CARGO` no
    cubre no esta en celdas delgadas — esta en etiquetas que nunca se vieron. Una
    etiqueta nueva no tiene donantes propios, pero SI tiene vecindario: se puede
    embeber y colocar. Un cliente manda ANALISTA DE RIESGO CREDITICIO, no lo hemos
    visto jamas, y aun asi sabemos a que se parece.

    Los vecinos pesan por similitud x precision (su propia W): un vecino parecido
    pero mal estimado aporta poco. Una celda nunca se presta a si misma.
    """
    idx = np.array([pos[c] for c in t.index])
    B = X[idx]
    B = B / np.linalg.norm(B, axis=1, keepdims=True)
    propias = objetivo is None
    dest = list(t.index) if propias else list(objetivo)
    Z = B if propias else (lambda A: A / np.linalg.norm(A, axis=1, keepdims=True))(
        X[[pos[c] for c in dest]])
    m = t["m"].to_numpy(float)
    W = t["W"].to_numpy(float)
    emp = t["empresas"].to_numpy(float)
    out = np.full(len(dest), np.nan)
    var_s = np.full(len(dest), np.nan)
    n_emp = np.zeros(len(dest))
    paso = 512
    for i0 in range(0, len(dest), paso):
        S = Z[i0:i0 + paso] @ B.T
        for j2 in range(S.shape[0]):
            fila = S[j2].copy()
            if propias:
                fila[i0 + j2] = -np.inf          # nunca a si misma
            vec = np.argpartition(-fila, k)[:k]
            sim = np.clip(fila[vec], 0.0, None)
            peso = sim * W[vec]
            if peso.sum() <= 0:
                continue
            peso = peso / peso.sum()
            out[i0 + j2] = float((peso * m[vec]).sum())
            var_s[i0 + j2] = float((peso ** 2 / W[vec]).sum())
            n_emp[i0 + j2] = float(emp[vec].sum())
    return out, var_s, n_emp


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(m, splits.empresas_test(m))

    rng = np.random.default_rng(SEM)
    emp = np.array(sorted(train.empresa_ruc.unique()))
    if len(emp) > MUESTRA_EMPRESAS:
        emp = rng.choice(emp, MUESTRA_EMPRESAS, replace=False)
    d = train[train.empresa_ruc.isin(emp)].reset_index(drop=True)
    val = set(rng.choice(emp, max(1, len(emp) // 4), replace=False))
    tr = d[~d.empresa_ruc.isin(val)].reset_index(drop=True)
    ts = d[d.empresa_ruc.isin(val)].reset_index(drop=True)
    print(f"train {len(tr):,} filas / {tr.empresa_ruc.nunique()} empresas")
    print(f"eval  {len(ts):,} filas / {ts.empresa_ruc.nunique()} empresas")

    tau2, sigma2 = componentes_varianza(tr, "cargo_norm")
    votos = tabla_votos(tr, "cargo_norm", tau2=tau2, sigma2=sigma2)
    t = tabla_celdas(votos, "cargo_norm")
    print(f"celdas con estimacion directa: {len(t):,}")
    print(f"  de 1-2 empresas: {(t.empresas <= 2).sum():,} "
          f"({t.loc[t.empresas <= 2, 'personas'].sum() / t.personas.sum():.1%} de la gente)")

    cache = embeddings.CacheArchivo(s.gcs_cache_embeddings or CACHE)
    cliente = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                        s.vertex_location)
    etiquetas = sorted(set(tr.cargo_norm) | set(ts.cargo_norm))
    print(f"embebiendo {len(etiquetas):,} etiquetas...")
    X = embeddings.embeber(etiquetas, cliente, s.vertex_embedding_model, cache=cache)
    cache.volcar()
    pos = {e: i for i, e in enumerate(etiquetas)}

    y = pd.to_numeric(ts["y"], errors="coerce")

    def evaluar(nombre, mapa, suelo_empresas=SUELO_EMPRESAS):
        ref = ts["cargo_norm"].map(mapa)
        # los suelos de sanidad se mantienen salvo que se diga lo contrario
        info = ts["cargo_norm"].map(t["empresas"]).fillna(0)
        share = ts["cargo_norm"].map(t["share"]).fillna(1.0)
        ref = ref.where((info >= suelo_empresas) & (share <= SUELO_SHARE))
        r = error_y_cobertura(ts.assign(y=y), ref)
        print(f"{nombre:<34} {r['cobertura']:>9.1%} {r['mae']:>9.4f} "
              f"{r['mae_intra']:>10.4f}")
        return {"metodo": nombre, "cobertura": r["cobertura"], "mae": r["mae"]}

    print("\n" + "=" * 76)
    print("PRESTAR FUERZA AL VECINDARIO (Fay-Herriot sobre las celdas de CARGO)")
    print("=" * 76)
    print(f"{'metodo':<34} {'cobertura':>9} {'MAE':>9} {'MAE intra':>10}")
    print("-" * 76)

    filas = [evaluar("CARGO crudo (baseline)", t["m"].to_dict())]

    nuevas = sorted(set(ts.cargo_norm) - set(t.index))
    print(f"etiquetas de eval NO vistas en train: {len(nuevas):,} "
          f"({ts.cargo_norm.isin(nuevas).mean():.1%} de las personas de eval)")

    for k in VECINOS:
        syn, var_s, _ = sintetico(t, X, pos, k)
        ok = np.isfinite(syn)
        dif = t["m"].to_numpy(float)[ok] - syn[ok]
        # sigma_u^2 por momentos: cuanto varian las celdas alrededor de su vecindario,
        # descontando el ruido de muestreo de ambas partes. Sin parametros libres.
        su2 = max(0.0, float(np.var(dif))
                  - float(np.mean(t["v"].to_numpy()[ok] + var_s[ok])))
        gamma = np.where(ok, su2 / (su2 + t["v"].to_numpy(float)), 1.0)
        mu = np.where(ok, gamma * t["m"].to_numpy(float) + (1 - gamma)
                      * np.nan_to_num(syn), t["m"].to_numpy(float))
        mapa = dict(zip(t.index, mu))
        g_delg = gamma[(t.empresas <= 2).to_numpy()]
        print(f"  [k={k:>2}] sigma_u = {np.sqrt(su2):.4f}   "
              f"gamma medio en celdas de 1-2 empresas = {g_delg.mean():.3f}")
        filas.append(evaluar(f"CARGO + vecindario k={k}", mapa))
        filas.append(evaluar("  ...suelo relajado (e>=1)", mapa, suelo_empresas=1))

        # EL MECANISMO QUE DE VERDAD IMPORTA: una etiqueta nunca vista no tiene
        # donantes propios, pero si tiene vecindario. Se embebe y se coloca. Aqui
        # esta el 46% de la gente que CARGO no puede atender.
        if nuevas:
            syn_n, _, emp_n = sintetico(t, X, pos, k, objetivo=nuevas)
            m2 = dict(mapa)
            m2.update({e: v for e, v in zip(nuevas, syn_n) if np.isfinite(v)})
            # el suelo de empresas lo cumple el VECINDARIO, no la celda
            emp2 = dict(zip(t.index, t["empresas"]))
            emp2.update(dict(zip(nuevas, emp_n)))
            sh2 = dict(zip(t.index, t["share"]))
            sh2.update({e: 0.0 for e in nuevas})
            ref = ts.cargo_norm.map(m2).where(
                (ts.cargo_norm.map(emp2).fillna(0) >= SUELO_EMPRESAS)
                & (ts.cargo_norm.map(sh2).fillna(1.0) <= SUELO_SHARE))
            r = error_y_cobertura(ts.assign(y=y), ref)
            print(

                  f"  ...+ etiquetas nuevas k={k:<9} {r['cobertura']:>9.1%} "
                  f"{r['mae']:>9.4f} {r['mae_intra']:>10.4f}")
            filas.append({"metodo": f"  ...+ etiquetas nuevas k={k}",
                          "cobertura": r["cobertura"], "mae": r["mae"]})
    f = pd.DataFrame(filas)
    base = f.iloc[0]
    print("\n" + "=" * 76)
    print("FRENTE AL BASELINE")
    print("=" * 76)
    for _, r in f.iloc[1:].iterrows():
        den = r.cobertura - base.cobertura
        c = ((r.mae * r.cobertura - base.mae * base.cobertura) / den
             if den > 1e-9 else np.nan)
        extra = f"   c* = {c:.4f} ({np.exp(c)-1:+.1%})" if np.isfinite(c) else ""
        print(f"  {r.metodo:<32} MAE {r.mae/base.mae-1:+7.2%}   "
              f"cobertura {r.cobertura-base.cobertura:+6.1%} pts{extra}")

    print()
    print("COMO SE LEE")
    print("  A cobertura IGUAL, cualquier bajada de MAE es ganancia limpia: mismas")
    print("  celdas, mismas personas atendidas, solo mejor estimadas. Es lo que `11`")
    print("  no pudo conseguir engrosando.")
    print("  Con el suelo relajado se anade cobertura, y ahi vuelve a aplicar el c*.")
    print()
    print("AVISO: k se elige por ESTABILIDAD, no por el MAE que salga aqui (D-005")
    print("Enmienda 1). Este barrido mide sensibilidad, no selecciona.")


if __name__ == "__main__":
    main()
