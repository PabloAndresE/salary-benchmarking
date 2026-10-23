"""Logs en JSON para Cloud Logging por defecto; `LOG_FORMAT=local` para leerlos en una
terminal. `LOG_LEVEL` fija el nivel. NUNCA se loguean datos personales: ni nombres, ni
cedulas, ni RUC, ni sueldos. Solo identificadores tecnicos."""

import json
import logging
import os
import sys


class _FormatoJson(logging.Formatter):
    # Cloud Logging lee `severity` y `message` del JSON de stdout
    def format(self, registro: logging.LogRecord) -> str:
        datos = {
            "severity": registro.levelname,
            "message": registro.getMessage(),
            "logger": registro.name,
        }
        request_id = getattr(registro, "request_id", None)
        if request_id:
            datos["request_id"] = request_id
        if registro.exc_info:
            datos["exception"] = self.formatException(registro.exc_info)
        return json.dumps(datos, ensure_ascii=False)


def setup_logging() -> None:
    nivel = os.getenv("LOG_LEVEL", "INFO").upper()
    manejador = logging.StreamHandler(sys.stdout)
    if os.getenv("LOG_FORMAT", "json").lower() == "local":
        manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    else:
        manejador.setFormatter(_FormatoJson())
    raiz = logging.getLogger()
    raiz.handlers[:] = [manejador]
    raiz.setLevel(nivel)
