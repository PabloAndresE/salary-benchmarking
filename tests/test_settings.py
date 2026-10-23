import pytest

from src.config.ajustes import cargar_settings


def test_sbu_por_anio():
    s = cargar_settings()
    ultimo = max(s.sbu)
    assert s.get_sbu(2016) == 366
    assert s.get_sbu(2025) == 470
    # Los años futuros caen al último conocido PERO AVISANDO. Ya pasó una vez: la tabla
    # acababa en 2025 con el año en curso 2026, así que un dato de 2026 se normalizaba
    # con el SBU de 2025 en silencio. La tolerancia existe para las filas de BigQuery
    # con año nulo, no para tapar un acuerdo ministerial que nadie ha copiado.
    #
    # Se compara contra `max(s.sbu)` a propósito: escribir el número aquí obliga a tocar
    # el test cada enero, y un test que hay que "arreglar" al añadir un dato correcto
    # enseña a cambiarlo sin leerlo.
    with pytest.warns(UserWarning, match="SBU de 2099"):
        assert s.get_sbu(2099) == s.sbu[ultimo]
    assert s.get_sbu(0) == s.sbu[ultimo], "año nulo de BigQuery: sin aviso, es el previsto"


def test_el_sbu_estricto_se_niega_a_adivinar():
    # El producto convierte el entregable a dólares con el SBU: adivinarlo desplaza TODAS
    # las cifras del informe, así que ahí se para y se pide el dato.
    s = cargar_settings()
    with pytest.raises(ValueError, match="No hay SBU para 2099"):
        s.get_sbu(2099, estricto=True)
    assert s.get_sbu(2025, estricto=True) == 470


def test_el_sbu_de_2026_esta_y_es_el_del_acuerdo():
    # Acuerdo Ministerial MDT-2025-195, Registro Oficial Suplemento 187 del 18/12/2025.
    # Va con test porque es el divisor de `y = log(sueldo/SBU)`: un valor equivocado
    # desplaza TODAS las cifras del ano y lo hace en silencio.
    assert cargar_settings().get_sbu(2026, estricto=True) == 482


def test_los_defaults_son_los_de_staging_y_se_cambian_por_entorno(monkeypatch):
    monkeypatch.delenv("BQ_PROJECT", raising=False)
    assert cargar_settings().bq_project == "act-cicd-stage-prueba"
    monkeypatch.setenv("BQ_PROJECT", "otro")
    assert cargar_settings().bq_project == "otro"
