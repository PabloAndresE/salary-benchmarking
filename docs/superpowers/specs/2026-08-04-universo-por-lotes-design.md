# Corrida del universo por lotes (reanudable) — Diseño

## 1. Problema

`construir_base` arma **todo el universo en memoria** (~48k estudios / ~4,67M filas) y hace **una sola escritura** `WRITE_TRUNCATE`. Para el universo real eso es (a) todo-o-nada — un corte a la hora 1.5 pierde todo; (b) pesado en memoria (varios GB; el review de Fase 1 lo marcó); (c) sin forma de reanudar. Se necesita una corrida **por lotes, reanudable**, sin romper la frontera de privacidad.

## 2. Objetivo

Un modo de corrida que procese el universo en lotes de estudios, escribiendo cada lote a `benchmarking_tesis.nomina_features` con `WRITE_APPEND`, **reanudable automáticamente** (reinicia salta lo ya escrito), con memoria acotada por lote y sin persistir identificadores en ningún lado. El `construir_base` actual (muestra/dev) se conserva.

## 3. Arquitectura

**Estado = la tabla destino.** El conjunto "ya hecho" es `SELECT DISTINCT numero_proceso` de la tabla destino. No hay tabla de estado separada (nada que se desincronice).

**Idempotencia por atomicidad.** Cada lote se escribe como **un load job de BigQuery** (atómico, todo-o-nada). Si el proceso muere a mitad, el lote no commiteado no aparece en destino → sus estudios se reprocesan al reiniciar. Si el load sí commiteó, sus estudios están en destino → se saltan. Auto-consistente.

**Lote = conjunto de estudios completos.** Se particiona por `numero_proceso` (nunca se parte un estudio entre lotes), así `n_personas_estudio` sigue correcto por lote.

**Privacidad intacta.** La anonimización ocurre en memoria por lote, antes de escribir. Nunca se persiste cédula en disco ni en tablas intermedias.

## 4. Componentes

**`src/benchmarking/adquisicion/bigquery_source.py`**
- `leer_personas_por_proceso(runner, procesos: list[str]) -> pd.DataFrame`: igual que `SQL_PERSONAS` pero con `WHERE numero_proceso IN (...)` sobre la lista dada (además de los filtros existentes). Reusa las mismas columnas/casts.

**`src/benchmarking/escritura/bigquery_sink.py`**
- `escribir(...)` gana un parámetro `write_disposition="WRITE_TRUNCATE"` (default preserva el comportamiento de `construir_base`); todo lo demás (guardia PII, cast `anio_valoracion→Int64`, range partition, cluster) igual.
- `tabla_existe(client, table_id) -> bool`.
- `procesos_existentes(client, table_id) -> set[str]`: `DISTINCT numero_proceso` de la tabla, o `set()` si no existe (el conjunto "ya hecho").

**`src/benchmarking/orquestador.py`**
- Refactor DRY: extraer `_ensamblar(base, scvs, base_url, settings, descargar, max_workers) -> pd.DataFrame` con la lógica actual de armado (n_personas_estudio → composición concurrente → merge → cargo_norm → anonimizar → features → cuarentena → SCVS). `construir_base` pasa a leer personas + `leer_scvs` + `_ensamblar` (comportamiento idéntico).
- `construir_universo(runner, base_url, settings, escribir_lote, batch_size=500, max_workers=None, descargar=descargar_plantilla, hechos=frozenset()) -> int`: lista estudios, filtra los que ya están en `hechos`, carga SCVS **una vez**, y por cada lote de `batch_size` estudios pendientes: `leer_personas_por_proceso` → `_ensamblar` → `escribir_lote(df)`; loguea progreso; devuelve total de filas escritas. `escribir_lote` y `hechos` se **inyectan** (mantiene el orquestador testeable sin BQ real).

**`src/benchmarking/cli.py`**
- Subcomando `construir-universo`: flags `--batch-size` (default 500), `--concurrencia` (= settings), `--reset` (borra+recrea la tabla). Cablea contra BQ real: si `--reset`, borra la tabla; calcula `hechos = procesos_existentes(...)`; construye un `escribir_lote` que usa `WRITE_TRUNCATE` en la primera escritura si la tabla no existe (la crea particionada/clusterizada) y `WRITE_APPEND` en el resto; llama a `construir_universo`. El subcomando `construir-base` (muestra/dry-run) se mantiene.

## 5. Manejo de esquema entre lotes

Para que el esquema no derive entre appends: el **cast canónico de dtypes** ya vive en `escribir` (`anio_valoracion→Int64`, columnas numéricas por `agregar_features`). La primera escritura crea la tabla (partición/cluster) desde ese DataFrame; los appends siguientes cargan DataFrames con los mismos dtypes. No se define un schema explícito de 33 campos (se confía en el cast canónico + la config de partición en la creación).

## 6. Invariantes

- **Reanudable:** reiniciar sin `--reset` continúa donde quedó (salta `numero_proceso` ya en destino).
- **Idempotente:** ningún estudio se duplica (skip por `hechos` + atomicidad del load por lote).
- **Frontera de privacidad:** sin cédula/nombres persistidos; anonimización en memoria por lote.
- **Memoria acotada:** nunca más de ~un lote (`batch_size` estudios ≈ ~48k filas con default 500) en RAM.
- **Grano** persona-estudio y todas las columnas/semántica idénticas a `construir_base`.
- **`construir_base` sin cambios de comportamiento** (mismo resultado; solo refactor interno vía `_ensamblar`).

## 7. Testing (sin red/BQ — runner y escribir_lote inyectados)

- `construir_universo`: mock runner (listar_estudios con N estudios; `leer_personas_por_proceso` devuelve personas del lote; `leer_scvs`), `escribir_lote` mock que colecta los DataFrames, `hechos` con algunos estudios ya hechos y `batch_size` chico → verifica: (a) los estudios en `hechos` se saltan; (b) los lotes se forman por `batch_size`; (c) SCVS se lee una sola vez; (d) el total devuelto = suma de filas; (e) las filas escritas tienen las columnas esperadas y sin PII.
- `_ensamblar`: equivale a la lógica de `construir_base` (un test de que `construir_base` sigue dando el mismo resultado que antes protege el refactor).
- `leer_personas_por_proceso`: la SQL contiene el filtro `IN` con los procesos dados.
- `escribir(..., write_disposition=...)`: se pasa al `job_config`; `tabla_existe`/`procesos_existentes` con client mock (existe→set de procesos; no existe→`set()`).
- CLI `construir-universo`: mockeando BQ, `--reset` borra; `hechos` se pasa; `escribir_lote` usa TRUNCATE→APPEND correctamente; `--batch-size`/`--concurrencia` se propagan.

## 8. Fuera de alcance

- Cache de descargas por hash (innecesario con lotes).
- Migrar `print`→`logging`, métricas/telemetría.
- Concurrencia entre lotes (los lotes son secuenciales; la concurrencia es intra-lote, en las descargas).
- Fase 2 (DINARDAP).
