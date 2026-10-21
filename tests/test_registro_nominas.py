"""Guardar las nominas cargadas: solo cargo y sueldo, apagado por defecto, y sin tumbar
el informe si BigQuery falla. Nada de esto toca la red: `guardar` se sustituye."""
import io

import pandas as pd
import pytest

from benchmarking.servicio import registro_nominas as rn

pytest.importorskip("fastapi", reason="extra opcional: pip install -e .[servicio]")
from test_servicio import base_npz, cliente  # noqa: E402,F401  (fixtures)

COLUMNAS = {n for n, _ in rn.ESQUEMA}


def _xlsx(df):
    b = io.BytesIO()
    df.to_excel(b, index=False)
    return b.getvalue()


def _nomina():
    return pd.DataFrame({"cargo": ["CONTADOR", "VENDEDOR", "", "GUARDIA"],
                         "sueldo": ["1200", "650.5", "", "no se"],
                         "nombre": ["Ana Perez", "Luis Mora", "", "Juan Diaz"],
                         "sexo": ["F", "M", "", "M"]})


def test_solo_se_guarda_la_lista_blanca_aunque_la_nomina_traiga_nombres():
    df = _nomina()
    det = [{"fila": 0, "referencia": 1100.0, "base": "datos directos",
            "cargo_base": "", "cargo_normalizado": "CONTADOR", "confianza": "ALTA"}]
    filas = rn.filas_registro(df, "cargo", "sueldo", det, id_carga="t1", carga_hash="h",
                              anio=2026, ruc=" 0990000000001 ", ciiu="G4649.22",
                              segmento="MEDIANA")
    assert all(set(f) == COLUMNAS for f in filas)
    texto = repr(filas)
    for dato in ("Ana Perez", "Luis Mora", "Juan Diaz"):
        assert dato not in texto
    # la fila vacia de la hoja no se guarda; las demas si, con su numero de fila
    assert [f["fila"] for f in filas] == [0, 1, 3]
    assert filas[0]["empresa_ruc"] == "0990000000001"
    assert [f["sueldo"] for f in filas] == [1200.0, 650.5, None]
    assert filas[0]["puesto_asignado"] == "CONTADOR"


def test_por_analogia_no_hay_puesto_asignado():
    df = pd.DataFrame({"cargo": ["HEAD OF AI"], "sueldo": ["4000"]})
    det = [{"fila": 0, "referencia": 4100.0, "base": "por analogia", "cargo_base": "",
            "cargo_normalizado": "HEAD OF AI"}]
    f, = rn.filas_registro(df, "cargo", "sueldo", det, id_carga="t", carga_hash="h",
                           anio=2026, ruc=None, ciiu=None, segmento=None)
    assert f["puesto_asignado"] is None and f["via"] == "por analogia"


def test_sin_columna_de_sueldo_se_guarda_el_cargo_igual():
    df = pd.DataFrame({"cargo": ["CONTADOR"]})
    f, = rn.filas_registro(df, "cargo", None, [], id_carga="t", carga_hash="h",
                           anio=2026, ruc=None, ciiu=None, segmento=None)
    assert f["cargo"] == "CONTADOR" and f["sueldo"] is None


def _subir(cliente, **form):
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(_nomina()))}, data=form)
    assert r.status_code == 202, r.text
    return cliente.get(f"/informes/{r.json()['id']}").json()


def test_apagado_por_defecto(cliente, monkeypatch):
    llamadas = []
    monkeypatch.delenv("GUARDAR_NOMINAS", raising=False)
    monkeypatch.setattr(rn, "guardar", lambda *a, **k: llamadas.append(a))
    assert _subir(cliente)["estado"] == "listo"
    assert llamadas == []


def test_encendido_guarda_la_carga_sin_datos_personales(cliente, monkeypatch):
    llamadas = []
    monkeypatch.setenv("GUARDAR_NOMINAS", "si")
    monkeypatch.setenv("NOMINAS_TABLA", "p.d.nominas_recibidas")
    monkeypatch.setattr(rn, "guardar", lambda filas, tabla, project=None:
                        llamadas.append((filas, tabla)))
    inf = _subir(cliente)
    assert inf["estado"] == "listo"
    (filas, tabla), = llamadas
    assert tabla == "p.d.nominas_recibidas"
    assert len(filas) == 3 and all(set(f) == COLUMNAS for f in filas)
    assert {f["id_carga"] for f in filas} == {inf["id"]}
    assert "Ana Perez" not in repr(filas)


def test_si_guardar_falla_el_informe_sale_igual(cliente, monkeypatch):
    monkeypatch.setenv("GUARDAR_NOMINAS", "si")

    def _revienta(*a, **k):
        raise RuntimeError("BigQuery caido")

    monkeypatch.setattr(rn, "guardar", _revienta)
    inf = _subir(cliente)
    assert inf["estado"] == "listo" and inf["detalle"]
