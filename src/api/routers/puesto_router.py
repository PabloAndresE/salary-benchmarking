from typing import Annotated, Any

from fastapi import APIRouter, Query

from src.api.requests.consulta_request import PuestosRequestModel
from src.infrastructure.motor import obtener_motor
from src.services import puesto_service
from src.shared.contracts.responses import BaseResponseModel
from src.shared.exceptions.http_request_exception import HTTPRequestException

router = APIRouter(prefix="/puestos", tags=["puestos"])


@router.get("", response_model=BaseResponseModel[list[dict[str, Any]]])
def buscar_puestos(consulta: Annotated[PuestosRequestModel, Query()]):
    """Que puestos de la base se parecen a lo escrito: el buscador de correcciones."""
    resp = puesto_service.buscar_puestos(
        motor=obtener_motor(), q=consulta.q, limite=consulta.limite, p_min=consulta.p_min
    )
    if resp.status != 0:
        raise HTTPRequestException(response_model=resp)
    return resp
