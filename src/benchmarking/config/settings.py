import warnings

from pydantic_settings import BaseSettings, SettingsConfigDict

_SBU = {2016:366,2017:375,2018:386,2019:394,2020:400,
        2021:400,2022:425,2023:450,2024:460,2025:470}

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIPELINE_", extra="ignore")
    salt: str                                    # PIPELINE_SALT (obligatorio)
    min_sbu: float = 0.5
    edad_min: int = 18
    edad_max: int = 80
    bq_project: str = "act-cicd-stage-prueba"
    bq_dataset: str = "benchmarking_tesis"
    actuafast_base_url: str = "https://actuafast-api-611856784485.us-east1.run.app"
    sbu: dict[int, int] = _SBU
    # Medido contra la API real (20 estudios de 2025 por nivel, cliente con reintentos):
    #   hilos  ok  perdidos  peticiones  estudios/s
    #     2    20      0         20         0,54
    #     4    19      0         20         0,80   <- óptimo
    #     6    17      3         41         0,28
    #     8    13      7         67         0,16
    # A partir de 6 el servidor corta conexiones, los reintentos se disparan y el
    # rendimiento cae. El antiguo valor 8 perdía ~80% de las plantillas y además era
    # 5x más lento. No subir sin volver a medir.
    descargas_concurrentes: int = 4              # PIPELINE_DESCARGAS_CONCURRENTES
    # Bucket del cache de plantillas crudas (PIPELINE_GCS_BUCKET_PLANTILLAS).
    # Vacio = sin cache. Con cache, cambiar que columnas se extraen de la plantilla
    # cuesta minutos en vez de ~10 horas de re-descarga.
    gcs_bucket_plantillas: str = ""

    # La revision del modelo entra en la clave de cache: si Google la cambia sin avisar,
    # los resultados dejan de ser reproducibles y hay que enterarse (spec de clustering 11).
    # LIMITE MEDIDO de este modelo: codifica el area y NO la jerarquia — pares que solo se
    # diferencian en el rango puntuan 0,857 frente a 0,764 los que se diferencian en el
    # area. El nivel viene de otra senal, no de aqui (D-012).
    vertex_embedding_model: str = "text-multilingual-embedding-002"
    vertex_location: str = "us-central1"
    gcs_cache_embeddings: str = ""      # gs://bucket/ruta.npz, o vacio para no cachear

    def get_sbu(self, anio: int, estricto: bool = False) -> int:
        """SBU del anio. Con `estricto`, falla en vez de adivinar.

        La tolerancia existe para el camino de DATOS: en BigQuery hay filas con
        `anio_valoracion` nulo, que llegan aqui como 0, y tirar por eso seria peor.

        Pero envejece mal y ya paso: la tabla acaba en 2025 y el ano en curso es 2026, asi
        que un dato de 2026 se normalizaba con el SBU de 2025 SIN AVISAR. El objetivo es
        `log(sueldo/SBU)`, o sea que un SBU equivocado desplaza todo de forma sistematica,
        y al volver a dolares lo desplaza otra vez.

        Por eso el camino de PRODUCTO —donde el SBU convierte el entregable a dolares—
        llama con `estricto=True`: ahi adivinar corrompe cada cifra del informe y es mejor
        parar y pedir el dato, que es publico y sale en un acuerdo ministerial.
        """
        if anio in self.sbu:
            return self.sbu[anio]
        if estricto:
            raise ValueError(
                f"No hay SBU para {anio}. La tabla llega hasta "
                f"{max(self.sbu)}. Anadelo en `config/settings.py` (`_SBU`) antes de "
                f"emitir dolares de ese anio: usar el del anio anterior desplaza TODAS "
                f"las cifras del informe.")
        ultimo = max(self.sbu)
        if anio > ultimo:
            warnings.warn(
                f"SBU de {anio} desconocido: se usa el de {ultimo} ({self.sbu[ultimo]}). "
                f"Anade el valor real en `config/settings.py`.", stacklevel=2)
        return self.sbu[ultimo]

def cargar_settings() -> Settings:
    return Settings()
