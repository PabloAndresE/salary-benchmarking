"""Que puestos de la base se parecen a lo que escribio el usuario: el buscador de
correcciones del front."""

import numpy as np

from src.domain import sinonimos
from src.domain.base_referencia import _vecinos
from src.infrastructure.motor import Motor
from src.shared.contracts.responses import BaseResponseModel, error, exito
from src.shared.utils.conversion import claves_a_camel

# POR ENCIMA DE ESTO, EL PARECIDO SIGNIFICA ALGO. Medido sobre la base de 65.181 titulos:
#
#                            p50     p90     p99     max
#   pares AL AZAR          0,588   0,693   0,780   0,955
#   mismo puesto (fusion)  0,970   0,991   0,997   1,000
#
# 0,85 deja pasar al 0,08% del azar y conserva al 97,9% de los pares que de verdad son el
# mismo puesto. NO SE FILTRA CON ESTO, SE ETIQUETA (`sobre_el_ruido`).
UMBRAL_RUIDO = 0.85

N_REORDENAR = 50  # cuantos puestos reordena el juez en /puestos (D-048)
P_MIN_SUGERENCIA = 0.5  # bajo esto el juez dice "no es el mismo cargo": no se sugiere (decision del autor)
N_RESPALDO = 3  # si nada llega a `p_min`, las N mas probables, marcadas `seguro: false`
P_SEGURO = 0.9  # desde aqui, entre sugerencias manda el parecido


