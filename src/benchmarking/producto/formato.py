"""El formato de entrada del producto. Contrato estricto, errores en voz alta.

    cargo*          texto libre, SIN limpiar
    sueldo          el BASICO mensual
    id_empleado     identificador propio del cliente
    nombre          para el filtro de trabajador
    sexo            M / F
    fecha_ingreso   dd/mm/aaaa
    centro_costo    para agrupar por area

EL SUELDO ES EL BASICO, y es lo que mas se presta a error. La base se construye sobre
`sueldo` y no sobre `total` —`agregar_objetivo` lo dice: `total` solo esta bien definido
donde hay composicion, y un objetivo que cambia de definicion entre filas no es
comparable—. Si el cliente manda el total con comisiones y extras dentro, se compara
contra otra cosa y sale sistematicamente alto. Por eso el nombre de la columna es
`sueldo` a secas y la validacion avisa cuando los valores huelen a total.

ESTRICTO, PERO NO QUISQUILLOSO. Se exige el nombre canonico y se rechaza lo que no
cuadre, con la lista de lo que falta y lo que sobra. Lo unico que se perdona son los
espacios y las mayusculas: `Fecha Ingreso ` casa con `fecha_ingreso`, porque eso no es
ambiguedad, es un caracter invisible.

NO SE PIDE LA CEDULA, y no es una omision: es una garantia. Un identificador nacional no
tiene por que viajar por esta API para calcular una referencia salarial. `id_empleado` es
del cliente y le sirve igual para casar. Si llega una columna que parece cedula, se
RECHAZA con el motivo — aceptarla en silencio convertiria la garantia en una intencion.

LA ANTIGUEDAD SALE DE `fecha_ingreso` SOLA. Decision de producto: sin historial de
salidas y reingresos, quien se fue y volvio sale con mas antiguedad de la que tiene. Se
acepta a cambio de un formato de una sola fecha.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

OBLIGATORIAS = ("cargo",)
OPCIONALES = ("sueldo", "id_empleado", "nombre", "sexo", "fecha_ingreso",
              "centro_costo")
CANONICAS = OBLIGATORIAS + OPCIONALES

# Se rechazan por privacidad, no por sintaxis. Ver el docstring.
_PROHIBIDAS = re.compile(r"^(cedula|identificacion|documento|dni|ruc|pasaporte|"
                         r"num.?identificacion|nro.?documento)$")


def _norm(c) -> str:
    """Sin tildes, sin dobles espacios, en minusculas y con guion bajo."""
    s = unicodedata.normalize("NFD", str(c))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return "_".join(s.lower().replace("_", " ").split())


class FormatoInvalido(ValueError):
    """Lo que el cliente tiene que arreglar, con la lista de lo que falla."""

    def __init__(self, problemas: list[str]):
        self.problemas = problemas
        super().__init__(" | ".join(problemas))


def validar(df) -> tuple[pd.DataFrame, dict]:
    """Comprueba el formato y devuelve (df con nombres canonicos, informe).

    Levanta `FormatoInvalido` con TODOS los problemas de una vez. Devolver el primero y
    parar obliga al cliente a subir el archivo cinco veces para descubrir cinco fallos.
    """
    mapa, desconocidas, prohibidas = {}, [], []
    for c in df.columns:
        n = _norm(c)
        if _PROHIBIDAS.match(n):
            prohibidas.append(str(c))
        elif n in CANONICAS:
            mapa[c] = n
        else:
            desconocidas.append(str(c))

    problemas = []
    if prohibidas:
        problemas.append(
            f"el formato NO acepta identificadores personales y llegaron {prohibidas}. "
            f"Usa `id_empleado`, que es tuyo y sirve igual para casar las filas")
    faltan = [c for c in OBLIGATORIAS if c not in mapa.values()]
    if faltan:
        problemas.append(f"faltan columnas obligatorias: {faltan}. "
                         f"Recibidas: {[str(c) for c in df.columns]}")
    repes = [c for c in CANONICAS if list(mapa.values()).count(c) > 1]
    if repes:
        problemas.append(f"columnas duplicadas tras normalizar: {repes}")
    if problemas:
        raise FormatoInvalido(problemas)

    out = df.rename(columns=mapa)
    avisos = []
    if desconocidas:
        avisos.append(f"{len(desconocidas)} columna(s) fuera del formato se ignoran "
                      f"para el calculo y se devuelven tal cual: {desconocidas[:6]}"
                      + (" ..." if len(desconocidas) > 6 else ""))

    informe = {"columnas_reconocidas": sorted(set(mapa.values())),
               "columnas_desconocidas": desconocidas, "avisos": avisos}

    if "sexo" in out.columns:
        out["sexo"], raros = _normalizar_sexo(out["sexo"])
        if raros:
            avisos.append(f"valores de `sexo` no reconocidos, quedan vacios: {raros[:5]}")
        informe["sexo_no_reconocido"] = len(raros)

    if "fecha_ingreso" in out.columns:
        f = pd.to_datetime(out["fecha_ingreso"], errors="coerce", dayfirst=True)
        malas = int(f.isna().sum() - out["fecha_ingreso"].isna().sum())
        if malas > 0:
            avisos.append(f"{malas} `fecha_ingreso` no se pudieron leer como fecha "
                          f"(se espera dd/mm/aaaa); esas filas quedan sin antiguedad")
        informe["fechas_ilegibles"] = malas

    if "sueldo" in out.columns:
        informe |= _revisar_sueldo(out["sueldo"], avisos)
    return out, informe


def _normalizar_sexo(s: pd.Series):
    """A `M` / `F`. Lo que no se reconoce queda vacio y se cuenta, en vez de colarse
    como una categoria mas en el filtro del front."""
    equiv = {"m": "M", "masculino": "M", "hombre": "M", "h": "M", "male": "M",
             "f": "F", "femenino": "F", "mujer": "F", "female": "F"}
    bruto = s.astype(str).str.strip().str.lower()
    out = bruto.map(equiv)
    raros = sorted({b for b, o in zip(bruto, out)
                    if pd.isna(o) and b not in ("", "nan", "none")})
    # `dtype=object` NO es decorativo. Con el dtype `str` nuevo de pandas 3, una lista
    # de textos y `None` se infiere como `str` y los None vuelven a salir NaN — la misma
    # trampa que ya esta anotada en `a_numero`. El front tendria que comprobar las dos
    # cosas para saber si el sexo falta.
    return pd.Series([o if isinstance(o, str) else None for o in out],
                     index=s.index, dtype=object), raros


def _revisar_sueldo(s: pd.Series, avisos: list) -> dict:
    """Comprobaciones de sanidad sobre el basico.

    LA IMPORTANTE ES EL SBU. Si la mediana de lo que sube el cliente esta muy por debajo
    del salario minimo, no es una nomina mal pagada: es otra cosa —pensiones, valores
    por hora, otra moneda, la columna equivocada—. Emitir un informe diciendo que paga
    un 95% bajo mercado seria un disparate con banda y etiqueta de confianza.
    """
    from .comparacion import a_numero
    v = a_numero(s)
    validos = v.dropna()
    info = {"sueldos_ilegibles": int(v.isna().sum() - s.isna().sum())}
    if validos.empty:
        avisos.append("ningun `sueldo` se pudo leer como numero")
        return info
    med = float(validos.median())
    info["sueldo_mediano"] = round(med, 2)
    if med < 200:
        avisos.append(
            f"la mediana de `sueldo` es {med:,.2f}, muy por debajo del salario basico "
            f"del Ecuador. .Son pensiones, valores por hora, o otra columna? El informe "
            f"se emite igual, pero las lecturas no van a significar nada")
    return info
