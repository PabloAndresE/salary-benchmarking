import numpy as np
import pandas as pd
from benchmarking.producto.comparacion import (a_numero, anclar, comparar,
                                               texto_resumen)


def _sbu(anio):
    return 470.0


def _ref(refs, confianzas, ancho=0.2):
    """La salida minima de `referenciar`: referencia, confianza y las DOS bandas.

    `ancho` es la media anchura en log. Es un argumento porque el ancho de la banda ya no
    es decorativo: es lo que decide la lectura de mercado.
    """
    r = np.asarray(refs, dtype=float)
    a = np.asarray(ancho, dtype=float)
    d = {"referencia_log": r, "confianza": list(confianzas)}
    for pre in ("", "per"):
        for q, z in ((10, -2.0), (25, -1.0), (75, 1.0), (90, 2.0)):
            d[f"p{q}{pre}_log"] = r + z * a
    return pd.DataFrame(d)


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
    det, _, res = comparar(df, "sueldo", "cargo", _ref(ref, ["ALTA"] * 4), _sbu, 2025)
    c = det[det.cargo == "CONTADOR"].iloc[0]
    assert abs(c["vs_mercado"]) < 0.01, "frente al mercado esta en linea"
    assert c["vs_politica_interna"] < -0.10, "frente a su casa esta por debajo"
    assert abs(res["nivel_vs_mercado"] - 0.2) < 0.05


def test_detecta_puestos_fuera_de_linea():
    df = pd.DataFrame({"cargo": ["BARATO", "NORMAL", "CARO"],
                       "sueldo": [np.exp(0.5) * 470, np.exp(1.0) * 470, np.exp(2.0) * 470]})
    _, puesto, _ = comparar(df, "sueldo", "cargo",
                            _ref([1.0, 1.0, 1.0], ["ALTA"] * 3), _sbu, 2025)
    p = puesto.set_index("cargo")
    assert p.loc["BARATO", "lectura"] == "muy por debajo"
    assert p.loc["CARO", "lectura"] == "muy por encima"
    assert p.loc["NORMAL", "lectura"] == "en linea"


def test_avisa_cuando_el_ancla_es_ruido():
    df = pd.DataFrame({"cargo": ["A", "B"], "sueldo": [500.0, 600.0]})
    _, puesto, res = comparar(df, "sueldo", "cargo", _ref([1.0, 1.0], ["ALTA"] * 2), _sbu, 2025)
    assert res["ancla_fiable"] is False
    assert "ORIENTATIVO" in texto_resumen(res, puesto)


def test_sin_referencia_no_inventa_comparacion():
    df = pd.DataFrame({"cargo": ["X"], "sueldo": [500.0]})
    det, _, _ = comparar(df, "sueldo", "cargo", _ref([np.nan], ["BAJA"]), _sbu, 2025)
    assert det["lectura_mercado"].iloc[0] == "sin referencia"


def test_el_mismo_exceso_NO_significa_lo_mismo_en_dos_cargos():
    # EL defecto que esto arregla. Antes la lectura usaba cortes fijos de +/-5% y +/-15%
    # iguales para todo cargo, que es el mismo error que `tau` global: un umbral que tiene
    # que escalar con la dispersion del puesto, escrito como constante.
    #
    # Medido sobre la nomina de demo, cuatro de diez cargos marcados "muy por encima"
    # estaban DENTRO de su propia banda:
    #     GERENTE GENERAL      +15,4%  banda +/-95,0%   <- dentro, es un sueldo normal
    #     TRABAJADOR AGRICOLA  +15,5%  banda +/- 0,2%   <- muy fuera, es una anomalia
    exceso = np.log(1.15)
    df = pd.DataFrame({"cargo": ["ANCHO", "ESTRECHO"],
                       "sueldo": [np.exp(1.0 + exceso) * 470,
                                  np.exp(1.0 + exceso) * 470]})
    ref = _ref([1.0, 1.0], ["ALTA"] * 2, ancho=[0.60, 0.02])
    det, _, _ = comparar(df, "sueldo", "cargo", ref, _sbu, 2025)
    d = det.set_index("cargo")
    # el mismo +15% en los dos
    assert abs(d.loc["ANCHO", "vs_mercado"] - d.loc["ESTRECHO", "vs_mercado"]) < 1e-9
    # y lecturas distintas, que es lo correcto
    assert d.loc["ANCHO", "lectura_mercado"] == "en linea"
    assert d.loc["ESTRECHO", "lectura_mercado"] == "muy por encima"


def test_la_persona_se_compara_contra_la_banda_de_PERSONAS():
    # La banda de empresas no lleva `sigma` y es mas estrecha. Usarla junto al sueldo de
    # una persona la hace parecer mas rara de lo que es. `detalle` usa la de personas.
    df = pd.DataFrame({"cargo": ["X"], "sueldo": [np.exp(1.25) * 470]})
    r = _ref([1.0], ["ALTA"], ancho=0.10)          # banda de EMPRESAS estrecha
    for q, z in ((10, -2.0), (25, -1.0), (75, 1.0), (90, 2.0)):
        r[f"p{q}per_log"] = 1.0 + z * 0.40         # la de PERSONAS, mucho mas ancha
    det, _, _ = comparar(df, "sueldo", "cargo", r, _sbu, 2025)
    assert det["lectura_mercado"].iloc[0] == "en linea", "cae dentro de la de personas"


