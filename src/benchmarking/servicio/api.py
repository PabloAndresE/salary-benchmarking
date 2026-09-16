"""Servicio HTTP: una nomina entra, un informe sale.

    uvicorn benchmarking.servicio.api:app --port 8080

POR QUE POR LOTES Y NO UNA CONSULTA POR TITULO. El ancla de empresa —lo que habilita la
lectura de equidad interna, la parte mas valiosa del producto— necesita TODAS las filas a
la vez: es la mediana de (lo que paga - lo que dice el mercado) sobre la nomina entera.
Una API que conteste titulo a titulo devuelve la mitad del producto y ademas invita a
usarla mal. Hay un `/referencia` suelto para explorar, y dice en su respuesta que no
lleva ancla.

LA BASE SE CARGA UNA VEZ. Medido: 2,5 s de arranque y 406 MB residentes, de los cuales
382 son la matriz de embeddings. Construirla son 28 minutos y eso ocurre offline.

CONCURRENCIA. `BaseReferencia.referenciar` no muta el objeto, asi que la base se comparte
entre peticiones sin copia. El diccionario de embeddings SI crece cuando llega un titulo
nuevo, y por eso va detras de un cerrojo y con tope: sin el, una racha de titulos basura
lo hace crecer sin limite.

    OJO PARA QUIEN TOQUE ESTO: la base es mutable. Los experimentos intercambian
    `b.efecto` y `b.nivel` en caliente para comparar variantes. Hacer eso aqui,
    con la base compartida, corromperia las peticiones en vuelo. No se hace.

DATOS PERSONALES. La nomina que sube un cliente lleva nombres y sueldos: es dato personal
bajo LOPDP. Este servicio **no escribe el archivo a disco** —se procesa en memoria— y el
resultado vive en memoria con caducidad. No hay base de datos a proposito: persistir eso
es una decision de arquitectura y de contrato, no un detalle de implementacion.

LO QUE NO TRAE, y hay que decirlo antes de exponerlo: autenticacion, cuotas,
multi-tenencia y trazabilidad de accesos. Detras de una puerta, no en internet abierto.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import os
import pathlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..config.settings import cargar_settings
from ..evaluacion import embeddings
from ..producto.antiguedad import TRAMOS as TRAMOS_ANTIGUEDAD
from ..producto.antiguedad import antiguedad_anios, tramo
from ..producto.base_referencia import (MIN_EMPRESAS_VEREDICTO, SEGMENTOS,
                                        BaseReferencia)
from ..producto.formato import CANONICAS, FormatoInvalido, OBLIGATORIAS
from ..producto.formato import validar as validar_formato
from ..producto.comparacion import comparar, texto_resumen
from ..producto.referenciar_nomina import _POSIBLES, _POSIBLES_SUELDO, _buscar_sueldo

ESQUEMA = "1.0"
TTL_SEGUNDOS = 60 * 60          # el informe caduca en una hora: no es un almacen
TOPE_EMBEDDINGS_NUEVOS = 50_000  # techo del cache caliente de titulos no vistos

# UNIDADES DECLARADAS. Un front que formatee `vs_mercado` como dolares produce un numero
# creible y falso, que es peor que un error. Viaja con cada respuesta.
UNIDADES = {
    "sueldo_actual": {"unidad": "usd", "formato": "$#,##0.00"},
    "referencia": {"unidad": "usd", "formato": "$#,##0.00"},
    "p10": {"unidad": "usd"}, "p25": {"unidad": "usd"},
    "p75": {"unidad": "usd"}, "p90": {"unidad": "usd"},
    "vs_mercado": {"unidad": "ratio", "formato": "+0.0%"},
    "vs_politica_interna": {"unidad": "ratio", "formato": "+0.0%"},
    "brecha_grafia": {"unidad": "ratio", "formato": "+0.0%"},
    "incert_centro": {"unidad": "ratio", "formato": "0.0%"},
    "ancho_rel": {"unidad": "ratio"},
    "similitud": {"unidad": "coseno", "rango": [0, 1]},
    "empresas": {"unidad": "conteo"}, "personas": {"unidad": "conteo"},
    "antiguedad_anios": {"unidad": "anios", "formato": "0.0"},
    # La lista sale de donde se calcula, no se copia: el front la necesita COMPLETA
    # —una nomina joven no trae `mas de 20` y el filtro saldria sin esa opcion— y dos
    # copias son dos cosas que hay que acordarse de cambiar juntas.
    "antiguedad_tramo": {"unidad": "categoria", "valores": list(TRAMOS_ANTIGUEDAD)},
}


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
_CIIU = json.loads((pathlib.Path(__file__).parent.parent / "datos" / "ciiu.json")
                   .read_text(encoding="utf-8"))


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


def _opt(v: str | None) -> str | None:
    """Un campo de formulario vacio es AUSENCIA, no la cadena vacia.

    Y `"string"` tambien: es el marcador que Swagger deja puesto en los campos
    opcionales, y mandarlo tal cual daba un 400 confuso —«segmento invalido: string»—
    en la primera prueba de cualquiera que abra `/docs`. La interfaz de pruebas no
    deberia ser una trampa.
    """
    if v is None:
        return None
    t = v.strip()
    return None if t == "" or t.lower() == "string" else t


# LO QUE EL MODELO PRODUCE, para poder ordenarlo primero en la respuesta.
#
# LAS COLUMNAS DEL CLIENTE VIAJAN POR DEFECTO. Lo intente al reves —devolver solo lo del
# modelo, por minimizar el movimiento de dato personal— y estaba mal: el front necesita
# el NOMBRE para decir a quien hay que subirle el sueldo, la ANTIGUEDAD para explicar por
# que cobra lo que cobra, y el SEXO para el analisis de brecha. Sin eso el informe no se
# puede pintar y obliga al front a rehacer el cruce por su cuenta.
#
# Se puede recortar con `columnas_originales=false`, para el front que ya tiene el
# archivo y solo quiere los numeros.
#
# OJO: que `sexo` viaje al front NO contradice la regla de que `sexo` nunca es una
# variable del modelo. No entra en ningun calculo de la referencia; sale para que se
# pueda MEDIR la brecha, que es exactamente su uso previsto (D-011).
#
# `fila` es el indice 0-based de la nomina subida, para casar sin ambiguedad aunque haya
# dos personas con el mismo nombre y cargo.
SALIDA_MODELO = (
    # `cargo` es lo que escribio el cliente, fila por fila. `cargo_normalizado` es la
    # clave con la que se agrupo `por_puesto`: sin ella el front no puede unir las dos
    # tablas, porque la etiqueta de un puesto es UNA grafia y el detalle trae todas.
    "fila", "cargo", "cargo_normalizado", "estado", "antiguedad_anios",
    "antiguedad_tramo",
    "referencia", "sueldo_actual",
    "vs_mercado", "vs_politica_interna", "lectura_mercado", "lectura_interna",
    "p10", "p25", "p75", "p90", "confianza", "incert_centro", "ancho_rel",
    "base", "empresas", "personas", "similitud", "segmento", "rubro",
    # A QUE NIVEL se comparo ese cargo. Sin esto, `rubro: "G47"` obliga al front a
    # deducir del largo del codigo si eso es una division o una clase.
    "rubro_nivel",
)


def _col(df, pedida: str | None) -> str | None:
    """Casa el nombre de columna que pide el cliente con el real, tolerando espacios.

    DOS COSAS QUE FALLABAN. `_opt` recorta los extremos, y hay columnas que TERMINAN en
    espacio —la plantilla actuarial trae `'Ultimo sueldo/pension mensual '`—, asi que el
    nombre recortado dejaba de coincidir. Y `_buscar_sueldo` devolvia None sin decir
    nada: el cliente pedia una columna explicitamente, se le ignoraba, y recibia un
    informe sin comparacion y sin saber por que.

    Se compara normalizando los dos lados. Si aun asi no aparece, quien llama levanta un
    400 con la lista: fallar en voz alta.
    """
    if not pedida:
        return None
    norm = lambda x: " ".join(str(x).split()).casefold()
    objetivo = norm(pedida)
    for c in df.columns:
        if norm(c) == objetivo:
            return c
    return None


def _py(v):
    """De tipos de numpy/pandas a tipos de Python, y de NaN a None.

    FastAPI no serializa `numpy.int64` y falla con un 500 opaco. El camino por lotes se
    salvaba de casualidad —`to_dict` convierte algunas columnas— y `/referencia` no. Se
    normaliza en un solo sitio para que no vuelva a depender de la suerte.
    """
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if not np.isfinite(f) else f
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, np.ndarray):
        return [_py(x) for x in v.tolist()]
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    return v


def _estado(fila) -> str:
    """Estado EXPLICITO en vez de un NaN que el front tiene que adivinar.

    Un nulo puede significar cinco cosas distintas —no conocemos el cargo, el sueldo era
    ilegible, la celda no llega al suelo— y cada una lleva a un mensaje distinto en la
    interfaz. Devolverlas todas como `null` obliga al front a reinventar la logica.
    """
    if str(fila.get("base", "") or "") == "sin cargo":
        return "cargo_vacio"
    lect = str(fila.get("lectura_mercado", "") or "")
    if lect == "sueldo ilegible":
        return "sueldo_ilegible"
    if lect == "sin referencia" or not np.isfinite(
            pd.to_numeric(fila.get("referencia"), errors="coerce")):
        return "sin_referencia"
    base = str(fila.get("base", "") or "")
    if base.startswith("rubro"):
        return "directa_rubro"
    if base == "datos directos":
        return "directa"
    return "analogia"


@dataclass
class Trabajo:
    id: str
    estado: str = "en_cola"
    creado: float = field(default_factory=time.time)
    error: str | None = None
    resultado: dict[str, Any] | None = None
    excel: bytes | None = None


class Almacen:
    """Trabajos en memoria con caducidad. NO es una base de datos y no debe serlo: aqui
    dentro hay nombres y sueldos de personas."""

    def __init__(self, ttl: float = TTL_SEGUNDOS):
        self._d: dict[str, Trabajo] = {}
        self._ttl = ttl
        self._lock = threading.Lock()

    def _purgar(self) -> None:
        corte = time.time() - self._ttl
        for k in [k for k, t in self._d.items() if t.creado < corte]:
            del self._d[k]

    def nuevo(self) -> Trabajo:
        with self._lock:
            self._purgar()
            t = Trabajo(id=uuid.uuid4().hex)
            self._d[t.id] = t
            return t

    def get(self, tid: str) -> Trabajo | None:
        with self._lock:
            self._purgar()
            return self._d.get(tid)


# QUE SABE HACER UNA BASE, y que deja de funcionar si no lo trae. Existe porque una
# base vieja NO falla: responde igual, con menos, y en silencio. El servicio arrancaba
# con `demo/base_v8.npz` escrito a mano mientras el RUC, el padron y la cascada vivian en
# la v13 — o sea que tres funciones enteras estaban muertas y nada lo decia.
#
# Cada entrada es (nombre, como se comprueba, que se pierde si falta).
CAPACIDADES = (
    ("padron",
     lambda b: len(b.pad_idx) > 0,
     "`empresas_analizadas` no es calculable y no se detecta si el cliente esta "
     "dentro de su propio mercado"),
    ("ruc_a_industria",
     lambda b: len(b.meta_ruc) > 0,
     "el RUC no resuelve ni el rubro ni el segmento: el informe cae al mercado "
     "entero sin decir por que"),
    ("rubro_multinivel",
     lambda b: any(len(str(r)) > 1 for r in b.rubros),
     "el veredicto no puede bajar al sector del cliente; se compara todo contra la "
     "seccion"),
    ("segmento_del_ruc",
     lambda b: any(v[2] for v in b.meta_ruc.values()),
     "el tamano de la empresa hay que pedirlo a mano o no se corrige el sesgo de "
     "los cargos altos"),
    ("brecha_grafia",
     lambda b: bool(np.isfinite(b.brecha_gen).any()),
     "no se reporta la diferencia entre grafias femenina y masculina"),
)


def capacidades_de(base) -> dict:
    """Que puede y que no puede hacer esta base. Nunca revienta por una capacidad."""
    out = {}
    for nombre, prueba, _ in CAPACIDADES:
        try:
            out[nombre] = bool(prueba(base))
        except Exception:                                    # noqa: BLE001
            out[nombre] = False
    return out


def _ruta_base_por_defecto() -> str:
    """La base mas nueva de `demo/`, por numero de version.

    NO por fecha de modificacion: copiar un fichero viejo lo volveria el mas nuevo. Y no
    una constante escrita a mano, que es como se llego a servir la v8 durante una semana
    mientras se construian la v9 a la v13.
    """
    import re
    d = pathlib.Path("demo")
    if not d.is_dir():
        return "demo/base_referencia.npz"
    cand = []
    for f in d.glob("base_v*.npz"):
        m = re.fullmatch(r"base_v(\d+)", f.stem)
        if m:
            cand.append((int(m.group(1)), f))
    if not cand:
        return "demo/base_referencia.npz"
    return str(max(cand)[1]).replace("\\", "/")


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
        self.capacidades = capacidades_de(self.base)
        faltan = [(n, p) for n, _, p in CAPACIDADES if not self.capacidades[n]]
        print(f"[base] {ruta_base}  {len(self.base.celdas):,} puestos  "
              f"{self.carga_s}s", flush=True)
        for n, porque in faltan:
            # EN VOZ ALTA. Una base a la que le falta algo contesta igual que una
            # completa, solo que peor, y eso no se nota mirando una respuesta.
            print(f"[base] SIN {n}: {porque}", flush=True)

    def _vertex(self):
        if self._cli is None:
            self._cli = embeddings.cliente_vertex(
                self.settings.vertex_embedding_model, self.settings.bq_project,
                self.settings.vertex_location)
        return self._cli

    def asegurar(self, titulos) -> int:
        """Embebe los titulos que la base no conoce. Devuelve cuantos hubo.

        Es la unica parte con dependencia de red, y por eso el informe va por lotes: en
        una API sincrona esto serian 100-300 ms de latencia impredecible por peticion.
        """
        faltan = sorted({t for t in titulos if t and t not in self.emb})
        if not faltan:
            return 0
        X = embeddings.embeber(faltan, self._vertex(),
                               self.settings.vertex_embedding_model)
        with self._lock:
            if len(self.emb) - len(self.base.celdas) > TOPE_EMBEDDINGS_NUEVOS:
                # Se tira el cache caliente entero antes que crecer sin limite. Es un
                # servicio de larga vida y los titulos nuevos no dejan de llegar.
                self.emb = {c: self.base.Z[i]
                            for i, c in enumerate(self.base.celdas)}
            self.emb.update(dict(zip(faltan, X)))
        return len(faltan)


def leer_nomina_bytes(contenido: bytes, nombre: str, col_cargo: str | None = None):
    """Como `leer_nomina` pero desde memoria y sin `SystemExit`.

    El CLI aborta el proceso ante una nomina mala, que es lo correcto en una terminal y
    catastrofico en un servidor: mataria al worker. Aqui se levanta `ValueError` y la capa
    HTTP lo convierte en un 400 con el motivo.

    Y NO SE ESCRIBE A DISCO: la nomina lleva nombres y sueldos.
    """
    buf = io.BytesIO(contenido)
    try:
        df = (pd.read_csv(buf, dtype=str) if nombre.lower().endswith(".csv")
              else pd.read_excel(buf, dtype=str))
    except Exception as e:                                   # noqa: BLE001
        raise ValueError(f"no se pudo leer el archivo: {e}") from e
    if df.empty:
        raise ValueError("el archivo no tiene filas")
    if col_cargo:
        real = _col(df, col_cargo)
        if real is None:
            raise ValueError(f"la columna '{col_cargo}' no esta en el archivo. "
                             f"Columnas: {list(df.columns)}")
        return df, real
    normal = {c.strip().lower().replace(" ", "_"): c for c in df.columns}
    for cand in _POSIBLES:
        if cand in normal:
            return df, normal[cand]
    raise ValueError(f"no encuentro la columna de cargo. Columnas: {list(df.columns)}. "
                     f"Indicala con el parametro `columna_cargo`.")


def _anidar_sector(filas: list) -> list:
    """`sector_*` plano -> un bloque `sector_mas_fino`, o `null`.

    POR QUE ANIDADO. Las tres columnas planas se leen como "datos del sector" y el front
    las pinta al lado de la referencia. Juntas en un bloque con nombre se leen como lo
    que son: la EXPLICACION de por que el veredicto uso el nivel que uso. Y `null` dice
    "no hay nada que explicar" mucho mejor que tres cadenas vacias.

    `umbral` viaja dentro a proposito, en vez de estar escrito en el front: si algun dia
    se cambia `MIN_EMPRESAS_VEREDICTO`, el texto del informe sigue siendo cierto solo.
    """
    out = []
    for f in filas:
        g = {k: v for k, v in f.items() if not k.startswith("sector_")}
        cod = f.get("sector_codigo") or ""
        g["sector_mas_fino"] = ({"codigo": cod,
                                 "nivel": f.get("sector_nivel") or "",
                                 "empresas": int(f.get("sector_empresas") or 0),
                                 "umbral": MIN_EMPRESAS_VEREDICTO}
                                if cod else None)
        out.append(g)
    return out


def procesar(motor: Motor, df, col_cargo: str, anio: int,
             segmento: str | None, rubro: str | None,
             col_sueldo: str | None, columnas_extra: list[str] | None = None,
             columnas_originales: bool = True,
             informe_formato: dict | None = None,
             ruc: str | None = None,
             ciiu: str | None = None) -> tuple[dict, bytes]:
    """El informe completo. Es la misma cadena que el CLI, sin tocar el disco."""
    titulos = df[col_cargo].fillna("").astype(str).str.strip().str.upper()
    nuevos = motor.asegurar(titulos.tolist())

    ref = motor.base.referenciar(titulos.tolist(), motor.emb, anio=anio,
                                 segmento=segmento, rubro=rubro, ruc=ruc,
                                 ciiu=ciiu)
    salida = pd.concat([df.reset_index(drop=True),
                        ref.drop(columns=["cargo"]).reset_index(drop=True)], axis=1)

    cs = _buscar_sueldo(df, col_sueldo)
    por_puesto = resumen = None
    if cs:
        salida, por_puesto, resumen = comparar(salida, cs, col_cargo, ref,
                                               motor.settings.get_sbu, anio)
    salida["estado"] = [_estado(f) for _, f in salida.iterrows()]
    # ANTIGUEDAD, para el filtro del front y para explicar por que alguien cobra lo que
    # cobra. Se calcula descontando los periodos fuera: ver `producto/antiguedad.py`.
    salida["antiguedad_anios"] = antiguedad_anios(df, anio).to_numpy()
    salida["antiguedad_tramo"] = tramo(salida["antiguedad_anios"]).to_numpy()
    # La hoja del cliente no lleva escala logaritmica ni la banda de empresas: esa va en
    # `por_puesto`, que es donde la unidad coincide. Mismo criterio que el CLI.
    salida = salida.drop(columns=[c for c in salida.columns
                                  if c.endswith("_log") or c.endswith("_emp")
                                  or c == "sd"], errors="ignore")

    # EL EXCEL LLEVA TODO —es el entregable humano— y el JSON solo lo del modelo.
    xls = io.BytesIO()
    with pd.ExcelWriter(xls) as w:
        salida.to_excel(w, sheet_name="detalle", index=False)
        if por_puesto is not None:
            por_puesto.to_excel(w, sheet_name="por_puesto", index=False)

    limpio = lambda d: [{str(k): _py(v) for k, v in fila.items()}
                        for fila in d.to_dict("records")]

    json_det = salida.copy()
    json_det.insert(0, "fila", range(len(json_det)))
    json_det["cargo"] = df[col_cargo].fillna("").astype(str).str.strip().to_numpy()
    quedan = [c for c in SALIDA_MODELO if c in json_det.columns]
    if columnas_originales:
        quedan += [c for c in json_det.columns if c not in quedan]
    else:
        quedan += [c for c in (columnas_extra or []) if c in json_det.columns
                   and c not in quedan]
    json_det = json_det[quedan]

    # ---- TARJETAS DE CABECERA -------------------------------------------------
    # Todo EXACTO, sin cotas. `trabajadores` porque las celdas son disjuntas —cada
    # persona esta en una sola— y `empresas` porque el padron guarda QUE empresas
    # respaldan cada celda, no solo cuantas: la union se calcula de verdad en vez de
    # sumar conteos, que contaria varias veces a la que respalda varios cargos.
    # SE CUENTA LO QUE DE VERDAD SE USO, celda por celda. Con `--rubro`, las celdas
    # que tenian respaldo sectorial se comparan contra empresas de ESE rubro y las que
    # no, contra el mercado entero — el fallback es por cargo. Contar el padron entero
    # daria 4.405 empresas cuando la comparacion de dos tercios de las filas se hizo
    # contra un subconjunto: la tarjeta describiria algo que no paso.
    usa_rubro = {}
    if "rubro" in ref.columns:
        usa_rubro = {t: str(r or "") for t, r in zip(ref["cargo"], ref["rubro"])}
    idx = [(t, motor.base.idx[t]) for t in set(titulos) if t in motor.base.idx]
    vistos, trabajadores, empresas = set(), 0, set()
    n_sectoriales = 0
    for t, i in idx:
        g = int(motor.base.grupo[i])
        if g in vistos:
            continue
        vistos.add(g)
        trabajadores += int(motor.base.personas[i])
        del_celda = motor.base.empresas_de(i)
        r = usa_rubro.get(t, "")
        if r:
            n_sectoriales += 1
            del_celda = [e for e in del_celda.tolist()
                         if e < len(motor.base.pad_ciiu)
                         and str(motor.base.pad_ciiu[e] or "").startswith(r)]
        empresas.update(int(e) for e in del_celda)
    con_padron = len(motor.base.pad_idx) > 0

    tam = motor.base.pad_tam
    tallas = [int(tam[e]) for e in empresas if e < len(tam) and tam[e] > 0]
    mercado = {
        "cargos_del_cliente": int(pd.Series(titulos).nunique()),
        "cargos_con_datos_en_la_base": len(vistos),
        "cargos_comparados_contra_su_rubro": n_sectoriales,
        "trabajadores_analizados": trabajadores,
        "empresas_analizadas": len(empresas) if con_padron else None,
        "tamano_de_las_empresas": ({"minimo": min(tallas), "maximo": max(tallas),
                                    "mediana": int(np.median(tallas)),
                                    "con_dato": len(tallas),
                                    "sin_dato": len(empresas) - len(tallas)}
                                   if tallas else None),
    }
    if rubro and n_sectoriales < len(vistos):
        mercado["nota_rubro"] = (
            f"{n_sectoriales} de {len(vistos)} cargos se comparan contra empresas de "
            f"{rubro}; el resto no llega al suelo de respaldo en ese sector y se compara "
            f"contra el mercado entero. El fallback es por cargo.")
    # .CUANTO SE ESTA MIRANDO EL CLIENTE AL ESPEJO? Si su empresa participo en los
    # estudios, su propio sueldo entra en la mediana que le sirve de referencia. NO se le
    # quita —de una mediana ponderada no se resta un voto sin guardar los votos, que
    # seria guardar lo que paga cada empresa por cada cargo; ver D-027—, pero se dice.
    #
    # El umbral son 10 empresas y esta medido, no elegido: por encima, quitar una mueve
    # el centro un 0,39% y corregirlo seria corregir ruido; por debajo lo mueve un 5,4%
    # y el cliente pesa entre un 15% y un 33% del mercado.
    if "tu_empresa" in ref.columns and ruc:
        propio = ref[["cargo", "tu_empresa", "tu_influencia", "empresas"]].drop_duplicates("cargo")
        dentro = propio[propio["tu_empresa"].astype(bool)]
        finos = dentro[pd.to_numeric(dentro["empresas"], errors="coerce") < 10]
        mercado["cargos_donde_tu_empresa_esta_en_el_mercado"] = int(len(dentro))
        mercado["cargos_donde_eso_pesa"] = int(len(finos))
        if len(finos):
            peor = finos.sort_values("tu_influencia", ascending=False).iloc[0]
            mercado["nota_espejo"] = (
                f"Tu empresa respalda {len(dentro)} de los cargos que comparas, y en "
                f"{len(finos)} el mercado es tan estrecho que tu propio sueldo pesa lo "
                f"suyo dentro de la referencia — en {peor['cargo']}, un "
                f"{100 * float(peor['tu_influencia']):.0f}%. Esas lecturas no son "
                f"independientes: mira `tu_influencia` en `por_puesto`.")
        elif len(dentro):
            mercado["nota_espejo"] = (
                f"Tu empresa respalda {len(dentro)} de los cargos que comparas, todos "
                f"con 10 o mas empresas detras. Medido, quitarte moveria la referencia "
                f"un 0,4%: la comparacion se sostiene.")
    if not con_padron:
        mercado["nota"] = ("Esta base se construyo sin padron de empresas: "
                           "`empresas_analizadas` no es calculable. Reconstruyela.")
    elif tallas and len(tallas) < len(empresas):
        mercado["nota_tamano"] = (f"{len(empresas) - len(tallas)} de {len(empresas)} "
                                  f"empresas no tienen tamano registrado y quedan fuera "
                                  f"del rango.")

    industria = None
    if rubro:
        grupos_ciiu = {}
        for e in empresas:
            if e < len(motor.base.pad_ciiu):
                g6 = str(motor.base.pad_ciiu[e] or "")
                if g6.startswith(rubro):
                    grupos_ciiu[g6] = grupos_ciiu.get(g6, 0) + 1
        top = sorted(grupos_ciiu.items(), key=lambda kv: -kv[1])[:5]
        # CONTRA QUE SE COMPARO, que con la cascada ya no es una sola cosa: unos cargos
        # bajan a la division del cliente y otros se quedan en su seccion.
        #
        # `nombre` es el nivel MAS FINO al que se llego, no el que cubre mas cargos. Es
        # decision de producto: la etiqueta contesta "hasta donde supimos afinar contigo",
        # y una libreria prefiere leer "comercio al por menor" antes que "comercio al por
        # mayor y al por menor; reparacion de vehiculos".
        #
        # EL PRECIO, para que quede escrito: el nivel mas fino puede cubrir UN solo cargo
        # de veinte, y la etiqueta describira igual el informe entero. Por eso viajan
        # `cargos_en_ese_nivel` —cuantos cubre de verdad— y `niveles` con el reparto
        # completo. Si esa cifra es 1 de 20, la etiqueta es cierta y engañosa a la vez, y
        # quien pinte la pantalla tiene con que matizarlo.
        usados = {}
        if "rubro" in ref.columns and "rubro_nivel" in ref.columns:
            vistos = set()
            for t, cod, niv in zip(ref["cargo"], ref["rubro"], ref["rubro_nivel"]):
                if t in vistos or not str(cod):
                    continue
                vistos.add(t)
                k = (str(cod), str(niv))
                usados[k] = usados.get(k, 0) + 1
        # el mas fino primero: codigo mas largo. Empate -> el que cubra mas cargos.
        orden = sorted(usados.items(), key=lambda kv: (-len(kv[0][0]), -kv[1]))
        (cod_pre, niv_pre), n_pre = orden[0] if orden else ((rubro, "seccion"), 0)
        industria = {
            # lo que el front rotula como "el mercado". Es el nivel predominante.
            "codigo": cod_pre,
            "nivel": niv_pre,
            "nombre": nombre_ciiu(cod_pre),
            "cargos_en_ese_nivel": n_pre,
            "niveles": [{"codigo": c, "nivel": n, "cargos": v, "nombre": nombre_ciiu(c)}
                        for (c, n), v in orden],
            # LA SECCION, y solo la seccion. Lo que el front rotula como "el mercado"
            # es `nombre` —el nivel mas fino al que llego la cascada—; esto se queda
            # aparte y con su nombre honesto, para que dentro de seis meses nadie lea
            # "nombre_seccion" y reciba una division.
            "ciiu_seccion": rubro,
            "nombre_seccion": nombre_ciiu(rubro),
            "grupos_ciiu": [{"codigo": c, "empresas": n, "nombre": nombre_ciiu(c)}
                            for c, n in top],
        }

    cuerpo = {
        "esquema": ESQUEMA,
        # ARRIBA, no dentro de `meta`. Estaba en `meta` aqui y en la raiz en
        # `/referencia`: el mismo contrato en dos sitios segun el endpoint, asi que un
        # front que leia `respuesta.unidades` recibia nada de este y lo daba por vacio.
        # Es justo el fallo que `UNIDADES` existe para evitar —formatear un ratio como
        # dolares da un numero creible y falso—, solo que en la capa de arriba.
        "unidades": UNIDADES,
        "mercado": mercado,
        "industria": industria,
        "meta": {
            "anio": anio, "sbu": motor.settings.get_sbu(anio),
            "segmento": segmento, "rubro": rubro,
            "titulos_nuevos_embebidos": nuevos,
            "puestos_en_la_base": len(motor.base.celdas),
            "tau": round(float(np.sqrt(motor.base.tau2)), 4),
            "sigma": round(float(np.sqrt(motor.base.sigma2)), 4),
            "columnas_omitidas": ([] if columnas_originales else
                                  [c for c in salida.columns
                                   if c not in SALIDA_MODELO
                                   and c not in (columnas_extra or [])]),
            "nota_detalle": ("Cada fila trae lo del modelo primero y despues tus propias "
                             "columnas. `fila` es el indice 0-based del archivo que "
                             "subiste." if columnas_originales else
                             "Solo viajan las columnas del modelo: usa `fila` para casar "
                             "con tu copia del archivo."),
            "aviso": "La brecha_grafia compara dos GRAFIAS de titulo escritas por "
                     "empresas distintas, sin control por empresa, sector ni "
                     "antiguedad. NO es una brecha salarial medida.",
        },
        "formato": informe_formato,
        "reparto_estado": {str(k): int(v) for k, v
                           in salida["estado"].value_counts().items()},
        "reparto_confianza": ({str(k): int(v) for k, v
                               in ref["confianza"].value_counts().items()}
                              if "confianza" in ref else {}),
        "detalle": limpio(json_det),
        "por_puesto": (_anidar_sector(limpio(por_puesto))
                       if por_puesto is not None else []),
        "resumen": {k: _py(v) for k, v in (resumen or {}).items()},
        "texto": texto_resumen(resumen, por_puesto) if resumen is not None else "",
    }
    return cuerpo, xls.getvalue()


# ============================== capa HTTP ==============================
from contextlib import asynccontextmanager  # noqa: E402

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form,  # noqa: E402
                     HTTPException, UploadFile)
from fastapi.responses import Response  # noqa: E402

_estado_app: dict[str, Any] = {}
ALMACEN = Almacen()


@asynccontextmanager
async def ciclo(app: FastAPI):
    import os
    s = cargar_settings()
    _estado_app["motor"] = Motor(
        os.environ.get("BASE_REFERENCIA") or _ruta_base_por_defecto(), s)
    yield
    _estado_app.clear()


app = FastAPI(title="Referenciador salarial", version=ESQUEMA, lifespan=ciclo)

# CORS PARA DESARROLLO LOCAL. Sin esto, un front en `localhost:5173` pidiendo a
# `localhost:8000` recibe un bloqueo del navegador y no llega ni una peticion.
#
# NO SE ABRE A `*`, y no es celo: este servicio devuelve referencias salariales
# construidas sobre 6.722 empresas. `*` mas un despliegue publico es un volcado de datos
# de compensacion a quien pase por ahi. Los origenes por defecto son los puertos tipicos
# de desarrollo en la propia maquina; para cualquier otra cosa, `CORS_ORIGINS` con la
# lista explicita. El docstring del modulo ya lo dice: detras de una puerta.
_ORIGENES = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://localhost:4200,"
    "http://localhost:8080,http://127.0.0.1:3000,http://127.0.0.1:5173"
).split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_ORIGENES,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def motor() -> Motor:
    m = _estado_app.get("motor")
    if m is None:
        raise HTTPException(503, "la base todavia no esta cargada")
    return m


@app.get("/salud")
def salud(m: Motor = Depends(motor)):
    faltan = [n for n, ok in m.capacidades.items() if not ok]
    return {"ok": True, "esquema": ESQUEMA,
            "puestos": len(m.base.celdas), "carga_s": m.carga_s,
            "anios_con_sbu": sorted(m.settings.sbu),
            # QUE SABE HACER ESTA BASE. Un front que reciba `ruc_a_industria: false`
            # sabe que no tiene sentido pedir el RUC; sin esto, lo pide y no pasa nada.
            "base": m.ruta_base,
            "capacidades": m.capacidades,
            "degradado": faltan or None,
            "aviso": (None if not faltan else
                      f"esta base no soporta {faltan}; el servicio responde igual pero "
                      f"con menos. Reconstruyela o apunta BASE_REFERENCIA a una nueva")}


@app.post("/informes", status_code=202)
def crear(tareas: BackgroundTasks,
          archivo: UploadFile = File(..., description="Excel o CSV. Primera hoja, "
                                                      "encabezados en la fila 1."),
          anio: int | None = Form(
              None, description="Ano del SBU con el que se dolariza. Por defecto EL "
                                "ACTUAL: un informe es del ano en que se emite, y "
                                "fijarlo a mano es como se acaba entregando dolares del "
                                "ano pasado sin que nadie lo note. Solo se pasa para "
                                "rehacer un informe viejo."),
          ruc: str | None = Form(
              None, description="RUC de la empresa del cliente. Con el se resuelve su "
                                "industria (CIIU) y su tamano sin que tenga que "
                                "saberselos, y se detecta si su propia empresa esta en "
                                "la base."),
          segmento: str | None = Form(
              None, description="OPCIONAL. Tamano de la empresa del cliente: "
                                "MICROEMPRESA, PEQUENA, MEDIANA o GRANDE. Corrige el "
                                "sesgo de los cargos altos (D-018)."),
          rubro: str | None = Form(
              None, description="OPCIONAL. CIIU de primer nivel (una letra). Compara "
                                "solo contra ese sector donde haya respaldo. NO mejora "
                                "la precision: estrecha el respaldo (D-023)."),
          formato_libre: bool = Form(
              False, description="Por defecto se exige el FORMATO del producto: "
                                 "columna `cargo` obligatoria, y opcionales `sueldo`, "
                                 "`id_empleado`, `nombre`, `sexo`, `fecha_ingreso`, "
                                 "`centro_costo`. No se aceptan cedulas. Ponlo en true "
                                 "para subir un archivo cualquiera indicando las "
                                 "columnas a mano."),
          columna_cargo: str | None = Form(
              None, description="Solo con formato_libre=true."),
          columna_sueldo: str | None = Form(
              None, description="OPCIONAL. Solo si la columna no se autodetecta."),
          columnas_originales: bool = Form(
              True, description="Por defecto el JSON devuelve TUS columnas —nombre, "
                                "antiguedad, sexo, centro de costos— junto a los "
                                "resultados. Ponlo en false si el front ya tiene el "
                                "archivo y solo quiere los numeros."),
          columnas_extra: str | None = Form(
              None, description="OPCIONAL. Solo se usa con columnas_originales=false: "
                                "que columnas tuyas rescatar igualmente, separadas por "
                                "coma."),
          m: Motor = Depends(motor)):
    """Sube una nomina. Devuelve 202 y un id: el trabajo corre por detras.

    Se valida ANTES de encolar todo lo que se puede validar barato —el SBU del ano, el
    segmento, y que el archivo se deje leer y tenga columna de cargo—. Un 400 inmediato
    con el motivo es mucho mas util que un trabajo que falla treinta segundos despues.
    """
    # EL ANO POR DEFECTO ES EL ACTUAL. Estaba fijado a 2025 y eso envejece solo: en
    # enero se seguirian emitiendo dolares del ano anterior sin que nadie lo note.
    anio = int(anio) if anio else _dt.date.today().year
    segmento, rubro = _opt(segmento), _opt(rubro)
    ruc = _opt(ruc)
    columna_cargo, columna_sueldo = _opt(columna_cargo), _opt(columna_sueldo)

    # LA INDUSTRIA SE DERIVA DEL RUC. Un area de RR.HH. sabe su RUC y no sabe que es
    # "seccion C". Si ademas pasan `rubro` a mano, manda el explicito y se avisa si no
    # coinciden, en vez de elegir uno en silencio.
    ficha = None
    ciiu_cliente = None
    if ruc:
        g6, tam_emp, seg_ruc = m.base.meta_ruc.get(ruc.strip(), ("", -1, ""))
        # `en_la_base` sale de `pad_ruc` y NO de `meta_ruc`: el segundo solo se puebla
        # cuando el marco trae las columnas de SCVS, asi que con una base construida sin
        # ellas se le decia a una empresa que no esta cuando si esta. El padron lleva a
        # TODAS las empresas que aportaron datos, que es justo la pregunta.
        ficha = {"ruc": ruc.strip(), "en_la_base": ruc.strip() in m.base.pad_ruc,
                 # COMPLETO. `ciiu_grupo` se queda por compatibilidad, pero lo que el
                 # cliente reconoce como suyo es `ciiu` entero: `G4761.03`, no `G476`.
                 "ciiu": g6 or None,
                 "ciiu_grupo": (g6[:4] if g6 else None),
                 "ciiu_seccion": (g6[:1] if g6 else None),
                 "n_empleados": tam_emp if tam_emp > 0 else None}
        # EL CIIU COMPLETO VIAJA AL MODELO, no solo su primera letra. De el sale el
        # nivel al que se compara cada cargo: sin esto `rubro_del_veredicto` no tiene
        # con que bajar y todo se compara contra la seccion — o sea que la cascada
        # entera queda muerta sin que nada falle.
        ciiu_cliente = g6 or None
        if g6 and not rubro:
            # UN DERIVADO NO PUEDE DAR 400. La validacion de mas abajo rechaza los rubros
            # sin respaldo, y aplicada a un valor que el cliente no mando produce un error
            # que no puede corregir. Si no hay respaldo, no se deriva: el informe sale
            # global, igual que si no hubiera mandado el RUC, y la ficha lo dice.
            if g6[:1] in m.base.rubros:
                rubro = g6[:1]
                ficha["rubro_derivado"] = rubro
            else:
                ficha["rubro_sin_respaldo"] = g6[:1]
        elif g6 and rubro and rubro.upper() != g6[:1]:
            ficha["aviso"] = (f"pediste rubro {rubro.upper()} y el RUC dice {g6[:1]}; "
                              f"manda el que pediste")

        # EL SEGMENTO TAMBIEN SALE DEL RUC, y con la misma regla que el rubro: el
        # explicito manda y se avisa si no coinciden. A diferencia del rubro, este SI
        # mejora la precision -- corrige el sesgo de los cargos altos (D-018) -- asi que
        # que el cliente no lo sepa no puede costarle el ajuste.
        #
        # Va en `aviso_segmento` y no en `aviso` para no pisar el del rubro cuando los dos
        # discrepan en el mismo pedido.
        if seg_ruc:
            ficha["segmento_del_ruc"] = seg_ruc
        if seg_ruc and not segmento and seg_ruc in SEGMENTOS:
            segmento = seg_ruc
            ficha["segmento_derivado"] = segmento
        elif seg_ruc and segmento and segmento.upper() != seg_ruc:
            ficha["aviso_segmento"] = (
                f"pediste segmento {segmento.upper()} y el RUC dice {seg_ruc}; "
                f"manda el que pediste")
    extra_pedidas = [t.strip() for t in (_opt(columnas_extra) or "").split(",")
                     if t.strip()]
    try:
        m.settings.get_sbu(int(anio), estricto=True)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if segmento and segmento.upper() not in SEGMENTOS:
        raise HTTPException(400, f"segmento invalido: {segmento}. "
                                 f"Validos: {list(SEGMENTOS)}")
    # El rubro se valida igual que el segmento. Antes solo avisaba por `warnings` y caia
    # al global: el cliente recibia un informe entero creyendo que era sectorial.
    if rubro and rubro.upper() not in m.base.rubros:
        raise HTTPException(400, f"rubro sin datos suficientes: {rubro}. "
                                 f"Con respaldo en esta base: {list(m.base.rubros)}")
    contenido = archivo.file.read()
    if not contenido:
        raise HTTPException(400, "el archivo llego vacio")
    try:
        df, col = leer_nomina_bytes(contenido, archivo.filename or "n.xlsx",
                                    columna_cargo if formato_libre else None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    # FORMATO ESTRICTO por defecto: nombres canonicos, sin cedulas, y todos los
    # problemas de una vez. `formato_libre` existe para el archivo que llega como
    # llega, pero deja de ser un contrato y pasa a ser una conversion manual.
    informe_formato = None
    if not formato_libre:
        try:
            df, informe_formato = validar_formato(df)
        except FormatoInvalido as e:
            raise HTTPException(400, {"formato": "estricto",
                                      "problemas": e.problemas,
                                      "obligatorias": list(OBLIGATORIAS),
                                      "aceptadas": list(CANONICAS)}) from e
        col = "cargo"
        columna_sueldo = "sueldo" if "sueldo" in df.columns else None
    # Si el cliente NOMBRA la columna de sueldo, tiene que existir. Ignorarla en silencio
    # le devuelve un informe sin comparacion y sin explicacion.
    if columna_sueldo and formato_libre:
        real = _col(df, columna_sueldo)
        if real is None:
            raise HTTPException(400, f"la columna de sueldo '{columna_sueldo}' no esta "
                                     f"en el archivo. Columnas: {list(df.columns)}")
        columna_sueldo = real

    # se casan ahora, con el archivo ya leido, para poder avisar de las que no existen
    extra, no_estan = [], []
    for c in extra_pedidas:
        real = _col(df, c)
        (extra if real else no_estan).append(real or c)
    if no_estan:
        raise HTTPException(400, f"columnas_extra que no estan en el archivo: "
                                 f"{no_estan}. Columnas: {list(df.columns)}")

    t = ALMACEN.nuevo()

    def correr():
        t.estado = "procesando"
        try:
            t.resultado, t.excel = procesar(m, df, col, int(anio),
                                            segmento.upper() if segmento else None,
                                            rubro.upper() if rubro else None,
                                            columna_sueldo, extra,
                                            columnas_originales, informe_formato,
                                            ruc, ciiu_cliente)
            t.estado = "listo"
        except Exception as e:                               # noqa: BLE001
            t.estado, t.error = "error", f"{type(e).__name__}: {e}"

    tareas.add_task(correr)
    return {"id": t.id, "estado": t.estado, "filas": len(df), "columna_cargo": col,
            "anio": anio, "empresa": ficha, "caduca_en_s": TTL_SEGUNDOS}


@app.get("/informes/{tid}")
def consultar(tid: str):
    t = ALMACEN.get(tid)
    if t is None:
        raise HTTPException(404, "no existe o ya caduco")
    if t.estado == "error":
        raise HTTPException(422, t.error or "fallo el procesamiento")
    if t.estado != "listo":
        return {"id": t.id, "estado": t.estado}
    return {"id": t.id, "estado": t.estado, **(t.resultado or {})}


@app.get("/informes/{tid}/excel")
def excel(tid: str):
    t = ALMACEN.get(tid)
    if t is None or t.excel is None:
        raise HTTPException(404, "no existe, no esta listo, o ya caduco")
    return Response(
        t.excel,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="informe_{tid[:8]}.xlsx"'})


@app.get("/referencia")
def referencia(cargo: str, anio: int | None = None, segmento: str | None = None,
               rubro: str | None = None, m: Motor = Depends(motor)):
    """Un titulo suelto, para explorar. NO es el producto.

    Sin la nomina completa no hay ancla de empresa, y sin ancla no hay lectura de equidad
    interna — que es la mitad util del informe. La respuesta lo dice para que nadie
    construya un front encima creyendo que esto basta.
    """
    # mismo criterio que /informes: el ano por defecto es el ACTUAL, y vacio o
    # "string" son ausencia
    anio = int(anio) if anio else _dt.date.today().year
    try:
        m.settings.get_sbu(anio, estricto=True)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    segmento, rubro = _opt(segmento), _opt(rubro)
    if rubro and rubro.upper() not in m.base.rubros:
        raise HTTPException(400, f"rubro sin datos suficientes: {rubro}. "
                                 f"Con respaldo: {list(m.base.rubros)}")
    t = cargo.strip().upper()
    if not t:
        raise HTTPException(400, "cargo vacio")
    m.asegurar([t])
    fila = m.base.referenciar([t], m.emb, anio=anio, segmento=segmento,
                              rubro=rubro).iloc[0]
    d = {str(k): _py(v) for k, v in fila.items()
         if not str(k).endswith("_log") and k != "sd"}
    d["unidades"] = UNIDADES
    d["aviso"] = ("Sin la nomina completa no hay ancla de empresa: falta la lectura de "
                  "equidad interna. Para el informe completo, POST /informes.")
    return d
