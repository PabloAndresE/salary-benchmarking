"""Error, cobertura, riesgo generalizado y puntuacion propia.

Por que el riesgo GENERALIZADO y no el selectivo a cobertura igualada: el riesgo selectivo
"solo considera el riesgo respecto de las predicciones aceptadas, asumiendo que una
seleccion especifica ya ocurrio" (Traub et al., NeurIPS 2024). Su denominador cambia con
cada metodo, asi que CARGO al 60,5% y el arquetipo al 100% no se leen en la misma escala.
Aqui el denominador es N para todos.

Nota: la version previa de este modulo barria `min_donantes` (1..30) como perilla de
confianza. Era degenerada — con la celda media a ~26.000 donantes ningun umbral recortaba
nada y la curva del arquetipo era un punto. Ver D-011.
"""
import numpy as np
import pandas as pd
from scipy.special import erf

from .referencia import (SUELO_EMPRESAS, SUELO_SHARE, _cuantil_por_grupo,
                         aplicar_abstencion, predecir,
                         predecir_desde_votos, tabla_votos)
from .splits import SEMILLA

# E|X - mu| para X normal: sd * raiz(2/pi). Enlaza el coste de abstenerse con el umbral de
# anchura, de modo que barrer `c` sea barrer el umbral y no una perilla aparte.
_RAIZ_2_PI = float(np.sqrt(2.0 / np.pi))


def error_y_cobertura(test, y_ref):
    """MAE, RMSE, sesgo con signo, MAE intra-empresa y cobertura.

    Error y cobertura van SIEMPRE juntos: comparar solo el error favorece al metodo que se
    abstiene mas, porque acierta mas donde unicamente opina teniendo datos.

    `mae_intra` descompone e_fi = e_barra_f + (e_fi - e_barra_f) y reporta la segunda
    parte. e_barra_f es el efecto empresa: impredecible bajo leave-company-out e IDENTICO
    para todos los metodos. Ahi vive el grueso de la sd del error y solo diluye la senal.
    """
    y = pd.to_numeric(test["y"], errors="coerce").to_numpy(float)
    ref = pd.to_numeric(pd.Series(y_ref).reindex(test.index), errors="coerce").to_numpy(float)
    ok = np.isfinite(y) & np.isfinite(ref)
    n_total, n_eval = len(y), int(ok.sum())
    if n_eval == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "sesgo": float("nan"),
                "mae_intra": float("nan"), "cobertura": 0.0,
                "n_evaluadas": 0, "n_total": n_total}

    err = y[ok] - ref[ok]
    emp = (test["empresa_ruc"].to_numpy()[ok] if "empresa_ruc" in test.columns
           else np.zeros(n_eval))
    centrado = pd.Series(err).groupby(pd.Series(emp)).transform(lambda v: v - v.mean())
    return {"mae": float(np.abs(err).mean()),
            "rmse": float(np.sqrt((err ** 2).mean())),
            "sesgo": float(err.mean()),
            "mae_intra": float(np.abs(centrado.to_numpy()).mean()),
            "cobertura": n_eval / n_total,
            "n_evaluadas": n_eval, "n_total": n_total}


