import numpy as np
from sklearn.decomposition import PCA
from sklearn.utils.extmath import randomized_svd
from benchmarking.evaluacion.representacion import normalizar_mfa, primer_valor_singular


def _bloques_con_factor(n=400, semilla=0):
    """Un bloque estrecho y uno ancho, cada uno con su propio factor latente."""
    rng = np.random.default_rng(semilla)
    fa, fb = rng.normal(size=n), rng.normal(size=n)
    A = fa[:, None] * rng.normal(1, .1, (1, 3)) + rng.normal(0, .3, (n, 3))
    B = fb[:, None] * rng.normal(1, .1, (1, 100)) + rng.normal(0, .3, (n, 100))
    return A, B


def _masa_del_primer_eje_en(X, columnas):
    """Fraccion de la direccion principal que vive en esas columnas."""
    v = PCA(n_components=1).fit(X).components_[0]
    return float(v[columnas] @ v[columnas])


def test_ningun_bloque_domina_el_primer_eje():
    # LO QUE MFA PROMETE, y no es lo mismo que igualar distancias: que ningun bloque se
    # quede la direccion principal por tener mas columnas. Es el eje que usan k-means y
    # GMM, y el caso real son 768 columnas de texto contra 4 de composicion.
    A, B = _bloques_con_factor()
    masa = _masa_del_primer_eje_en(normalizar_mfa([A, B]), slice(0, 3))
    assert 0.2 < masa < 0.8, f"el primer eje esta acaparado: masa={masa:.4f}"


def test_sin_mfa_el_bloque_ancho_se_queda_el_primer_eje():
    # Control, sin el cual el test anterior podria pasar por casualidad. Medido: 0,0003.
    A, B = _bloques_con_factor()
    X = np.hstack([A - A.mean(0), B - B.mean(0)])
    assert _masa_del_primer_eje_en(X, slice(0, 3)) < 0.01


def test_invariante_a_la_escala_del_bloque():
    # Que un bloque venga en dolares o en miles de dolares no puede cambiar el resultado.
    rng = np.random.default_rng(1)
    a, b = rng.normal(0, 1, (100, 4)), rng.normal(0, 1, (100, 6))
    np.testing.assert_allclose(normalizar_mfa([a, b]), normalizar_mfa([a * 1000, b]),
                               atol=1e-8)


def test_invariante_al_centrado():
    rng = np.random.default_rng(4)
    a, b = rng.normal(0, 1, (100, 4)), rng.normal(0, 1, (100, 6))
    np.testing.assert_allclose(normalizar_mfa([a, b]), normalizar_mfa([a + 500, b]),
                               atol=1e-8)


def test_primer_valor_singular_unitario_por_bloque():
    # La definicion de MFA, comprobada. La tolerancia es 1e-4 y no 1e-6 porque
    # `randomized_svd` es aproximado por construccion —error medido ~1e-5— y la exactitud
    # de una constante de normalizacion es irrelevante: lo que importa es que los dos
    # bloques queden en la misma escala, no el septimo decimal.
    rng = np.random.default_rng(2)
    X = normalizar_mfa([rng.normal(0, 3, (150, 5)), rng.normal(0, 0.1, (150, 20))])
    for ini, fin in ((0, 5), (5, 25)):
        B = X[:, ini:fin]
        s = randomized_svd(B - B.mean(axis=0), n_components=1, random_state=0)[1][0]
        assert abs(s - 1.0) < 1e-4


def test_bloque_constante_no_revienta():
    X = normalizar_mfa([np.ones((10, 3)),
                        np.random.default_rng(3).normal(0, 1, (10, 2))])
    assert np.isfinite(X).all()
    assert not np.any(X[:, :3]), "un bloque constante debe quedar en cero, no en NaN"


def test_acepta_un_bloque_de_una_sola_columna():
    # `antiguedad_total` es exactamente eso, y es uno de los bloques reales.
    rng = np.random.default_rng(5)
    X = normalizar_mfa([rng.normal(0, 1, 50), rng.normal(0, 1, (50, 4))])
    assert X.shape == (50, 5) and np.isfinite(X).all()


def test_no_tiene_parametros_libres():
    # LA razon de ser de este modulo (correccion 2 de D-009): si hubiera un peso que
    # elegir, habria algo que afinar contra el salario, y el pre-registro se cae.
    import inspect
    firma = inspect.signature(normalizar_mfa).parameters
    assert set(firma) == {"bloques", "semilla"}, f"parametro nuevo: {set(firma)}"


def test_determinista():
    rng = np.random.default_rng(6)
    bloques = [rng.normal(0, 1, (80, 5)), rng.normal(0, 1, (80, 30))]
    np.testing.assert_allclose(normalizar_mfa(bloques), normalizar_mfa(bloques), atol=0)


def test_primer_valor_singular_de_un_bloque_constante_es_cero():
    assert primer_valor_singular(np.zeros((10, 4))) == 0.0
