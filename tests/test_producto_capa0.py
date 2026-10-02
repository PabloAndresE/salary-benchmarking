"""Capa 0 (D-040): una sola funcion de texto, igual al construir y al consultar."""
from collections import Counter

import numpy as np
import pandas as pd

from benchmarking.producto.base_referencia import BaseReferencia
from benchmarking.producto.base_referencia import (_fusionar_capa0, _fusionar_erratas,
                                                  _fusionar_genero)
from benchmarking.producto.capa0 import (Capa0, compatibles, grado_numerico, limpiar,
                                         proponer_erratas, quitar_grado_final,
                                         quitar_letra_final)
from benchmarking.producto.nivel import nivel_rubrica, seniority_lexica


def _sbu(anio):
    return 470.0


# --- las cuatro que pidio el autor -------------------------------------------------------
def test_casero_no_se_corrige_aunque_haya_mil_cajero():
    # CASERO no llega ni a candidato (otra clave fonetica, y la distancia solo mira 7+
    # letras); el diccionario es la segunda barrera. CARIDAD -> CALIDAD si es candidato
    # (7 letras, distancia 1) y es la proteccion del diccionario la que lo para.
    frec = Counter({"CAJERO": 1000, "CASERO": 3, "CAGERO": 2,
                    "CALIDAD": 1000, "CARIDAD": 2, "CALIDDA": 1})
    diccionario = {"CAJERO", "CASERO", "CALIDAD", "CARIDAD"}
    propuestas, descartes = proponer_erratas(frec, diccionario)
    assert "CASERO" not in propuestas
    assert "CARIDAD" not in propuestas
    assert descartes["existe en el diccionario"] >= 1
    assert propuestas.get("CAGERO") == "CAJERO"   # errata fonetica (G ante E suena J)
    assert propuestas.get("CALIDDA") == "CALIDAD"


def test_una_errata_en_dos_palabras_del_mismo_titulo():
    c = Capa0(erratas={"ASISNTENTE": "ASISTENTE", "CONTABILIDA": "CONTABILIDAD"})
    c.preparar(["ASISTENTE DE CONTABILIDAD", "ASISNTENTE DE CONTABILIDA"])
    assert c.atomo("ASISNTENTE DE CONTABILIDA") == c.atomo("ASISTENTE DE CONTABILIDAD")


def test_una_abreviatura_antes_de_quitar_el_punto():
    c = Capa0(abreviaturas={"ASIST.": "ASISTENTE", "SUPERV.": "SUPERVISOR"})
    c.preparar(["ASISTENTE CONTABLE", "SUPERVISOR DE CALIDAD"])
    assert c.atomo("ASIST. CONTABLE") == "ASISTENTE CONTABLE"
    assert c.atomo("SUPERV.DE CALIDAD") == "SUPERVISOR DE CALIDAD"   # punto pegado


def test_un_plural():
    c = Capa0().preparar(["ASESOR DE VENTA", "ASESOR DE VENTAS", "OPERADOR", "OPERADORES",
                          "ANALISIS DE DATOS"])
    assert c.atomo("ASESOR DE VENTAS") == c.atomo("ASESOR DE VENTA")
    assert c.atomo("OPERADORES") == "OPERADOR"
    assert c.atomo("ANALISIS DE DATOS").startswith("ANALISIS")      # -IS no se toca


# --- el resto de la capa 0 ----------------------------------------------------------------
def test_codigo_inicial_y_puntuacion():
    assert limpiar("09.01 ANALISTA DE COSTOS") == "ANALISTA DE COSTOS"
    assert limpiar("1. JEFE DE COMPRAS") == "JEFE DE COMPRAS"
    assert limpiar("3 LANCHERO") == "LANCHERO"
    assert limpiar("ASIST-CONTABLE") == "ASIST CONTABLE"
    assert limpiar("123") == "123"                                  # no se borra todo


