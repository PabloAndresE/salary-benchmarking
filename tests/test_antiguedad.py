"""Antiguedad con salidas y reingresos.

Lo que se fija sobre todo es que NO es una resta: restar el primer ingreso a la fecha de
corte le regala a la persona los anios que estuvo fuera.
"""
import numpy as np
import pandas as pd

from benchmarking.producto.antiguedad import antiguedad_anios, columnas_de_fecha, tramo


def test_sin_salidas_es_la_resta_simple():
    df = pd.DataFrame({"Fecha de primer ingreso": ["01/01/2020"]})
    assert abs(antiguedad_anios(df, 2025).iloc[0] - 6.0) < 0.02


def test_los_anios_FUERA_no_cuentan():
    # entra 2010, sale 2015, vuelve 2020: 5 + 6 = 11 anios, no 16.
    df = pd.DataFrame({"Fecha de primer ingreso": ["01/01/2010"],
                       "Fecha de salida 1": ["01/01/2015"],
                       "Fecha de reingreso 1": ["01/01/2020"]})
    a = antiguedad_anios(df, 2025).iloc[0]
    assert abs(a - 11.0) < 0.05, f"dio {a}: le esta regalando los anios fuera"


def test_dos_salidas_y_dos_reingresos():
    df = pd.DataFrame({"Fecha de primer ingreso": ["01/01/2000"],
                       "Fecha de salida 1": ["01/01/2002"],
                       "Fecha de reingreso 1": ["01/01/2010"],
                       "Fecha de salida 2": ["01/01/2012"],
                       "Fecha de reingreso 2": ["01/01/2020"]})
    a = antiguedad_anios(df, 2025).iloc[0]      # 2 + 2 + 6
    assert abs(a - 10.0) < 0.05, f"dio {a}"


def test_quien_se_fue_y_no_volvio_deja_de_sumar():
    df = pd.DataFrame({"Fecha de primer ingreso": ["01/01/2010"],
                       "Fecha de salida 1": ["01/01/2015"]})
    assert abs(antiguedad_anios(df, 2025).iloc[0] - 5.0) < 0.05


def test_la_fecha_de_corte_es_el_ano_del_INFORME_y_no_hoy():
    # Un estudio valorado a 2025 tiene que dar lo mismo en enero que en noviembre de 2026.
    df = pd.DataFrame({"Fecha de primer ingreso": ["01/01/2020"]})
    assert antiguedad_anios(df, 2025).iloc[0] < antiguedad_anios(df, 2030).iloc[0]
    assert abs(antiguedad_anios(df, 2030).iloc[0] - 11.0) < 0.02


def test_dia_primero_no_mes_primero():
    # `03/04/2020` es 3 de abril. Sin dayfirst se lee marzo y la antiguedad sale con un
    # mes de error en un tercio de las filas, en silencio.
    a = antiguedad_anios(pd.DataFrame({"Fecha de primer ingreso": ["03/04/2020"]}), 2020)
    b = antiguedad_anios(pd.DataFrame({"Fecha de primer ingreso": ["04/03/2020"]}), 2020)
    assert a.iloc[0] < b.iloc[0]


def test_sin_fecha_es_NaN_y_no_cero():
    # Un cero se leeria como "recien entrado", que es otra afirmacion.
    df = pd.DataFrame({"Fecha de primer ingreso": [None, "", "no es fecha"]})
    assert antiguedad_anios(df, 2025).isna().all()


def test_sin_columna_de_ingreso_no_revienta():
    df = pd.DataFrame({"cargo": ["X"], "sueldo": ["1"]})
    assert antiguedad_anios(df, 2025).isna().all()


def test_detecta_las_columnas_de_la_plantilla_real():
    cols = ["Nombres", "Fecha de primer ingreso", "Fecha de \nsalida 1",
            "Fecha de \nreingreso 1", "Fecha de \nsalida 2", "Fecha de \nreingreso 2",
            "Fecha de \nsalida 3", "Fecha de nacimiento"]
    ing, sal, rei = columnas_de_fecha(pd.DataFrame(columns=cols))
    assert ing == "Fecha de primer ingreso"
    assert len(sal) == 3 and len(rei) == 2
    assert "1" in str(sal[0]) and "3" in str(sal[-1]), "ordenadas por numero"
    assert "Fecha de nacimiento" not in sal + rei


def test_los_tramos_para_el_filtro():
    t = tramo([0.5, 2, 4, 7, 15, 30, None])
    assert list(t[:6]) == ["menos de 1", "1 a 3", "3 a 5", "5 a 10", "10 a 20",
                           "mas de 20"]
    assert t.iloc[6] is None


def test_un_tramo_ABIERTO_se_cuenta_UNA_sola_vez():
    # El bucle recorre una vuelta por columna de salida. Sin marcar los tramos ya
    # cerrados en la fecha de corte, el periodo abierto se sumaba en CADA vuelta: quien
    # llevaba 2 anios salia con 4, y el error crecia con el numero de columnas.
    cols = {"Fecha de primer ingreso": ["01/01/2024"]}
    for k in (1, 2, 3):
        cols[f"Fecha de salida {k}"] = [None]
    for k in (1, 2):
        cols[f"Fecha de reingreso {k}"] = [None]
    a = antiguedad_anios(pd.DataFrame(cols), 2025).iloc[0]
    assert abs(a - 2.0) < 0.05, f"dio {a}: cuenta el tramo abierto varias veces"


