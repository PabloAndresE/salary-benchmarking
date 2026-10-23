from typing import Annotated, Any

from fastapi import APIRouter, Form

from src.api.requests.informe_request import CrearInformeRequestModel
from src.infrastructure.motor import obtener_motor
from src.services import informe_service
from src.shared.contracts.responses import BaseResponseModel
from src.shared.exceptions.http_request_exception import HTTPRequestException

router = APIRouter(prefix="/informes", tags=["informes"])


# `def`, no `async def`: el informe bloquea 20-35 s y en el unico worker congelaria el
# event loop. Como `def` corre en el threadpool.
@router.post("", response_model=BaseResponseModel[dict[str, Any]], response_model_exclude_none=False)
def crear_informe(solicitud: Annotated[CrearInformeRequestModel, Form()]):
    """Sube una nomina y devuelve el informe completo en la misma respuesta."""
    resp = informe_service.crear_informe(
        motor=obtener_motor(),
        contenido=solicitud.archivo.file.read(),
        nombre_archivo=solicitud.archivo.filename or "n.xlsx",
        anio=solicitud.anio,
        mapeo=solicitud.mapeo,
        ruc=solicitud.ruc,
        segmento=solicitud.segmento,
        rubro=solicitud.rubro,
        formato_libre=solicitud.formato_libre,
        columna_cargo=solicitud.columna_cargo,
        columna_sueldo=solicitud.columna_sueldo,
        columnas_originales=solicitud.columnas_originales,
        columnas_extra=solicitud.columnas_extra,
        incluir_excel=solicitud.incluir_excel,
    )
    if resp.status != 0:
        raise HTTPRequestException(response_model=resp)
    return resp
