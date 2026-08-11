import datetime as dt
from unittest.mock import MagicMock
import pandas as pd
from pandas.testing import assert_frame_equal
from benchmarking.config.settings import cargar_settings
from benchmarking.orquestador import construir_base
from benchmarking.orquestador import construir_universo

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
                "centro_de_costo":["Ventas","Planta","Gerencia"],
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
    # contexto de estudio y centro de costo presentes
    assert (df["n_personas_estudio"] == 3).all()
    assert df[df.cargo_norm == "VENDEDOR"].iloc[0].centro_de_costo == "Ventas"
    # columnas retiradas
    assert "cargo_orig" not in df.columns and "tuvo_salidas" not in df.columns
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

def test_construir_base_dedup_composicion_evita_fanout(monkeypatch):
    # Si la plantilla trae la misma cedula duplicada, el merge NO debe inflar el grano
    # (una fila por persona-estudio).
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

    def plantilla_duplicada(raw):
        return pd.DataFrame({
            "identificacion": ["1700000001", "1700000001", "1700000002"],
            "comisiones": [400.0, 400.0, 0.0],
            "extras": [0.0, 0.0, 0.0],
            "otros": [0.0, 0.0, 0.0],
        })
    monkeypatch.setattr("benchmarking.orquestador.parsear_plantilla", plantilla_duplicada)

    df = construir_base(runner, "http://x", s, limite=1, descargar=lambda *a, **k: b"fake")
    assert len(df) == 2   # sin fan-out: 2 personas en la base -> 2 filas en la salida

def _fake_runner_multi():
    # 3 estudios, cada uno con las 2 cedulas del fixture de plantilla
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["GRANDE"],"ciiu_n1":["G"],
                 "ciiu_n6":["G4711"],"n_empleados":[300]})
        else:
            filas = []
            for proc in ("P1","P2","P3"):
                for ced in ("1700000001","1700000002"):
                    filas.append({"identificacion":ced,"numero_proceso":proc,"id_version":"v",
                                  "anio_valoracion":2024,"empresa_ruc":"1790011111001",
                                  "cargo":"VENDEDOR","centro_de_costo":"Ventas","sexo":"F",
                                  "edad":30,"sueldo":600.0,"remuneracion_promedio":None,
                                  "fecha_ingreso":dt.date(2014,1,1)})
            m.to_dataframe.return_value = pd.DataFrame(filas)
        return m
    runner.query.side_effect = fake_query
    return runner

def test_construir_base_concurrente_equivale_a_secuencial(monkeypatch, plantilla_xlsx_bytes):
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    desc = lambda *a, **k: plantilla_xlsx_bytes
    df1 = construir_base(_fake_runner_multi(), "http://x", s, descargar=desc, max_workers=1)
    df4 = construir_base(_fake_runner_multi(), "http://x", s, descargar=desc, max_workers=4)
    key = ["numero_proceso","id_hash"]
    assert_frame_equal(df1.sort_values(key).reset_index(drop=True),
                       df4.sort_values(key).reset_index(drop=True))
    assert len(df4) == 6   # 3 estudios x 2 personas, sin fan-out

def test_construir_base_concurrente_resiliente(monkeypatch, plantilla_xlsx_bytes):
    # un estudio falla al descargar; con concurrencia el lote no cae y se conservan sus filas
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    def desc(numero_proceso, id_version, base_url):
        if numero_proceso == "P2":
            raise ValueError("XLSX corrupto")
        return plantilla_xlsx_bytes
    df = construir_base(_fake_runner_multi(), "http://x", s, descargar=desc, max_workers=4)
    assert len(df) == 6                                   # nadie se pierde
    # P2 sin composición; P1/P3 con composición
    assert (~df[df.numero_proceso=="P2"]["tiene_composicion"]).all()
    assert df[df.numero_proceso=="P1"]["tiene_composicion"].all()

