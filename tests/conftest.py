import io
import os

import numpy as np
import openpyxl
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from fakes.ajustes import make_fake_ajustes
from fakes.cliente_v13 import ClienteV13
from src.domain.base_referencia import BaseReferencia

# los tests no llaman a Vertex al arrancar el servicio (calentamiento de la API)
os.environ.setdefault("CALENTAR", "no")
# ...ni escriben nominas en BigQuery: guardar viene ENCENDIDO por defecto en produccion
os.environ.setdefault("GUARDAR_NOMINAS", "no")
# ...ni cargan los modelos reales aunque haya `artefactos/` en el disco: los tests son los
# mismos en un clon recien hecho que en una maquina con la version bajada
os.environ.setdefault("JUEZ", "no")
os.environ.setdefault("TRADUCTOR", "no")


@pytest.fixture
def plantilla_xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plantilla de empleados"
    ws.append(
        [
            "Tipo de\nidentificación",
            "Identificación",
            "Apellidos",
            "Nombres",
            "Cargo ",
            "Centro de costos ",
            "Sexo",
            "Último sueldo/pensión mensual ",
            "Comisiones mensuales promedio  ",
            "Horas extras mensuales promedio ",
            "Otros mensuales promedio ",
        ]
    )
    ws.append(["CEDULA", "1700000001", "Perez", "Ana", "VENDEDOR", "Ventas", "F", 600, 400, 0, 0])
    ws.append(["CEDULA", "1700000002", "Gomez", "Luis", "OPERARIO", "Planta", "M", 500, 0, 0, 0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def base_npz(tmp_path):
    """Una base SINTETICA de tres puestos, guardada como la de produccion."""
    filas, emb = [], {}
    for k, cargo in enumerate(("CONTADOR", "VENDEDOR", "GUARDIA")):
        v = np.zeros(4)
        v[k] = 1.0
        emb[cargo] = v
        for i in range(14):
            filas.append((f"E{k}{i}", cargo, 1.0 + 0.2 * k + 0.01 * (i % 5)))
    marco = pd.DataFrame(filas, columns=["empresa_ruc", "cargo_norm", "y"])
    b = BaseReferencia.construir(marco, emb, lambda a: 470.0)
    ruta = tmp_path / "base.npz"
    b.guardar(ruta)
    return str(ruta)


@pytest.fixture
def cliente(base_npz, monkeypatch):
    """La app arrancada sobre `base_npz`, detras del adaptador v1.3 (ver `fakes/cliente_v13.py`)."""
    from src import main as api

    monkeypatch.setattr("src.config.ajustes.cargar_settings", lambda: make_fake_ajustes())
    monkeypatch.setenv("BASE_REFERENCIA", base_npz)
    with TestClient(api.app) as c:
        yield ClienteV13(c)
