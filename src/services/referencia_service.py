"""Un titulo suelto, para explorar. NO es el producto: sin la nomina completa no hay ancla
de empresa, y sin ancla no hay lectura de equidad interna."""

import datetime as _dt

import numpy as np

from src.domain import sinonimos
from src.domain.base_referencia import SEGMENTOS
from src.domain.presentacion import UNIDADES
from src.infrastructure.motor import Motor
from src.services.puesto_service import _empresas_de_grupo
from src.shared.contracts.responses import BaseResponseModel, error, exito
from src.shared.utils.conversion import a_python, claves_a_camel, opcional


def obtener_referencia(
    *, motor: Motor, cargo: str, anio: int | None, segmento: str | None, rubro: str | None, ruc: str | None
) -> BaseResponseModel:
    """Un titulo suelto, para explorar. NO es el producto.

    Sin la nomina completa no hay ancla de empresa, y sin ancla no hay lectura de equidad
    interna — que es la mitad util del informe. La respuesta lo dice para que nadie
    construya un front encima creyendo que esto basta.
    """
    # mismo criterio que /informes: el ano por defecto es el ACTUAL, y vacio o
    # "string" son ausencia
    m = motor
    anio = int(anio) if anio else _dt.date.today().year
    try:
        m.settings.get_sbu(anio, estricto=True)
    except ValueError as e:
        return error(400, str(e))
    segmento, rubro, ruc = opcional(segmento), opcional(rubro), opcional(ruc)
    if rubro and rubro.upper() not in m.base.rubros:
        return error(400, f"rubro sin datos suficientes: {rubro}. " f"Con respaldo: {list(m.base.rubros)}")
    # D-063: el tamano del cliente sale de su RUC (padron de la Superintendencia), como en /informes; el que se
    # pida a mano manda, y si no coinciden se avisa
    seg_ruc = (m.base.meta_ruc.get(ruc.strip(), ("", -1, ""))[2] or "") if ruc else ""
    aviso_seg = None
    if seg_ruc and not segmento and seg_ruc in SEGMENTOS:
        segmento = seg_ruc
    elif seg_ruc and segmento and segmento.upper() != seg_ruc:
        aviso_seg = f"pediste segmento {segmento.upper()} y el RUC dice {seg_ruc}; se usa el que pediste"
    elif ruc and not seg_ruc:
        aviso_seg = "el RUC no esta en el padron de la Superintendencia: sin tamano, la referencia no se ajusta"
    if segmento and segmento.upper() not in SEGMENTOS:
        return error(400, f"segmento invalido: {segmento}. Validos: {list(SEGMENTOS)}")
    t = cargo.strip().upper()
    if not t:
        return error(400, "cargo vacio")
    m.asegurar([t])
    fila = m.base.referenciar([t], m.emb, anio=anio, segmento=segmento, rubro=rubro).iloc[0]
    d = {str(k): a_python(v) for k, v in fila.items() if not str(k).endswith("_log") and k != "sd"}
    d["unidades"] = UNIDADES
    d["aviso"] = (
        "Sin la nomina completa no hay ancla de empresa: falta la lectura de "
        "equidad interna. Para el informe completo, POST /informes."
    )
    principal = _sinonimo_principal(m, t, fila, anio, segmento, rubro)
    if principal:
        d["sinonimo_principal"] = principal
    if ruc:
        d["segmento_del_ruc"] = seg_ruc or None
    if aviso_seg:
        d["aviso_segmento"] = aviso_seg
    return exito(claves_a_camel(d))


def _sinonimo_principal(m, t, fila, anio, segmento, rubro):
    """D-072: si el cargo tiene un sinonimo aprobado con MAS empresas, su referencia y rango, para mostrarlo al lado
    (`JEFE DE RRHH` -> `JEFE DE RECURSOS HUMANOS`). No cambia la cifra del cargo consultado."""
    g0 = sinonimos.grupo_de(m.base, t)
    if g0 is None:
        g0 = sinonimos.grupo_de(m.base, sinonimos.canonico(t))
    if g0 is None or not m.sinonimos.get(g0):
        return None
    n0 = int(fila.get("empresas") or 0)
    mejor = max(m.sinonimos[g0], key=lambda g: _empresas_de_grupo(m, g))
    if _empresas_de_grupo(m, mejor) <= n0:
        return None
    i = int(np.flatnonzero(np.asarray(m.base.grupo) == mejor)[0])
    cargo = m.etiqueta.get(mejor, str(m.base.celdas[i]))
    r = m.base.referenciar([cargo], m.emb, anio=anio, segmento=segmento, rubro=rubro).iloc[0]
    return {
        "cargo": cargo,
        "referencia": a_python(r["referencia"]),
        "rango_desde": a_python(r["rango_desde"]),
        "rango_hasta": a_python(r["rango_hasta"]),
        "empresas": a_python(r["empresas"]),
        "confianza": r["confianza"],
        "aviso": (
            f"{cargo} es el mismo cargo y tiene mas empresas detras ({a_python(r['empresas'])}); "
            f"su referencia puede ser mas representativa."
        ),
    }
