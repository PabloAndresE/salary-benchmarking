"""Comparar lo que paga un cliente contra el mercado.

Tres preguntas distintas, y conviene no mezclarlas:

  1. .Como se situa la EMPRESA frente al mercado?      un numero, el nivel general
  2. .Que PUESTOS estan fuera de linea?                por cargo
  3. .Que PERSONAS estan fuera de la politica propia?  equidad interna

La 3 es la menos obvia y la mas util. Si una empresa paga un 12% por encima del mercado y
un contador concreto esta justo en la referencia de mercado, ese contador esta MAL PAGADO
para su casa aunque frente al mercado parezca correcto. Medirlo exige separar el nivel de
la empresa del posicionamiento de cada puesto, que es lo que hace `anclar`.

POR QUE ESTO FUNCIONA. El efecto empleador es el 81% de lo que no se puede predecir
(tau = 0,29). Frente a una empresa nueva ese termino es irreducible — no hay forma de
saber si paga bien o mal. Pero un CLIENTE entrega su nomina con los sueldos dentro: nos
lo esta diciendo el. Medido (`research/experimentos/e1_premisa/06`): anclar mejora el
error un 12,8%, y un 14,6% en empresas con mas de 100 personas referenciadas.

  ADVERTENCIA: ese 12,8% esta medido sobre UNA sola particion y NO ha pasado el contraste
  pareado. El -1,63% de `12` tenia la misma pinta y se cayo al ponerle intervalo. Las
  partes 1 y 2 son aritmetica directa y no dependen de ese numero; la 3 si. Tratarla como
  preliminar hasta verificarla.
"""
import numpy as np
import pandas as pd

MIN_PARA_ANCLA = 5      # por debajo, el nivel de la empresa es ruido y se dice


def _log_sueldo(sueldos, sbu, anio):
    s = pd.to_numeric(sueldos, errors="coerce")
    return np.log(s.where(s > 0) / float(sbu(int(anio))))


def anclar(y_obs, y_ref, confianza=None, solo_fiables=True):
    """Nivel de la empresa: la mediana de (lo que paga - lo que dice el mercado).

    Se calcula DEJANDO FUERA a cada persona de su propio ancla. Si el nivel se estima con
    el sueldo de Juan y luego se juzga a Juan contra el, Juan siempre parecera normal —
    y el diagnostico de equidad interna no detectaria nada.

    Por defecto solo entran los puestos con referencia fiable: anclar sobre analogias
    lejanas es propagar ruido al numero que despues corrige a todos los demas.
    """
    r = pd.Series(y_obs, dtype=float) - pd.Series(y_ref, dtype=float)
    usable = r.notna()
    if solo_fiables and confianza is not None:
        usable &= pd.Series(confianza).isin(["ALTA", "MEDIA"]).to_numpy()
    validos = r[usable]
    n = len(validos)
    if n == 0:
        return pd.Series(np.nan, index=r.index), 0, float("nan")

    global_ = float(validos.median())
    # leave-one-out: para cada persona, la mediana de las demas
    orden = np.sort(validos.to_numpy())
    ancla = pd.Series(global_, index=r.index, dtype=float)
    if n > 1:
        pos = {i: k for k, i in enumerate(validos.sort_values().index)}
        for i in validos.index:
            k = pos[i]
            resto = np.delete(orden, k)
            ancla.at[i] = float(np.median(resto))
    return ancla, n, global_


def _lectura(y, p10, p25, p75, p90):
    """Donde cae un sueldo DENTRO DE LA BANDA de su cargo, no a que % de la referencia.

    Antes esto usaba cortes fijos de +/-5% y +/-15% para todos los cargos, y era el mismo
    error que `tau` global: un umbral que tiene que escalar con la dispersion del puesto,
    escrito como constante. Medido sobre la nomina de demo, cuatro de diez cargos marcados
    "muy por encima" estaban DENTRO de su propia banda:

        GERENTE GENERAL      +15,4%  "muy por encima"  banda +/-95,0%  <- dentro
        TRABAJADOR AGRICOLA  +15,5%  "muy por encima"  banda +/- 0,2%  <- muy fuera

    El mismo +15% no significa lo mismo en los dos sitios, y la banda ya lo sabia: estaba
    calculada y la etiqueta no la miraba.

    "en linea" pasa a significar *dentro del 50% central del mercado*, que es una frase
    que el cliente puede comprobar.
    """
    out = np.full(len(y), "sin referencia", dtype=object)
    hay = np.isfinite(y) & np.isfinite(p25) & np.isfinite(p75)
    out[hay & (y < p10)] = "muy por debajo"
    out[hay & (y >= p10) & (y < p25)] = "por debajo"
    out[hay & (y >= p25) & (y <= p75)] = "en linea"
    out[hay & (y > p75) & (y <= p90)] = "por encima"
    out[hay & (y > p90)] = "muy por encima"
    return out


