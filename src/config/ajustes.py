"""Configuracion del servicio. Solo variables de entorno, como pide el estandar: sin
pydantic-settings. Los defaults son los de staging (`act-cicd-stage-prueba`)."""

import os
import warnings
from dataclasses import dataclass, field

# Salario basico unificado por ano. Cada cifra es un acuerdo ministerial: NO se
# interpola, NO se proyecta y NO se adivina. Es el divisor de `y = log(sueldo/SBU)`,
# asi que un valor equivocado desplaza TODAS las cifras de TODOS los informes de ese
# ano — y lo hace en silencio, porque el resultado sigue pareciendo razonable.
#
# 2026: USD 482, Acuerdo Ministerial MDT-2025-195 del 15/12/2025, publicado en el
# Registro Oficial Suplemento 187 del 18/12/2025, vigente desde el 1 de enero de 2026.
SBU = {
    2016: 366,
    2017: 375,
    2018: 386,
    2019: 394,
    2020: 400,
    2021: 400,
    2022: 425,
    2023: 450,
    2024: 460,
    2025: 470,
    2026: 482,
}


@dataclass(frozen=True)
class Ajustes:
    bq_project: str = field(default_factory=lambda: os.getenv("BQ_PROJECT", "act-cicd-stage-prueba"))
    vertex_embedding_model: str = field(
        default_factory=lambda: os.getenv("VERTEX_MODELO_EMBEDDINGS", "text-multilingual-embedding-002")
    )
    vertex_location: str = field(default_factory=lambda: os.getenv("VERTEX_LOCATION", "us-central1"))
    sbu: dict[int, int] = field(default_factory=lambda: dict(SBU))

    def get_sbu(self, anio: int, estricto: bool = False) -> int:
        """SBU del anio. Con `estricto`, falla en vez de adivinar.

        El servicio llama SIEMPRE con `estricto=True`: el SBU convierte el entregable a
        dolares, y adivinarlo corrompe cada cifra del informe. Es mejor parar y pedir el
        dato, que es publico y sale en un acuerdo ministerial.

        La tolerancia queda para leer la base, construida con filas de BigQuery que traen
        `anio_valoracion` nulo (llega aqui como 0).
        """
        if anio in self.sbu:
            return self.sbu[anio]
        if estricto:
            raise ValueError(
                f"No hay SBU para {anio}. La tabla llega hasta "
                f"{max(self.sbu)}. Anadelo en `config/ajustes.py` (`SBU`) antes de "
                f"emitir dolares de ese anio: usar el del anio anterior desplaza TODAS "
                f"las cifras del informe."
            )
        ultimo = max(self.sbu)
        if anio > ultimo:
            warnings.warn(
                f"SBU de {anio} desconocido: se usa el de {ultimo} ({self.sbu[ultimo]}). "
                f"Anade el valor real en `config/ajustes.py`.",
                stacklevel=2,
            )
        return self.sbu[ultimo]


def cargar_settings() -> Ajustes:
    return Ajustes()