def test_conserva_el_cargo_de_la_plantilla(monkeypatch, plantilla_xlsx_bytes):
    # La plantilla trae el cargo escrito por el EMPLEADOR: una segunda etiqueta del mismo
    # puesto, independiente de la del estudio actuarial. Donde coinciden, la etiqueta es
    # fiable (buen must-link); donde divergen, hay etiqueta colapsada. Se tiraba.
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["G"],"ciiu_n1":["G"],"ciiu_n6":["G1"],"n_empleados":[10]})
        else:
            m.to_dataframe.return_value = pd.DataFrame({
                "identificacion":["1700000001","1700000002"],
                "numero_proceso":["P1","P1"], "id_version":["v","v"],
                "anio_valoracion":[2025,2025], "empresa_ruc":["1790011111001"]*2,
                "cargo":["TRABAJADOR EN GENERAL","OPERARIO"],   # etiqueta del estudio
                "centro_de_costo":["X","X"], "sexo":["F","M"], "edad":[30,40],
                "sueldo":[600.0,500.0], "remuneracion_promedio":[None,None],
                "fecha_ingreso":[dt.date(2014,1,1)]*2})
        return m
    runner.query.side_effect = fake_query
    df = construir_base(runner, "http://x", s, descargar=lambda *a, **k: plantilla_xlsx_bytes)

    assert "cargo_plantilla" in df.columns
    # el fixture trae VENDEDOR y OPERARIO como cargos del empleador
    fila = df[df.cargo == "TRABAJADOR EN GENERAL"].iloc[0]
    assert fila.cargo_plantilla == "VENDEDOR", "debe traer la etiqueta del empleador, no la del estudio"
    assert fila.cargo == "TRABAJADOR EN GENERAL", "la etiqueta original no se toca"


def test_plantilla_sin_columna_cargo_no_rompe(monkeypatch):
    # Regresion: si una plantilla no trae columna de cargo, el estudio debe seguir
    # aportando composicion en vez de caer entero a fallo_parseo.
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["G"],"ciiu_n1":["G"],"ciiu_n6":["G1"],"n_empleados":[10]})
        else:
            m.to_dataframe.return_value = pd.DataFrame({
                "identificacion":["1700000001"], "numero_proceso":["P1"], "id_version":["v"],
                "anio_valoracion":[2025], "empresa_ruc":["1790011111001"], "cargo":["X"],
                "centro_de_costo":["C"], "sexo":["F"], "edad":[30], "sueldo":[600.0],
                "remuneracion_promedio":[None], "fecha_ingreso":[dt.date(2014,1,1)]})
        return m
    runner.query.side_effect = fake_query
    monkeypatch.setattr("benchmarking.orquestador.parsear_plantilla", lambda raw: pd.DataFrame({
        "identificacion": ["1700000001"], "comisiones": [400.0], "extras": [0.0], "otros": [0.0]}))
    df = construir_base(runner, "http://x", s, descargar=lambda *a, **k: b"fake")
    assert df["tiene_composicion"].all()
    assert df["cargo_plantilla"].isna().all()


def test_enlace_tolera_cedulas_sin_cero_inicial(monkeypatch):
    # La plantilla guarda las cedulas sin el cero inicial (pasaron por formato numerico),
    # la base BQ si lo conserva. El enlace por texto exacto perdia TODA cedula de las
    # provincias 01-09 -> sesgo geografico en la composicion, no perdida al azar.
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["G"],"ciiu_n1":["G"],"ciiu_n6":["G1"],"n_empleados":[10]})
        else:
            m.to_dataframe.return_value = pd.DataFrame({
                "identificacion":["0928066398","1724894736","0104110309"],  # dos con cero inicial
                "numero_proceso":["P1"]*3, "id_version":["v"]*3, "anio_valoracion":[2025]*3,
                "empresa_ruc":["1790011111001"]*3, "cargo":["A","B","C"],
                "centro_de_costo":["X"]*3, "sexo":["F","M","F"], "edad":[30,40,50],
                "sueldo":[600.0,700.0,800.0], "remuneracion_promedio":[None,None,None],
                "fecha_ingreso":[dt.date(2014,1,1)]*3})
        return m
    runner.query.side_effect = fake_query

    def plantilla_sin_ceros(raw):
        return pd.DataFrame({
            "identificacion": ["928066398", "1724894736", "104110309"],   # ceros perdidos
            "comisiones": [400.0, 300.0, 200.0],
            "extras": [0.0, 0.0, 0.0],
            "otros": [0.0, 0.0, 0.0],
        })
    monkeypatch.setattr("benchmarking.orquestador.parsear_plantilla", plantilla_sin_ceros)

    df = construir_base(runner, "http://x", s, descargar=lambda *a, **k: b"fake")
    assert len(df) == 3
    assert df["tiene_composicion"].all(), "las cedulas con cero inicial deben enlazar igual"
    assert abs(df[df.cargo_norm=="A"].iloc[0].total - 1000.0) < 1e-6   # 600 + 400


