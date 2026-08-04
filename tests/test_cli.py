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
