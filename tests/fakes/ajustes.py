"""Ajustes falsos para los tests: un SBU que conoce el ano ACTUAL —el servicio dolariza
con el actual por defecto, y si el doble solo supiera 2025 los tests probarian un camino
que produccion no usa— y nada que toque la red."""

import datetime as _dt

ANIO = _dt.date.today().year


def _sbu(anio, estricto=False):
    if anio not in (2025, ANIO):
        if estricto:
            raise ValueError(f"No hay SBU para {anio}")
        return 470.0
    return 470.0


class make_fake_ajustes:  # noqa: N801 (nombre de builder del estandar)
    sbu = {2025: 470, ANIO: 470}
    vertex_embedding_model = "x"
    bq_project = "p"
    vertex_location = "l"
    gcs_cache_embeddings = ""
    get_sbu = staticmethod(_sbu)
