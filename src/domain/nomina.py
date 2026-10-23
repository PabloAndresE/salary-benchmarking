"""Leer la nomina que sube el cliente, en memoria, y las correcciones del usuario.

NO SE ESCRIBE A DISCO: la nomina lleva nombres y sueldos. Los errores salen como
`ValueError` con el motivo, y el service los convierte en un 400."""

import io
import json

import pandas as pd

from src.domain.columnas_nomina import _POSIBLES


def columna(df, pedida: str | None) -> str | None:
    """Casa el nombre de columna que pide el cliente con el real, tolerando espacios.

    DOS COSAS QUE FALLABAN. `_opt` recorta los extremos, y hay columnas que TERMINAN en
    espacio —la plantilla actuarial trae `'Ultimo sueldo/pension mensual '`—, asi que el
    nombre recortado dejaba de coincidir. Y `_buscar_sueldo` devolvia None sin decir
    nada: el cliente pedia una columna explicitamente, se le ignoraba, y recibia un
    informe sin comparacion y sin saber por que.

    Se compara normalizando los dos lados. Si aun asi no aparece, quien llama levanta un
    400 con la lista: fallar en voz alta.
    """
    if not pedida:
        return None

    def norm(x):
        return " ".join(str(x).split()).casefold()

    objetivo = norm(pedida)
    for c in df.columns:
        if norm(c) == objetivo:
            return c
    return None


def leer_nomina_bytes(contenido: bytes, nombre: str, col_cargo: str | None = None):
    """Como `leer_nomina` pero desde memoria y sin `SystemExit`.

    El CLI aborta el proceso ante una nomina mala, que es lo correcto en una terminal y
    catastrofico en un servidor: mataria al worker. Aqui se levanta `ValueError` y la capa
    HTTP lo convierte en un 400 con el motivo.

    Y NO SE ESCRIBE A DISCO: la nomina lleva nombres y sueldos.
    """
    buf = io.BytesIO(contenido)
    try:
        df = pd.read_csv(buf, dtype=str) if nombre.lower().endswith(".csv") else pd.read_excel(buf, dtype=str)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"no se pudo leer el archivo: {e}") from e
    if df.empty:
        raise ValueError("el archivo no tiene filas")
    if col_cargo:
        real = columna(df, col_cargo)
        if real is None:
            raise ValueError(f"la columna '{col_cargo}' no esta en el archivo. " f"Columnas: {list(df.columns)}")
        return df, real
    normal = {c.strip().lower().replace(" ", "_"): c for c in df.columns}
    for cand in _POSIBLES:
        if cand in normal:
            return df, normal[cand]
    raise ValueError(
        f"no encuentro la columna de cargo. Columnas: {list(df.columns)}. "
        f"Indicala con el parametro `columna_cargo`."
    )


def leer_mapeo(crudo: str | None, n_filas: int) -> dict[int, str]:
    """Las correcciones del usuario: `{"7": "ODONTOLOGA"}`. Vacio si no manda nada.

    LA CLAVE ES LA FILA, NO EL TEXTO, y ahi esta todo el diseno. El mismo titulo aparece
    en muchas filas y el usuario corrige PERSONAS, no cadenas: si tres dicen `ASISTENTE
    DE LIMPIEZA` y una es en realidad supervisora, un mapeo texto->texto moveria a las
    tres. `fila` es el indice 0-based del archivo subido, el mismo que ya viaja en el
    detalle.

    FALLA EN VOZ ALTA. Una fila fuera de rango o un JSON roto dan 400 con el motivo: si
    se ignorasen, el cliente corregiria cuatro cargos, leeria "cambios aplicados" y
    estaria viendo exactamente los mismos numeros.
    """
    if not crudo or not str(crudo).strip():
        return {}
    try:
        d = json.loads(crudo)
    except json.JSONDecodeError as e:
        raise ValueError(f"`mapeo` no es JSON valido: {e}") from e
    if not isinstance(d, dict):
        raise ValueError('`mapeo` tiene que ser un objeto {"fila": "cargo"}, ' f"y llego {type(d).__name__}")
    out, malas = {}, []
    for k, v in d.items():
        try:
            i = int(k)
        except TypeError, ValueError:
            malas.append(f"clave {k!r} no es un numero de fila")
            continue
        if not 0 <= i < n_filas:
            malas.append(f"fila {i} fuera de rango (el archivo tiene {n_filas})")
        elif not isinstance(v, str) or not v.strip():
            malas.append(f"fila {i}: el cargo corregido esta vacio")
        else:
            out[i] = v.strip()
    if malas:
        raise ValueError("`mapeo` invalido: " + "; ".join(malas[:5]))
    return out
