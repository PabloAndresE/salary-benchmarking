"""Caché del XLSX crudo de las plantillas.

No es una optimización de rendimiento: es lo que vuelve **reversible** la decisión de
qué columnas se extraen de la plantilla. Sin caché, descubrir que hacía falta una
columna más cuesta ~10 horas de re-descarga de los ~12.000 estudios con plantilla —
y eso empuja a querer acertar de una vez, que es justo lo que no se puede hacer
investigando. Con caché, cuesta minutos.

Se cachea también la **ausencia** de plantilla (404), que es el caso mayoritario en los
años 2023 y anteriores: sin eso, cada reproceso volvería a preguntarle a la API 36.000
veces para recibir 36.000 veces la misma respuesta.

Los rechazos deterministas (4xx distinto de 404) NO se cachean: son ~47 en toda la
corrida, así que no compensa la complejidad de distinguirlos al leer.
"""

AUSENTE = b""      # centinela: el estudio existe pero no tiene plantilla


class CacheMemoria:
    """Caché en memoria. Para tests y para corridas de una sola pasada."""

    def __init__(self):
        self._d = {}

    @staticmethod
    def _k(numero_proceso, id_version):
        return (str(numero_proceso), str(id_version))

    def leer(self, numero_proceso, id_version):
        """Devuelve los bytes, `AUSENTE` si se sabe que no hay plantilla, o None si no se sabe."""
        return self._d.get(self._k(numero_proceso, id_version))

    def guardar(self, numero_proceso, id_version, contenido):
        self._d[self._k(numero_proceso, id_version)] = contenido


class CacheGCS:
    """Caché en Cloud Storage, un objeto por (estudio, versión).

    El objeto vacío significa "este estudio no tiene plantilla": distinguir ausencia de
    desconocimiento es la mitad del valor del caché.
    """

    _TIPO = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(self, bucket, prefijo="plantillas", cliente=None):
        from google.cloud import storage
        self._bucket = (cliente or storage.Client()).bucket(bucket)
        self._prefijo = prefijo.strip("/")

    def _ruta(self, numero_proceso, id_version):
        return f"{self._prefijo}/{numero_proceso}/{id_version}.xlsx"

    def leer(self, numero_proceso, id_version):
        from google.api_core.exceptions import NotFound
        blob = self._bucket.blob(self._ruta(numero_proceso, id_version))
        try:
            return blob.download_as_bytes()      # una sola llamada; exists() sería otra
        except NotFound:
            return None

    def guardar(self, numero_proceso, id_version, contenido):
        self._bucket.blob(self._ruta(numero_proceso, id_version)).upload_from_string(
            contenido, content_type=self._TIPO)
