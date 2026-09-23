import numpy as np
import pandas as pd
from benchmarking.producto.nivel import (ClasificadorNivel, escalera_salarial,
                                         etiquetar, nivel_lexico,
                                         seniority_lexica)


def test_lee_el_rango_del_titulo():
    assert nivel_lexico("AUXILIAR DE BODEGA") == 1
    assert nivel_lexico("TECNICO ELECTRICISTA") == 2
    assert nivel_lexico("SUPERVISOR DE PLANTA") == 3
    assert nivel_lexico("JEFE DE CAJA") == 4
    assert nivel_lexico("GERENTE GENERAL") == 5


def test_sin_palabra_de_rango_devuelve_nada():
    # El 49% de las etiquetas. Son las que el clasificador tiene que resolver.
    for e in ("CONTADOR", "VENDEDOR", "CHOFER", "MEDICO OCUPACIONAL"):
        assert nivel_lexico(e) is None


def test_con_dos_rangos_gana_el_mas_alto():
    # `JEFE TECNICO` es un jefe. Falla en `ASISTENTE DE GERENCIA`, y se acepta: la
    # alternativa —descartar los titulos con dos rangos— tira senal util.
    assert nivel_lexico("JEFE TECNICO DE MANTENIMIENTO") == 4
    assert nivel_lexico("GERENTE Y JEFE DE AREA") == 5


def test_tolera_plurales_y_minusculas():
    assert nivel_lexico("auxiliares de limpieza") == 1
    assert nivel_lexico("Supervisores de Ruta") == 3


def test_no_confunde_subcadenas():
    # `SUBGERENTE` no debe leerse como `GERENTE` (4, no 5).
    assert nivel_lexico("SUBGERENTE COMERCIAL") == 4


def test_etiquetar_deja_nulos_donde_no_hay_rango():
    s = etiquetar(["JEFE DE X", "CONTADOR", "AUXILIAR Y"])
    assert s["JEFE DE X"] == 4 and s["AUXILIAR Y"] == 1
    assert pd.isna(s["CONTADOR"])


def _caso_separable(n=60, semilla=0):
    """Cinco niveles separables en el espacio de embedding."""
    rng = np.random.default_rng(semilla)
    X, y = [], []
    for nivel in (1, 2, 3, 4, 5):
        centro = np.zeros(6)
        centro[nivel - 1] = 1.0
        X.append(centro + rng.normal(0, 0.15, (n, 6)))
        y += [nivel] * n
    return np.vstack(X), np.array(y)


def test_el_clasificador_aprende_niveles_separables():
    X, y = _caso_separable()
    c = ClasificadorNivel().entrenar(X[::2], y[::2])
    assert (c.predecir(X[1::2]) == y[1::2]).mean() > 0.9


def test_el_nivel_esperado_es_continuo_y_ordena():
    X, y = _caso_separable()
    c = ClasificadorNivel().entrenar(X, y)
    esp = c.nivel_esperado(X)
    assert esp.min() >= 1.0 and esp.max() <= 5.0
    # el nivel esperado debe crecer con el nivel verdadero
    medias = [esp[y == k].mean() for k in (1, 2, 3, 4, 5)]
    assert all(b > a for a, b in zip(medias, medias[1:]))


def test_la_escalera_detecta_orden_monotono():
    # LA prueba del producto: .el nivel predicho ordena el salario?
    niveles = np.repeat([1, 2, 3, 4, 5], 20)
    y = np.repeat([0.0, 0.3, 0.6, 1.0, 1.5], 20) + np.random.default_rng(1).normal(0, .05, 100)
    g, recorrido, monotona = escalera_salarial(niveles, y)
    assert monotona and abs(recorrido - np.exp(1.5)) < 0.3


def test_la_escalera_no_se_inventa_orden_donde_no_lo_hay():
    niveles = np.repeat([1, 2, 3, 4, 5], 20)
    y = np.random.default_rng(2).normal(0, .5, 100)
    _, _, monotona = escalera_salarial(niveles, y)
    assert not monotona


def test_enmascarar_quita_el_rango_y_deja_el_resto():
    from benchmarking.producto.nivel import enmascarar
    assert enmascarar("AUXILIAR DE BODEGA") == "PUESTO DE BODEGA"
    assert enmascarar("JEFE DE BODEGA") == "PUESTO DE BODEGA"
    assert enmascarar("GERENTE GENERAL") == "PUESTO GENERAL"


def test_dos_titulos_de_distinto_rango_e_igual_area_quedan_iguales():
    # ESA es la razon de existir del enmascarado: el modelo no puede distinguirlos por la
    # palabra, tiene que inferir el nivel del resto — o admitir que no sabe.
    from benchmarking.producto.nivel import enmascarar
    assert enmascarar("AUXILIAR DE CAJA") == enmascarar("SUPERVISOR DE CAJA")


def test_un_titulo_sin_rango_no_se_toca():
    from benchmarking.producto.nivel import enmascarar
    assert enmascarar("CONTADOR") == "CONTADOR"
    assert enmascarar("trabajador agricola") == "TRABAJADOR AGRICOLA"


