"""Conversiones de valores y de nombres para la respuesta."""

import numpy as np
import pandas as pd


def a_python(v):
    """De tipos de numpy/pandas a tipos de Python, y de NaN a None.

    FastAPI no serializa `numpy.int64` y falla con un 500 opaco. Se normaliza en un solo
    sitio para que no dependa de la suerte.
    """
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if not np.isfinite(f) else f
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, np.ndarray):
        return [a_python(x) for x in v.tolist()]
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def a_camel(nombre: str) -> str:
    """`rango_desde` -> `rangoDesde`. Las claves del contrato van en camelCase (estandar)."""
    cabeza, *resto = str(nombre).split("_")
    return cabeza + "".join(p[:1].upper() + p[1:] for p in resto)


def claves_a_camel(obj, conservar: frozenset[str] = frozenset(), claves_dato: frozenset[str] = frozenset()):
    """Pasa a camelCase las claves de dicts anidados.

    - `conservar`: claves que viajan como llegaron. Son las columnas propias del cliente:
      son sus datos, no el contrato del servicio.
    - `claves_dato`: dicts cuyas claves HIJAS son valores, no nombres de campo
      (`repartoEstado: {"directa_rubro": 3}`): esas no se tocan.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nueva = k if k in conservar else a_camel(k)
            if k in claves_dato and isinstance(v, dict):
                out[nueva] = v
            else:
                out[nueva] = claves_a_camel(v, conservar, claves_dato)
        return out
    if isinstance(obj, list):
        return [claves_a_camel(x, conservar, claves_dato) for x in obj]
    return obj


def opcional(v: str | None) -> str | None:
    """Un campo vacio es AUSENCIA, no la cadena vacia. Y `"string"` tambien: es el
    marcador que Swagger deja en los campos opcionales, y mandarlo tal cual daba un 400
    confuso —«segmento invalido: string»— en la primera prueba desde `/docs`."""
    if v is None:
        return None
    t = str(v).strip()
    return None if t == "" or t.lower() == "string" else t
