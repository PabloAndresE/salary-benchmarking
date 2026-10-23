from pydantic import BaseModel, ConfigDict, Field

from src.services.puesto_service import P_MIN_SUGERENCIA


class ReferenciaRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cargo: str = Field(description="El titulo del cargo, tal como lo escribe el cliente.")
    anio: int | None = Field(None, description="Ano del SBU. Por defecto el actual.")
    segmento: str | None = Field(None, description="MICROEMPRESA, PEQUENA, MEDIANA o GRANDE.")
    rubro: str | None = Field(None, description="CIIU de primer nivel (una letra).")
    ruc: str | None = Field(None, description="RUC del cliente: resuelve su tamano.")


class PuestosRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str = Field(description="Lo que escribio el usuario.")
    limite: int = Field(12, description="Cuantas sugerencias, de 1 a 50.")
    p_min: float = Field(P_MIN_SUGERENCIA, alias="pMin", description="Probabilidad minima del juez para sugerir.")