def test_enlace_normaliza_decimal_espurio(monkeypatch):
    # Si la columna del xlsx llego como float, astype(str) produce "1724894736.0".
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["G"],"ciiu_n1":["G"],"ciiu_n6":["G1"],"n_empleados":[10]})
        else:
            m.to_dataframe.return_value = pd.DataFrame({
                "identificacion":["1724894736"], "numero_proceso":["P1"], "id_version":["v"],
                "anio_valoracion":[2025], "empresa_ruc":["1790011111001"], "cargo":["A"],
                "centro_de_costo":["X"], "sexo":["F"], "edad":[30], "sueldo":[600.0],
                "remuneracion_promedio":[None], "fecha_ingreso":[dt.date(2014,1,1)]})
        return m
    runner.query.side_effect = fake_query
    monkeypatch.setattr("benchmarking.orquestador.parsear_plantilla", lambda raw: pd.DataFrame({
        "identificacion": ["1724894736.0"], "comisiones": [400.0], "extras": [0.0], "otros": [0.0]}))
    df = construir_base(runner, "http://x", s, descargar=lambda *a, **k: b"fake")
    assert df["tiene_composicion"].all()


def test_normalizar_cedula_no_altera_el_id_hash(monkeypatch):
    # La normalizacion es SOLO para el enlace. Si tocara `identificacion`, cambiaria el
    # id_hash y las personas dejarian de ser comparables con las filas ya escritas.
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    from benchmarking.ingesta.anonimizacion import anonimizar
    esperado = anonimizar(pd.DataFrame({"identificacion":["0928066398"]}), s.salt)["id_hash"].iloc[0]

    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["G"],"ciiu_n1":["G"],"ciiu_n6":["G1"],"n_empleados":[10]})
        else:
            m.to_dataframe.return_value = pd.DataFrame({
                "identificacion":["0928066398"], "numero_proceso":["P1"], "id_version":["v"],
                "anio_valoracion":[2025], "empresa_ruc":["1790011111001"], "cargo":["A"],
                "centro_de_costo":["X"], "sexo":["F"], "edad":[30], "sueldo":[600.0],
                "remuneracion_promedio":[None], "fecha_ingreso":[dt.date(2014,1,1)]})
        return m
    runner.query.side_effect = fake_query
    monkeypatch.setattr("benchmarking.orquestador.parsear_plantilla", lambda raw: pd.DataFrame({
        "identificacion": ["928066398"], "comisiones": [400.0], "extras": [0.0], "otros": [0.0]}))
    df = construir_base(runner, "http://x", s, descargar=lambda *a, **k: b"fake")
    assert df["id_hash"].iloc[0] == esperado, "el hash debe salir de la cedula original, no de la normalizada"
    assert "_ced_key" not in df.columns                      # la llave de enlace no se filtra a la salida


def test_composicion_cuenta_motivos_por_separado(monkeypatch, plantilla_xlsx_bytes):
    # Distinguir "el estudio no tiene plantilla" (404, normal en <=2022) de "no pude
    # bajarla" (red agotada, pérdida de datos real) es lo que hace visible una
    # degradación silenciosa en vez de que se descubra semanas después.
    from benchmarking.orquestador import _composicion_estudios
    from benchmarking.adquisicion.plantilla_client import DescargaFallida, PlantillaRechazada
    estudios = pd.DataFrame({"numero_proceso": ["P1","P2","P3","P4","P5"], "id_version": ["v"]*5})

    def desc(numero_proceso, id_version, base_url):
        if numero_proceso == "P2": return None                       # 404: no existe
        if numero_proceso == "P3": raise DescargaFallida("red")      # pérdida real
        if numero_proceso == "P4": return b"no-es-un-xlsx"           # falla al parsear
        if numero_proceso == "P5": raise PlantillaRechazada("400")   # rechazo determinista
        return plantilla_xlsx_bytes

    comp, conteo = _composicion_estudios(estudios, "http://x", desc, max_workers=2)
    assert conteo == {"ok": 1, "sin_plantilla": 1, "fallo_descarga": 1,
                      "fallo_parseo": 1, "rechazado": 1}
    assert comp["numero_proceso"].unique().tolist() == ["P1"]      # solo el bueno aporta montos