def buscar_puestos(*, motor: Motor, q: str, limite: int = 12, p_min: float = P_MIN_SUGERENCIA) -> BaseResponseModel:
    """Que puestos de la base se parecen a `q`. Para el buscador de correcciones.

    PARA QUE EXISTE. `DENTISTA` no esta en la base y se resuelve por analogia contra
    `HIGIENISTA`, que tiene 2 empresas detras, mientras `ODONTOLOGA` —25 empresas— esta
    ahi al lado. Sin una forma de VER el vecindario, el cliente no puede corregirlo:
    recibe una referencia construida sobre dos empresas y no sabe ni que paso.

    `empresas` NO ES UN EXTRA, es lo que decide si la sugerencia sirve. Dos candidatos
    con la misma similitud y 2 contra 25 empresas detras no valen lo mismo, y esa
    diferencia no se ve en el coseno.

    NO SE FILTRA NADA, NI POR RESPALDO NI POR PARECIDO. Se devuelve todo con lo que hace
    falta para juzgarlo —`empresas`, `personas`, `similitud`, `sobre_el_ruido`— y el front
    decide que pinta y como: esconder candidatos dejaria al usuario eligiendo entre
    opciones sin saber que habia mas, que es el problema que este endpoint viene a
    resolver, no a repetir.
    """
    m = motor
    t = str(q or "").strip().upper()
    if not t:
        return error(400, "`q` vacio")
    limite = max(1, min(int(limite), 50))
    m.asegurar([t])
    if t not in m.emb:
        return error(503, "no se pudo embeber el texto; reintenta")
    Q = np.vstack([m.emb[t]]).astype(float)
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    # con juez se piden mas vecinos: el juez reordena los N_REORDENAR primeros PUESTOS (no grafias)
    vec, sim = _vecinos(
        Q, m.base.Z, min(max(limite * 6, 300 if m.base.juez else 0), len(m.base.celdas)), excluir_propio=False
    )
    # UNA FILA POR PUESTO, NO POR GRAFIA. La base guarda 65.181 titulos que son 50.420
    # puestos: `VENDEDOR`, `VENDEDOR.`, `VENDEDORA`, `VEENDEDOR` y `VENDERDOR` son el
    # mismo, y la fusion ya lo sabe. Sin colapsar, buscar `VENDEDOR` devolvia ocho
    # opciones y siete eran la misma palabra con otra puntuacion: el usuario no podia
    # llegar a nada distinto, y nada impedia ofrecerle una ERRATA como correccion.
    #
    # Se pide `limite * 6` vecinos para tener de donde colapsar, porque un puesto muy
    # repetido se lleva muchos de los primeros puestos. Sin ese margen, buscar `VENDEDOR`
    # devolveria un solo resultado.
    por_grupo = {}
    for j, sj in zip(vec[0], sim[0]):
        j, sj = int(j), float(sj)
        g = int(m.base.grupo[j])
        prev = por_grupo.get(g)
        if prev is None:
            por_grupo[g] = {
                "grafias": [str(m.base.celdas[j])],
                "empresas": int(m.base.emp[j]),
                "personas": int(m.base.personas[j]),
                "similitud": sj,
            }
        else:
            prev["grafias"].append(str(m.base.celdas[j]))
            prev["similitud"] = max(prev["similitud"], sj)
    out = []
    for g, d in por_grupo.items():
        out.append(
            {
                "cargo": m.etiqueta.get(g, d["grafias"][0]),
                # TODAS las del grupo, no solo las que entraron en esta busqueda:
                # antes el numero cambiaba con el `limite` de la consulta.
                "grafias": m.n_grafias.get(g, len(d["grafias"])),
                "empresas": d["empresas"],
                "personas": d["personas"],
                "similitud": round(d["similitud"], 3),
                # .esta el parecido por encima del ruido del modelo? Ver UMBRAL_RUIDO
                "sobre_el_ruido": d["similitud"] >= UMBRAL_RUIDO,
            }
        )
    # ORDEN POR PARECIDO, a secas. Lo de arriba es lo mas parecido.
    #
    # HUBO UN INTENTO de ordenar el bloque de ruido POR RESPALDO, con el argumento de que
    # ahi dentro el modelo no distingue —`DENTISTA` puntua 0,752 con `TELEFONISTA` y
    # 0,763 con `ODONTOLOGA`— y que si el usuario elige a ciegas, mejor el de 25 empresas
    # que el de 1. Se retira, medido sobre los propios casos:
    #
    #   - arreglaba `DENTISTA` y empeoraba `TECNICO DE DIALISIS`, subiendo `ASISTENTE DE
    #     DISENO` (30 empresas) por encima de `TECNICO EN HEMODIALISIS` (1);
    #   - y al ampliar el grupo de candidatos para poder colapsar por grafia, se volvio
    #     claramente malo: `MAQUNISTA` (68 empresas, 0,714) adelantaba a `ODONTOLOGA`
    #     (25 empresas, 0,763). El respaldo alto sin parecido es solo "cargo comun".
    #
    # El respaldo viaja en `empresas` y la fiabilidad en `sobre_el_ruido`: con eso el
    # front decide que pinta y como. Ordenar aqui por algo que no es parecido era meter
    # un criterio que no se puede validar.
    out.sort(key=lambda r: -r["similitud"])
    for r in out:
        r["sinonimo"] = False
        r["p_juez"] = None
    # REORDEN POR EL JUEZ (D-048). El embedding ordena por como SUENA: `DENTISTA` traia arriba
    # `HIGIENISTA`, `TELEFONISTA` y `EBANISTA`, y `ODONTOLOGIA` cuarto. La v3 juzga los
    # N_REORDENAR mas parecidos contra lo escrito y se ordenan por su P; `p_juez` le dice al front
    # cuales son el mismo cargo con seguridad. Solo cambia el ORDEN de las sugerencias, no las bandas.
    if m.base.juez is not None and out:
        top = out[:N_REORDENAR]
        for r, p in zip(top, m.base.juez.P([(t, r["cargo"]) for r in top])):
            r["p_juez"] = round(float(p), 3)
        # por encima de P_SEGURO el juez ya dice "el mismo cargo": entre esos manda el parecido, para
        # que el titulo exacto no quede detras de sus variantes con funcion anadida (todas P ~ 0,99)
        top.sort(key=lambda r: (-min(r["p_juez"], P_SEGURO), -r["similitud"]))
        out = top + out[N_REORDENAR:]
    # SINONIMOS APROBADOS POR EL AUTOR (D-046, D-047), JUSTO DESPUES DEL CARGO ESCRITO. Si lo
    # escrito es un cargo de la base (tal cual o por la capa 0), sus sinonimos van detras de el
    # aunque el embedding los ponga lejos: `CONDUCTOR` esta en el puesto 1.312 de `CHOFER`.
    g0 = sinonimos.grupo_de(m.base, t)
    if g0 is not None and m.sinonimos.get(g0):
        ya = {r["cargo"] for r in out}
        extra = []
        for g in sorted(m.sinonimos[g0], key=lambda g: -_personas_de_grupo(m, g)):
            i = int(np.flatnonzero(np.asarray(m.base.grupo) == g)[0])
            cargo = m.etiqueta.get(g, str(m.base.celdas[i]))
            if cargo in ya:
                continue
            extra.append(
                {
                    "cargo": cargo,
                    "grafias": m.n_grafias.get(g, 1),
                    "empresas": int(m.base.emp[i]),
                    "personas": int(m.base.personas[i]),
                    "similitud": round(float(Q[0] @ m.base.Z[i] / np.linalg.norm(m.base.Z[i])), 3),
                    "sobre_el_ruido": False,
                    "sinonimo": True,
                    "p_juez": None,
                }
            )
        pos = next((k + 1 for k, r in enumerate(out) if r["cargo"] == m.etiqueta.get(g0)), 0)
        out = out[:pos] + extra + out[pos:]
    # SINONIMOS DE CONSULTA (`consulta.csv`): un titulo que no existe en la base y no se parece por
    # las letras al cargo que nombra (`DENTISTA` -> `ODONTOLOGO`). Su grupo va PRIMERO.
    gq = m.sinonimos_consulta.get(sinonimos.clave(m.base, t))
    if gq is not None:
        i = int(np.flatnonzero(np.asarray(m.base.grupo) == gq)[0])
        cargo = m.etiqueta.get(gq, str(m.base.celdas[i]))
        out = [r for r in out if r["cargo"] != cargo]
        out.insert(
            0,
            {
                "cargo": cargo,
                "grafias": m.n_grafias.get(gq, 1),
                "empresas": int(m.base.emp[i]),
                "personas": int(m.base.personas[i]),
                "similitud": round(float(Q[0] @ m.base.Z[i] / np.linalg.norm(m.base.Z[i])), 3),
                "sobre_el_ruido": False,
                "sinonimo": True,
                "p_juez": None,
            },
        )
    # EQUIVALENTE EN ESPANOL (D-050, solo para mostrar). Un titulo en ingles se traduce y se
    # resuelve en la base (tal cual, capa 0 o juez, con candados); ese cargo va PRIMERO.
    for r in out:
        r["equivalente"] = False
    if getattr(m.base, "traductor", None) is not None:
        res = m.base.resolver_idioma([t], m.emb)
        if t in res:
            j, _, _, tt = res[t]
            g = int(m.base.grupo[j])
            cargo = m.etiqueta.get(g, str(m.base.celdas[j]))
            out = [r for r in out if r["cargo"] != cargo]
            out.insert(
                0,
                {
                    "cargo": cargo,
                    "grafias": m.n_grafias.get(g, 1),
                    "empresas": int(m.base.emp[j]),
                    "personas": int(m.base.personas[j]),
                    "similitud": round(float(Q[0] @ m.base.Z[j] / np.linalg.norm(m.base.Z[j])), 3),
                    "sobre_el_ruido": False,
                    "sinonimo": False,
                    "p_juez": None,
                    "equivalente": True,
                    "traduccion": tt,
                },
            )
    out = _filtrar_por_juez(out, t, p_min, m)
    return exito(claves_a_camel(_agrupar_grados(out)[:limite]))


