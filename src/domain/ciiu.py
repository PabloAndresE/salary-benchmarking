"""Nombres del catalogo CIIU rev.4 a cualquier nivel (seccion, division, grupo, clase)."""

import json
import pathlib

# Secciones CIIU rev.4. La base solo guarda la LETRA, asi que el nivel de grupo
# —`C239`, "Productos minerales no metalicos"— no se puede resolver aqui: haria falta
# `ciiu_n6` en el marco y una tabla de descripciones. Se da la seccion y se dice que el
# grupo no esta, en vez de dejar la tarjeta a medias sin explicacion.
# NOMBRES CIIU DE TODOS LOS NIVELES, del catalogo de la Superintendencia (`scvs_ciiu`),
# volcado al repo: 770 entradas —22 secciones, 88 divisiones, 238 grupos, 422 clases—
# en 49 KB. Es un estandar publico, no dato de cliente, y vive aqui para que pintar una
# etiqueta no dependa de una consulta a BigQuery.
#
# Antes habia aqui un diccionario de 22 secciones escrito a mano, y no daba para mas: con
# la cascada el informe se compara contra divisiones y clases —`G47`, `G4761`— y esas no
# tenian nombre. La `nota` de `industria` lo confesaba: "su descripcion en palabras
# necesita la tabla CIIU del INEC, que no esta en la base". Ya esta.
_CIIU = json.loads((pathlib.Path(__file__).parent / "datos" / "ciiu.json").read_text(encoding="utf-8"))


def nombre_ciiu(codigo: str) -> str:
    """El nombre de un codigo CIIU a cualquier nivel. Cae al nivel superior si falta.

    SE CORTA EN EL PUNTO Y COMA. En CIIU el `;` separa actividades que comparten codigo
    por convencion, y la primera es la que nombra el rubro:

        D352  "Fabricacion de gas; distribucion de combustibles gaseosos por tuberias"
        M71   "Actividades de arquitectura e ingenieria; ensayos y analisis tecnicos"
        O84   "Administracion publica y defensa; planes de seguridad social..."

    Afecta a 20 de 769 nombres (3%) y no crea ni una ambiguedad: comprobado, ningun par
    de codigos del mismo nivel queda con el mismo nombre al cortar.

    LA COMA NO SE CORTA, y es deliberado: ahi no separa actividades, ENUMERA. Cortarla
    dejaria el primer elemento de una lista haciendose pasar por el todo —`K65` quedaria
    en "Seguros" perdiendo reaseguros y fondos de pensiones, y `G4741` en "Venta al por
    menor de computadores" perdiendo periferico, programas y telecomunicaciones—. Si el
    texto no cabe en la pantalla, se trunca por longitud con puntos suspensivos: eso al
    menos avisa de que hay mas.
    """
    c = str(codigo or "").strip().upper()
    while c:
        if c in _CIIU:
            return _CIIU[c].split(";")[0].strip()
        c = c[:-1]
    return "sin clasificar"


CIIU_SECCION = {k: v for k, v in _CIIU.items() if len(k) == 1}