def test_el_efecto_de_nivel_se_mide_dentro_del_area():
    # Contraste sin confusion: la misma area con dos rangos. Si se midiera ENTRE areas se
    # mezclaria "los jefes cobran mas" con "contabilidad paga mas que bodega".
    from benchmarking.producto.nivel import efecto_nivel
    filas = []
    for area, base in (("BODEGA", 0.0), ("CONTABLE", 1.0)):   # areas con niveles distintos
        for nivel, palabra, extra in ((1, "AUXILIAR", 0.0), (4, "JEFE", 0.6)):
            for e in range(20):
                filas.append({"cargo_norm": f"{palabra} DE {area}", "empresa_ruc": f"E{e}",
                              "y": base + extra})
    ef = efecto_nivel(pd.DataFrame(filas))
    assert set(ef) == {1, 4}
    assert ef[4] - ef[1] > 0.5, "debe recuperar los 0,6 de diferencia por escalon"


def test_el_efecto_de_nivel_ignora_las_areas_de_un_solo_rango():
    # Un area donde solo hay auxiliares no dice nada sobre cuanto vale ser jefe.
    from benchmarking.producto.nivel import efecto_nivel
    filas = [{"cargo_norm": "AUXILIAR DE X", "empresa_ruc": f"E{e}", "y": 0.0}
             for e in range(20)]
    assert efecto_nivel(pd.DataFrame(filas)) == {}


def test_operador_cuenta_como_operario():
    # 40.962 personas. Sinonimo de OPERARIO, que ya estaba: era un descuido.
    assert nivel_lexico("OPERADOR DE PARQUEADERO") == 1
    assert nivel_lexico("OPERADOR DE MAQUINARIA") == 1


def test_ejecutivo_NO_es_nivel_directivo():
    # Falsa amistad del idioma: `EJECUTIVO DE VENTAS` es un vendedor en Ecuador, no un
    # directivo. Meterlo mandaria 17.000 personas al escalon 5 por error.
    assert nivel_lexico("EJECUTIVO DE VENTAS") is None


def test_las_ocupaciones_sin_rango_siguen_sin_nivel():
    # No es un hueco del diccionario: un DOCENTE no es ni auxiliar ni gerente.
    for e in ("TRABAJADOR AGRICOLA", "DOCENTE", "CHOFER", "GUARDIA", "MEDICO OCUPACIONAL"):
        assert nivel_lexico(e) is None


# --- el candado de seniority ------------------------------------------------
# Es un modificador DENTRO del escalon, no un escalon. Validado contra 48 pares de
# la banda 0,93-0,97 juzgados a mano: caza 5 de los 12 `no` sin romper ninguno de
# los 36 `si`. Ver `research/experimentos/e2_nivel/13a`.

def test_la_seniority_no_cambia_el_escalon():
    # `SUPERVISOR DE CALIDAD SR` sigue siendo un supervisor. Si `SR` entrara en
    # `RANGOS` romperia la escalera, que esta medida sobre cinco escalones.
    assert nivel_lexico("SUPERVISOR DE CALIDAD SR") == 3
    assert nivel_lexico("SUPERVISOR DE CALIDAD") == 3


def test_lee_la_marca_de_seniority():
    assert seniority_lexica("SUPERVISOR DE CALIDAD SR") > 0
    assert seniority_lexica("ANALISTA JUNIOR DE RIESGOS") < 0
    assert seniority_lexica("SOUS CHEF DE COCINA") < 0
    assert seniority_lexica("SUPERVISOR DE CALIDAD") == 0


def test_separa_lo_que_un_humano_separa():
    # Los cinco pares que el candado existe para cazar, de los 48 juzgados.
    for a, b in (("SUPERVISOR CALIDAD", "SUPERVISOR DE CALIDAD SR"),
                 ("CHEF DE COCINA", "SOUS CHEF DE COCINA"),
                 ("ANALISTA INTELIGENCIA DE NEGOCIOS",
                  "ANALISTA JUNIOR - INTELIGENCIA DE NEGOCIOS"),
                 ("GERENTE DE INGENIERIA INDUSTRIAL",
                  "GERENTE CORPORATIVO DE INGENIERIA")):
        assert seniority_lexica(a) != seniority_lexica(b), (a, b)


def test_no_separa_lo_que_un_humano_junta():
    # `GENERAL` y los numeros se probaron y se dejaron FUERA: con ellos dentro,
    # estos pares se romperian y estan juzgados como el mismo puesto.
    for a, b in (("SUPERVISOR DE ETIQUETADO", "SUPERVISOR GENERAL DE ETIQUETADO"),
                 ("TECNICO MECANICO A", "TECNICO MECANICO I"),
                 ("JEFE SERVICIOS", "JEFE DE SERVICIOS GENERAL"),
                 ("ASISTENTE DE TESORERIA JR.", "ASISTENTE DE TESORERIA JUNIOR")):
        assert seniority_lexica(a) == seniority_lexica(b), (a, b)


def test_no_confunde_subcadenas_de_seniority():
    # Los limites de palabra son lo que impide que una subcadena cuele. `ASESORA`
    # contiene `SR`? no, pero `SENIORITY` si contiene `SENIOR`, y no debe contar:
    # es otra palabra.
    assert seniority_lexica("ASESORA DE SERVICIOS") == 0
    assert seniority_lexica("SENIORITY MANAGER") == 0
    assert seniority_lexica("JEFE DE CORPORATIVIDAD") == 0
