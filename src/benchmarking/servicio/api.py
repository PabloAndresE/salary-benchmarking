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

import io
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..config.settings import cargar_settings
from ..evaluacion import embeddings
from ..producto.base_referencia import SEGMENTOS, BaseReferencia
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
}


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
        if col_cargo not in df.columns:
            raise ValueError(f"la columna '{col_cargo}' no esta en el archivo. "
                             f"Columnas: {list(df.columns)}")
        return df, col_cargo
    normal = {c.strip().lower().replace(" ", "_"): c for c in df.columns}
    for cand in _POSIBLES:
        if cand in normal:
            return df, normal[cand]
    raise ValueError(f"no encuentro la columna de cargo. Columnas: {list(df.columns)}. "
                     f"Indicala con el parametro `columna_cargo`.")


def procesar(motor: Motor, df, col_cargo: str, anio: int,
             segmento: str | None, rubro: str | None,
             col_sueldo: str | None) -> tuple[dict, bytes]:
    """El informe completo. Es la misma cadena que el CLI, sin tocar el disco."""
    titulos = df[col_cargo].fillna("").astype(str).str.strip().str.upper()
    nuevos = motor.asegurar(titulos.tolist())

    ref = motor.base.referenciar(titulos.tolist(), motor.emb, anio=anio,
                                 segmento=segmento, rubro=rubro)
    salida = pd.concat([df.reset_index(drop=True),
                        ref.drop(columns=["cargo"]).reset_index(drop=True)], axis=1)

    cs = _buscar_sueldo(df, col_sueldo)
    por_puesto = resumen = None
    if cs:
        salida, por_puesto, resumen = comparar(salida, cs, col_cargo, ref,
                                               motor.settings.get_sbu, anio)
    salida["estado"] = [_estado(f) for _, f in salida.iterrows()]
    # La hoja del cliente no lleva escala logaritmica ni la banda de empresas: esa va en
    # `por_puesto`, que es donde la unidad coincide. Mismo criterio que el CLI.
    salida = salida.drop(columns=[c for c in salida.columns
                                  if c.endswith("_log") or c.endswith("_emp")
                                  or c == "sd"], errors="ignore")

    xls = io.BytesIO()
    with pd.ExcelWriter(xls) as w:
        salida.to_excel(w, sheet_name="detalle", index=False)
        if por_puesto is not None:
            por_puesto.to_excel(w, sheet_name="por_puesto", index=False)

    limpio = lambda d: [{str(k): _py(v) for k, v in fila.items()}
                        for fila in d.to_dict("records")]

    cuerpo = {
        "esquema": ESQUEMA,
        "meta": {
            "anio": anio, "sbu": motor.settings.get_sbu(anio),
            "segmento": segmento, "rubro": rubro,
            "titulos_nuevos_embebidos": nuevos,
            "puestos_en_la_base": len(motor.base.celdas),
            "tau": round(float(np.sqrt(motor.base.tau2)), 4),
            "sigma": round(float(np.sqrt(motor.base.sigma2)), 4),
            "unidades": UNIDADES,
            "aviso": "La brecha_grafia compara dos GRAFIAS de titulo escritas por "
                     "empresas distintas, sin control por empresa, sector ni "
                     "antiguedad. NO es una brecha salarial medida.",
        },
        "reparto_estado": {str(k): int(v) for k, v
                           in salida["estado"].value_counts().items()},
        "reparto_confianza": ({str(k): int(v) for k, v
                               in ref["confianza"].value_counts().items()}
                              if "confianza" in ref else {}),
        "detalle": limpio(salida),
        "por_puesto": limpio(por_puesto) if por_puesto is not None else [],
        "resumen": {k: _py(v) for k, v in (resumen or {}).items()},
        "texto": texto_resumen(resumen, por_puesto) if resumen is not None else "",
    }
    return cuerpo, xls.getvalue()