def comparar(df, col_sueldo, col_cargo, ref_df, sbu, anio):
    """Anade al DataFrame del cliente las tres lecturas.

    `ref_df` es la salida de `BaseReferencia.referenciar`: trae la referencia, las DOS
    bandas —la de personas y la de empresas— y la confianza.

    Devuelve (detalle_por_persona, resumen_por_puesto, resumen_empresa).
    """
    col = lambda c: pd.Series(np.asarray(ref_df[c], dtype=float), index=df.index)
    y = _log_sueldo(df[col_sueldo], sbu, anio)
    ref = col("referencia_log")
    confianza = list(ref_df["confianza"])
    ancla, n_ancla, nivel = anclar(y, ref, confianza)

    out = df.copy()
    out["sueldo_actual"] = pd.to_numeric(df[col_sueldo], errors="coerce")
    out["referencia"] = (np.exp(ref) * float(sbu(int(anio)))).round(2)
    # 1 y 2: frente al MERCADO
    out["vs_mercado"] = (np.exp(y - ref) - 1.0).round(4)
    # 3: frente a la POLITICA PROPIA de la empresa
    out["vs_politica_interna"] = (np.exp(y - ref - ancla) - 1.0).round(4)
    out["confianza"] = confianza

    # UNA PERSONA se compara contra la banda de PERSONAS. La de empresas es mas estrecha
    # —no lleva la dispersion dentro de la nomina— y usarla aqui hace que la gente parezca
    # mas rara de lo que es, sobre todo en los cargos comprimidos.
    yv = y.to_numpy(float)
    p10, p25 = col("p10per_log").to_numpy(float), col("p25per_log").to_numpy(float)
    p75, p90 = col("p75per_log").to_numpy(float), col("p90per_log").to_numpy(float)
    out["lectura_mercado"] = _lectura(yv, p10, p25, p75, p90)
    # Para la equidad interna se descuenta el nivel de la empresa y se mira contra la
    # misma banda: "si mi empresa pagara a mercado, .donde estaria esta persona?".
    a = ancla.to_numpy(float)
    out["lectura_interna"] = _lectura(yv - a, p10, p25, p75, p90)

    # UN PUESTO de la empresa se compara contra la banda de EMPRESAS, y con la MEDIANA de
    # lo que paga la empresa —que es su voto—, no con cada persona. Es la misma unidad con
    # la que se construyo la banda.
    out["_y"] = yv
    for q in ("p10", "p25", "p75", "p90"):
        out["_" + q] = col(q + "_log").to_numpy(float)
    por_puesto = (out.groupby(col_cargo)
                     .agg(personas=(col_sueldo, "size"),
                          sueldo_medio=("sueldo_actual", "median"),
                          referencia=("referencia", "first"),
                          vs_mercado=("vs_mercado", "median"),
                          confianza=("confianza", "first"),
                          _voto=("_y", "median"), _p10=("_p10", "first"),
                          _p25=("_p25", "first"), _p75=("_p75", "first"),
                          _p90=("_p90", "first"))
                     .sort_values("vs_mercado").reset_index())
    por_puesto["lectura"] = _lectura(
        por_puesto["_voto"].to_numpy(float), por_puesto["_p10"].to_numpy(float),
        por_puesto["_p25"].to_numpy(float), por_puesto["_p75"].to_numpy(float),
        por_puesto["_p90"].to_numpy(float))
    por_puesto = por_puesto.drop(columns=[c for c in por_puesto.columns
                                          if c.startswith("_")])
    out = out.drop(columns=[c for c in out.columns if c.startswith("_")])

    resumen = {
        "personas": int(len(out)),
        "con_referencia": int(out["referencia"].notna().sum()),
        "usadas_para_el_ancla": int(n_ancla),
        "nivel_vs_mercado": float(np.exp(nivel) - 1.0) if np.isfinite(nivel) else float("nan"),
        "ancla_fiable": bool(n_ancla >= MIN_PARA_ANCLA),
    }
    return out, por_puesto, resumen


def texto_resumen(resumen, por_puesto):
    """El resumen que un gerente lee primero."""
    lin = []
    n = resumen["nivel_vs_mercado"]
    if np.isfinite(n):
        lado = "POR ENCIMA" if n > 0 else "POR DEBAJO"
        lin.append(f"La empresa paga un {abs(n):.1%} {lado} del mercado.")
    if not resumen["ancla_fiable"]:
        lin.append("")
        lin.append("  " + "!" * 68)
        lin.append(f"  AVISO: el nivel de la empresa sale de solo "
                   f"{resumen['usadas_para_el_ancla']} personas con referencia fiable.")
        lin.append("  Con tan pocas, ese porcentaje es ORIENTATIVO y la lectura de equidad")
        lin.append("  interna no es concluyente. Medido: la mejora por anclar pasa de 8,1%")
        lin.append("  con 5-19 personas referenciadas a 14,6% con mas de 100.")
        lin.append("  " + "!" * 68)
    lin.append(f"{resumen['con_referencia']} de {resumen['personas']} personas "
               f"tienen referencia de mercado.")
    # Se filtra por la LECTURA, que es relativa a la banda de cada cargo, no por el
    # porcentaje. Con el corte fijo de +/-15% este listado sacaba ocho puestos "muy por
    # encima" de los cuales CUATRO estaban dentro de su propia banda — y es el primer
    # parrafo que lee un gerente.
    bajos = por_puesto[por_puesto.lectura == "muy por debajo"]
    altos = por_puesto[por_puesto.lectura == "muy por encima"]
    if len(bajos):
        lin.append(f"\nPuestos MUY POR DEBAJO del mercado ({len(bajos)}):")
        for _, r in bajos.head(8).iterrows():
            lin.append(f"  {str(r.iloc[0])[:38]:<40} {r.vs_mercado:>+7.1%}  "
                       f"({int(r.personas)} pers., confianza {r.confianza})")
    if len(altos):
        lin.append(f"\nPuestos MUY POR ENCIMA ({len(altos)}):")
        for _, r in altos.tail(8).iterrows():
            lin.append(f"  {str(r.iloc[0])[:38]:<40} {r.vs_mercado:>+7.1%}  "
                       f"({int(r.personas)} pers., confianza {r.confianza})")
    return "\n".join(lin)
