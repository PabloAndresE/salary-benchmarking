"""Como se presenta lo que produce el modelo: unidades, orden de columnas, estado de cada
fila, la etiqueta de cada puesto y el bloque del sector. Es presentacion pura: nada de
esto toca un calculo."""

import numpy as np
import pandas as pd

from src.domain.antiguedad import TRAMOS as TRAMOS_ANTIGUEDAD
from src.domain.base_referencia import MIN_EMPRESAS_VEREDICTO

# UNIDADES DECLARADAS. Un front que formatee `vs_mercado` como dolares produce un numero
# creible y falso, que es peor que un error. Viaja con cada respuesta.
UNIDADES = {
    "sueldo_actual": {"unidad": "usd", "formato": "$#,##0.00"},
    "referencia": {"unidad": "usd", "formato": "$#,##0.00"},
    "p10": {"unidad": "usd"},
    "p25": {"unidad": "usd"},
    "p75": {"unidad": "usd"},
    "p90": {"unidad": "usd"},
    # 2026-10-07: `p10`..`p90` son la banda de EMPRESAS (el mercado); la de personas, aparte
    "p10_per": {"unidad": "usd"},
    "p25_per": {"unidad": "usd"},
    "p75_per": {"unidad": "usd"},
    "p90_per": {"unidad": "usd"},
    "posicion_mercado": {"unidad": "percentil", "rango": [10, 90]},
    "referencia_equivalente": {"unidad": "usd", "formato": "$#,##0.00"},
    "prima_idioma": {"unidad": "fraccion", "formato": "0%"},
    # el rango de mercado que se MUESTRA: p25-p75 de la banda de empresas
    "rango_desde": {"unidad": "usd"},
    "rango_hasta": {"unidad": "usd"},
    "vs_mercado": {"unidad": "ratio", "formato": "+0.0%"},
    "vs_politica_interna": {"unidad": "ratio", "formato": "+0.0%"},
    "brecha_grafia": {"unidad": "ratio", "formato": "+0.0%"},
    "incert_centro": {"unidad": "ratio", "formato": "0.0%"},
    "ancho_rel": {"unidad": "ratio"},
    "similitud": {"unidad": "coseno", "rango": [0, 1]},
    "empresas": {"unidad": "conteo"},
    "personas": {"unidad": "conteo"},
    # La masa salarial: dolares al mes, y su diferencia como ratio. Va aqui para que el
    # front no la formatee como porcentaje ni al reves — que es exactamente el fallo que
    # `UNIDADES` existe para evitar.
    "masa_real": {"unidad": "usd", "formato": "$#,##0"},
    "masa_a_mercado": {"unidad": "usd", "formato": "$#,##0"},
    "masa_vs_mercado": {"unidad": "ratio", "formato": "+0.0%"},
    "masa_personas": {"unidad": "conteo"},
    "antiguedad_anios": {"unidad": "anios", "formato": "0.0"},
    # La lista sale de donde se calcula, no se copia: el front la necesita COMPLETA
    # —una nomina joven no trae `mas de 20` y el filtro saldria sin esa opcion— y dos
    # copias son dos cosas que hay que acordarse de cambiar juntas.
    "antiguedad_tramo": {"unidad": "categoria", "valores": list(TRAMOS_ANTIGUEDAD)},
}


# LO QUE EL MODELO PRODUCE, para poder ordenarlo primero en la respuesta.
#
# LAS COLUMNAS DEL CLIENTE VIAJAN POR DEFECTO. Lo intente al reves —devolver solo lo del
# modelo, por minimizar el movimiento de dato personal— y estaba mal: el front necesita
# el NOMBRE para decir a quien hay que subirle el sueldo, la ANTIGUEDAD para explicar por
# que cobra lo que cobra, y el SEXO para el analisis de brecha. Sin eso el informe no se
# puede pintar y obliga al front a rehacer el cruce por su cuenta.
#
# Se puede recortar con `columnas_originales=false`, para el front que ya tiene el
# archivo y solo quiere los numeros.
#
# OJO: que `sexo` viaje al front NO contradice la regla de que `sexo` nunca es una
# variable del modelo. No entra en ningun calculo de la referencia; sale para que se
# pueda MEDIR la brecha, que es exactamente su uso previsto (D-011).
#
# `fila` es el indice 0-based de la nomina subida, para casar sin ambiguedad aunque haya
# dos personas con el mismo nombre y cargo.
SALIDA_MODELO = (
    # `cargo` es lo que escribio el cliente, fila por fila. `cargo_normalizado` es la
    # clave con la que se agrupo `por_puesto`: sin ella el front no puede unir las dos
    # tablas, porque la etiqueta de un puesto es UNA grafia y el detalle trae todas.
    "fila",
    "cargo",
    "cargo_normalizado",
    "estado",
    "antiguedad_anios",
    "antiguedad_tramo",
    "referencia",
    "sueldo_actual",
    "vs_mercado",
    "vs_politica_interna",
    "lectura_mercado",
    "lectura_interna",
    "posicion_mercado",
    "equivalente",
    "rango_desde",
    "rango_hasta",
    # D-067: la referencia del equivalente en espanol y la prima del ingles aplicada; D-068: el tipeo corregido
    "referencia_equivalente",
    "prima_idioma",
    "corregido",
    "p10",
    "p25",
    "p75",
    "p90",
    "confianza",
    "incert_centro",
    "ancho_rel",
    "base",
    "empresas",
    "personas",
    "similitud",
    "segmento",
    "rubro",
    # A QUE NIVEL se comparo ese cargo. Sin esto, `rubro: "G47"` obliga al front a
    # deducir del largo del codigo si eso es una division o una clase.
    "rubro_nivel",
)


