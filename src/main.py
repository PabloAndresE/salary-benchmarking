"""Salary Benchmarking: referencias salariales de mercado.

    uv run uvicorn src.main:app --port 8080 --workers 1

Una nomina entra (`POST /informes`) y el informe sale en la misma respuesta. `/referencia`
y `/puestos` sirven para explorar y para el buscador de correcciones. Toda respuesta va
en el sobre `BaseResponseModel` (`message`, `status`, `content`): `status = 0` es exito, y
si no, es el codigo HTTP con que sale.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.routers import informe_router, puesto_router, referencia_router, salud_router
from src.config.logging_config import setup_logging
from src.infrastructure.artefactos import preparar_artefactos
from src.infrastructure.motor import iniciar_motor, liberar_motor
from src.middleware.logger import RequestLoggerMiddleware
from src.services import registro_nomina_service
from src.shared.constants import ESQUEMA
from src.shared.contracts.responses import error
from src.shared.exceptions.http_request_exception import HTTPRequestException

logger = logging.getLogger(__name__)


@asynccontextmanager
async def ciclo(app: FastAPI):
    setup_logging()
    preparar_artefactos()  # con ARTEFACTOS_GCS: base y modelos desde el bucket
    iniciar_motor()
    if registro_nomina_service.activo():
        logger.info("las nominas se guardan en %s", registro_nomina_service.dataset_destino())
    else:
        logger.warning("las nominas NO se guardan (GUARDAR_NOMINAS=no)")
    yield
    liberar_motor()


app = FastAPI(title="Salary Benchmarking", version=os.getenv("VERSION_API", ESQUEMA), lifespan=ciclo)

# CORS DESDE EL ENTORNO. NO se abre a `*`: el servicio devuelve referencias salariales de
# 6.722 empresas, y `*` mas un despliegue publico es un volcado de datos de compensacion.
# Por defecto, los puertos tipicos de desarrollo local; en Cloud Run, `CORS_ORIGINS`.
_ORIGENES = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://localhost:4200,"
        "http://localhost:8080,http://127.0.0.1:3000,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware, allow_origins=_ORIGENES, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)
app.add_middleware(RequestLoggerMiddleware)


@app.exception_handler(HTTPRequestException)
async def _sobre_con_error(request: Request, exc: HTTPRequestException):
    return JSONResponse(status_code=exc.response_model.status, content=exc.response_model.model_dump())


@app.exception_handler(RequestValidationError)
async def _validacion(request: Request, exc: RequestValidationError):
    # Solo `loc`, `msg` y `type`: ni `input` (puede traer datos del cliente) ni `ctx`
    # (con un ValueError dentro no se serializa y la respuesta saldria como 500).
    errores = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return JSONResponse(status_code=422, content=error(422, "peticion invalida", errores).model_dump())


@app.exception_handler(StarletteHTTPException)
async def _http(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content=error(exc.status_code, str(exc.detail)).model_dump())


@app.exception_handler(Exception)
async def _inesperado(request: Request, exc: Exception):
    logger.error("error no controlado en %s", request.url.path.split("?")[0], exc_info=exc)
    return JSONResponse(status_code=500, content=error(500, "error interno").model_dump())


for _r in (salud_router.router, informe_router.router, referencia_router.router, puesto_router.router):
    app.include_router(_r)
