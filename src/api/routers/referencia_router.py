from typing import Annotated, Any

from fastapi import APIRouter, Query

from src.api.requests.consulta_request import ReferenciaRequestModel
from src.infrastructure.motor import obtener_motor
from src.services import referencia_service
from src.shared.contracts.responses import BaseResponseModel
from src.shared.exceptions.http_request_exception import HTTPRequestException

router = APIRouter(prefix="/referencia", tags=["referencia"])


@router.get("", response_model=BaseResponseModel[dict[str, Any]])
def obtener_referencia(consulta: Annotated[ReferenciaRequestModel, Query()]):
    """Un titulo suelto, para explorar. NO es el producto: no lleva ancla de empresa."""
    resp = referencia_service.obtener_referencia(
        motor=obtener_motor(),
        cargo=consulta.cargo,
        anio=consulta.anio,
        segmento=consulta.segmento,
        rubro=consulta.rubro,
        ruc=consulta.ruc,
    )
    if resp.status != 0:
        raise HTTPRequestException(response_model=resp)
    return resp
