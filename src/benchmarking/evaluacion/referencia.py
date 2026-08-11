"""Referencia salarial de una celda: componentes de varianza, votos ponderados y
distribucion predictiva.

El modelo, por celda c:      y_fi = mu_c + a_f + e_fi
                             a_f ~ (0, tau2)   e_fi ~ (0, sigma2)

De el sale TODO lo que este modulo hace, sin un solo hiperparametro elegido a mano:

1. **El peso del voto de cada empresa**, w_f = 1/(tau2 + sigma2/n_f). Es inverso-varianza.
   Interpola entre "una empresa un voto" (n grande) y "una persona un voto" (tau2->0), y
   acota el ratio maximo de pesos en 1 + sigma2/tau2 — no en 3.000. Ese es el arreglo de
   D-011: la correccion 1 de D-009 elimino la dominancia del empleador grande pero
   desempareo el estimador de la metrica, porque la mediana SIMPLE de medianas de empresa
   estima la paga del empleador tipico y el MAE se mide contra personas.

2. **La referencia**: cuantil ponderado al 50%. Mediana y no media por lo medido sobre
   498.653 personas — la diferencia es 0,0533 en log y NO es neutral entre metodos, asi
   que usar la media seria un sesgo a favor de la hipotesis propia (D-006 #6).

3. **La anchura predictiva**, sd = raiz(tau2 + sigma2 + 1/suma(w_f)). Es la perilla de
   confianza correcta: la regla optima de abstencion en regresion umbraliza la varianza
   condicional (Zaoui, Denis & Hebiri 2020), no un conteo de donantes. 500 personas de 3
   empresas homogeneas dan mejor referencia que 20 de 10 empresas dispares, y la regla
   vieja preferia la segunda.

Este modulo NO decide cuando abstenerse: eso es `aplicar_abstencion`, funcion pura sobre
la tabla que devuelve `predecir`. Asi la curva barre el umbral sin recalcular.
"""
import numpy as np
import pandas as pd

SUELO_EMPRESAS = 3      # identificabilidad de tau2 + confidencialidad (precedente QCEW)
SUELO_SHARE = 0.80      # regla de dominancia (precedente QCEW). Ver D-011.


def componentes_varianza(train, col_celda):
    """(tau2, sigma2) globales, por momentos, sobre el modelo de un factor dentro de celda.

    Estimador ANOVA desbalanceado clasico:
        sigma2 = SSW / (N - G)
        tau2   = max(0, (SSB/(G - C) - sigma2) / n0)
    con G grupos (celda, empresa), C celdas y n0 el tamano efectivo de grupo.

    Globales y no por celda: con el 76,6% de la gente en empresas de >=100, estimar esto
    por celda anadiria ruido sin anadir informacion (mismo argumento que D-006 #3).
    """
    d = train[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"])
    if d.empty:
        return 0.0, 0.0

    g = (d.groupby([col_celda, "empresa_ruc"], sort=False)["y"]
           .agg(n="size", media="mean", var=lambda v: float(v.var(ddof=0)))
           .reset_index())
    n_total, n_grupos = len(d), len(g)
    n_celdas = int(g[col_celda].nunique())

    ssw = float((g["n"] * g["var"]).sum())
    sigma2 = ssw / (n_total - n_grupos) if n_total > n_grupos else 0.0

    g["_wn"] = g["n"] * g["media"]
    g["_n2"] = g["n"].astype(float) ** 2
    porc = g.groupby(col_celda, sort=False).agg(N_c=("n", "sum"), s=("_wn", "sum"),
                                                sn2=("_n2", "sum"))
    porc["media_c"] = porc["s"] / porc["N_c"]
    g = g.join(porc["media_c"], on=col_celda)
    ssb = float((g["n"] * (g["media"] - g["media_c"]) ** 2).sum())

    df_b = n_grupos - n_celdas
    if df_b <= 0:
        return 0.0, float(sigma2)
    n0 = (n_total - float((porc["sn2"] / porc["N_c"]).sum())) / df_b
    tau2 = (ssb / df_b - sigma2) / n0 if n0 > 0 else 0.0
    return float(max(tau2, 0.0)), float(sigma2)


def pesos_empresa(n, tau2, sigma2):
    """w_f = 1/(tau2 + sigma2/n_f). Derivado del modelo, no elegido."""
    n = np.asarray(n, dtype=float)
    denom = tau2 + np.divide(sigma2, n, out=np.full_like(n, np.inf), where=n > 0)
    return np.divide(1.0, denom, out=np.zeros_like(denom), where=denom > 0)


def cuantil_ponderado(valores, pesos, q=0.5):
    """Cuantil empirico ponderado con interpolacion. Con pesos iguales da la mediana."""
    v = np.asarray(valores, dtype=float).ravel()
    w = np.asarray(pesos, dtype=float).ravel()
    ok = np.isfinite(v) & np.isfinite(w) & (w > 0)
    v, w = v[ok], w[ok]
    if v.size == 0:
        return float("nan")
    if v.size == 1:
        return float(v[0])
    o = np.argsort(v, kind="mergesort")
    v, w = v[o], w[o]
    acum = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(q, acum, v))