# ============================== capa HTTP ==============================
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form,  # noqa: E402
                     HTTPException, UploadFile)
from fastapi.responses import Response  # noqa: E402

_estado_app: dict[str, Any] = {}
ALMACEN = Almacen()


@asynccontextmanager
async def ciclo(app: FastAPI):
    import os
    s = cargar_settings()
    _estado_app["motor"] = Motor(os.environ.get("BASE_REFERENCIA",
                                                "demo/base_v8.npz"), s)
    yield
    _estado_app.clear()


app = FastAPI(title="Referenciador salarial", version=ESQUEMA, lifespan=ciclo)


def motor() -> Motor:
    m = _estado_app.get("motor")
    if m is None:
        raise HTTPException(503, "la base todavia no esta cargada")
    return m


@app.get("/salud")
def salud(m: Motor = Depends(motor)):
    return {"ok": True, "esquema": ESQUEMA,
            "puestos": len(m.base.celdas), "carga_s": m.carga_s,
            "anios_con_sbu": sorted(m.settings.sbu)}


@app.post("/informes", status_code=202)
def crear(tareas: BackgroundTasks,
          archivo: UploadFile = File(..., description="Excel o CSV. Primera hoja, "
                                                      "encabezados en la fila 1."),
          anio: int = Form(2025, description="Ano del SBU con el que se dolariza."),
          segmento: str | None = Form(
              None, description="OPCIONAL. Tamano de la empresa del cliente: "
                                "MICROEMPRESA, PEQUENA, MEDIANA o GRANDE. Corrige el "
                                "sesgo de los cargos altos (D-018)."),
          rubro: str | None = Form(
              None, description="OPCIONAL. CIIU de primer nivel (una letra). Compara "
                                "solo contra ese sector donde haya respaldo. NO mejora "
                                "la precision: estrecha el respaldo (D-023)."),
          columna_cargo: str | None = Form(
              None, description="OPCIONAL. Solo si la columna no se autodetecta."),
          columna_sueldo: str | None = Form(
              None, description="OPCIONAL. Solo si la columna no se autodetecta."),
          m: Motor = Depends(motor)):
    """Sube una nomina. Devuelve 202 y un id: el trabajo corre por detras.

    Se valida ANTES de encolar todo lo que se puede validar barato —el SBU del ano, el
    segmento, y que el archivo se deje leer y tenga columna de cargo—. Un 400 inmediato
    con el motivo es mucho mas util que un trabajo que falla treinta segundos despues.
    """
    segmento, rubro = _opt(segmento), _opt(rubro)
    columna_cargo, columna_sueldo = _opt(columna_cargo), _opt(columna_sueldo)
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
                                    columna_cargo)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    t = ALMACEN.nuevo()

    def correr():
        t.estado = "procesando"
        try:
            t.resultado, t.excel = procesar(m, df, col, int(anio),
                                            segmento.upper() if segmento else None,
                                            rubro.upper() if rubro else None,
                                            columna_sueldo)
            t.estado = "listo"
        except Exception as e:                               # noqa: BLE001
            t.estado, t.error = "error", f"{type(e).__name__}: {e}"

    tareas.add_task(correr)
    return {"id": t.id, "estado": t.estado, "filas": len(df), "columna_cargo": col,
            "caduca_en_s": TTL_SEGUNDOS}


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
def referencia(cargo: str, anio: int = 2025, segmento: str | None = None,
               rubro: str | None = None, m: Motor = Depends(motor)):
    # mismo saneado que en /informes: vacio y "string" son ausencia
    """Un titulo suelto, para explorar. NO es el producto.

    Sin la nomina completa no hay ancla de empresa, y sin ancla no hay lectura de equidad
    interna — que es la mitad util del informe. La respuesta lo dice para que nadie
    construya un front encima creyendo que esto basta.
    """
    try:
        m.settings.get_sbu(int(anio), estricto=True)
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