def test_las_letras_se_fusionan_y_los_numeros_no():                 # D-041
    c = Capa0().preparar(["AYUDANTE", "AUXILIAR DE COCINA 2"])
    assert c.atomo("AYUDANTE A") == c.atomo("AYUDANTE B") == c.atomo("AYUDANTE (C)") \
        == "AYUDANTE"
    assert c.atomo("AUXILIAR DE COCINA 2") == "AUXILIAR DE COCINA 2"
    assert c.atomo("QUIMICO II") == "QUIMICO II"
    assert quitar_letra_final("JEFE V") == "JEFE V"                     # romano, no letra
    assert quitar_letra_final("COORDINADOR M & R") == "COORDINADOR M & R"
    assert quitar_letra_final("CHOFER LICENCIA C") == "CHOFER LICENCIA C"
    assert quitar_letra_final("OPERARIO CATEGORIA B") == "OPERARIO"
    assert Capa0(letras=False).preparar([]).atomo("AYUDANTE B") == "AYUDANTE B"


def test_el_grado_numerico_esta_apagado_por_defecto_y_con_guardas_si_se_enciende():
    assert quitar_grado_final("AUXILIAR DE COCINA 2") == "AUXILIAR DE COCINA"
    assert quitar_grado_final("QUIMICO II") == "QUIMICO"
    assert quitar_grado_final("OPERARIO CATEGORIA B") == "OPERARIO"
    assert quitar_grado_final("COORDINADOR M & R") == "COORDINADOR M & R"   # sigla
    assert quitar_grado_final("CHOFER LICENCIA C") == "CHOFER LICENCIA C"   # tipo
    assert quitar_grado_final("JEFE DE VENTAS") == "JEFE DE VENTAS"
    c = Capa0(grado=True).preparar(["AUXILIAR DE COCINA"])
    assert c.atomo("AUXILIAR DE COCINA 3") == "AUXILIAR DE COCINA"


def test_candado_de_grado():
    assert grado_numerico("AUXILIAR 2") == {2}
    assert grado_numerico("AUXILIAR 2 DE CONTABILIDAD") == {2}
    assert grado_numerico("TECNICO2") == {2}
    assert grado_numerico("QUIMICO II") == {2}
    assert grado_numerico("1. JEFE DE COMPRAS") == set()            # codigo de planilla
    assert grado_numerico("JEFE DE I+D") == set()
    assert grado_numerico("COORDINADOR ZONA 2") == set()            # lugar, no grado
    assert grado_numerico("EJECUTIVO ASISTENTE (OFC 1)") == set()
    assert grado_numerico("ASISTENTE DE OFICINA 2") == {2}          # OFICINA no es guarda
    assert not compatibles("AUXILIAR 1", "AUXILIAR 2")
    assert not compatibles("QUIMICO I", "QUIMICO II")
    assert compatibles("AUXILIAR", "AUXILIAR 2")                    # sin numero no bloquea
    assert compatibles("AYUDANTE A", "AYUDANTE B")


def test_el_candado_bloquea_aunque_la_pasada_quiera_juntar():
    celdas = ["AUXILIAR 1", "AUXILIAR 2", "AUXILIAR"]
    gnum = [grado_numerico(c) for c in celdas]
    grupo = np.arange(3)
    # un diccionario que se colara un numero daria el mismo atomo a los tres
    nuevo, k = _fusionar_capa0(["AUXILIAR"] * 3, grupo, grados=gnum)
    assert nuevo[0] != nuevo[1]
    assert k == 1                                     # el sin numero se une a uno solo
    nuevo, _ = _fusionar_capa0(["AUXILIAR"] * 3, grupo)          # sin candado, los tres
    assert len(set(nuevo)) == 1
    # genero: OPERARIA 2 y OPERARIO 3 son par de genero, pero el numero los separa
    celdas = ["OPERARIA 2", "OPERARIO 3"]
    gnum = [grado_numerico(c) for c in celdas]
    niv = np.array([np.nan, np.nan])
    nuevo, pares = _fusionar_genero(celdas, np.arange(2), niv, {0: 5, 1: 5}, grados=gnum)
    assert nuevo[0] != nuevo[1] and not pares
    nuevo, pares = _fusionar_genero(["OPERARIA 2", "OPERARIO 2"], np.arange(2), niv,
                                    {0: 5, 1: 5}, grados=[{2}, {2}])
    assert nuevo[0] == nuevo[1]
    # errata: el raro no se absorbe en un comun con otro numero
    celdas = ["SUPERVISOR DE BODEGA 1", "SUPERVISOR DE BODEGA 2"]
    nuevo, k = _fusionar_erratas(celdas, np.arange(2), niv, {0: 40, 1: 1},
                                 grados=[grado_numerico(c) for c in celdas])
    assert k == 0


