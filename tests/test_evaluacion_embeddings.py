from unittest.mock import MagicMock

import numpy as np
from benchmarking.evaluacion.embeddings import CacheArchivo, CacheMemoriaEmb, embeber


def _cliente_falso():
    cl = MagicMock()
    cl.get_embeddings.side_effect = lambda textos: [
        MagicMock(values=[float(len(t)), 1.0, 0.0, 0.0]) for t in textos]
    return cl


def _enviados(cl):
    return sorted(t for c in cl.get_embeddings.call_args_list for t in c.args[0])


def test_solo_embebe_textos_unicos():
    # 68.504 titulos distintos entre 1,14 M de filas: embeber por fila seria 17x mas caro.
    cl = _cliente_falso()
    X = embeber(["VENDEDOR", "VENDEDOR", "CONTADOR", "VENDEDOR"], cl, "m")
    assert X.shape == (4, 4)
    assert _enviados(cl) == ["CONTADOR", "VENDEDOR"]
    np.testing.assert_array_equal(X[0], X[1])          # filas repetidas, mismo vector


def test_las_filas_quedan_alineadas_con_la_entrada():
    cl = _cliente_falso()
    textos = ["CONTADOR", "VENDEDOR", "CONTADOR"]
    X = embeber(textos, cl, "m")
    assert X[0][0] == len("CONTADOR") and X[1][0] == len("VENDEDOR")
    np.testing.assert_array_equal(X[0], X[2])


def test_el_cache_evita_volver_a_llamar():
    cache, cl = CacheMemoriaEmb(), _cliente_falso()
    embeber(["VENDEDOR"], cl, "m", cache=cache)
    n1 = cl.get_embeddings.call_count
    embeber(["VENDEDOR"], cl, "m", cache=cache)
    assert cl.get_embeddings.call_count == n1


def test_la_revision_del_modelo_entra_en_la_clave():
    # Si Google cambia el modelo, el cache no debe devolver vectores del anterior.
    cache, cl = CacheMemoriaEmb(), _cliente_falso()
    embeber(["VENDEDOR"], cl, "modelo-A", cache=cache)
    n1 = cl.get_embeddings.call_count
    embeber(["VENDEDOR"], cl, "modelo-B", cache=cache)
    assert cl.get_embeddings.call_count > n1


def test_el_tipo_de_tarea_entra_en_la_clave():
    # CLUSTERING y SEMANTIC_SIMILARITY devuelven vectores distintos para el mismo texto:
    # mezclarlos en un cache seria comparar cosas que no son comparables.
    cache, cl = CacheMemoriaEmb(), _cliente_falso()
    embeber(["VENDEDOR"], cl, "m", cache=cache, tarea="CLUSTERING")
    n1 = cl.get_embeddings.call_count
    embeber(["VENDEDOR"], cl, "m", cache=cache, tarea="SEMANTIC_SIMILARITY")
    assert cl.get_embeddings.call_count > n1


def test_respeta_el_tamano_de_lote():
    cl = _cliente_falso()
    embeber([f"CARGO{i}" for i in range(7)], cl, "m", lote=3)
    assert [len(c.args[0]) for c in cl.get_embeddings.call_args_list] == [3, 3, 1]


def test_el_cache_en_archivo_sobrevive_al_proceso(tmp_path):
    # El de memoria se pierde al terminar, y volver a embeber 68.504 etiquetas cuesta
    # dinero y rompe la reproducibilidad del resultado.
    ruta = tmp_path / "emb.npz"
    cl = _cliente_falso()
    cache = CacheArchivo(ruta)
    X1 = embeber(["VENDEDOR", "CONTADOR"], cl, "m", cache=cache)
    cache.volcar()
    n1 = cl.get_embeddings.call_count

    cl2 = _cliente_falso()
    X2 = embeber(["VENDEDOR", "CONTADOR"], cl2, "m", cache=CacheArchivo(ruta))
    assert cl2.get_embeddings.call_count == 0, "deberia salir entero del archivo"
    np.testing.assert_allclose(X1, X2)
    assert n1 > 0


def test_el_cache_en_archivo_no_escribe_si_no_hay_nada_nuevo(tmp_path):
    ruta = tmp_path / "emb.npz"
    cache = CacheArchivo(ruta)
    cache.volcar()
    assert not ruta.exists(), "un cache vacio no debe crear el archivo"
