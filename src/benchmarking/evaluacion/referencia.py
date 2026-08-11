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


def _agregados_grupo(d, col_celda):
    """n, media y suma de cuadrados centrada de cada grupo (celda, empresa).

    Sin `lambda` en el `agg`: una lambda obliga a pandas a recorrer los grupos en Python,
    y con 55.920 celdas de `CARGO` eso son decenas de segundos por llamada. `ssw` sale de
    la identidad suma(y^2) - suma(y)^2/n, que es una sola pasada vectorizada.
    """
    t = d.assign(_y2=d["y"].astype(float) ** 2)
    g = (t.groupby([col_celda, "empresa_ruc"], sort=False)
           .agg(n=("y", "size"), suma=("y", "sum"), suma2=("_y2", "sum")).reset_index())
    g["media"] = g["suma"] / g["n"]
    g["ssw"] = (g["suma2"] - g["suma"] ** 2 / g["n"]).clip(lower=0.0)
    return g


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

    g = _agregados_grupo(d, col_celda)
    n_total, n_grupos = len(d), len(g)
    n_celdas = int(g[col_celda].nunique())

    ssw = float(g["ssw"].sum())
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


def sigma2_por_celda(train, col_celda, sigma2_global=None):
    """`sigma2_c` por celda, encogido hacia el global. Devuelve (Serie, sigma2_global).

    POR QUE existe, y por que no basta el sigma2 global (medido, ver `mediciones.md` 11):
    con un sigma2 unico para todas las celdas, `sd_pred` solo varia por el conteo de
    donantes — y entonces la anchura predictiva ES el conteo de donantes disfrazado, que
    es exactamente lo que D-011 quito. Medido sobre un marco con dispersion real variando
    12x entre celdas: `sd_pred` variaba 1,06x y su correlacion con el error real era
    **negativa** (-0,384). La regla optima de abstencion umbraliza la varianza CONDICIONAL
    (Zaoui, Denis & Hebiri 2020); una varianza igual para todas las celdas no esta
    condicionada a nada.

    EL ENCOGIMIENTO NO TIENE PARAMETROS LIBRES. Empirical Bayes clasico sobre la escala
    log: `log s2_c` tiene varianza de muestreo ~ 2/df_c, asi que la varianza real entre
    celdas se estima por momentos —V = var(log s2) - media(2/df)— y el peso de cada celda
    sale de ahi: w_c = V/(V + 2/df_c). Las celdas con pocos grados de libertad se van
    hacia el global solas; las grandes conservan su estimacion. Es la misma idea que usa
    limma para varianzas de genes.

    `tau2` se deja GLOBAL a proposito: estimar la varianza entre empresas por celda
    necesita muchas empresas, y en `CARGO` la celda tipica tiene 3-5. Con ese `df` la
    estimacion es ruido puro y el encogimiento la devolveria al global de todos modos.
    Queda anotado como limite del metodo, no como descuido.
    """
    d = train[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"])
    if sigma2_global is None:
        sigma2_global = componentes_varianza(train, col_celda)[1]
    if d.empty:
        return pd.Series(dtype=float), float(sigma2_global)

    g = _agregados_grupo(d, col_celda)
    porc = g.groupby(col_celda, sort=False).agg(ssw=("ssw", "sum"), N=("n", "sum"),
                                                G=("n", "size"))
    porc["df"] = porc["N"] - porc["G"]

    utiles = porc[(porc["df"] >= 1) & (porc["ssw"] > 0)].copy()
    if len(utiles) < 3:
        return pd.Series(float(sigma2_global), index=porc.index), float(sigma2_global)

    utiles["s2"] = utiles["ssw"] / utiles["df"]
    L = np.log(utiles["s2"].to_numpy(float))
    var_muestreo = 2.0 / utiles["df"].to_numpy(float)
    V = max(0.0, float(L.var(ddof=1)) - float(var_muestreo.mean()))
    w = V / (V + var_muestreo) if V > 0 else np.zeros_like(var_muestreo)
    encogido = np.exp(w * L + (1.0 - w) * float(L.mean()))

    salida = pd.Series(float(sigma2_global), index=porc.index, dtype=float)
    salida.loc[utiles.index] = encogido
    return salida, float(sigma2_global)


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


def tabla_votos(train, col_celda, tau2=None, sigma2=None, sigma2_celda=None):
    """El voto de cada empresa en cada celda, con su peso. Es el insumo de `predecir`.

    Se expone aparte porque **el bootstrap remuestrea votos, no filas**. Remuestrear una
    empresa con reemplazo solo duplica su voto: recomputarlo desde las filas en cada
    replica cuesta 19,8 horas por informe (medido), y desde esta tabla, minutos.
    """
    tr = train[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"])
    if tau2 is None or sigma2 is None:
        tau2, sigma2 = componentes_varianza(train, col_celda)
    if sigma2_celda is None:
        sigma2_celda, _ = sigma2_por_celda(train, col_celda, sigma2_global=sigma2)

    v = (tr.groupby([col_celda, "empresa_ruc"], sort=False)["y"]
           .agg(voto="median", n="size").reset_index())
    # sigma2 DE LA CELDA, no el global: es lo que hace que `sd_pred` sea una varianza
    # condicional y no el conteo de donantes disfrazado. Ver `sigma2_por_celda`.
    v["s2"] = v[col_celda].map(sigma2_celda).fillna(float(sigma2)).astype(float)
    denom = float(tau2) + v["s2"].to_numpy(float) / v["n"].to_numpy(float)
    # Caso degenerado: sin varianza estimada el peso inverso-varianza es 1/0. Pasa cuando
    # todos los donantes valen lo mismo — imposible en datos reales, trivial en tests.
    # Sin la guarda, `predecir` devolveria NaN en silencio: parece abstencion y es un cero
    # mal dividido, que es la peor forma de fallar.
    v["w"] = np.where(denom > 0, 1.0 / np.where(denom > 0, denom, 1.0), 1.0)
    v.attrs["tau2"] = float(tau2)
    return v


def _cuantil_por_grupo(codigos, v, w, n_grupos, q=0.5):
    """Cuantil ponderado de cada grupo. `codigos` ascendente, y `v` ascendente dentro de
    cada grupo. Vectorizado: sin bucle de Python sobre celdas.

    Con 55.920 celdas de `CARGO` y 400 replicas de bootstrap, un bucle por celda son 22
    millones de iteraciones. Aqui son unas pocas operaciones de numpy.
    """
    total = np.bincount(codigos, weights=w, minlength=n_grupos)
    primeros = np.searchsorted(codigos, np.arange(n_grupos), side="left")
    ultimos = np.searchsorted(codigos, np.arange(n_grupos), side="right") - 1
    cum = np.cumsum(w)
    offset = np.where(primeros > 0, cum[np.maximum(primeros - 1, 0)], 0.0)
    dentro = cum - offset[codigos]
    with np.errstate(invalid="ignore", divide="ignore"):
        a = (dentro - 0.5 * w) / total[codigos]

    bajos = np.bincount(codigos[a < q], minlength=n_grupos)
    tam = ultimos - primeros + 1
    pos = primeros + np.clip(bajos, 0, np.maximum(tam - 1, 0))
    ant = np.maximum(pos - 1, primeros)

    x0, x1 = a[ant], a[pos]
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(x1 > x0, (q - x0) / np.where(x1 > x0, x1 - x0, 1.0), 0.0)
    salida = v[ant] + np.clip(t, 0.0, 1.0) * (v[pos] - v[ant])
    # extremos: el cuantil cae fuera del rango que cubren los pesos
    salida = np.where(bajos == 0, v[primeros], salida)
    return np.where(bajos >= tam, v[ultimos], salida)


def _resumen_por_celda(votos, col_celda, tau2):
    """Referencia, anchura y diagnosticos de cada celda. Todo vectorizado."""
    v = votos.sort_values([col_celda, "voto"], kind="mergesort")
    codigos, celdas = pd.factorize(v[col_celda], sort=True)
    orden = np.argsort(codigos, kind="stable")
    codigos = codigos[orden]
    vv = v["voto"].to_numpy(float)[orden]
    ww = v["w"].to_numpy(float)[orden]
    nn = v["n"].to_numpy(float)[orden]
    s2 = v["s2"].to_numpy(float)[orden]
    k = len(celdas)

    suma_w = np.bincount(codigos, weights=ww, minlength=k)
    suma_n = np.bincount(codigos, weights=nn, minlength=k)
    max_n = np.zeros(k)
    np.maximum.at(max_n, codigos, nn)
    n_emp = np.bincount(codigos, minlength=k)
    primeros = np.searchsorted(codigos, np.arange(k), side="left")

    with np.errstate(invalid="ignore", divide="ignore"):
        sd = np.sqrt(float(tau2) + s2[primeros] + 1.0 / suma_w)
        share = np.where(suma_n > 0, max_n / np.where(suma_n > 0, suma_n, 1.0), np.nan)
    return pd.DataFrame({"y_ref_bruto": _cuantil_por_grupo(codigos, vv, ww, k),
                         "sd_pred": sd,
                         "n_donantes": suma_n.astype(int),
                         "n_empresas_donantes": n_emp.astype(int),
                         "share_max_empresa": share},
                        index=pd.Index(celdas, name=col_celda))


_COLS = ["y_ref_bruto", "sd_pred", "n_donantes", "n_empresas_donantes",
         "share_max_empresa"]


def predecir_desde_votos(votos, test, col_celda, tau2=None, loco=True):
    """Como `predecir`, pero partiendo de la tabla de votos ya calculada.

    `loco=False` salta el leave-company-out. Es lo correcto cuando train y test no
    comparten empresas —que es SIEMPRE en la evaluacion real, porque el split es por
    empresa— y ahorra la unica parte que no se puede vectorizar.
    """
    if tau2 is None:
        tau2 = votos.attrs.get("tau2", 0.0)
    if votos.empty:
        return pd.DataFrame({c: np.nan for c in _COLS}, index=test.index).assign(
            n_donantes=0, n_empresas_donantes=0)

    resumen = _resumen_por_celda(votos, col_celda, tau2)
    salida = resumen.reindex(test[col_celda].to_numpy())
    salida.index = test.index
    salida["n_donantes"] = salida["n_donantes"].fillna(0).astype(int)
    salida["n_empresas_donantes"] = salida["n_empresas_donantes"].fillna(0).astype(int)
    if not loco:
        return salida

    # Atajo: si ninguna empresa de test dona, el leave-company-out no puede activarse.
    # Es SIEMPRE el caso en la evaluacion real —el split es por empresa—, y comprobarlo
    # cuesta O(empresas) en vez de O(filas de test).
    if not (set(test["empresa_ruc"].unique()) & set(votos["empresa_ruc"].unique())):
        return salida

    # Solo las filas cuya empresa TAMBIEN dona en su celda necesitan el recalculo caro.
    donantes = set(zip(votos[col_celda], votos["empresa_ruc"]))
    pares = list(zip(test[col_celda], test["empresa_ruc"]))
    afectadas = [i for i, par in enumerate(pares) if par in donantes]
    if not afectadas:
        return salida

    por_celda = {c: g for c, g in votos.groupby(col_celda, sort=False)}
    cache, vacio = {}, (np.nan, np.nan, 0, 0, np.nan)
    for i in afectadas:
        clave = pares[i]
        if clave not in cache:
            g = por_celda[clave[0]]
            g = g[g["empresa_ruc"] != clave[1]]
            if g.empty or g["w"].sum() <= 0:
                cache[clave] = vacio
            else:
                n = g["n"].to_numpy(float)
                cache[clave] = (
                    cuantil_ponderado(g["voto"], g["w"]),
                    float(np.sqrt(float(tau2) + float(g["s2"].iloc[0])
                                  + 1.0 / g["w"].sum())),
                    int(n.sum()), int(len(g)), float(n.max() / n.sum()))
        salida.iloc[i] = cache[clave]
    return salida.astype({"n_donantes": int, "n_empresas_donantes": int})


def predecir(train, test, col_celda, tau2=None, sigma2=None, sigma2_celda=None):
    """Referencia bruta y anchura predictiva por fila de `test`, con leave-company-out.

    NO aplica abstencion — eso es `aplicar_abstencion`. Devuelve:
      y_ref_bruto, sd_pred, n_donantes (personas), n_empresas_donantes, share_max_empresa

    `sd_pred = raiz(tau2 + sigma2_c + 1/suma(w_f))` tiene tres partes: la empresa nueva
    (tau2, global), la persona nueva (sigma2_c, **propio de la celda**) y el error de
    estimacion de mu_c. Las dos ultimas ordenan la abstencion; sin el sigma2 por celda la
    segunda es constante y `sd_pred` degenera en el conteo de donantes.

    Los componentes se pueden pasar precalculados: se estiman UNA vez sobre todo el train
    y se comparten, porque `sd_pred` solo es comparable entre celdas si vienen de la misma
    estimacion.
    """
    if tau2 is None or sigma2 is None:
        tau2, sigma2 = componentes_varianza(train, col_celda)
    votos = tabla_votos(train, col_celda, tau2=tau2, sigma2=sigma2,
                        sigma2_celda=sigma2_celda)
    return predecir_desde_votos(votos, test, col_celda, tau2=tau2)


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
