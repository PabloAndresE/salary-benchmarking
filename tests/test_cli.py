import sys
from unittest.mock import MagicMock
import pandas as pd

def test_cli_pasa_concurrencia_y_muestra(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    capturado = {}
    def fake_construir_base(runner, base_url, s, limite=None, max_workers=None):
        capturado["limite"] = limite
        capturado["max_workers"] = max_workers
        return pd.DataFrame()          # vacío -> dry-run no escribe
    monkeypatch.setattr("benchmarking.cli.construir_base", fake_construir_base)
    monkeypatch.setattr("benchmarking.cli.bigquery.Client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(sys, "argv",
                        ["benchmarking","construir-base","--muestra","2","--concurrencia","12","--dry-run"])
    from benchmarking.cli import main
    main()
    assert capturado["limite"] == 2
    assert capturado["max_workers"] == 12

def test_cli_universo_wire(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    cap = {}
    def fake_universo(runner, base_url, s, escribir_lote=None, batch_size=None, max_workers=None, hechos=None):
        cap["batch_size"] = batch_size; cap["max_workers"] = max_workers; cap["hechos"] = hechos
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
