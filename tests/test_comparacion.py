

def test_la_masa_salarial_NO_es_la_mediana_y_el_texto_lo_dice():
    """Dos cifras que contestan preguntas distintas, y en una piramide difieren mucho.

    `nivel_vs_mercado` es la persona TIPICA; `masa_vs_mercado` es la planilla. La mediana
    cuenta a cada persona como una cabeza, la masa las cuenta por lo que pesan. Un gerente
    que lee "pagamos 6% bajo mercado" presupuesta el 6% de su planilla — y se pasa.
    """
    import numpy as np
    import pandas as pd
    from benchmarking.producto.comparacion import comparar, texto_resumen

    # 10 abajo pagados por debajo, 2 arriba pagados muy por encima
    cargos = ["OPERARIO"] * 10 + ["GERENTE"] * 2
    ref_log = np.log([2.0] * 10 + [20.0] * 2)          # el mercado, en log(sueldo/SBU)
    sueldos = [0.90 * 940.0] * 10 + [1.40 * 9400.0] * 2
    df = pd.DataFrame({"cargo": cargos, "sueldo": sueldos})
    ref = pd.DataFrame({
        "cargo": cargos, "referencia_log": ref_log,
        "p10_log": ref_log - 0.3, "p25_log": ref_log - 0.15,
        "p75_log": ref_log + 0.15, "p90_log": ref_log + 0.3,
        "p10per_log": ref_log - 0.4, "p25per_log": ref_log - 0.2,
        "p75per_log": ref_log + 0.2, "p90per_log": ref_log + 0.4,
        "confianza": ["ALTA"] * 12,
    })
    _, pp, res = comparar(df, "sueldo", "cargo", ref, lambda a: 470.0, 2026)

    # la mediana ve a los 10 de abajo: ~-10%
    assert res["nivel_vs_mercado"] < -0.05
    # la masa ve el peso de los 2 gerentes y sale POR ENCIMA
    assert res["masa_vs_mercado"] > 0, res["masa_vs_mercado"]
    # ...o sea que las dos cifras no solo difieren: apuntan a LADOS OPUESTOS
    assert np.sign(res["nivel_vs_mercado"]) != np.sign(res["masa_vs_mercado"])

    txt = texto_resumen(res, pp)
    assert "persona TIPICA" in txt and "NOMINA ENTERA" in txt


def test_la_masa_solo_suma_a_quien_tiene_LAS_DOS_cifras():
    # Sumar el sueldo de alguien sin referencia contra una referencia que no existe daria
    # una diferencia inventada. Se cuenta cuanta gente queda fuera para poder juzgarlo.
    import numpy as np
    import pandas as pd
    from benchmarking.producto.comparacion import comparar

    df = pd.DataFrame({"cargo": ["A", "B"], "sueldo": [1000.0, 1000.0]})
    ref = pd.DataFrame({
        "cargo": ["A", "B"], "referencia_log": [np.log(2.0), np.nan],
        "p10_log": [0.0, np.nan], "p25_log": [0.0, np.nan],
        "p75_log": [1.0, np.nan], "p90_log": [1.0, np.nan],
        "p10per_log": [0.0, np.nan], "p25per_log": [0.0, np.nan],
        "p75per_log": [1.0, np.nan], "p90per_log": [1.0, np.nan],
        "confianza": ["ALTA", "BAJA"],
    })
    _, _, res = comparar(df, "sueldo", "cargo", ref, lambda a: 470.0, 2026)
    assert res["masa_personas"] == 1 and res["personas"] == 2
    assert res["masa_real"] == 1000.0