def test_mas_columnas_de_salida_no_cambian_el_resultado():
    base = {"Fecha de primer ingreso": ["01/01/2020"]}
    a1 = antiguedad_anios(pd.DataFrame(base), 2025).iloc[0]
    a2 = antiguedad_anios(pd.DataFrame({**base, "Fecha de salida 1": [None],
                                        "Fecha de salida 2": [None],
                                        "Fecha de reingreso 1": [None]}), 2025).iloc[0]
    assert abs(a1 - a2) < 1e-9


def test_detecta_el_nombre_CANONICO_con_guion_bajo():
    # El formato del producto usa `fecha_ingreso`. La regex admitia espacios entre las
    # palabras pero no el guion bajo, asi que la antiguedad salia vacia para TODAS las
    # filas y en silencio — el peor modo de fallo.
    ing, _, _ = columnas_de_fecha(pd.DataFrame(columns=["cargo", "fecha_ingreso"]))
    assert ing == "fecha_ingreso"
    a = antiguedad_anios(pd.DataFrame({"fecha_ingreso": ["01/01/2020"]}), 2025)
    assert abs(a.iloc[0] - 6.0) < 0.02


# --- el parseo de fechas ISO, que estaba roto -------------------------------------

def test_una_fecha_ISO_NO_se_lee_con_el_dia_y_el_mes_cambiados():
    # EL DEFECTO, medido sobre una nomina real de 303 filas: 195 se quedaron SIN
    # antiguedad y 101 recibieron un numero equivocado. Solo 7 salieron bien, y de
    # casualidad, porque su dia coincidia con su mes.
    #
    # `pd.to_datetime(s, dayfirst=True)` deduce UN formato de la primera fila. Si esa
    # fila es ambigua —`2004-09-06`, donde 09 y 06 caben los dos como mes— deduce
    # ano-DIA-mes y lo aplica a todas.
    df = pd.DataFrame({"fecha_ingreso": ["2004-09-06", "2025-06-20", "2020-10-10"]})
    a = antiguedad_anios(df, 2026)
    # 6 de septiembre de 2004, no 9 de junio (que daria 22,56)
    assert abs(a.iloc[0] - 22.32) < 0.01, f"salio {a.iloc[0]}"
    # y el dia 20 no se pierde por no existir el mes 20
    assert pd.notna(a.iloc[1]) and abs(a.iloc[1] - 1.53) < 0.01


def test_el_formato_ecuatoriano_dd_mm_sigue_leyendose_como_siempre():
    # Lo de arriba no puede haberse arreglado rompiendo esto: en una plantilla de RR.HH.
    # ecuatoriana `03/04/2020` es 3 de abril, no 4 de marzo.
    df = pd.DataFrame({"fecha_ingreso": ["06/09/2004", "20/06/2025", "03/04/2020"]})
    a = antiguedad_anios(df, 2026)
    assert abs(a.iloc[0] - 22.32) < 0.01
    assert abs(a.iloc[1] - 1.53) < 0.01
    # 3 de abril de 2020 -> hasta el 31/12/2026
    assert abs(a.iloc[2] - 6.75) < 0.02, f"salio {a.iloc[2]}"


def test_da_lo_MISMO_como_venga_escrita_la_misma_fecha():
    # La antiguedad decide indemnizaciones. No puede depender de si RR.HH. exporto el
    # Excel con fechas de verdad, con texto ISO o con texto latino.
    import datetime as dt
    formas = {
        "ISO": ["2004-09-06"],
        "ISO con hora": ["2004-09-06 00:00:00"],
        "ISO con barras": ["2004/09/06"],
        "latino": ["06/09/2004"],
        "latino con guiones": ["06-09-2004"],
        "fecha de Excel": [dt.date(2004, 9, 6)],
    }
    salidas = {n: float(antiguedad_anios(pd.DataFrame({"fecha_ingreso": v}), 2026).iloc[0])
               for n, v in formas.items()}
    assert len(set(round(v, 4) for v in salidas.values())) == 1, salidas
    assert abs(next(iter(salidas.values())) - 22.32) < 0.01


def test_una_fila_no_le_impone_su_formato_a_las_demas():
    # El nucleo del defecto: pandas deducia el formato de la PRIMERA fila. Mezclando
    # estilos, cada celda tiene que resolverse sola.
    df = pd.DataFrame({"fecha_ingreso": ["2004-09-06", "20/06/2025", "2020/10/10",
                                         "03-04-2020"]})
    a = antiguedad_anios(df, 2026)
    assert a.notna().all(), f"alguna se perdio: {a.tolist()}"
    assert abs(a.iloc[0] - 22.32) < 0.01 and abs(a.iloc[1] - 1.53) < 0.01


def test_lo_ilegible_sigue_quedando_vacio_y_no_inventa_un_cero():
    df = pd.DataFrame({"fecha_ingreso": ["2004-09-06", None, "no es una fecha", ""]})
    a = antiguedad_anios(df, 2026)
    assert pd.notna(a.iloc[0]) and a.iloc[1:].isna().all()
