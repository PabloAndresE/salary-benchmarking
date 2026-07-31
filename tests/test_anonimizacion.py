import pandas as pd
from benchmarking.ingesta.anonimizacion import hash_cedula, anonimizar

def test_hash_determinista_y_16():
    h1 = hash_cedula("1700000001", "sal")
    h2 = hash_cedula("1700000001", "sal")
    assert h1 == h2 and len(h1) == 16

def test_hash_cambia_con_salt():
    assert hash_cedula("1700000001", "a") != hash_cedula("1700000001", "b")

def test_anonimizar_elimina_pii_y_agrega_hash():
    df = pd.DataFrame({"identificacion":["1700000001"], "nombres":["Ana"],
                       "apellidos":["Perez"], "sueldo":[500.0]})
    out = anonimizar(df, salt="sal")
    assert "id_hash" in out.columns
    assert "identificacion" not in out.columns
    assert "nombres" not in out.columns and "apellidos" not in out.columns
    assert out.loc[0, "sueldo"] == 500.0
