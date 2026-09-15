"""El segmento del cliente sale de su RUC, igual que el rubro.

POR QUE IMPORTA. El segmento es el ajuste que SI mejora la precision --corrige el sesgo
de los cargos altos (D-018)-- a diferencia del rubro, que solo estrecha el respaldo
(D-023). Si el cliente no lo declara y nadie lo deriva, el informe sale sin la unica
correccion que de verdad paga, y sin que nadie lo note.

POR QUE SE PROPAGA Y NO SE CALCULA. La clasificacion ya existe aguas arriba: `SQL_SCVS`
trae `segmento` por RUC junto a `ciiu_n6` y `n_empleados`, y es la MISMA con la que se
armaron las celdas de referencia. Derivarlo de `n_empleados` con cortes propios pondria al
cliente en un segmento calculado con otra regla que la de las celdas contra las que se lo
compara, y el ajuste dejaria de significar lo que dice. Eso es lo que fija el primer test.

Nada de esto toca datos reales ni la red: base de juguete a un `.npz` temporal.
"""
import datetime as _dt
import io

import numpy as np
import pandas as pd
import pytest

fastapi = pytest.importorskip("fastapi", reason="extra opcional: pip install -e .[servicio]")
from fastapi.testclient import TestClient

from benchmarking.producto.base_referencia import BaseReferencia

ANIO = _dt.date.today().year
RUC_CLIENTE = "E00"


def _sbu(anio, estricto=False):
    if anio not in (2025, ANIO) and estricto:
        raise ValueError(f"No hay SBU para {anio}")
    return 470.0


def _marco_con_scvs():
    """La base de juguete, pero con las columnas del padron publico (SCVS).

    `test_servicio.py` construye su marco sin ellas, y por eso alli `meta_ruc` queda
    vacio: sin columnas de SCVS no hay industria ni segmento que resolver.
    """
    filas, emb = [], {}
    for k, cargo in enumerate(("CONTADOR", "VENDEDOR", "GUARDIA")):
        v = np.zeros(4)
        v[k] = 1.0
        emb[cargo] = v
        for i in range(14):
            filas.append((f"E{k}{i}", cargo, 1.0 + 0.2 * k + 0.01 * (i % 5),
                          "PEQUENA" if k == 0 else "GRANDE",
                          "C2394" if k == 0 else "G4610",
                          40 if k == 0 else 900))
    marco = pd.DataFrame(filas, columns=["empresa_ruc", "cargo_norm", "y",
                                         "segmento", "ciiu_n6", "n_empleados"])
    return marco, emb


@pytest.fixture
def base_scvs(tmp_path):
    marco, emb = _marco_con_scvs()
    b = BaseReferencia.construir(marco, emb, lambda a: 470.0)
    ruta = tmp_path / "base.npz"
    b.guardar(ruta)
    return str(ruta)


@pytest.fixture
def cliente(base_scvs, monkeypatch):
    from benchmarking.servicio import api

    class _S:
        sbu = {2025: 470, ANIO: 470}
        vertex_embedding_model = "x"
        bq_project = "p"
        vertex_location = "l"
        get_sbu = staticmethod(_sbu)

    monkeypatch.setattr(api, "cargar_settings", lambda: _S())
    monkeypatch.setenv("BASE_REFERENCIA", base_scvs)
    with TestClient(api.app) as c:
        yield c


def _xlsx(df):
    b = io.BytesIO()
    with pd.ExcelWriter(b) as w:
        df.to_excel(w, index=False)
    return b.getvalue()


def _nomina():
    return pd.DataFrame({"cargo": ["CONTADOR", "VENDEDOR"], "sueldo": ["1500", "800"]})


# -- la propagacion --------------------------------------------------------------------


def test_el_segmento_viaja_en_meta_ruc_tal_como_lo_dice_scvs(base_scvs):
    """El segmento guardado es el de SCVS, no uno recalculado de `n_empleados`."""
    b = BaseReferencia.cargar(base_scvs, lambda a: 470.0)

    ciiu, tam, seg = b.meta_ruc[RUC_CLIENTE]
    assert seg == "PEQUENA", "el segmento tiene que salir de la columna de SCVS"
    # COMPLETO, no truncado. Antes se guardaban 4 caracteres y `C2394` quedaba en
    # `C239`: se perdia el nivel de clase, que es justo el que el cliente reconoce como
    # suyo. Los niveles mas gruesos se sacan cortando; lo tirado no se recupera.
    assert ciiu == "C2394" and tam == 40

    # Y la empresa grande del otro rubro conserva el suyo: no se colapsa todo a uno.
    assert b.meta_ruc["E10"][2] == "GRANDE"


def test_una_base_guardada_antes_del_segmento_sigue_cargando(base_scvs, tmp_path):
    """Compatibilidad hacia atras, sin script de migracion.

    Las bases ya guardadas no tienen `ruc_seg`. Tienen que cargar igual y simplemente no
    derivar el segmento, que es el comportamiento anterior -- no reventar al abrirlas.
    """
    with np.load(base_scvs, allow_pickle=True) as z:
        sin_seg = {k: z[k] for k in z.files if k != "ruc_seg"}
    ruta = tmp_path / "vieja.npz"
    np.savez_compressed(ruta, **sin_seg)

    b = BaseReferencia.cargar(str(ruta), lambda a: 470.0)

    assert len(b.meta_ruc[RUC_CLIENTE]) == 3, "la tupla se completa en el borde"
    assert b.meta_ruc[RUC_CLIENTE][2] == "", "sin dato, no se inventa un segmento"


# -- la derivacion en el servicio ------------------------------------------------------