def test_lee_los_sueldos_como_los_escribe_rrhh():
    # `leer_nomina` lee con dtype=str, asi que esta es la UNICA conversion a numero. Con
    # `pd.to_numeric` a secas fallaba todo lo que no fuera ingles puro, y un Excel en
    # configuracion regional espanola escribe `1.500,64`.
    casos = {"1500.64": 1500.64, "1,500.64": 1500.64, "1.500,64": 1500.64,
             "$1500.64": 1500.64, "1 500,64": 1500.64, "1500,64": 1500.64,
             " 1500.64 ": 1500.64,
             # un solo separador con tres digitos detras es de MILES, no decimal
             "1.500": 1500.0, "1,500": 1500.0,
             "1,50": 1.5, "1.5": 1.5,
             "12.345.678,90": 12345678.90, "12,345,678.90": 12345678.90}
    got = a_numero(list(casos))
    for k, (txt, esperado) in enumerate(casos.items()):
        assert abs(got.iloc[k] - esperado) < 1e-9, f"{txt!r} -> {got.iloc[k]}"
    assert a_numero(["", "abc", None]).isna().all()


def test_un_sueldo_ilegible_no_se_confunde_con_falta_de_referencia():
    # Antes los dos decian "sin referencia" y el cliente concluia que no conocemos su
    # cargo, cuando la referencia estaba bien y lo ilegible era su numero.
    df = pd.DataFrame({"cargo": ["A", "B"], "sueldo": ["1.500,64", "sin dato"]}, dtype=str)
    det, puesto, res = comparar(df, "sueldo", "cargo", _ref([1.0, 1.0], ["ALTA"] * 2),
                                _sbu, 2025)
    assert det["lectura_mercado"].iloc[0] != "sueldo ilegible", "este si se lee"
    assert det["lectura_mercado"].iloc[1] == "sueldo ilegible"
    assert res["sueldos_ilegibles"] == 1
    assert "formato de la columna" in texto_resumen(res, puesto)


def test_por_puesto_entrega_la_banda_QUE_SUSTENTA_LA_LECTURA():
    # La banda de EMPRESAS se calculaba, decidia la columna `lectura` y se botaba en la
    # linea siguiente: el cliente recibia "en linea" / "muy por encima" sin los numeros
    # que lo justifican. `_lectura` existe precisamente para que la frase sea comprobable
    # —"dentro del 50% central del mercado"— y sin la banda no se podia comprobar.
    df = pd.DataFrame({"cargo": ["BARATO", "NORMAL", "CARO"],
                       "sueldo": [np.exp(0.5) * 470, np.exp(1.0) * 470,
                                  np.exp(2.0) * 470]})
    _, puesto, _ = comparar(df, "sueldo", "cargo",
                            _ref([1.0, 1.0, 1.0], ["ALTA"] * 3), _sbu, 2025)
    p = puesto.set_index("cargo")
    for q in ("p10_emp", "p25_emp", "p75_emp", "p90_emp"):
        assert q in p.columns, f"falta {q}: la lectura viaja sin su banda"

    # En DOLARES, no en log: `_ref` pone p25 = ref - 0,2 y p75 = ref + 0,2.
    assert abs(p.loc["NORMAL", "p25_emp"] - np.exp(0.8) * 470) < 0.01
    assert abs(p.loc["NORMAL", "p75_emp"] - np.exp(1.2) * 470) < 0.01
    assert (p["p10_emp"] < p["p25_emp"]).all() and (p["p75_emp"] < p["p90_emp"]).all()

    # LA INVARIANTE: la etiqueta tiene que ser comprobable contra la banda publicada.
    for cargo, r in p.iterrows():
        dentro = r["p25_emp"] <= r["sueldo_mediano"] <= r["p75_emp"]
        assert dentro == (r["lectura"] == "en linea"), (
            f"{cargo}: lectura {r['lectura']!r} no cuadra con su propia banda")


def test_el_resumen_por_puesto_usa_la_MEDIANA_y_lo_dice_en_el_nombre():
    # La columna se llamaba `sueldo_medio` y contenia una mediana. El numero estaba bien
    # y el nombre mentia: un cliente que lea "medio" y sume por su cuenta encuentra otra
    # cosa y deja de creerse el informe. Y la mediana es la correcta, porque es la unidad
    # con la que vota cada empresa de la base.
    df = pd.DataFrame({"cargo": ["CONTADOR"] * 4,
                       "sueldo": [900.0, 900.0, 900.0, 9000.0]})
    _, puesto, _ = comparar(df, "sueldo", "cargo", _ref([1.0] * 4, ["ALTA"] * 4),
                            _sbu, 2025)
    assert "sueldo_medio" not in puesto.columns, "el nombre mentia"
    assert puesto["sueldo_mediano"].iloc[0] == 900.0, "un solo sueldo no mueve el voto"
