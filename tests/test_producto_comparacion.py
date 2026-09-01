import numpy as np
import pandas as pd
from benchmarking.producto.comparacion import anclar, comparar, texto_resumen


def _sbu(anio):
    return 470.0


def test_el_ancla_detecta_el_nivel_de_la_empresa():
    # Todos cobran un 20% por encima de su referencia: el ancla debe ser log(1,2).
    ref = pd.Series([0.5, 1.0, 1.5, 0.8, 1.2])
    y = ref + np.log(1.2)
    ancla, n, nivel = anclar(y, ref, ["ALTA"] * 5)
    assert n == 5 and abs(np.exp(nivel) - 1.2) < 1e-9


def test_el_ancla_deja_fuera_a_la_propia_persona():
    # Si el ancla incluyera a Juan, Juan siempre pareceria normal y el diagnostico de
    # equidad interna no detectaria nada. EL punto del leave-one-out.
    ref = pd.Series([1.0] * 6)
    y = pd.Series([1.1, 1.1, 1.1, 1.1, 1.1, 3.0])       # el ultimo cobra muchisimo mas
    ancla, _, _ = anclar(y, ref, ["ALTA"] * 6)
    assert abs(ancla.iloc[5] - 0.1) < 1e-9, "su ancla debe salir de los OTROS"
    assert ancla.iloc[5] < 0.2, "no puede arrastrar su propio exceso al ancla"


def test_el_ancla_ignora_las_referencias_flojas():
    # Anclar sobre analogias lejanas propaga ruido al numero que corrige a todos.
    ref = pd.Series([1.0, 1.0, 1.0, 1.0])
    y = pd.Series([1.1, 1.1, 1.1, 5.0])
    _, n, nivel = anclar(y, ref, ["ALTA", "ALTA", "ALTA", "BAJA"])
    assert n == 3 and abs(np.exp(nivel) - np.exp(0.1)) < 1e-9


def test_mercado_y_politica_interna_son_preguntas_distintas():
    # La empresa paga +20% en general. Un contador justo en la referencia de mercado
    # esta EN LINEA con el mercado y POR DEBAJO de su propia casa.
    df = pd.DataFrame({"cargo": ["A", "B", "C", "CONTADOR"],
                       "sueldo": [np.exp(1.0 + np.log(1.2)) * 470,
                                  np.exp(1.2 + np.log(1.2)) * 470,
                                  np.exp(0.8 + np.log(1.2)) * 470,
                                  np.exp(1.0) * 470]})
    ref = [1.0, 1.2, 0.8, 1.0]
    det, _, res = comparar(df, "sueldo", "cargo", ref, ["ALTA"] * 4, _sbu, 2025)
    c = det[det.cargo == "CONTADOR"].iloc[0]
    assert abs(c["vs_mercado"]) < 0.01, "frente al mercado esta en linea"
    assert c["vs_politica_interna"] < -0.10, "frente a su casa esta por debajo"
    assert abs(res["nivel_vs_mercado"] - 0.2) < 0.05


def test_detecta_puestos_fuera_de_linea():
    df = pd.DataFrame({"cargo": ["BARATO", "NORMAL", "CARO"],
                       "sueldo": [np.exp(0.5) * 470, np.exp(1.0) * 470, np.exp(2.0) * 470]})
    _, puesto, _ = comparar(df, "sueldo", "cargo", [1.0, 1.0, 1.0], ["ALTA"] * 3,
                            _sbu, 2025)
    p = puesto.set_index("cargo")
    assert p.loc["BARATO", "lectura"] == "muy por debajo"
    assert p.loc["CARO", "lectura"] == "muy por encima"
    assert p.loc["NORMAL", "lectura"] == "en linea"


def test_avisa_cuando_el_ancla_es_ruido():
    df = pd.DataFrame({"cargo": ["A", "B"], "sueldo": [500.0, 600.0]})
    _, puesto, res = comparar(df, "sueldo", "cargo", [1.0, 1.0], ["ALTA"] * 2, _sbu, 2025)
    assert res["ancla_fiable"] is False
    assert "ORIENTATIVO" in texto_resumen(res, puesto)


def test_sin_referencia_no_inventa_comparacion():
    df = pd.DataFrame({"cargo": ["X"], "sueldo": [500.0]})
    det, _, _ = comparar(df, "sueldo", "cargo", [np.nan], ["BAJA"], _sbu, 2025)
    assert det["lectura_mercado"].iloc[0] == "sin referencia"
