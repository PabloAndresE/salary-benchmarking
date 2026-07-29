from benchmarking.ingesta.composicion import parsear_plantilla, calcular_composicion


def test_parsear_columnas(plantilla_xlsx_bytes):
    df = parsear_plantilla(plantilla_xlsx_bytes)
    assert set(["identificacion", "cargo", "sueldo", "comisiones", "extras", "otros"]).issubset(df.columns)
    assert len(df) == 2
    assert df.loc[0, "comisiones"] == 400


def test_composicion_suma_uno(plantilla_xlsx_bytes):
    df = calcular_composicion(parsear_plantilla(plantilla_xlsx_bytes))
    fila = df.iloc[0]
    assert abs(fila.total - 1000) < 1e-6
    assert abs(fila.pct_fijo + fila.pct_comisiones + fila.pct_extras + fila.pct_otros - 1) < 1e-6
    assert abs(fila.pct_comisiones - 0.4) < 1e-6
