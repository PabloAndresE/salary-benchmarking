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
