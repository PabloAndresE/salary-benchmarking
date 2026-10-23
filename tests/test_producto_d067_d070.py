"""D-067..D-070: corrector de tipeo, reglas de palabras de sinonimos y cortes de confianza por ancho."""
from src.domain import sinonimos
from src.domain.base_referencia import CONF_ANCHO_ALTA, CONF_ANCHO_BAJA
from src.domain.tipeo import Corrector, distancia


def test_distancia_cuenta_la_transposicion_como_uno():
    assert distancia("BODEGA", "BODGEA") == 1
    assert distancia("CONTADOR", "CONTDOR") == 1


def test_el_tipeo_se_corrige_y_lo_ajeno_no():
    c = Corrector(["CONTADOR GENERAL", "GERENTE GENERAL", "ANALISTA DE SISTEMAS"], [100, 80, 50],
                  protegidas={"GERENTE"})
    assert c.titulo("CONTDOR GENERL") == "CONTADOR GENERAL"
    assert c.titulo("ANALISTA DE SISTEMSA") == "ANALISTA DE SISTEMAS"
    assert c.titulo("ASDFGH QWERTY") is None
    assert c.titulo("CONTADOR GENERAL") is None          # sin cambios -> None


def test_las_reglas_de_palabras_del_autor():
    assert sinonimos.canonico("JEFE DE RRHH") == "JEFE DE RECURSOS HUMANOS"
    assert sinonimos.canonico("GERENTE DE TALENTO HUMANO") == "GERENTE DE RECURSOS HUMANOS"
    assert sinonimos.canonico("ANALISTA DE TI") == "ANALISTA DE SISTEMAS"
    assert sinonimos.canonico("CONDUCTORA") == "CHOFER"
    assert sinonimos.canonico("TITULAR") == "TITULAR"     # TI dentro de otra palabra no se toca


def test_cortes_de_confianza_por_ancho_publicados():
    assert (CONF_ANCHO_ALTA, CONF_ANCHO_BAJA) == (2.0, 3.0)


def test_d091_manager_es_jefe_y_head_es_gerente():
    from src.domain.idioma import invertir_rangos
    assert invertir_rangos("SALES MANAGER") == "SALES CHIEF"                 # -> JEFE DE VENTAS
    assert invertir_rangos("HEAD OF HR") == "HR MANAGER"                     # -> GERENTE DE RECURSOS HUMANOS
    assert invertir_rangos("HEAD OF INSURANCE - CONSULTING") == "INSURANCE MANAGER"
    assert invertir_rangos("GENERAL MANAGER") == "GENERAL MANAGER"           # sigue siendo Gerente General
    assert invertir_rangos("MANAGING DIRECTOR") == "MANAGING DIRECTOR"
    assert invertir_rangos("JEFE DE VENTAS") == "JEFE DE VENTAS"             # en espanol no se toca
