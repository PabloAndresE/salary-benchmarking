import pytest
from benchmarking.config.settings import cargar_settings

def test_el_salt_se_exige_EN_LA_FRONTERA_y_no_al_arrancar(monkeypatch):
    # Antes `cargar_settings()` moria sin PIPELINE_SALT, para cualquier subcomando. Eso
    # FABRICABA el mal habito que la regla del salt existe para evitar: para sacar un
    # informe —que no anonimiza nada— habia que inventarse un salt, y ese valor basura
    # quedaba vivo en la shell para la siguiente ingesta, que escribiria `id_hash`
    # incomparables con todo lo ya escrito y en silencio.
    monkeypatch.delenv("PIPELINE_SALT", raising=False)
    s = cargar_settings()                    # el informe puede correr
    assert s.salt is None
    assert s.get_sbu(2025) == 470
    # ...y la frontera se planta, con el motivo escrito.
    with pytest.raises(ValueError, match="PIPELINE_SALT"):
        s.salt_obligatorio()


def test_con_salt_la_frontera_lo_devuelve(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT", "x")
    assert cargar_settings().salt_obligatorio() == "x"

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
