from benchmarking.evaluacion.splits import empresas_test, partir, guardar, cargar
from sintetico import generar


def test_ninguna_empresa_cruza():
    df = generar(n_empresas=40, personas_por_empresa=10)
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    assert set(tr["empresa_ruc"]) & set(ts["empresa_ruc"]) == set()
    assert len(tr) + len(ts) == len(df)


def test_proporcion_aproximada():
    df = generar(n_empresas=40, personas_por_empresa=10)
    assert 8 <= len(empresas_test(df, frac=0.2)) <= 12


def test_estratifica_por_segmento():
    df = generar(n_empresas=40, personas_por_empresa=10)
    ts = df[df["empresa_ruc"].isin(empresas_test(df, frac=0.25))]
    assert ts["segmento"].nunique() == df["segmento"].nunique()


def test_al_menos_una_empresa_por_estrato():
    # Sin este minimo, los estratos pequenos desaparecen del test y la estratificacion
    # falla justo donde mas hace falta.
    df = generar(n_empresas=40, personas_por_empresa=10)
    te = empresas_test(df, frac=0.05)
    estratos = (df["segmento"].astype(str) + "|" + df["ciiu_n1"].astype(str))
    en_test = estratos[df["empresa_ruc"].isin(te)]
    assert en_test.nunique() == estratos.nunique()


def test_determinista():
    df = generar(n_empresas=40, personas_por_empresa=10)
    assert empresas_test(df, semilla=7) == empresas_test(df, semilla=7)
    assert empresas_test(df, semilla=7) != empresas_test(df, semilla=8)


def test_persistencia_con_hash(tmp_path):
    # El hash entra en el pre-registro: prueba de que el test-set no se cambio despues.
    df = generar(n_empresas=20, personas_por_empresa=5)
    te = empresas_test(df, frac=0.2)
    h = guardar(te, tmp_path / "split.json")
    assert len(h) == 64 and cargar(tmp_path / "split.json") == te