def predecir(train, test, col_celda, tau2=None, sigma2=None):
    """Referencia bruta y anchura predictiva por fila de `test`, con leave-company-out.

    NO aplica abstencion — eso es `aplicar_abstencion`. Devuelve:
      y_ref_bruto, sd_pred, n_donantes (personas), n_empresas_donantes, share_max_empresa

    `sd_pred` incluye el ruido irreducible (empresa nueva + persona nueva) y el error de
    estimacion de mu_c. Solo el tercero mejora con mas donantes, que es exactamente lo que
    debe ordenar la abstencion.
    """
    tr = train[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"])
    if tau2 is None or sigma2 is None:
        tau2, sigma2 = componentes_varianza(train, col_celda)
    irreducible = float(tau2 + sigma2)

    votos = (tr.groupby([col_celda, "empresa_ruc"], sort=False)["y"]
               .agg(voto="median", n="size").reset_index())
    # Caso degenerado: sin varianza estimada, el peso inverso-varianza es 1/0. Pasa
    # cuando todos los donantes valen lo mismo — imposible en datos reales, trivial en
    # tests y en celdas diminutas. Sin esta guarda `predecir` devolveria NaN en silencio,
    # que es la peor forma de fallar: parece abstencion y es un cero mal dividido.
    degenerado = irreducible <= 0.0
    votos["w"] = (np.ones(len(votos), dtype=float) if degenerado
                  else pesos_empresa(votos["n"], tau2, sigma2))

    porcelda = {}
    for celda, g in votos.groupby(col_celda, sort=False):
        porcelda[celda] = (g["voto"].to_numpy(float), g["w"].to_numpy(float),
                           g["n"].to_numpy(float),
                           {r: i for i, r in enumerate(g["empresa_ruc"])})

    VACIO = (np.nan, np.nan, 0, 0, np.nan)
    cache = {}

    def resolver(celda, emp):
        # Todas las personas de la misma empresa en la misma celda comparten referencia:
        # se calcula una vez por par, no una vez por persona. Con 1,3 M de filas eso es
        # la diferencia entre segundos y horas.
        clave = (celda, emp)
        if clave in cache:
            return cache[clave]
        dat = porcelda.get(celda)
        if dat is None:
            cache[clave] = VACIO
            return VACIO
        v, w, n, pos = dat
        j = pos.get(emp)
        if j is not None:
            keep = np.ones(len(v), dtype=bool)
            keep[j] = False
            v, w, n = v[keep], w[keep], n[keep]
        if len(v) == 0 or w.sum() <= 0:
            cache[clave] = VACIO
            return VACIO
        # El termino 1/suma(w) es el error de estimacion de mu_c, y solo tiene sentido si
        # w es inverso-varianza. En el caso degenerado los pesos son uniformes y no lo es:
        # la predictiva correcta ahi es una masa puntual.
        estimacion = 0.0 if degenerado else 1.0 / w.sum()
        r = (cuantil_ponderado(v, w),
             float(np.sqrt(irreducible + estimacion)),
             int(n.sum()), int(len(v)), float(n.max() / n.sum()))
        cache[clave] = r
        return r

    filas = [resolver(c, e) for c, e in zip(test[col_celda], test["empresa_ruc"])]
    return pd.DataFrame(filas, index=test.index,
                        columns=["y_ref_bruto", "sd_pred", "n_donantes",
                                 "n_empresas_donantes", "share_max_empresa"])


def aplicar_abstencion(pred, max_sd=None, min_empresas=SUELO_EMPRESAS,
                       share_max=SUELO_SHARE):
    """`y_ref` con NaN donde el metodo se abstiene. Funcion pura: no recalcula nada.

    Tres reglas, y sirven para cosas distintas — el pre-registro las declara por separado:

    - `max_sd`  : el CRITERIO. Anchura predictiva por encima del umbral -> no publico.
                  Se declara en unidades interpretables antes de tocar el test.
    - `min_empresas` y `share_max`: SUELOS de sanidad, no de precision. Con 2 empresas no
                  se separa tau2 de sigma2 y cada donante deduce al otro; con una empresa
                  aportando >80% de la gente, la celda es un empleador con testigos.
    """
    y = pd.to_numeric(pred["y_ref_bruto"], errors="coerce").copy()
    fuera = pred["n_empresas_donantes"] < int(min_empresas)
    fuera |= pred["share_max_empresa"].fillna(1.0) > float(share_max)
    if max_sd is not None:
        fuera |= pred["sd_pred"].isna() | (pred["sd_pred"] > float(max_sd))
    return y.mask(fuera).rename("y_ref")