def _filtrar_por_juez(out, t, p_min, m):
    """DECISION DEL AUTOR (2026-10-06): las sugerencias que el juez da por distintas (P < p_min) no
    se muestran. Cambia la regla original de "no se filtra nada, el front decide", ahora que el
    orden lo da un juez validado. Siempre quedan el cargo escrito y los sinonimos; si no queda
    nada mas, las N_RESPALDO mas probables con `seguro: false`, para no dejar al usuario sin
    opciones (titulos raros o con erratas). Sin juez no se filtra.

    PALABRA DESCONOCIDA: si lo escrito tiene una palabra que no aparece en ningun titulo de la base
    (`DESTISTA`), el juez no es confiable (dio P > 0,9 a `DESTALLE`, `ESTADISTICA`, `DISENADOR`):
    nada es `seguro` salvo el cargo escrito y los sinonimos, y `palabras_desconocidas` lo dice
    para que el front sugiera revisar la ortografia."""
    from src.domain.capa0 import limpiar
    from src.shared.utils.texto import _norm

    desconocidas = [w for w in limpiar(_norm(t)).split() if w not in m.vocabulario]
    for r in out:
        r["palabras_desconocidas"] = desconocidas
        r["seguro"] = bool(
            r["sinonimo"]
            or r.get("equivalente")
            or r["similitud"] >= 0.999
            or (not desconocidas and r["p_juez"] is not None and r["p_juez"] >= p_min)
        )
    if m.base.juez is None:
        return out
    seguros = [r for r in out if r["seguro"]]
    if any(not r["sinonimo"] and not r.get("equivalente") and r["similitud"] < 0.999 for r in seguros):
        return seguros
    resto = sorted((r for r in out if not r["seguro"]), key=lambda r: -(r["p_juez"] or 0))
    return seguros + resto[:N_RESPALDO]


