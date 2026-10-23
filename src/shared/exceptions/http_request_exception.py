from src.shared.contracts.responses import BaseResponseModel


class HTTPRequestException(Exception):
    """La lanza el ROUTER cuando un service devuelve un sobre con `status != 0`; el handler
    de `main.py` la convierte en la respuesta con ese mismo codigo HTTP."""

    def __init__(self, response_model: BaseResponseModel):
        self.response_model = response_model
        super().__init__(response_model.message)
