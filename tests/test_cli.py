import sys
from unittest.mock import MagicMock
import pandas as pd

def test_cli_pasa_concurrencia_y_muestra(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    capturado = {}
    def fake_construir_base(runner, base_url, s, limite=None, descargar=None, max_workers=None):
        capturado["limite"] = limite
        capturado["max_workers"] = max_workers
        capturado["descargar"] = descargar
        return pd.DataFrame()          # vacío -> dry-run no escribe
    monkeypatch.setattr("benchmarking.cli.construir_base", fake_construir_base)
    monkeypatch.setattr("benchmarking.cli.bigquery.Client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(sys, "argv",
                        ["benchmarking","construir-base","--muestra","2","--concurrencia","12","--dry-run"])
    from benchmarking.cli import main
    main()
    assert capturado["limite"] == 2
    assert capturado["max_workers"] == 12
    assert capturado["descargar"] is not None      # el CLI inyecta el descargador

def test_cli_universo_wire(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    cap = {}
    def fake_universo(runner, base_url, s, escribir_lote=None, batch_size=None,
                      max_workers=None, descargar=None, hechos=None):
        cap["batch_size"] = batch_size; cap["max_workers"] = max_workers
        cap["hechos"] = hechos; cap["descargar"] = descargar
        return 0
    monkeypatch.setattr("benchmarking.cli.construir_universo", fake_universo)
    monkeypatch.setattr("benchmarking.cli.bigquery.Client", lambda *a, **k: MagicMock())
    monkeypatch.setattr("benchmarking.cli.tabla_existe", lambda *a, **k: True)
    monkeypatch.setattr("benchmarking.cli.procesos_existentes", lambda *a, **k: {"P9"})
    monkeypatch.setattr(sys, "argv",
                        ["benchmarking","construir-universo","--batch-size","250","--concurrencia","6"])
    from benchmarking.cli import main
    main()
    assert cap["batch_size"] == 250
    assert cap["max_workers"] == 6
    assert cap["hechos"] == {"P9"}
    assert cap["descargar"] is not None


def test_cli_engancha_el_cache_si_hay_bucket(monkeypatch):
    # Sin bucket: la funcion cruda. Con bucket: envuelta con el cache de GCS.
    monkeypatch.setenv("PIPELINE_SALT", "x")
    from benchmarking.config.settings import cargar_settings
    from benchmarking.adquisicion.plantilla_client import descargar_plantilla
    from benchmarking.cli import _con_cache

    monkeypatch.delenv("PIPELINE_GCS_BUCKET_PLANTILLAS", raising=False)
    assert _con_cache(cargar_settings()) is descargar_plantilla

    creado = {}
    class FakeCache:
        def __init__(self, bucket, **kw): creado["bucket"] = bucket
    monkeypatch.setattr("benchmarking.adquisicion.cache_plantillas.CacheGCS", FakeCache)
    monkeypatch.setenv("PIPELINE_GCS_BUCKET_PLANTILLAS", "mi-bucket")
    f = _con_cache(cargar_settings())
    assert f is not descargar_plantilla
    assert creado["bucket"] == "mi-bucket"
