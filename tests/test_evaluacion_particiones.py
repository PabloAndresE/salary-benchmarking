import numpy as np
import pandas as pd
from sintetico import generar
from benchmarking.evaluacion.particiones import (
    aleatoria, cargo_crudo, oraculo_salarial, solo_texto, techo_alcanzable)
from benchmarking.evaluacion.splits import empresas_test, partir

_COLS = ["antiguedad_total", "pct_fijo", "pct_comisiones", "pct_extras"]


def _marco(n_empresas=40):
    df = generar(n_empresas=n_empresas, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    return partir(df, empresas_test(df, frac=0.25))


def test_cargo_crudo_no_poda_nada():
    # Podar CARGO a sus etiquetas grandes dejaria a la mayoria en una celda "otros":
    # ganarle a ese rival no demostraria nada (D-005). Compite entero.
    df = pd.DataFrame({"cargo_norm": ["VENDEDOR"] * 3 + [f"RARO{i}" for i in range(50)]})
    c = cargo_crudo(df)
    assert c.nunique() == 51 and (c == "VENDEDOR").sum() == 3


def test_aleatoria_respeta_k_y_es_determinista():
    df = generar(n_empresas=20, personas_por_empresa=10)
    a = aleatoria(df, k=7, semilla=5)
    assert a.nunique() == 7
    pd.testing.assert_series_equal(a, aleatoria(df, k=7, semilla=5))


def test_solo_texto_agrupa_por_los_embeddings_dados():
    # Se le inyectan los embeddings: el modulo no llama a Vertex.
    df = pd.DataFrame({"cargo_norm": ["A", "A", "B", "B"]})
    emb = np.array([[0., 0.], [0.1, 0.], [9., 9.], [9.1, 9.]])
    c = solo_texto(df, k=2, embeddings=emb, semilla=1)
    assert c.iloc[0] == c.iloc[1] and c.iloc[2] == c.iloc[3] and c.iloc[0] != c.iloc[2]


def test_el_oraculo_se_ajusta_SOLO_en_train():
    # EL defecto 4 de D-011. Ajustarlo sobre todo el df incluia el test y el MAE colapsaba
    # al error de cuantizacion. Prueba: lo que haya en test no puede mover las fronteras.
    tr, ts = _marco()
    a = oraculo_salarial(tr, ts, k=4, semilla=1)
    ts2 = ts.copy()
    ts2.loc[ts2.index[:5], "y"] = 99.0          # atipicos brutales solo en test
    b = oraculo_salarial(tr, ts2, k=4, semilla=1)
    pd.testing.assert_series_equal(a.iloc[5:], b.iloc[5:])


def test_el_oraculo_sigue_haciendo_trampa():
    # Es su trabajo: agrupar por el salario. Si dejara de hacerlo, la alarma no sonaria.
    tr = pd.DataFrame({"y": [0.0, 0.05, 0.1, 5.0, 5.05, 5.1]})
    c = oraculo_salarial(tr, tr, k=2, semilla=1)
    assert c.iloc[0] == c.iloc[2] and c.iloc[3] == c.iloc[5] and c.iloc[0] != c.iloc[3]


def test_el_techo_no_ve_la_y_de_test():
    tr, ts = _marco()
    a = techo_alcanzable(tr, ts, tr[_COLS].to_numpy(float), ts[_COLS].to_numpy(float))
    ts2 = ts.copy()
    ts2["y"] = -99.0
    pd.testing.assert_series_equal(
        a, techo_alcanzable(tr, ts2, tr[_COLS].to_numpy(float), ts2[_COLS].to_numpy(float)))


def test_el_techo_es_mejor_que_el_azar_pero_no_es_magia():
    tr, ts = _marco(n_empresas=60)
    pred = techo_alcanzable(tr, ts, tr[_COLS].to_numpy(float), ts[_COLS].to_numpy(float))
    mae = float((ts["y"] - pred).abs().mean())
    azar = float((ts["y"] - tr["y"].median()).abs().mean())
    assert mae < azar
    # Cota teorica: con el efecto empresa inobservable bajo leave-company-out, ningun
    # metodo baja de raiz(eta2_empresa) x MAE aleatorio. Un techo muy por debajo delata
    # que se colo informacion del test.
    assert mae > 0.4 * azar, f"techo sospechosamente bajo: {mae:.3f} vs azar {azar:.3f}"


def test_el_techo_usa_perdida_absoluta():
    # Si optimizara MSE estaria estimando la media condicional mientras la metrica puntua
    # el error absoluto: el mismo desemparejamiento que D-011 corrigio en el estimador.
    import inspect
    from benchmarking.evaluacion import particiones
    assert 'loss="absolute_error"' in inspect.getsource(particiones.techo_alcanzable)


def test_todas_devuelven_serie_alineada():
    tr, ts = _marco()
    emb = np.random.default_rng(0).normal(0, 1, (len(ts), 8))
    for s in (cargo_crudo(ts), aleatoria(ts, 3), solo_texto(ts, 3, emb),
              oraculo_salarial(tr, ts, 3)):
        assert isinstance(s, pd.Series) and s.index.equals(ts.index) and s.notna().all()
