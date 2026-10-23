"""El MOTOR: la base y los modelos, cargados UNA vez por instancia.

Es el estado pesado del servicio (~3 GB: base, juez y traductor) y por eso NO es un
service de funciones: vive aqui, se crea al arrancar y los services lo reciben por
nombre. Ver Known Deviations en `.claude/rules/architecture.md`.

CONCURRENCIA. `BaseReferencia.referenciar` no muta el objeto, asi que la base se
comparte entre peticiones sin copia. El diccionario de embeddings SI crece cuando llega
un titulo nuevo, y por eso va detras de un cerrojo y con tope.

    OJO PARA QUIEN TOQUE ESTO: la base es mutable. Los experimentos intercambian
    `b.efecto` y `b.nivel` en caliente para comparar variantes. Hacer eso aqui,
    con la base compartida, corromperia las peticiones en vuelo. No se hace.
"""

import logging
import os
import threading
import time
from collections import Counter

import numpy as np

from src.domain import idioma as idioma_mod
from src.domain import sinonimos
from src.domain.base_referencia import BaseReferencia, ruta_base_mas_nueva
from src.domain.presentacion import representante
from src.infrastructure.modelos import juez as juez_mod
from src.integrations.vertex import vertex_client as embeddings

logger = logging.getLogger(__name__)

TOPE_EMBEDDINGS_NUEVOS = 50_000


# QUE SABE HACER UNA BASE, y que deja de funcionar si no lo trae. Existe porque una
# base vieja NO falla: responde igual, con menos, y en silencio. El servicio arrancaba
# con `demo/base_v8.npz` escrito a mano mientras el RUC, el padron y la cascada vivian en
# la v13 — o sea que tres funciones enteras estaban muertas y nada lo decia.
#
# Cada entrada es (nombre, como se comprueba, que se pierde si falta).
CAPACIDADES = (
    (
        "padron",
        lambda b: len(b.pad_idx) > 0,
        "`empresas_analizadas` no es calculable y no se detecta si el cliente esta " "dentro de su propio mercado",
    ),
    (
        "ruc_a_industria",
        lambda b: len(b.meta_ruc) > 0,
        "el RUC no resuelve ni el rubro ni el segmento: el informe cae al mercado " "entero sin decir por que",
    ),
    (
        "rubro_multinivel",
        lambda b: any(len(str(r)) > 1 for r in b.rubros),
        "el veredicto no puede bajar al sector del cliente; se compara todo contra la " "seccion",
    ),
    (
        "segmento_del_ruc",
        lambda b: any(v[2] for v in b.meta_ruc.values()),
        "el tamano de la empresa hay que pedirlo a mano o no se corrige el sesgo de " "los cargos altos",
    ),
    (
        "brecha_grafia",
        lambda b: bool(np.isfinite(b.brecha_gen).any()),
        "no se reporta la diferencia entre grafias femenina y masculina",
    ),
)


def capacidades_de(base) -> dict:
    """Que puede y que no puede hacer esta base. Nunca revienta por una capacidad."""
    out = {}
    for nombre, prueba, _ in CAPACIDADES:
        try:
            out[nombre] = bool(prueba(base))
        except Exception:  # noqa: BLE001
            out[nombre] = False
    return out


def _ruta_base_por_defecto() -> str:
    """La base mas nueva de `demo/`, por numero de version (ver `ruta_base_mas_nueva`)."""
    return ruta_base_mas_nueva("demo")