def test_la_errata_solo_se_aplica_si_el_titulo_corregido_existe():
    c = Capa0(erratas={"VENDEROR": "VENDEDOR"}).preparar(["VENDEDOR"])
    assert c.atomo("VENDEROR") == "VENDEDOR"
    assert c.atomo("VENDEROR DE AUTOS") == "VENDEROR DE AUTO" or \
        c.atomo("VENDEROR DE AUTOS").startswith("VENDEROR")         # destino inexistente


def test_genero_por_palabra():
    c = Capa0(genero={"VENDEDORA": "VENDEDOR"}).preparar(["VENDEDOR", "VENDEDORA"])
    assert c.atomo("VENDEDORA") == c.atomo("VENDEDOR")


# --- el nivel de la rubrica (criterio C) ---------------------------------------------------
def test_nivel_rubrica():
    assert nivel_rubrica("ASISTENTE DE GERENTE") == 1         # tras DE no cuenta
    assert nivel_rubrica("AUXILIAR TECNICO DE BODEGA") == 1   # TECNICO no abre el titulo
    assert nivel_rubrica("TECNICO ESPECIALISTA") == 2
    assert nivel_rubrica("ASSISTANT MANAGER") == 4
    assert nivel_rubrica("SUBJEFE DE ALMACEN") == 3
    assert nivel_rubrica("JEFA DE COMPRAS") == 4
    assert nivel_rubrica("VENDEDOR") is None                  # sin nivel: no bloquea
    assert seniority_lexica("ANALISTA SEMISENIOR") == 0.5
    assert seniority_lexica("ANALISTA SEMI SENIOR") == 0.5


# --- construir y consultar con la MISMA funcion -------------------------------------------
def _base_con_capa0(capa0, umbral=None):
    filas = [(f"E{i}", "ASISTENTE CONTABLE", 1.0 + 0.01 * (i % 5)) for i in range(12)]
    filas += [(f"F{i}", "ASIST. CONTABLE", 1.05 + 0.01 * (i % 5)) for i in range(11)]
    filas += [(f"G{i}", "CHOFER", 0.7 + 0.01 * (i % 5)) for i in range(12)]
    marco = pd.DataFrame(filas, columns=["empresa_ruc", "cargo_norm", "y"])
    emb = {"ASISTENTE CONTABLE": np.array([1.0, 0.0]), "ASIST. CONTABLE": np.array([0.0, 1.0]),
           "CHOFER": np.array([0.7, -0.7]), "ASIST CONTABLE": np.array([0.5, 0.5])}
    return BaseReferencia.construir(marco, emb, _sbu, umbral_fusion=umbral,
                                    capa0=capa0), emb


def test_la_capa0_agrupa_al_construir_aunque_no_haya_fusion_por_coseno():
    b, _ = _base_con_capa0(Capa0(abreviaturas={"ASIST.": "ASISTENTE"}))
    i, j = b.idx["ASISTENTE CONTABLE"], b.idx["ASIST. CONTABLE"]
    assert b.grupo[i] == b.grupo[j]
    assert b.grupo[i] != b.grupo[b.idx["CHOFER"]]


def test_la_consulta_usa_la_misma_capa0_que_la_construccion(tmp_path):
    b, emb = _base_con_capa0(Capa0(abreviaturas={"ASIST": "ASISTENTE",
                                                 "ASIST.": "ASISTENTE"}))
    r = b.referenciar(["ASIST CONTABLE"], emb).iloc[0]       # no esta tal cual en la base
    assert r["base"] == "datos directos"
    assert r["cargo_base"] in ("ASISTENTE CONTABLE", "ASIST. CONTABLE")
    ruta = tmp_path / "b.npz"
    b.guardar(ruta)
    b2 = BaseReferencia.cargar(ruta, _sbu)
    assert b2.capa0 is not None and b2.capa0.abreviaturas == b.capa0.abreviaturas
    r2 = b2.referenciar(["ASIST CONTABLE"], emb).iloc[0]
    assert r2["cargo_base"] == r["cargo_base"]


def test_sin_capa0_la_base_se_comporta_como_antes():
    b, emb = _base_con_capa0(None, umbral=None)
    assert b.capa0 is None
    assert b.grupo[b.idx["ASISTENTE CONTABLE"]] != b.grupo[b.idx["ASIST. CONTABLE"]]
    assert b.referenciar(["ASIST CONTABLE"], emb).iloc[0]["cargo_base"] == ""
