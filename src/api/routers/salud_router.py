from typing import Any

from fastapi import APIRouter

from src.infrastructure.motor import obtener_motor
from src.services import salud_service
from src.shared.contracts.responses import BaseResponseModel, exito
from src.shared.exceptions.http_request_exception import HTTPRequestException

router = APIRouter(tags=["salud"])


@router.get("/health", response_model=BaseResponseModel[dict[str, Any]])
def health():
    """Vivo, sin dependencias: no toca la base ni la red. Para la sonda de Cloud Run."""
    return exito({"ok": True})


@router.get("/salud", response_model=BaseResponseModel[dict[str, Any]])
def salud():
    """Que base esta cargada y que sabe hacer: los interruptores del front."""
    resp = salud_service.obtener_salud(motor=obtener_motor())
    if resp.status != 0:
        raise HTTPRequestException(response_model=resp)
    return resp