def _fake_universo_runner():
    personas_all = pd.DataFrame([
        {"identificacion":ced,"numero_proceso":proc,"id_version":"v","anio_valoracion":2024,
         "empresa_ruc":"1790011111001","cargo":"VENDEDOR","centro_de_costo":"Ventas","sexo":"F",
         "edad":30,"sueldo":600.0,"remuneracion_promedio":700.0,"fecha_ingreso":dt.date(2014,1,1)}
        for proc in ("P1","P2","P3") for ced in ("1700000001","1700000002")])
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock(); s = sql.lower()
        if "scvs" in s or "balances" in s:
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["GRANDE"],"ciiu_n1":["G"],
                 "ciiu_n6":["G4711"],"n_empleados":[300]})
        elif "numero_proceso in (" in s:
            procs = [p for p in ("P1","P2","P3") if f"'{p}'" in sql]
            m.to_dataframe.return_value = personas_all[personas_all.numero_proceso.isin(procs)].reset_index(drop=True)
        else:  # listar_estudios
            m.to_dataframe.return_value = pd.DataFrame(
                {"numero_proceso":["P1","P2","P3"],"id_version":["v","v","v"],
                 "anio_valoracion":[2024,2024,2024],"empresa_ruc":["1790011111001"]*3})
        return m
    runner.query.side_effect = fake_query
    return runner

def test_construir_universo_lotea_y_reanuda(monkeypatch, plantilla_xlsx_bytes):
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    runner = _fake_universo_runner()
    escritos = []
    total = construir_universo(runner, "http://x", s, escribir_lote=escritos.append,
                               batch_size=1, max_workers=2,
                               descargar=lambda *a, **k: plantilla_xlsx_bytes, hechos={"P1"})
    # P1 ya hecho -> solo P2 y P3, en 2 lotes (batch_size=1)
    assert len(escritos) == 2
    procesados = pd.concat(escritos)["numero_proceso"].unique().tolist()
    assert set(procesados) == {"P2","P3"}
    assert total == sum(len(d) for d in escritos)
    # frontera: sin PII, con id_hash y composición armada
    for d in escritos:
        assert "identificacion" not in d.columns and "id_hash" in d.columns
        assert {"pct_fijo","total","segmento","n_personas_estudio"}.issubset(d.columns)
    # SCVS leído una sola vez
    scvs_calls = [c for c in runner.query.call_args_list
                  if "scvs" in c[0][0].lower() or "balances" in c[0][0].lower()]
    assert len(scvs_calls) == 1

def test_construir_universo_procesa_recientes_primero(monkeypatch, plantilla_xlsx_bytes):
    # Los estudios se procesan por anio_valoracion DESC (recientes primero), porque la
    # composición sólo existe en los recientes.
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    personas = pd.DataFrame([
        {"identificacion":"1700000001","numero_proceso":proc,"id_version":"v","anio_valoracion":anio,
         "empresa_ruc":"1790011111001","cargo":"X","centro_de_costo":"C","sexo":"F","edad":30,
         "sueldo":600.0,"remuneracion_promedio":700.0,"fecha_ingreso":dt.date(2014,1,1)}
        for proc, anio in [("A",2022),("B",2024),("C",2023)]])
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock(); low = sql.lower()
        if "scvs" in low or "balances" in low:
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["G"],"ciiu_n1":["G"],"ciiu_n6":["G1"],"n_empleados":[10]})
        elif "numero_proceso in (" in low:
            procs = [p for p in ("A","B","C") if f"'{p}'" in sql]
            m.to_dataframe.return_value = personas[personas.numero_proceso.isin(procs)].reset_index(drop=True)
        else:
            m.to_dataframe.return_value = pd.DataFrame(
                {"numero_proceso":["A","B","C"],"id_version":["v","v","v"],
                 "anio_valoracion":[2022,2024,2023],"empresa_ruc":["1790011111001"]*3})
        return m
    runner.query.side_effect = fake_query
    orden = []
    construir_universo(runner, "http://x", s, escribir_lote=lambda d: orden.append(d["numero_proceso"].iloc[0]),
                       batch_size=1, max_workers=2, descargar=lambda *a, **k: plantilla_xlsx_bytes)
    assert orden == ["B", "C", "A"]   # 2024, 2023, 2022
