import pytest
from benchmarking.config.settings import cargar_settings

def test_salt_requerido(monkeypatch):
    monkeypatch.delenv("PIPELINE_SALT", raising=False)
    with pytest.raises(Exception):
        cargar_settings()

def test_sbu_por_anio(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT", "x")
    s = cargar_settings()
    assert s.get_sbu(2016) == 366
    assert s.get_sbu(2025) == 470
    assert s.get_sbu(2099) == 470  # años futuros usan el último conocido

def test_descargas_concurrentes_default_y_override(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    monkeypatch.delenv("PIPELINE_DESCARGAS_CONCURRENTES", raising=False)
    from benchmarking.config.settings import cargar_settings
    # 4 es el óptimo medido contra la API real: por encima de 5 el servidor corta
    # conexiones, los reintentos se disparan y el rendimiento cae (ver settings.py).
    assert cargar_settings().descargas_concurrentes == 4
    monkeypatch.setenv("PIPELINE_DESCARGAS_CONCURRENTES","15")
    assert cargar_settings().descargas_concurrentes == 15
