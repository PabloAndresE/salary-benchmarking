import io
import os

import openpyxl
import pytest

# los tests no llaman a Vertex al arrancar el servicio (calentamiento de la API)
os.environ.setdefault("CALENTAR", "no")
# ...ni escriben nominas en BigQuery: guardar viene ENCENDIDO por defecto en produccion
os.environ.setdefault("GUARDAR_NOMINAS", "no")


@pytest.fixture
def plantilla_xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plantilla de empleados"
    ws.append(["Tipo de\nidentificación", "Identificación", "Apellidos", "Nombres",
               "Cargo ", "Centro de costos ", "Sexo",
               "Último sueldo/pensión mensual ", "Comisiones mensuales promedio  ",
               "Horas extras mensuales promedio ", "Otros mensuales promedio "])
    ws.append(["CEDULA", "1700000001", "Perez", "Ana", "VENDEDOR", "Ventas", "F",
               600, 400, 0, 0])
    ws.append(["CEDULA", "1700000002", "Gomez", "Luis", "OPERARIO", "Planta", "M",
               500, 0, 0, 0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