def estado_de_fila(fila) -> str:
    """Estado EXPLICITO en vez de un NaN que el front tiene que adivinar.

    Un nulo puede significar cinco cosas distintas —no conocemos el cargo, el sueldo era
    ilegible, la celda no llega al suelo— y cada una lleva a un mensaje distinto en la
    interfaz. Devolverlas todas como `null` obliga al front a reinventar la logica.
    """
    if str(fila.get("base", "") or "") == "sin cargo":
        return "cargo_vacio"
    if str(fila.get("base", "") or "") == "no reconocido":
        return "cargo_no_reconocido"  # D-075: lo escrito no es un cargo; sin cifra
    lect = str(fila.get("lectura_mercado", "") or "")
    if lect == "sueldo ilegible":
        return "sueldo_ilegible"
    if lect == "sin referencia" or not np.isfinite(pd.to_numeric(fila.get("referencia"), errors="coerce")):
        return "sin_referencia"
    base = str(fila.get("base", "") or "")
    if base.startswith("rubro"):
        return "directa_rubro"
    if base == "datos directos":
        return "directa"
    if base == "por traduccion":
        return "traduccion"  # D-067: equivalente en espanol + prima del ingles
    return "analogia"


def representante(grafias, frec) -> str:
    """De varias grafias del MISMO puesto, la que se le enseña al usuario.

    LA REGLA ES LA FRECUENCIA DE SUS PALABRAS en toda la base, y sale de que una errata
    es rara POR DEFINICION. En el grupo de vendedor:

        VENDEDOR    462 apariciones      VENDEDRO      1
        VENDEDORA    40                  VENDEROA      1
        VEDEDOR       3                  VEENDEDOR     1

    Se puntua por la palabra MENOS frecuente del titulo, porque un dedazo en cualquier
    palabra lo delata: `TRABAJAJOR AGRICOLA` puntua por `TRABAJAJOR`, no por `AGRICOLA`.
    Desempata con menos signos raros y mas corto.

    LAS DOS HEURISTICAS ANTERIORES FALLARON, y conviene que quede escrito:

      - por PERSONAS: `personas` esta agregada POR GRUPO, asi que las trece grafias
        traen el mismo numero y el desempate lo resolvia el azar. Salia `VEENDEDOR`.
      - por MAS CORTA: `VEDEDOR` tiene 7 letras y `VENDEDOR` 8, asi que la errata ganaba.

    Es presentacion pura y no toca ningun calculo.
    """

    def clave(t):
        palabras = t.split()
        raro = min((frec.get(w, 0) for w in palabras), default=0)
        return (-raro, sum(1 for c in t if not (c.isalnum() or c == " ")), len(t), t)

    return min(grafias, key=clave)


def anidar_sector(filas: list) -> list:
    """`sector_*` plano -> un bloque `sector_mas_fino`, o `null`.

    POR QUE ANIDADO. Las tres columnas planas se leen como "datos del sector" y el front
    las pinta al lado de la referencia. Juntas en un bloque con nombre se leen como lo
    que son: la EXPLICACION de por que el veredicto uso el nivel que uso. Y `null` dice
    "no hay nada que explicar" mucho mejor que tres cadenas vacias.

    `umbral` viaja dentro a proposito, en vez de estar escrito en el front: si algun dia
    se cambia `MIN_EMPRESAS_VEREDICTO`, el texto del informe sigue siendo cierto solo.
    """
    out = []
    for f in filas:
        g = {k: v for k, v in f.items() if not k.startswith("sector_")}
        cod = f.get("sector_codigo") or ""
        g["sector_mas_fino"] = (
            {
                "codigo": cod,
                "nivel": f.get("sector_nivel") or "",
                "empresas": int(f.get("sector_empresas") or 0),
                "umbral": MIN_EMPRESAS_VEREDICTO,
            }
            if cod
            else None
        )
        out.append(g)
    return out
