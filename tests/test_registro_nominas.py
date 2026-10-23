"""Guardar las nominas cargadas en el dataset del producto: tres tablas, solo cargo y
sueldo del empleado, encendido por defecto, y sin tumbar el informe si BigQuery falla.
Nada de esto toca la red: `guardar` se sustituye."""
import io

import pandas as pd
import pytest

from src.services import registro_nomina_service as rn

pytest.importorskip("fastapi", reason="extra opcional: pip install -e .[servicio]")
from test_servicio import base_npz, cliente  # noqa: E402,F401  (fixtures)


def _columnas(tabla):
    return {n for n, _ in rn.ESQUEMAS[tabla]}


def _xlsx(df):
    b = io.BytesIO()
    df.to_excel(b, index=False)
    return b.getvalue()


def _nomina():
    return pd.DataFrame({"cargo": ["CONTADOR", "VENDEDOR", "", "GUARDIA"],
                         "sueldo": ["1200", "650.5", "", "no se"],
                         "nombre": ["Ana Perez", "Luis Mora", "", "Juan Diaz"],
                         "sexo": ["F", "M", "", "M"]})


def _registro(df, detalle=(), hom=None, **kw):
    args = dict(id_carga="t1", carga_hash="h", anio=2026, ruc=None, ciiu=None,
                segmento=None, rubro=None, correcciones=None, version_api="v1.3",
                version_base="base_v31")
    args.update(kw)
    return rn.registro(df, "cargo", "sueldo" if "sueldo" in df else None, list(detalle),
                       hom, **args)


def test_tres_tablas_con_su_esquema_y_sin_datos_personales():
    t = _registro(_nomina(), ruc=" 0990000000001 ", ciiu="G4649.22", segmento="MEDIANA",
                  rubro="G", correcciones={1: "VENDEDOR EXTERNO"})
    assert set(t) == {"cargas", "nomina_filas", "homologaciones"}
    for nombre, filas in t.items():
        assert filas and all(set(f) == _columnas(nombre) for f in filas)
    texto = repr(t)
    for dato in ("Ana Perez", "Luis Mora", "Juan Diaz"):
        assert dato not in texto
    cab, = t["cargas"]
    assert cab["empresa_ruc"] == "0990000000001" and cab["ciiu"] == "G4649.22"
    assert cab["n_filas"] == 3 and cab["correcciones"] == 1
    assert cab["version_api"] == "v1.3" and cab["version_base"] == "base_v31"
    # la fila vacia de la hoja no se guarda; las demas si, con su numero de fila
    assert [f["fila"] for f in t["nomina_filas"]] == [0, 1, 3]
    assert [f["sueldo"] for f in t["nomina_filas"]] == [1200.0, 650.5, None]
    assert t["nomina_filas"][1]["cargo_corregido_usuario"] == "VENDEDOR EXTERNO"
    # las tres tablas comparten id y fecha: se unen por (id_carga, fila)
    assert len({f["fecha_carga"] for filas in t.values() for f in filas}) == 1


def test_el_puesto_sale_de_la_homologacion_aunque_el_detalle_no_lo_traiga():
    # con columnas_originales=false el detalle NO lleva cargo_base ni p_juez
    df = pd.DataFrame({"cargo": ["CONTDOR", "CONTADOR", "HEAD OF AI"],
                       "sueldo": ["1", "2", "3"]})
    det = [{"fila": 0, "base": "datos directos", "cargo_normalizado": "CONTDOR"},
           {"fila": 1, "base": "rubro G46", "cargo_normalizado": "CONTADOR"},
           {"fila": 2, "base": "por analogia", "cargo_normalizado": "HEAD OF AI"}]
    hom = pd.DataFrame({"cargo_base": ["CONTADOR", "", ""], "p_juez": [0.97, None, 0.4]})
    h = _registro(df, det, hom)["homologaciones"]
    assert [x["puesto_asignado"] for x in h] == ["CONTADOR", "CONTADOR", None]
    assert h[0]["p_juez"] == 0.97 and h[1]["p_juez"] is None


def test_sin_columna_de_sueldo_se_guarda_el_cargo_igual():
    f, = _registro(pd.DataFrame({"cargo": ["CONTADOR"]}))["nomina_filas"]
    assert f["cargo"] == "CONTADOR" and f["sueldo"] is None


def test_la_cabecera_se_escribe_al_final():
    assert rn.ORDEN[-1] == "cargas" and set(rn.ORDEN) == set(rn.ESQUEMAS)


def _subir(cliente, **form):
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(_nomina()))}, data=form)
    assert r.status_code == 202, r.text
    return cliente.get(f"/informes/{r.json()['id']}").json()


def test_encendido_por_defecto_y_al_dataset_del_producto(cliente, monkeypatch):
    llamadas = []
    monkeypatch.delenv("GUARDAR_NOMINAS", raising=False)
    monkeypatch.delenv("BENCHMARKING_DATASET", raising=False)
    monkeypatch.setattr(rn, "guardar", lambda t, d: llamadas.append((t, d)))
    inf = _subir(cliente)
    assert inf["estado"] == "listo"
    (t, d), = llamadas
    assert d == "act-cicd-stage-prueba.benchmarking"
    assert len(t["nomina_filas"]) == 3 and len(t["homologaciones"]) == 3
    assert t["cargas"][0]["id_carga"] == inf["id"]
    assert "Ana Perez" not in repr(t)


def test_el_puesto_se_guarda_aunque_el_front_pida_solo_los_numeros(cliente, monkeypatch):
    llamadas = []
    monkeypatch.setenv("GUARDAR_NOMINAS", "si")
    monkeypatch.setattr(rn, "guardar", lambda t, d: llamadas.append(t))
    _subir(cliente, columnas_originales="false")
    puestos = [h["puesto_asignado"] for h in llamadas[0]["homologaciones"]]
    assert puestos == ["CONTADOR", "VENDEDOR", "GUARDIA"]


def test_se_apaga_con_GUARDAR_NOMINAS_no(cliente, monkeypatch):
    llamadas = []
    monkeypatch.setenv("GUARDAR_NOMINAS", "no")
    monkeypatch.setattr(rn, "guardar", lambda *a, **k: llamadas.append(a))
    assert _subir(cliente)["estado"] == "listo"
    assert llamadas == []


def test_si_guardar_falla_el_informe_sale_igual(cliente, monkeypatch):
    monkeypatch.setenv("GUARDAR_NOMINAS", "si")

    def _revienta(*a, **k):
        raise RuntimeError("BigQuery caido")

    monkeypatch.setattr(rn, "guardar", _revienta)
    inf = _subir(cliente)
    assert inf["estado"] == "listo" and inf["detalle"]


def test_el_ddl_sale_del_mismo_esquema_que_escribe_la_api():
    sql = rn.ddl("p.benchmarking")
    for nombre, cols in rn.ESQUEMAS.items():
        assert f"CREATE TABLE IF NOT EXISTS `p.benchmarking.{nombre}`" in sql
        for col, _ in cols:
            assert f"  {col} " in sql
    assert sql.count("PARTITION BY DATE(fecha_carga)") == len(rn.ESQUEMAS)
