"""Que base esta cargada y que sabe hacer. Para el front: que interruptores encender."""

from src.infrastructure.motor import Motor
from src.shared.constants import ESQUEMA
from src.shared.contracts.responses import BaseResponseModel, exito
from src.shared.utils.conversion import claves_a_camel


def obtener_salud(*, motor: Motor) -> BaseResponseModel:
    m = motor
    # Las de la BASE mas las del SERVICIO. Estas ultimas son siempre ciertas en esta
    # version y estan para que el front las use de interruptor: mientras no lleguen, la
    # pantalla de correccion se esconde en vez de fingir que funciona.
    caps = dict(m.capacidades, mapeo=True, puestos=True)
    faltan = [n for n, ok in m.capacidades.items() if not ok]
    return exito(
        claves_a_camel(
            {
                "ok": True,
                "esquema": ESQUEMA,
                "puestos": len(m.base.celdas),
                "carga_s": m.carga_s,
                "anios_con_sbu": sorted(m.settings.sbu),
                # QUE SABE HACER ESTA BASE. Un front que reciba `ruc_a_industria: false`
                # sabe que no tiene sentido pedir el RUC; sin esto, lo pide y no pasa nada.
                "base": m.ruta_base,
                "capacidades": caps,
                "degradado": faltan or None,
                "aviso": (
                    None
                    if not faltan
                    else f"esta base no soporta {faltan}; el servicio responde igual pero "
                    f"con menos. Reconstruyela o apunta BASE_REFERENCIA a una nueva"
                ),
            }
        )
    )
