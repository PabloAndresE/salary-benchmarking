"""El sobre de TODA respuesta del servicio: `message`, `status` y `content`.

`status = 0` es exito; cualquier otro valor es el codigo HTTP con que sale la respuesta
(el contrato de actuafast: el codigo HTTP coincide con el `status` del sobre).
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class BaseResponseModel(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    message: str = "ok"
    status: int = 0
    content: T | None = None


def exito(content=None, message: str = "ok") -> BaseResponseModel:
    return BaseResponseModel(message=message, status=0, content=content)


def error(status: int, message: str, content=None) -> BaseResponseModel:
    return BaseResponseModel(message=message, status=status, content=content)
