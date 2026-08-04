# Concurrencia de descargas de plantillas — Diseño

## 1. Problema

En `construir_base`, la fase de composición descarga la plantilla-modificada de **cada estudio** vía HTTP. Hoy `_composicion_estudios` (en `src/benchmarking/orquestador.py`) lo hace **secuencialmente** en un `for` sobre los estudios. Para el universo (~48k estudios) eso es el cuello de botella dominante (latencia de red acumulada), estimado en varias horas. El resto del pipeline (lectura BQ, features, escritura) no es el problema.

## 2. Objetivo

Paralelizar **solo** la descarga+parseo de plantillas, con resultados **idénticos** a la versión secuencial. Reducir el tiempo del universo de secuencial-lento a ~1–2 h. No cambiar el esquema de salida ni la lógica de features/validación/escritura.

## 3. Enfoque

**`concurrent.futures.ThreadPoolExecutor`** (no asyncio). Justificación: `plantilla_client.descargar_plantilla` usa `requests` (síncrono) y el trabajo es I/O de red (el GIL se libera durante la espera de red), así que los hilos dan el paralelismo sin reescribir el cliente a async ni tocar sus reintentos.

## 4. Cambios (acotados)

**`src/benchmarking/orquestador.py`**
- Extraer un worker puro `_una_plantilla(e, base_url, descargar) -> pd.DataFrame | None`: hace download+parse dentro del `try/except` actual; devuelve el DataFrame de montos `[identificacion, comisiones, extras, otros, numero_proceso]` (identificacion como `str`) o `None` (y loguea el skip) ante 5xx agotado / XLSX corrupto / columna ausente / plantilla inexistente.
- `_composicion_estudios(estudios, base_url, descargar, max_workers=8)`: envía un `_una_plantilla` por estudio a un `ThreadPoolExecutor(max_workers)`, recolecta los resultados no-`None` con `as_completed`, y mantiene **igual** el cierre actual: `pd.concat(...)` + `drop_duplicates(subset=["numero_proceso","identificacion"], keep="first")`; y el mismo DataFrame vacío con dtypes explícitos cuando no hubo ninguna plantilla.
- `construir_base(runner, base_url, settings, limite=None, descargar=descargar_plantilla, max_workers=None)`: si `max_workers is None`, usa `settings.descargas_concurrentes`; lo pasa a `_composicion_estudios`.

**`src/benchmarking/config/settings.py`**
- Nuevo campo `descargas_concurrentes: int = 8` (env `PIPELINE_DESCARGAS_CONCURRENTES`).

**`src/benchmarking/cli.py`**
- Flag `--concurrencia N` (int, default `None`); se pasa como `max_workers` a `construir_base`.

## 5. Invariantes (no negociables)

- **Resultado idéntico** al secuencial: el orden de descarga no importa porque la composición se enlaza a la base por `(numero_proceso, cédula)` en un merge posterior. Cualquier test debe comparar ordenando por llaves.
- **Resiliencia por estudio**: un fallo (excepción/timeout/5xx agotado) omite ese estudio con un aviso; nunca tumba el lote. Las personas de ese estudio se conservan en la base con composición NULL.
- **Dedup** de composición por `(numero_proceso, identificacion)` intacto.
- **Frontera de privacidad** y todo aguas abajo (anonimizar, features, cuarentena, SCVS, sink) sin cambios.

## 6. Seguridad de hilos

- Cada worker es independiente: no comparte estado mutable. Los DataFrames resultantes se juntan en el hilo principal tras `as_completed`.
- **No se comparte `requests.Session` entre hilos** (no es thread-safe): cada llamada a `descargar_plantilla` crea su propia `Session` (comportamiento actual cuando `session=None`). El overhead de crear Session por descarga es despreciable frente a la latencia de red. Optimización futura opcional: Session thread-local.
- El `print` de skip es a nivel de línea; aceptable para v1 (se puede migrar a `logging` después).

## 7. Testing (sin red — `descargar` inyectado)

- **Equivalencia:** con un `descargar` mock determinista sobre varios estudios, `construir_base(..., max_workers=4)` produce el mismo DataFrame (mismas filas/valores, comparado ordenando por llaves) que el esperado.
- **Resiliencia concurrente:** un `descargar` que lanza excepción para un estudio y devuelve bytes válidos para otros → el lote no cae, el fallido se omite, el resto se procesa.
- **Cobertura del lote:** todos los estudios del lote se intentan (el mock registra N llamadas = N estudios).
- **Dedup bajo concurrencia:** una plantilla con cédula duplicada no infla el grano.

## 8. Fuera de alcance

- Reanudabilidad / checkpoint de estudios procesados (plan aparte).
- Session thread-local, límites de rate adaptativos, `logging` estructurado.
- Concurrencia de otras fases (lectura BQ, escritura) — no son el cuello de botella.
