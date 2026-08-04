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
    descargas_concurrentes: int = 8              # PIPELINE_DESCARGAS_CONCURRENTES

    def get_sbu(self, anio: int) -> int:
        return self.sbu.get(anio, max(self.sbu.values()))

def cargar_settings() -> Settings:
    return Settings()