def _agrupar_grados(out):
    """`LABORATORISTA 1`, `LABORATORISTA 2`, `LABORATORISTA 4` en UNA sugerencia, con la lista de
    grados en `grados`. Cada grado sigue siendo su propio puesto con su banda (D-040, criterio A:
    el grado es un escalon de ~7 %): solo se juntan para MOSTRAR. Principal: la version sin grado
    si esta; si no, la mejor ubicada. Solo el numero de grado al FINAL del titulo."""
    from src.domain.capa0 import grado_numerico, quitar_grado_final

    grupos, orden = {}, []
    for r in out:
        clave = quitar_grado_final(r["cargo"]) if grado_numerico(r["cargo"]) else r["cargo"]
        if clave not in grupos:
            grupos[clave] = []
            orden.append(clave)
        grupos[clave].append(r)
    res = []
    for clave in orden:
        filas = grupos[clave]
        sin_grado = [r for r in filas if not grado_numerico(r["cargo"])]
        principal = dict(sin_grado[0] if sin_grado else filas[0])
        principal["cargo_sin_grado"] = clave
        con_grado = [r for r in filas if grado_numerico(r["cargo"])]
        principal["grados"] = [
            {
                "grado": sorted(grado_numerico(r["cargo"]))[0],
                "cargo": r["cargo"],
                "empresas": r["empresas"],
                "personas": r["personas"],
                "p_juez": r["p_juez"],
            }
            for r in sorted(con_grado, key=lambda r: sorted(grado_numerico(r["cargo"]))[0])
        ]
        res.append(principal)
    return res


def _empresas_de_grupo(m, g):
    i = np.flatnonzero(np.asarray(m.base.grupo) == g)
    return int(m.base.emp[i[0]]) if len(i) else 0


def _personas_de_grupo(m, g):
    i = np.flatnonzero(np.asarray(m.base.grupo) == g)
    return int(m.base.personas[i[0]]) if len(i) else 0
