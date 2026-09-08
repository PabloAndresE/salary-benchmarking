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
    # Los años futuros caen al último conocido PERO AVISANDO: la tabla acaba en 2025 y
    # el año en curso es 2026, así que un dato de 2026 se normalizaba con el SBU de 2025
    # en silencio. La tolerancia existe para las filas de BigQuery con año nulo.
    with pytest.warns(UserWarning, match="SBU de 2099"):
        assert s.get_sbu(2099) == 470
    assert s.get_sbu(0) == 470, "año nulo de BigQuery: sin aviso, es el caso previsto"


def test_el_sbu_estricto_se_niega_a_adivinar(monkeypatch):
    # El producto convierte el entregable a dólares con el SBU: adivinarlo desplaza TODAS
    # las cifras del informe, así que ahí se para y se pide el dato.
    monkeypatch.setenv("PIPELINE_SALT", "x")
    s = cargar_settings()
    with pytest.raises(ValueError, match="No hay SBU para 2099"):
        s.get_sbu(2099, estricto=True)
    assert s.get_sbu(2025, estricto=True) == 470

def test_descargas_concurrentes_default_y_override(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    monkeypatch.delenv("PIPELINE_DESCARGAS_CONCURRENTES", raising=False)
    from benchmarking.config.settings import cargar_settings
    # 4 es el óptimo medido contra la API real: por encima de 5 el servidor corta
    # conexiones, los reintentos se disparan y el rendimiento cae (ver settings.py).
    assert cargar_settings().descargas_concurrentes == 4
    monkeypatch.setenv("PIPELINE_DESCARGAS_CONCURRENTES","15")
    assert cargar_settings().descargas_concurrentes == 15
