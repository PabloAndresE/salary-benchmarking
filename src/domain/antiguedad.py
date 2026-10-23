"""Antiguedad en anios desde las fechas de la nomina del cliente.

NO ES UNA RESTA. La plantilla trae `Fecha de primer ingreso` y luego pares de salida y
reingreso, porque en Ecuador es corriente salir y volver a la misma empresa. Restar el
primer ingreso a la fecha de corte le regala a esa persona los anios que estuvo fuera, y
la antiguedad es justo lo que decide indemnizaciones y escalafon.

    ingreso ──── salida 1    reingreso 1 ──── salida 2    reingreso 2 ──── (sigue)
    └── cuenta ──┘           └──── cuenta ────┘           └──── cuenta ──────┘
                 └─ fuera ───┘            └─ fuera ──┘

Un tramo sin salida es el que sigue abierto y se cierra en la FECHA DE CORTE: el 31 de
diciembre del ano del informe, no "hoy". Un estudio valorado a 2025 tiene que dar lo
mismo se corra en enero o en noviembre de 2026, o los numeros dejan de ser reproducibles.

La version que ya existia en `ingesta/features_base` hace `anio - fecha_ingreso.year` y
se salta todo esto. Esa alimenta la BASE y cambiarla movería estadisticos ya medidos;
esta es para la nomina del CLIENTE. Que convivan dos definiciones es deuda, y esta
anotada como tal.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

_RE_INGRESO = re.compile(r"primer\s*ingreso|fecha\s*de\s*ingreso|fecha\s*ingreso")
_RE_SALIDA = re.compile(r"salida")
_RE_REINGRESO = re.compile(r"reingreso")


def _norm(c) -> str:
    """Guiones bajos como espacios: el formato canonico usa `fecha_ingreso` y la
    plantilla de un cliente `Fecha de primer ingreso`. Sin esto la primera no se
    detectaba y la antiguedad salia vacia para TODAS las filas, en silencio."""
    return " ".join(str(c).replace("_", " ").split()).casefold()


def columnas_de_fecha(df) -> tuple[str | None, list[str], list[str]]:
    """(ingreso, salidas, reingresos) detectadas por nombre, en orden."""
    ingreso, salidas, reingresos = None, [], []
    for c in df.columns:
        n = _norm(c)
        if _RE_REINGRESO.search(n):
            reingresos.append(c)
        elif _RE_SALIDA.search(n):
            salidas.append(c)
        elif ingreso is None and _RE_INGRESO.search(n):
            ingreso = c
    orden = lambda c: (int(m.group()) if (m := re.search(r"\d+", str(c))) else 0)
    return ingreso, sorted(salidas, key=orden), sorted(reingresos, key=orden)


# Empieza por cuatro digitos y un separador: `2004-09-06`, `2025/06/20`. Cuando el ano
# va primero el orden es ano-mes-dia en todas partes —ISO 8601 y sus variantes—, asi que
# esas fechas NO son ambiguas y no deben tocarse con `dayfirst`.
_RE_ANIO_PRIMERO = re.compile(r"^\s*\d{4}[-/.]")


def _fechas(s: pd.Series) -> pd.Series:
    """A fecha, mirando cada celda por separado y segun donde este el ano.

    EL DEFECTO QUE ARREGLA, medido sobre una nomina real de 303 filas: 195 se quedaron
    SIN antiguedad y 101 recibieron un numero equivocado — solo 7 salieron bien, y de
    casualidad, porque su dia coincidia con su mes.

    La version anterior era `pd.to_datetime(s, dayfirst=True)` a secas. Pandas deduce UN
    formato mirando la primera fila y lo aplica a todas. Si esa primera fila es
    `2004-09-06` —ambigua, 09 y 06 caben los dos como mes— y ademas se le ha pedido
    `dayfirst`, deduce ano-DIA-mes. Desde ahi:

      - toda fecha ISO se lee con el dia y el mes cambiados, en silencio;
      - y si el dia real pasa de 12 no hay mes que le corresponda —no existe el mes 20—,
        asi que `errors="coerce"` la deja vacia y tampoco avisa.

    Un ingreso del 6 de septiembre de 2004 salia con 22,56 anios en vez de 22,32: la
    antiguedad leida como 9 de junio. Los errores llegaban a ocho meses, y esta cifra es
    la que decide indemnizaciones y escalafon.

    LA REGLA: si el ano va primero, es ano-mes-dia; si no, dia-mes-ano, que es como lo
    escribe un area de RR.HH. en Ecuador —`03/04/2020` es 3 de abril—. `format="mixed"`
    para que cada celda se resuelva sola y una fila no le imponga su formato al resto.
    """
    if pd.api.types.is_datetime64_any_dtype(s):
        return s                      # ya viene resuelta de Excel: no se re-interpreta
    t = s.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    anio_primero = t.str.match(_RE_ANIO_PRIMERO)
    if anio_primero.any():
        out[anio_primero] = pd.to_datetime(t[anio_primero], errors="coerce",
                                           yearfirst=True, dayfirst=False,
                                           format="mixed")
    resto = ~anio_primero
    if resto.any():
        out[resto] = pd.to_datetime(t[resto], errors="coerce", dayfirst=True,
                                    format="mixed")
    return out


def antiguedad_anios(df, anio: int) -> pd.Series:
    """Anios trabajados a 31 de diciembre de `anio`, descontando los periodos fuera.

    NaN si no hay fecha de ingreso legible: no se inventa un cero, que se leeria como
    "recien entrado" y es una afirmacion distinta de "no lo se".
    """
    ingreso, salidas, reingresos = columnas_de_fecha(df)
    if ingreso is None:
        return pd.Series(np.nan, index=df.index, dtype=float)

    corte = pd.Timestamp(year=int(anio), month=12, day=31)
    ini = _fechas(df[ingreso])
    fin_de = [_fechas(df[c]) for c in salidas]
    reini_de = [_fechas(df[c]) for c in reingresos]

    dias = pd.Series(0.0, index=df.index)
    abierto = ini.notna()
    # `cerrado_en_corte` marca a quien ya llego hasta la fecha de corte. Sin el, un
    # tramo abierto se sumaba UNA VEZ POR VUELTA del bucle y quien llevaba 2 anios
    # salia con 4: el error crecia con el numero de columnas de salida del archivo.
    cerrado_en_corte = pd.Series(False, index=df.index)
    inicio = ini.copy()
    # tramos: (ingreso, salida1), (reingreso1, salida2), (reingreso2, salida3)...
    for k in range(len(salidas) + 1):
        if k > 0:
            if k - 1 >= len(reini_de):
                break
            nuevo = reini_de[k - 1]
            # solo reabre a quien SALIO y tiene fecha de reingreso valida
            reabre = nuevo.notna() & ~abierto & ~cerrado_en_corte
            inicio = inicio.where(~reabre, nuevo)
            abierto = abierto | reabre
        vivos = abierto & ~cerrado_en_corte & inicio.notna()
        if not vivos.any():
            break
        fin = fin_de[k] if k < len(fin_de) else pd.Series(pd.NaT, index=df.index)
        cierra = fin.notna() & vivos
        hasta = fin.where(cierra, corte)
        dias = dias.add((hasta - inicio).dt.days.where(vivos).clip(lower=0).fillna(0),
                        fill_value=0)
        cerrado_en_corte = cerrado_en_corte | (vivos & ~cierra)
        abierto = abierto & ~cierra & ~cerrado_en_corte

    out = (dias / 365.25).round(2)
    return out.where(ini.notna())


# Los tramos, en un solo sitio. El servicio los publica en `UNIDADES` para que el front
# no tenga que deducir la lista de los datos que le llegaron —una nomina joven no trae
# `mas de 20` y el filtro saldria sin esa opcion—, y estaban escritos a mano alla y aca:
# dos listas que hay que acordarse de cambiar juntas son una que se va a desincronizar.
TRAMOS = ("menos de 1", "1 a 3", "3 a 5", "5 a 10", "10 a 20", "mas de 20")


def tramo(anios) -> pd.Series:
    """Cubos para el filtro de ANTIGUEDAD del front. Los cortes son los que usa la
    practica de compensaciones en Ecuador, no cuantiles: un filtro tiene que significar
    lo mismo entre dos informes distintos."""
    a = pd.to_numeric(pd.Series(anios), errors="coerce")
    etiquetas = list(TRAMOS)
    cortes = [-np.inf, 1, 3, 5, 10, 20, np.inf]
    out = pd.cut(a, bins=cortes, labels=etiquetas, right=False)
    return out.astype(object).where(a.notna(), None)