def crps_normal(y, mu, sd):
    """CRPS de una predictiva normal, forma cerrada.

        CRPS = sd * [ z(2*Phi(z) - 1) + 2*phi(z) - 1/raiz(pi) ],  z = (y - mu)/sd

    Estrictamente propio, y "generaliza el error absoluto, al que se reduce si F es un
    pronostico determinista" (Gneiting & Raftery 2007, 4.2). Es lo que hace que adoptarlo
    no rompa nada de lo pre-registrado: el MAE actual es su caso degenerado.
    """
    y = np.asarray(y, dtype=float)
    mu = np.asarray(mu, dtype=float)
    sd = np.asarray(sd, dtype=float)
    seguro = np.where(sd > 0, sd, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (y - mu) / seguro
        cdf = 0.5 * (1.0 + erf(z / np.sqrt(2.0)))
        pdf = np.exp(-0.5 * z ** 2) / np.sqrt(2.0 * np.pi)
        salida = seguro * (z * (2.0 * cdf - 1.0) + 2.0 * pdf - 1.0 / np.sqrt(np.pi))
    return np.where(sd > 0, salida, np.abs(y - mu))


def _riesgo(y, ref, coste):
    """(1/N) * suma sobre TODAS las filas de |err| si acepta, y `coste` si se abstiene."""
    ok = np.isfinite(y) & np.isfinite(ref)
    n = len(y)
    if n == 0:
        return float("nan"), 0.0, float("nan")
    perdida = float(np.abs(y[ok] - ref[ok]).sum()) + float(coste) * (n - int(ok.sum()))
    mae = float(np.abs(y[ok] - ref[ok]).mean()) if ok.any() else float("nan")
    return perdida / n, int(ok.sum()) / n, mae


def curva_coste(test, pred, costes, min_empresas=SUELO_EMPRESAS, share_max=SUELO_SHARE):
    """Riesgo generalizado barriendo el COSTE DE ABSTENERSE.

    `c` es una cantidad de negocio con significado —cuanto cuesta no tener respuesta—, no
    una perilla estadistica. Y el `c` donde se cruzan las curvas de dos metodos es la
    frontera entre los escenarios A y B de D-004.

    Con predictiva normal, E|y - mu| = sd*raiz(2/pi), asi que la regla de Bayes acepta
    cuando sd <= c/raiz(2/pi): barrer `c` ES barrer el umbral de anchura.
    """
    y = pd.to_numeric(test["y"], errors="coerce").to_numpy(float)
    filas = []
    for c in np.atleast_1d(np.asarray(costes, dtype=float)):
        ref = aplicar_abstencion(pred, max_sd=float(c) / _RAIZ_2_PI,
                                 min_empresas=min_empresas,
                                 share_max=share_max).to_numpy(float)
        r, cob, mae = _riesgo(y, ref, c)
        filas.append({"coste": float(c), "cobertura": cob, "mae_aceptadas": mae,
                      "riesgo": r})
    return pd.DataFrame(filas)


def curva_riesgo(test, pred, n_puntos=41, min_empresas=SUELO_EMPRESAS,
                 share_max=SUELO_SHARE):
    """Riesgo generalizado (sin termino de coste) frente a cobertura.

    Barre el umbral de anchura por CUANTILES de `sd_pred`, no linealmente. Es deliberado:
    el rango de `sd_pred` esta comprimido —domina el ruido irreducible tau2+sigma2, y solo
    el termino 1/suma(w) varia entre celdas—, asi que un barrido lineal concentraria casi
    todos los puntos en la misma cobertura. Con cuantiles la curva tiene resolucion en
    todo [0,1] tanto con 55.920 celdas como con 50.
    """
    y = pd.to_numeric(test["y"], errors="coerce").to_numpy(float)
    sd = pd.to_numeric(pred["sd_pred"], errors="coerce").to_numpy(float)
    validas = sd[np.isfinite(sd)]
    if validas.size == 0:
        return pd.DataFrame(columns=["umbral_sd", "cobertura", "riesgo_generalizado",
                                     "mae_aceptadas"])
    umbrales = np.unique(np.quantile(validas, np.linspace(0.0, 1.0, int(n_puntos))))
    # un umbral por debajo del minimo da el extremo de cobertura cero, que es donde
    # arranca la curva y sin el AUGRC se calcularia sobre un rango truncado.
    umbrales = np.concatenate(([np.nextafter(validas.min(), -np.inf)], umbrales))
    filas = []
    for u in umbrales:
        ref = aplicar_abstencion(pred, max_sd=float(u), min_empresas=min_empresas,
                                 share_max=share_max).to_numpy(float)
        r, cob, mae = _riesgo(y, ref, 0.0)
        filas.append({"umbral_sd": float(u), "cobertura": cob,
                      "riesgo_generalizado": r, "mae_aceptadas": mae})
    return (pd.DataFrame(filas).drop_duplicates(subset="cobertura")
            .sort_values("cobertura").reset_index(drop=True))


def augrc(curva):
    """Area bajo la curva de riesgo generalizado frente a cobertura, normalizada.

    Escalar comparable entre metodos con coberturas distintas, porque el denominador del
    riesgo es N para todos. Sustituye a AURC, que viola monotonicidad por sobreponderar
    los fallos de alta confianza (Traub et al., NeurIPS 2024) — y que un borrador previo
    de este plan recomendaba. Menor es mejor.
    """
    if curva.empty or len(curva) < 2:
        return float("nan")
    x = curva["cobertura"].to_numpy(float)
    z = curva["riesgo_generalizado"].to_numpy(float)
    ancho = x.max() - x.min()
    return float(np.trapezoid(z, x) / ancho) if ancho > 0 else float(z.mean())


def por_subgrupo(test, y_ref, col, minimo=30):
    """Error Y cobertura por nivel de `col`. Las dos columnas, siempre.

    Al bajar la cobertura el riesgo de un subgrupo puede empeorar aunque el global mejore
    (Shah et al., ICML 2022). Y las celdas que no alcanzan donantes no son un subconjunto
    aleatorio: son ocupaciones raras, empresas pequenas y provincias fuera de Pichincha y
    Guayas. El banco puede reportar un MAE excelente mientras la referencia se degrada
    justo para quien mas la necesita.
    """
    d = test.copy()
    d["_ref"] = pd.to_numeric(pd.Series(y_ref).reindex(test.index), errors="coerce")
    filas = []
    for nivel, g in d.groupby(d[col].astype(str), sort=True):
        if len(g) < int(minimo):
            continue
        r = error_y_cobertura(g, g["_ref"])
        filas.append({col: nivel, "n": len(g), "cobertura": r["cobertura"],
                      "mae": r["mae"], "sesgo": r["sesgo"], "mae_intra": r["mae_intra"]})
    return pd.DataFrame(filas)


def _posiciones_por_empresa(df):
    """{empresa: array de posiciones}. Se calcula una vez y se reutiliza en cada replica."""
    return {ruc: np.asarray(idx) for ruc, idx
            in df.groupby("empresa_ruc", sort=True).indices.items()}


def _compilar(votos, test, col_celda):
    """Representacion en numpy de un metodo: todo lo que NO cambia entre replicas.

    El bucle del bootstrap no puede tocar pandas. Con la tabla de votos ya ordenada por
    (celda, voto) y las celdas convertidas a codigos enteros, una replica es media docena
    de operaciones vectorizadas; con `sort_values` y `reindex` por replica son 10 horas
    (medido). Al remuestrear se ordenan los INDICES, no las filas: como la tabla ya viene
    ordenada, un `np.sort` sobre enteros basta para conservar el orden que
    `_cuantil_por_grupo` necesita.
    """
    v = votos.sort_values([col_celda, "voto"], kind="mergesort").reset_index(drop=True)
    celdas = pd.Index(pd.unique(v[col_celda]))          # ya en orden de celda
    codigo = pd.Series(np.arange(len(celdas)), index=celdas)
    cod_test = codigo.reindex(test[col_celda].to_numpy()).to_numpy(float)
    return {"cod": codigo.reindex(v[col_celda]).to_numpy(),
            "voto": v["voto"].to_numpy(float), "w": v["w"].to_numpy(float),
            "n": v["n"].to_numpy(float), "s2": v["s2"].to_numpy(float),
            "k": int(len(celdas)), "tau2": float(votos.attrs.get("tau2", 0.0)),
            "cod_test": np.where(np.isnan(cod_test), -1, cod_test).astype(int),
            "pos": _posiciones_por_empresa(v)}


def _referencia_np(c, idx, max_sd, min_empresas, share_max):
    """Referencia por celda y mascara de abstencion, en numpy. Devuelve (y_ref, sd)."""
    cod, w, n = c["cod"][idx], c["w"][idx], c["n"][idx]
    v, s2, k = c["voto"][idx], c["s2"][idx], c["k"]
    suma_w = np.bincount(cod, weights=w, minlength=k)
    suma_n = np.bincount(cod, weights=n, minlength=k)
    n_emp = np.bincount(cod, minlength=k)
    max_n = np.zeros(k)
    np.maximum.at(max_n, cod, n)
    primeros = np.searchsorted(cod, np.arange(k), side="left")
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = np.sqrt(c["tau2"] + s2[np.clip(primeros, 0, len(s2) - 1)] + 1.0 / suma_w)
        share = np.where(suma_n > 0, max_n / np.where(suma_n > 0, suma_n, 1.0), np.nan)
    ref = _cuantil_por_grupo(cod, v, w, k)
    fuera = (n_emp < int(min_empresas)) | (np.nan_to_num(share, nan=1.0) > float(share_max))
    if max_sd is not None:
        fuera |= ~np.isfinite(sd) | (sd > float(max_sd))
    return np.where(fuera, np.nan, ref), sd


def _sortear_empresas(empresas, rng):
    """Muestra bootstrap de EMPRESAS con reemplazo.

    Nunca de filas: la fila no es la unidad independiente (una empresa aporta cientos de
    personas y una persona recurre entre anios).
    """
    return empresas[rng.integers(0, len(empresas), len(empresas))]


def _indices(posiciones, elegidas):
    """Posiciones de las filas de las empresas elegidas. Trabajar con indices y no con
    DataFrames es lo que hace viable el bootstrap: concatenar trozos de DataFrame por
    replica costaba 19,8 horas por informe (medido)."""
    trozos = [posiciones[e] for e in elegidas if e in posiciones]
    return np.concatenate(trozos) if trozos else np.array([], dtype=int)


def replicas_bootstrap(train, test, particiones_tr, particiones_ts, n=400, semilla=SEMILLA,
                       max_sd=None, min_empresas=SUELO_EMPRESAS, share_max=SUELO_SHARE,
                       remuestrear_train=True):
    """MAE de cada metodo, replica a replica, con NUMEROS ALEATORIOS COMUNES.

    Dos etapas: se remuestrean empresas de train (hace variar mu_c, que en CARGO se estima
    con 3-5 empresas) y empresas de test (hace variar a quien se evalua). Todos los metodos
    se evaluan sobre la MISMA replica, asi que la diferencia pareada aisla la particion y
    cancela el efecto empresa, que es comun a los dos.

    El MAE se calcula sobre la INTERSECCION de filas donde todos respondieron: comparar
    sobre conjuntos distintos es lo que la co-primaria de cobertura existe para evitar.

    `remuestrear_train=False` reproduce el estimador defectuoso previo. Existe solo para
    que el test pueda demostrar la subestimacion de varianza; no usar.
    """
    nombres = list(particiones_ts)
    tr0 = train.assign(**{f"_c_{m}": particiones_tr[m].astype(str).to_numpy()
                          for m in nombres})
    ts0 = test.assign(**{f"_c_{m}": particiones_ts[m].astype(str).to_numpy()
                         for m in nombres}).reset_index(drop=True)

    # Los votos se calculan UNA vez por metodo. Remuestrear una empresa con reemplazo
    # solo duplica su voto, asi que la replica es una seleccion de filas de esta tabla.
    # Los componentes de varianza quedan FIJOS entre replicas: vienen de millones de
    # filas, mientras mu_c viene de 3-5 empresas, y esa es la incertidumbre que importa.
    # Es una simplificacion declarada, no un descuido.
    comp = {m: _compilar(tabla_votos(tr0, f"_c_{m}"), ts0, f"_c_{m}") for m in nombres}
    todos = {m: np.arange(len(comp[m]["voto"])) for m in nombres}
    pos_test = _posiciones_por_empresa(ts0)
    emp_tr = np.array(sorted(tr0["empresa_ruc"].unique()))
    emp_ts = np.array(sorted(ts0["empresa_ruc"].unique()))
    y0 = pd.to_numeric(ts0["y"], errors="coerce").to_numpy(float)

    rng = np.random.default_rng(int(semilla))
    filas = []
    for _ in range(int(n)):
        # LAS MISMAS empresas para todos los metodos: numeros aleatorios comunes. Es lo
        # que hace que la diferencia pareada cancele el efecto empresa en vez de pagarlo.
        emp_b = _sortear_empresas(emp_tr, rng) if remuestrear_train else None
        i_ts = _indices(pos_test, _sortear_empresas(emp_ts, rng))
        y = y0[i_ts]

        refs = {}
        for m in nombres:
            c = comp[m]
            idx = np.sort(_indices(c["pos"], emp_b)) if remuestrear_train else todos[m]
            if idx.size == 0:
                refs[m] = np.full(len(i_ts), np.nan)
                continue
            por_celda, _ = _referencia_np(c, idx, max_sd, min_empresas, share_max)
            cod = c["cod_test"][i_ts]
            refs[m] = np.where(cod >= 0, por_celda[np.clip(cod, 0, c["k"] - 1)], np.nan)
        comun = np.isfinite(y)
        for m in nombres:
            comun &= np.isfinite(refs[m])
        if not comun.any():
            continue
        filas.append({m: float(np.abs(y[comun] - refs[m][comun]).mean()) for m in nombres})
    return pd.DataFrame(filas, columns=nombres)


def ic_diferencia(replicas, a, b, alfa=0.05):
    """IC percentil de la diferencia PAREADA `a - b`, replica a replica.

    Leer el solapamiento de dos IC marginales en su lugar es el error de Schenker &
    Gentleman (2001): el solapamiento no implica no-significancia. Y aqui el contraste
    marginal paga entero el efecto empresa, que la diferencia pareada cancela.
    """
    d = (replicas[a] - replicas[b]).dropna().to_numpy(float)
    if d.size == 0:
        return {"dif": float("nan"), "ic_bajo": float("nan"), "ic_alto": float("nan"),
                "n_replicas": 0}
    return {"dif": float(d.mean()),
            "ic_bajo": float(np.quantile(d, alfa / 2)),
            "ic_alto": float(np.quantile(d, 1 - alfa / 2)),
            "n_replicas": int(d.size)}


def omega2_intra_empresa(df, col_celda):
    """omega2 de la celda sobre el residuo INTRA-empresa del objetivo.

    Se residualiza contra la empresa primero porque el empleador explica ~39% de la
    varianza del log-salario. Sin encogimiento: el 76,6% de la gente esta en empresas de
    100 o mas, asi que la correccion del modelo mixto apenas mueve nada (D-006 #3).
    omega2 y no eta2 porque penaliza los grados de libertad, y aqui se comparan
    cardinalidades muy distintas (55.920 celdas frente a 50).

    Confirmatorio, nunca arbitro: la decision la toma el error fuera de muestra.
    """
    d = df[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"]).copy()
    if d.empty:
        return float("nan")
    d["r"] = d["y"] - d.groupby("empresa_ruc")["y"].transform("mean")
    k, n = d[col_celda].nunique(), len(d)
    if k < 2 or n <= k:
        return float("nan")
    gran = d["r"].mean()
    g = d.groupby(col_celda)["r"].agg(["mean", "size"])
    ss_entre = float((g["size"] * (g["mean"] - gran) ** 2).sum())
    ss_total = float(((d["r"] - gran) ** 2).sum())
    ms_dentro = (ss_total - ss_entre) / (n - k)
    denom = ss_total + ms_dentro
    return float((ss_entre - (k - 1) * ms_dentro) / denom) if denom > 0 else float("nan")
