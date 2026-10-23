"""Una linea de log por peticion, con un `request_id` de 8 caracteres.

Se loguea el PATRON de la ruta (`/informes`), nunca la URL completa: la query de
`/referencia` lleva el RUC del cliente y no puede acabar en un log."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:8]
        request.state.request_id = request_id
        t0 = time.perf_counter()
        respuesta = await call_next(request)
        ruta = request.scope.get("route")
        patron = getattr(ruta, "path", "sin_ruta")
        logger.info(
            "%s %s -> %s %.1fms",
            request.method,
            patron,
            respuesta.status_code,
            (time.perf_counter() - t0) * 1000,
            extra={"request_id": request_id},
        )
        respuesta.headers["X-Request-Id"] = request_id
        return respuesta