def test_el_segmento_se_deriva_del_ruc_cuando_el_cliente_no_lo_declara(cliente):
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(_nomina()))},
                     data={"ruc": RUC_CLIENTE})
    assert r.status_code == 202
    assert r.json()["empresa"]["segmento_derivado"] == "PEQUENA"

    d = cliente.get(f"/informes/{r.json()['id']}").json()
    assert d["meta"]["segmento"] == "PEQUENA", \
        "el informe tiene que calcularse CON el segmento, no solo reportarlo"


def test_sin_ruc_no_hay_segmento_que_derivar(cliente):
    """No se adivina: sin RUC el informe sale sin segmento, como siempre."""
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(_nomina()))})
    assert r.status_code == 202
    assert r.json().get("empresa") is None

    d = cliente.get(f"/informes/{r.json()['id']}").json()
    assert d["meta"]["segmento"] is None


def test_el_segmento_explicito_manda_sobre_el_del_ruc_y_se_avisa(cliente):
    """Misma regla que el rubro: gana lo que pidio el cliente, y la discrepancia se dice.

    El aviso va en `aviso_segmento` y no en `aviso` para no pisar el del rubro cuando los
    dos discrepan en el mismo pedido.
    """
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(_nomina()))},
                     data={"ruc": RUC_CLIENTE, "segmento": "GRANDE"})
    assert r.status_code == 202

    emp = r.json()["empresa"]
    assert "segmento_derivado" not in emp, "no se deriva cuando vino explicito"
    assert "PEQUENA" in emp["aviso_segmento"] and "GRANDE" in emp["aviso_segmento"]

    d = cliente.get(f"/informes/{r.json()['id']}").json()
    assert d["meta"]["segmento"] == "GRANDE"


def test_un_segmento_derivado_no_puede_devolver_400(cliente):
    """El valor derivado nunca se rechaza por invalido.

    Si SCVS trajera algo fuera del catalogo, `_norm_segmento` lo deja en vacio y no se
    deriva. Un 400 sobre un valor que el cliente NO mando seria imposible de entender
    desde el front.
    """
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(_nomina()))},
                     data={"ruc": RUC_CLIENTE})
    assert r.status_code == 202


# -- el bug que destapo esto -----------------------------------------------------------


def test_un_rubro_derivado_sin_respaldo_no_tumba_el_pedido(cliente):
    """REGRESION de un bug preexistente, encontrado al derivar el segmento.

    La derivacion del rubro (`rubro = g6[:1]`) corre ANTES de la validacion que rechaza
    los rubros sin respaldo. Con un RUC cuya seccion no esta en la base --el caso de esta
    base de juguete, que tiene `rubros == []`-- el cliente recibia

        400 "rubro sin datos suficientes: C. Con respaldo en esta base: []"

    sobre un campo que no mando: subio su nomina, no toco ningun sector, y el sistema le
    respondia que su sector no tiene datos. Inaccionable desde el front.

    Ahora, sin respaldo no se deriva: el informe sale global --lo mismo que habria
    recibido sin mandar el RUC-- y la ficha lo dice en vez de callarlo.
    """
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(_nomina()))},
                     data={"ruc": RUC_CLIENTE})
    assert r.status_code == 202, "un rubro derivado sin respaldo no puede dar 400"

    emp = r.json()["empresa"]
    assert emp["rubro_sin_respaldo"] == "C"
    assert "rubro_derivado" not in emp

    d = cliente.get(f"/informes/{r.json()['id']}").json()
    assert d["meta"]["rubro"] is None, "el informe sale global, no sectorial"


def test_un_rubro_explicito_sin_respaldo_SI_da_400(cliente):
    """La contraparte, para que el arreglo de arriba no relaje la validacion.

    Cuando el rubro lo eligio el cliente, el 400 es la respuesta correcta: le dice que su
    pedido no se puede cumplir y con que rubros si. Solo el derivado se degrada en
    silencio, porque solo ese no lo pidio nadie.
    """
    r = cliente.post("/informes", files={"archivo": ("n.xlsx", _xlsx(_nomina()))},
                     data={"rubro": "C"})
    assert r.status_code == 400
    assert "sin datos suficientes" in r.json()["detail"]


def test_una_declaracion_a_medio_llenar_NO_decide_el_segmento():
    """El SQL toma el ultimo ano NO sospechoso, no el ultimo a secas.

    El caso real: un RUC declara 2 empleados en 2025 y 193 en 2024. Con el ultimo a
    secas entraba como MEDIANA siendo GRANDE, y el segmento alimenta `ajuste_seg`, la
    correccion que mas pesa en los cargos altos.

    Se comprueba sobre el TEXTO del SQL porque la consulta vive en BigQuery y aqui no
    hay red: lo que se fija es que la regla siga estando, no su resultado.
    """
    from benchmarking.adquisicion.bigquery_source import SQL_SCVS
    assert "sospechosa" in SQL_SCVS
    assert "ORDER BY sospechosa, anio DESC" in SQL_SCVS, \
        "el desempate tiene que anteponer las declaraciones sanas"
    # IFNULL: la mas antigua no tiene ano previo y su NULL ordenaria primero en BigQuery
    assert "IFNULL(" in SQL_SCVS
    # y se particiona por el RUC YA rellenado: la misma empresa aparece con y sin el
    # cero inicial, y particionar por el crudo devolvia dos filas para ella
    assert "LPAD(CAST(ruc AS STRING), 13, '0') ruc" in SQL_SCVS
    i_lpad = SQL_SCVS.index("LPAD(CAST(ruc")
    i_part = SQL_SCVS.index("PARTITION BY ruc")
    assert i_lpad < i_part, "el LPAD tiene que ir ANTES de particionar"
    assert "ruc IS NOT NULL" in SQL_SCVS, "una fila sin RUC no sirve para cruzar por RUC"
