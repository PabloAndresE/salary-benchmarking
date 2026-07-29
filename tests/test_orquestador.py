import datetime as dt
from unittest.mock import MagicMock
import pandas as pd
from benchmarking.config.settings import cargar_settings
from benchmarking.orquestador import construir_base

def test_construir_base_end_to_end(monkeypatch, plantilla_xlsx_bytes):
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["GRANDE"],"ciiu_n1":["G"],
                 "ciiu_n6":["G4711"],"n_empleados":[300]})
        else:  # SQL_PERSONAS -> la base por-persona
            m.to_dataframe.return_value = pd.DataFrame({
                "identificacion":["1700000001","1700000002","1700000009"],
                "numero_proceso":["140672","140672","140672"],
                "id_version":["abc","abc","abc"],
                "anio_valoracion":[2024,2024,2024],
                "empresa_ruc":["1790011111001","1790011111001","1790011111001"],
                "cargo":["VENDEDOR","OPERARIO","GERENTE"],
                "sexo":["F","M","M"],
                "edad":[30,40,50],
                "sueldo":[600.0,500.0,900.0],
                "remuneracion_promedio":[None,None,1100.0],   # esta persona no está en la plantilla
                "fecha_ingreso":[dt.date(2014,1,1),dt.date(2010,1,1),dt.date(2000,1,1)]})
        return m
    runner.query.side_effect = fake_query
    df = construir_base(runner, "http://x", s, limite=1,
                        descargar=lambda *a, **k: plantilla_xlsx_bytes)
    # frontera de privacidad
    assert "id_hash" in df.columns and "identificacion" not in df.columns
    assert {"pct_fijo","tiene_composicion","sueldo_sbu","segmento","provincia","en_clean"}.issubset(df.columns)
    # no se pierde ninguna persona (3 en la base, aunque 1 no tenga plantilla)
    assert len(df) == 3
    # persona con composición: total = sueldo(600) + comisiones(400) = 1000
    fila_vend = df[df.cargo_norm == "VENDEDOR"].iloc[0]
    assert fila_vend.tiene_composicion == True
    assert abs(fila_vend.total - 1000.0) < 1e-6
    assert abs(fila_vend.pct_comisiones - 0.4) < 1e-6
    assert fila_vend.segmento == "GRANDE"
    # persona sin plantilla: se conserva, composición NULL, total = respaldo remuneracion_promedio
    fila_ger = df[df.cargo_norm == "GERENTE"].iloc[0]
    assert fila_ger.tiene_composicion == False
    assert pd.isna(fila_ger.pct_fijo)
    assert abs(fila_ger.total - 1100.0) < 1e-6

def test_construir_base_tolera_fallo_de_plantilla(monkeypatch):
    # Un estudio cuya plantilla falla al descargar/parsear se omite; el lote NO cae
    # y las personas se conservan con composición NULL.
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["GRANDE"],"ciiu_n1":["G"],
                 "ciiu_n6":["G4711"],"n_empleados":[300]})
        else:
            m.to_dataframe.return_value = pd.DataFrame({
                "identificacion":["1700000001","1700000002"],
                "numero_proceso":["140672","140672"], "id_version":["abc","abc"],
                "anio_valoracion":[2024,2024], "empresa_ruc":["1790011111001","1790011111001"],
                "cargo":["VENDEDOR","OPERARIO"], "sexo":["F","M"], "edad":[30,40],
                "sueldo":[600.0,500.0], "remuneracion_promedio":[700.0,550.0],
                "fecha_ingreso":[dt.date(2014,1,1),dt.date(2010,1,1)]})
        return m
    runner.query.side_effect = fake_query
    def descargar_falla(*a, **k):
        raise ValueError("XLSX corrupto")
    df = construir_base(runner, "http://x", s, limite=1, descargar=descargar_falla)
    assert len(df) == 2                                  # nadie se pierde
    assert (~df["tiene_composicion"]).all()             # sin composición
    assert df["pct_fijo"].isna().all()
    # total cae al respaldo remuneracion_promedio
    assert abs(df[df.cargo_norm=="VENDEDOR"].iloc[0].total - 700.0) < 1e-6
