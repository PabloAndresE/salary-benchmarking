"""El contrato de entrada. Lo que mas se prueba es lo que RECHAZA."""
import pandas as pd
import pytest

from benchmarking.producto.formato import FormatoInvalido, validar


def test_el_minimo_es_solo_cargo():
    out, inf = validar(pd.DataFrame({"cargo": ["CONTADOR"]}))
    assert list(out.columns) == ["cargo"]
    assert inf["columnas_reconocidas"] == ["cargo"]


def test_sin_cargo_no_hay_informe():
    with pytest.raises(FormatoInvalido, match="obligatorias"):
        validar(pd.DataFrame({"sueldo": ["1500"]}))


def test_se_perdonan_mayusculas_tildes_y_espacios_pero_nada_mas():
    # Un caracter invisible no es ambiguedad; un nombre distinto si lo es.
    out, _ = validar(pd.DataFrame({"Cargo ": ["X"], " FECHA INGRESO": ["01/01/2020"],
                                   "Centro Costo": ["A"]}))
    assert set(out.columns) == {"cargo", "fecha_ingreso", "centro_costo"}
    _, inf = validar(pd.DataFrame({"cargo": ["X"], "puesto_2": ["Y"]}))
    assert inf["columnas_desconocidas"] == ["puesto_2"], "no se adivina"


def test_la_cedula_se_RECHAZA_y_no_se_ignora():
    # Es una garantia, no una omision: aceptarla en silencio la convertiria en intencion.
    for col in ("cedula", "Identificación", "DNI", "RUC"):
        with pytest.raises(FormatoInvalido, match="identificadores personales"):
            validar(pd.DataFrame({"cargo": ["X"], col: ["1712345678"]}))
    # id_empleado si, que es del cliente
    out, _ = validar(pd.DataFrame({"cargo": ["X"], "id_empleado": ["E-001"]}))
    assert "id_empleado" in out.columns


def test_se_reportan_TODOS_los_problemas_de_una_vez():
    # Devolver el primero obliga a subir el archivo cinco veces para hallar cinco fallos.
    with pytest.raises(FormatoInvalido) as e:
        validar(pd.DataFrame({"sueldo": ["1"], "cedula": ["17"]}))
    assert len(e.value.problemas) == 2


def test_las_columnas_de_mas_no_rompen_pero_se_declaran():
    out, inf = validar(pd.DataFrame({"cargo": ["X"], "mi_campo": ["a"]}))
    assert "mi_campo" in out.columns, "se devuelven tal cual"
    assert inf["columnas_desconocidas"] == ["mi_campo"]
    assert any("se ignoran" in a for a in inf["avisos"])


def test_el_sexo_se_normaliza_y_lo_raro_se_cuenta():
    out, inf = validar(pd.DataFrame({"cargo": list("abcde"),
                                     "sexo": ["M", "femenino", "Mujer", "X", ""]}))
    assert list(out["sexo"][:3]) == ["M", "F", "F"]
    assert out["sexo"].iloc[3] is None, "lo no reconocido no se cuela como categoria"
    assert inf["sexo_no_reconocido"] == 1


def test_avisa_si_los_sueldos_parecen_no_ser_sueldos():
    # Pensiones de $30 comparadas contra el mercado salarial darian -95% con banda y
    # etiqueta de confianza: un disparate bien presentado.
    _, inf = validar(pd.DataFrame({"cargo": ["a", "b"], "sueldo": ["22.5", "30"]}))
    assert any("salario basico" in a for a in inf["avisos"])
    _, inf2 = validar(pd.DataFrame({"cargo": ["a", "b"], "sueldo": ["600", "800"]}))
    assert not any("salario basico" in a for a in inf2["avisos"])


def test_avisa_de_las_fechas_ilegibles():
    _, inf = validar(pd.DataFrame({"cargo": ["a", "b", "c"],
                                   "fecha_ingreso": ["01/01/2020", "ayer", None]}))
    assert inf["fechas_ilegibles"] == 1
    assert any("dd/mm/aaaa" in a for a in inf["avisos"])