class Motor:
    """La base cargada una vez, y el cache de embeddings de titulos nuevos."""

    def __init__(self, ruta_base: str, settings):
        self.settings = settings
        t0 = time.time()
        self.base = BaseReferencia.cargar(ruta_base, settings.get_sbu)
        self.carga_s = round(time.time() - t0, 2)
        # vistas de `base.Z`, no copia
        self.emb = {c: self.base.Z[i] for i, c in enumerate(self.base.celdas)}
        self._lock = threading.Lock()
        self._cli = None
        self.ruta_base = str(ruta_base)
        # Frecuencia de cada palabra en los titulos de la base. Se calcula una vez al
        # arrancar —65.181 titulos, decimas de segundo— y la usa `_representante` para
        # distinguir una errata de una palabra bien escrita.
        frec = Counter()
        for c in self.base.celdas:
            for w in str(c).split():
                frec[w] += 1
        # EL REPRESENTANTE SE PRECALCULA POR GRUPO, sobre TODAS sus grafias. Elegirlo
        # entre las que casualmente entraron en una busqueda daba etiquetas distintas
        # segun la consulta y el limite: buscando `Vendedo` solo entraban 5 de las 13
        # grafias del grupo, `VENDEDOR` no estaba entre ellas, y salia `VEDEDOR`.
        porgrupo = {}
        for i, c in enumerate(self.base.celdas):
            porgrupo.setdefault(int(self.base.grupo[i]), []).append(str(c))
        self.etiqueta = {g: representante(v, frec) for g, v in porgrupo.items()}
        self.n_grafias = {g: len(v) for g, v in porgrupo.items()}
        # D-046/D-047: los sinonimos aprobados no tocan la base; sirven al buscador de cargos
        # D-070/D-072: los pares aprobados (rondas 1 y 2) mas las reglas de palabras del autor
        self.sinonimos = sinonimos.por_grupo(
            self.base, sinonimos.cargar_pares() + sinonimos.pares_por_reglas([str(c) for c in self.base.celdas])
        )
        self.sinonimos_consulta = sinonimos.de_consulta(self.base, sinonimos.cargar_consulta())
        # Las palabras que aparecen en algun titulo de la base. Ante una palabra desconocida
        # (`DESTISTA`, `ODONTOLGO`) el juez extrapola y da P altas a cualquier cosa: ahi no se le cree.
        from src.domain.capa0 import limpiar
        from src.shared.utils.texto import _norm

        self.vocabulario = {w for c in self.base.celdas for w in limpiar(_norm(str(c))).split()}
        # D-048: el juez v3 para los titulos nuevos. `JUEZ` = carpeta con los pesos; `JUEZ=no` lo
        # apaga. Sin pesos o sin torch, el servicio sigue sin el (por analogia, como antes).
        ruta_juez = os.environ.get("JUEZ", "modelos/juez_v3")
        self.base.juez = None if ruta_juez.lower() == "no" else juez_mod.cargar(ruta_juez)
        # 2026-10-06: el juez tambien filtra los vecinos de la analogia (`JUEZ_VECINOS=no` lo apaga)
        self.base.juez_vecinos = os.environ.get("JUEZ_VECINOS", "si").lower() != "no"
        # D-052: un nivel por grupo y el candado de nivel en la consulta (`NIVEL_GRUPO=no` los apaga)
        if os.environ.get("NIVEL_GRUPO", "si").lower() != "no" and getattr(self.base, "clf_nivel", None) is not None:
            self.base.nivel_por_grupo()
            self.base.candado_nivel = True
        # D-050: el traductor local ingles -> espanol, para MOSTRAR el equivalente en espanol
        # (`equivalente`, y primero en `/puestos`). No calcula bandas: para el sueldo empeora (la prima
        # de los titulos en ingles); `IDIOMA_SUELDO=si` lo haria, solo para medir. `TRADUCTOR=no` lo apaga.
        ruta_tr = os.environ.get("TRADUCTOR", "modelos/opus-mt-en-es")
        self.base.traductor = None if ruta_tr.lower() == "no" else idioma_mod.cargar(ruta_tr)
        if self.base.traductor is not None:
            # D-091 (decision del autor): MANAGER = jefe y HEAD = gerente (`INVERTIR_RANGOS=no` vuelve a lo literal)
            self.base.traductor.invertir = os.environ.get("INVERTIR_RANGOS", "si").lower() != "no"
        # 2026-10-07, decision de producto del autor: un titulo en ingles SIN datos directos propios (un
        # cargo nuevo) toma la banda de su equivalente en espanol, tal cual y sin prima. Medido en D-050
        # (`idioma_consulta`): +0,019 donde actua, subestima (prima del ingles ~30-40 %). Los clusters de la
        # base no se tocan. `IDIOMA_SUELDO=no` lo apaga; `IDIOMA_PRIMA=si` usaria la prima de D-055.
        # Desde la decision siguiente del autor (misma fecha): EL MISMO CARGO, LA MISMA BANDA en ingles y
        # en espanol: se usa el equivalente aunque el titulo en ingles tenga datos propios ("siempre").
        # D-067 (2026-10-10, reemplaza a "siempre"): un titulo en ingles con datos propios usa sus datos; sin
        # ellos, la banda de su equivalente en espanol mas la prima del ingles de su nivel (encogida), mostrada
        # aparte. `IDIOMA_SUELDO=siempre` vuelve a la regla anterior (sin prima); `IDIOMA_SUELDO=no` la apaga.
        # D-088 (2026-10-12, decision de producto del autor, reemplaza a D-067): TODO a espanol. El titulo en ingles
        # toma la banda de su equivalente en espanol, sin prima, y si no se resuelve se busca por su traduccion
        # tambien en la analogia (D-062); sin el sufijo de unidad (`- CONSULTING`). `IDIOMA_SUELDO=si` vuelve a
        # D-067 (equivalente + prima solo sin datos propios); `IDIOMA_SUELDO=no` apaga la capa.
        modo = os.environ.get("IDIOMA_SUELDO", "siempre").lower()
        self.base.idioma_sueldo = "siempre" if modo == "siempre" else (modo != "no")
        self.base.idioma_por_traduccion = modo == "siempre"
        self.base.quitar_sufijo = modo == "siempre"
        # D-068 (a): errores de tipeo corregidos contra el vocabulario de la base (`TIPEO=no` lo apaga)
        self.base.tipeo = os.environ.get("TIPEO", "si").lower() != "no"
        # D-069: la confianza tambien depende del ancho de la banda (`CONFIANZA_ANCHO=no` vuelve a la anterior)
        self.base.confianza_ancho = os.environ.get("CONFIANZA_ANCHO", "si").lower() != "no"
        # D-084: en MICRO y PEQUENA ningun cargo, de ningun nivel, queda sobre el GG (`TECHO_TODOS=no` lo limita
        # al nivel 5, como D-082)
        self.base.techo_todos_niveles = os.environ.get("TECHO_TODOS", "si").lower() != "no"
        # D-089: el juez no empareja SEGURO con SEGURIDAD (`CANDADO_SEGURIDAD=no` lo apaga)
        self.base.candado_seguridad = os.environ.get("CANDADO_SEGURIDAD", "si").lower() != "no"
        # D-075: lo que no es un cargo (`ASDFGH`, `ASTRONAUTA`) se responde `no reconocido`, sin cifra. Necesita una
        # base con el clasificador (v28 o mas nueva). `FILTRO_CARGO=no` lo apaga.
        self.base.filtro_cargo = (
            os.environ.get("FILTRO_CARGO", "si").lower() != "no" and getattr(self.base, "clf_cargo", None) is not None
        )
        # D-063: con el tamano del cliente (`segmento`, o el del RUC), el efecto del tamano segun el NIVEL del
        # cargo, para todos los cargos y tambien en la analogia; reemplaza a `ajuste_seg` (D-018). Sin tamano, la
        # referencia no cambia. `TAMANO=no` vuelve a D-018. Necesita una base con `ajuste_tam` (v26 o mas nueva).
        self.base.tamano_estandar = (
            os.environ.get("TAMANO", "si").lower() != "no" and getattr(self.base, "ajuste_tam", None) is not None
        )
        # D-064: en el candado de idioma, `CHIEF EXECUTIVE OFFICER` se lee como `GENERAL MANAGER` (glosario) y no
        # como un ejecutivo de nivel 1: el mismo cargo que `CEO`. `CANDADO_GLOSARIO=no` lo apaga.
        self.base.candado_glosario = os.environ.get("CANDADO_GLOSARIO", "si").lower() != "no"
        if (
            self.base.traductor is None
            or self.base.idioma_sueldo == "siempre"
            or os.environ.get("IDIOMA_PRIMA", "si").lower() == "no"
        ):
            self.base.idioma_prima = None
        if self.base.traductor is not None:
            logger.info("traductor %s", ruta_tr)
        else:
            logger.warning("sin traductor: los titulos en ingles se buscan tal cual")
        if self.base.juez is not None:
            logger.info("juez %s en %s", self.base.juez.nombre, self.base.juez.dispositivo)
        else:
            logger.warning("sin juez: los titulos nuevos van por analogia")
        self.capacidades = capacidades_de(self.base)
        faltan = [(n, p) for n, _, p in CAPACIDADES if not self.capacidades[n]]
        logger.info("base %s: %d puestos, cargada en %.2fs", ruta_base, len(self.base.celdas), self.carga_s)
        for n, porque in faltan:
            # EN VOZ ALTA. Una base a la que le falta algo contesta igual que una
            # completa, solo que peor, y eso no se nota mirando una respuesta.
            logger.warning("base SIN %s: %s", n, porque)
        # D-092: los cargos de direccion en ingles (CEO, CFO, MANAGING DIRECTOR, COUNTRY MANAGER...) toman la banda de
        # su equivalente en espanol por la prima del mercado que titula en ingles, estimada con los pares de direccion
        # de la base. `PRIMA_DIRECCION=no` la apaga (vuelve a todo a espanol sin excepcion).
        if (
            os.environ.get("PRIMA_DIRECCION", "si").lower() != "no"
            and self.base.traductor is not None
            and self.base.idioma_sueldo == "siempre"
        ):
            try:
                dirs = [
                    c for c in self.base.celdas if idioma_mod.es_direccion(c) and self.base.emp[self.base.idx[c]] >= 3
                ]
                self.asegurar(dirs)
                logger.info("prima de direccion %s", self.base.estimar_prima_direccion(self.emb))
            except Exception as e:  # noqa: BLE001 - se informa y se sigue
                self.base.prima_direccion = None
                logger.warning("sin prima de direccion (%r)", e)
        # CALENTAMIENTO (2026-10-12, medido): la primera consulta con un titulo nuevo tardaba 29,6 s —cliente de
        # Vertex, juez, traductor, corrector y clasificador se cargan al primer uso— y despues ~0,6 s. Se paga al
        # arrancar y no el primer cliente. `CALENTAR=no` lo salta; si falla (sin red), el servicio sigue.
        if os.environ.get("CALENTAR", "si").lower() != "no":
            t0 = time.time()
            try:
                prueba = ["ANALISTA DE PRUEBA DE ARRANQUE", "SALES TEST COORDINATOR", "CONTDOR GENERL"]
                self.asegurar(prueba)
                self.base.referenciar(prueba, self.emb)
                logger.info("calentamiento %.1fs", time.time() - t0)
            except Exception as e:  # noqa: BLE001 - se informa y se sigue
                logger.warning("calentamiento fallido (%r); la primera consulta sera lenta", e)

    def _vertex(self):
        if self._cli is None:
            self._cli = embeddings.cliente_vertex(
                self.settings.vertex_embedding_model, self.settings.bq_project, self.settings.vertex_location
            )
        return self._cli

    def asegurar(self, titulos) -> int:
        """Embebe los titulos que la base no conoce. Devuelve cuantos hubo.

        Es la unica parte con dependencia de red, y por eso el informe va por lotes: en
        una API sincrona esto serian 100-300 ms de latencia impredecible por peticion.
        """
        # D-050: tambien las traducciones de los titulos en ingles, que se buscan por ellas
        # D-087: tambien el titulo en ingles sin su sufijo de unidad (`HEAD OF X - CONSULTING` -> `HEAD OF X`)
        sufijos = (
            [idioma_mod.sin_sufijo(t) for t in titulos if t]
            if getattr(self.base, "quitar_sufijo", False) or getattr(self.base, "head_jefe", False)
            else []
        )
        titulos = list(titulos) + [x for x in sufijos if x not in titulos]
        titulos = list(titulos) + self.base.traducciones_a_embeber([t for t in titulos if t])
        faltan = sorted({t for t in titulos if t and t not in self.emb})
        if not faltan:
            return 0
        X = embeddings.embeber(faltan, self._vertex(), self.settings.vertex_embedding_model)
        with self._lock:
            if len(self.emb) - len(self.base.celdas) > TOPE_EMBEDDINGS_NUEVOS:
                # Se tira el cache caliente entero antes que crecer sin limite. Es un
                # servicio de larga vida y los titulos nuevos no dejan de llegar.
                self.emb = {c: self.base.Z[i] for i, c in enumerate(self.base.celdas)}
            self.emb.update(dict(zip(faltan, X)))
        return len(faltan)


_MOTOR: Motor | None = None


def iniciar_motor() -> Motor:
    """Carga la base y los modelos. Lo llama el arranque de la app, una sola vez."""
    global _MOTOR
    from src.config.ajustes import cargar_settings

    _MOTOR = Motor(os.environ.get("BASE_REFERENCIA") or _ruta_base_por_defecto(), cargar_settings())
    return _MOTOR


def liberar_motor() -> None:
    global _MOTOR
    _MOTOR = None


def obtener_motor() -> Motor:
    """El motor cargado; 503 mientras la instancia todavia esta arrancando."""
    if _MOTOR is None:
        from src.shared.contracts.responses import error
        from src.shared.exceptions.http_request_exception import HTTPRequestException

        raise HTTPRequestException(response_model=error(503, "la base todavia no esta cargada"))
    return _MOTOR
