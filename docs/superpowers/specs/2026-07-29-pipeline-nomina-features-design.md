# Diseño — Pipeline de la base transformada (`nomina_features`)

**Fecha:** 2026-07-29 · **Proyecto:** Benchmarking Salarial (trabajo de titulación, Maestría en IA — USFQ; y producto ActuaLab).

## 1. Contexto y problema

El EDA (`research/notebooks/01_eda_cargo_benchmarking.ipynb`) estableció que la columna `CARGO` de la fuente no sirve para comparar salarios directamente y que hay que **reagrupar a las personas por el tipo de trabajo real** (fase de clustering, posterior). Antes de esa fase hace falta una **base transformada, limpia, anonimizada y enriquecida**, que hoy no existe: la información está dispersa en BigQuery (estudios actuariales + SCVS), en un endpoint del backend (composición salarial) y en DINARDAP (profesión).

Este pipeline produce esa base — una única tabla `nomina_features` en BigQuery — que será el **insumo único** del clustering y del benchmarking. No vectoriza ni agrupa: solo entrega columnas tabulares crudas y derivadas.

## 2. Objetivo

Construir un pipeline de **producto, modular y reutilizable** (`src/benchmarking/`) que transforme las fuentes en `nomina_features`, respetando la frontera de privacidad (LOPDP), con una **única escritura** de la base a BigQuery, y un **enriquecimiento DINARDAP posterior e incremental**.

## 3. Alcance

**Fase 1 (este pipeline):** producir y escribir `nomina_features` con todo **menos** la profesión: adquisición, validación/cuarentena, anonimización, composición salarial, features derivadas y enriquecimiento SCVS.

**Fase 2 (proceso separado, posterior):** enriquecer la tabla ya escrita con `profesion_dinardap` vía DINARDAP, incremental y por tandas.

**Fuera de alcance (YAGNI):** vectorización y clustering (fase siguiente); scraping del IESS (no viable masivo — requiere credenciales por empresa); backfill DINARDAP del universo (decisión de producto); API/capa servida; multi-tenant.

## 4. Arquitectura

Paquete instalable `src/benchmarking/` (Python 3.11+, src-layout), alineado al handoff pero con la fuente en BigQuery (no GCS):

```
src/benchmarking/
  config/
    settings.py              # pydantic-settings: salt (env), umbrales, SBU, flags, destino
    esquema_plantilla.yaml   # contrato de columnas de la plantilla
  adquisicion/
    bigquery_source.py       # lee estudios_actuariales + SCVS (reemplaza al Almacen GCS del handoff)
    plantilla_client.py      # descarga plantilla-modificada (composición)  [adaptado de iess-scrapper]
    dinardap_client.py       # cliente DINARDAP (Fase 2)                    [copiado de iess-scrapper]
  ingesta/
    validacion.py            # sanity checks a nivel fila → cuarentena (nunca borrado silencioso)
    anonimizacion.py         # hash SHA-256(salt+cédula)[:16], drop nombres — LA FRONTERA
    composicion.py           # parsea plantilla → sueldo/comisiones/extras/otros + pct_*
    features_base.py         # sueldo_sbu, log_total, antiguedad_*, tuvo_salidas
    enriquecimiento.py       # join SCVS (segmento/ciiu/n_empleados/provincia)
  escritura/
    bigquery_sink.py         # escribe nomina_features (una sola escritura)
  enriquecimiento_dinardap/  # Fase 2 (separada)
    runner.py                # lee cédulas de la fuente en memoria, consulta DINARDAP, MERGE por id_hash
    cache.py                 # caché incremental cedula_hash→profesion
  cli.py                     # benchmarking construir-base [--muestra N] ; benchmarking enriquecer-dinardap
```

Cada módulo tiene una responsabilidad y se testea por separado.

## 5. Fuentes y cómo se combinan

- **`estudios_actuariales` (BigQuery, `act-actuafast.actuafastv2`) = base primaria.** Materializada, multi-año (2016–2025), trae cargo, `sueldo` base, `remuneracion_promedio`, sexo, edad, fechas, RUC. Rápida, sin HTTP.
- **Endpoint `plantilla-modificada` = solo composición.** `GET {backend}/estudios/{numero_proceso}/version/{id_version}/plantilla-modificada` devuelve un XLSX (hoja "Plantilla de empleados") con `Comisiones/Horas extras/Otros mensuales promedio` + cédula. Se descarga por estudio y se **enlaza a la base por `numero_proceso` + cédula→`id_hash`**.
- **SCVS (`scvs_balances_anuales`, `scvs_empresas`) = join en BigQuery** por RUC: `segmento`, `ciiu_n1/n6`, `n_empleados`, provincia (2 primeros dígitos del RUC).
- **DINARDAP = Fase 2**, por cédula.

**Reconciliación del fijo:** `sueldo` de BQ ≈ "Último sueldo/pensión mensual" de la plantilla. De la plantilla se toman los 3 rubros variables (que BQ no tiene); si el fijo discrepa entre fuentes, gana la plantilla y se marca `flag_discrepancia_fijo = true`.

## 6. La tabla `nomina_features`

**Grano:** una fila por persona-estudio (`id_hash` + `numero_proceso`). Anonimizada. La tesis usa el **universo completo** (~4,67 M filas); `--muestra` es solo para desarrollo. Ubicación: dataset nuevo en **us-central1** (obligatorio para joins).

| Columna | Tipo | Origen | Uso previsto |
|---|---|---|---|
| `id_hash` | STRING | hash(cédula) | identidad anónima / enlace |
| `empresa_ruc` | STRING | estudios | trazabilidad / join SCVS |
| `numero_proceso`, `id_version` | STRING | estudios | trazabilidad / enlace plantilla |
| `anio_valoracion` | INT64 | estudios | temporal / segmentación |
| `sueldo`, `comisiones`, `extras`, `otros`, `total` | FLOAT64 | plantilla | composición (montos) |
| `pct_fijo`, `pct_comisiones`, `pct_extras`, `pct_otros` | FLOAT64 | derivado | composición (feature clave, E2) |
| `sueldo_sbu` | FLOAT64 | derivado (`total`/SBU(año)) | nivel normalizado |
| `log_total` | FLOAT64 | derivado | nivel (uso con cautela; circularidad) |
| `cargo_orig`, `cargo_norm` | STRING | estudios | cargo (texto / LLM) |
| `centro_costo` | STRING | estudios | función (señal auxiliar) |
| `antiguedad_total`, `antiguedad_actual` | FLOAT64 | fechas | trayectoria / control |
| `tuvo_salidas` | BOOL | fechas | trayectoria |
| `sexo` | STRING | estudios | control / fairness (no-modelo) |
| `edad` | FLOAT64 | estudios | control / fairness (no-modelo) |
| `segmento`, `ciiu_n1`, `ciiu_n6`, `provincia` | STRING | SCVS/RUC | segmentación |
| `n_empleados` | INT64 | SCVS | segmentación |
| `en_clean` | BOOL | validación | calidad (pasó validación) |
| `motivo_cuarentena` | STRING | validación | calidad (por qué se marcó) |
| `flag_discrepancia_fijo` | BOOL | reconciliación | calidad |
| `profesion_dinardap` | STRING | DINARDAP | **añadida en Fase 2** (no en la escritura inicial) |

Las columnas de composición (`comisiones/extras/otros/total/pct_*`) quedan **`NULL` en los estudios sin plantilla disponible** (típicamente años viejos); `sueldo_sbu` usa `total` con respaldo a `remuneracion_promedio`. No se descartan filas por esto: la base es cruda y el clustering decide después qué filas/features usa.

Particionado por `anio_valoracion` (range partitioning, INT), clusterizado por `empresa_ruc`.

## 7. Flujo de datos (Fase 1)

1. **Adquisición:** leer estudios (persona-estudio) de BigQuery; listar los `(numero_proceso, id_version)` a procesar. **Por defecto se procesa el universo completo** — la tesis usa toda la base. El único costo es descargar la composición: **una llamada por estudio** — son **~48.000 estudios** (~5.900/año desde 2019), no los 4,67 M registros —, estimado en **~1–2 h con 10–20 descargas concurrentes** + reintentos, reanudable. (Los años 2016–2018 rinden poco, ~99% sin cargo.) La opción `--muestra` (estratificada por año y sector) queda solo como **utilidad de desarrollo**, para iterar rápido durante la construcción, no como base de la tesis.
2. **Base por-persona + composición:** leer de estudios BQ los registros persona-estudio (la base: cargo, sexo, edad, `sueldo`, `remuneracion_promedio`, fechas, RUC). Descargar la plantilla de cada estudio, parsear, y **enlazar la composición** (`comisiones/extras/otros` + fijo) a la base por `numero_proceso` + cédula; `NULL` donde no haya plantilla. **No se descartan filas** por falta de composición.
3. **Validación → cuarentena:** sanity checks (cargo placeholder, jubilado, `sueldo_sbu < 0,5`, edad fuera de rango, total ≤ 0). Filas inválidas se marcan con `motivo_cuarentena`, nunca se borran.
4. **Anonimización (frontera):** tras el enlace, `id_hash = SHA-256(salt + cédula)[:16]`; se eliminan nombres/apellidos; se descartan las cédulas. Aguas abajo nadie ve identificadores.
5. **Features:** `total` (= `sueldo`+`comisiones`+`extras`+`otros` donde haya composición; si no, respaldo a `remuneracion_promedio`/`sueldo`), `pct_*` (`NULL` sin composición), `sueldo_sbu` (`total`/SBU), `log_total`, `antiguedad_*`, `tuvo_salidas`.
6. **Enriquecimiento SCVS:** join por RUC → tamaño/sector/provincia.
7. **Escritura:** `nomina_features` a BigQuery — **la única escritura de la base**.

## 8. Frontera de privacidad (LOPDP)

- El XLSX de la plantilla (y en Fase 2 la respuesta DINARDAP) traen cédula/nombres → se procesan **en memoria y se descartan**; nada crudo toca disco ni el repositorio.
- Todo lo persistido está anonimizado (`id_hash`, sin cédula/nombre).
- `salt` desde variable de entorno (`PIPELINE_SALT`), nunca en código ni config.
- Data real jamás al repo (tests usan data sintética).

## 9. Manejo de errores, cobertura y reanudabilidad

- **Estudio sin plantilla / endpoint 5xx:** se registra "sin composición"; columnas de composición quedan `NULL`; el pipeline continúa.
- **Cobertura realista:** la composición se llenará sobre todo en años recientes (donde estudio y plantilla existen); años viejos (2016–2018, ~99% sin cargo) quedarán con composición `NULL` — la base lo refleja, no lo inventa.
- **Reanudable:** checkpoint de estudios ya procesados (patrón `queue.json` de iess-scrapper) para reanudar sin repetir descargas.

## 10. Configuración (`settings.py`, pydantic-settings)

Parametrizable, validado al arrancar: `salt` (env), umbrales de validación (piso `0,5·SBU`, edad 18–80), diccionario SBU por año (2016–2025), URL base del backend (auto-descubrible por project number), destino BQ (proyecto/dataset), y flags (`muestra`, `dinardap: false`). Nada hardcodeado.

## 11. Fase 2 — Enriquecimiento DINARDAP (proceso separado)

Corre sobre la tabla ya escrita, sin des-anonimizar:

1. Lee cédulas **desde la fuente** (`estudios_actuariales`/plantillas), que viven en producción actuafast **fuera de nuestra frontera**, solo en memoria.
2. Consulta DINARDAP (cliente copiado de iess-scrapper: público, semáforo=5, reintentos backoff 5/10/15s, User-Agent, proxy opcional), con **caché incremental** `cedula_hash→profesion`.
3. Recalcula `id_hash` con el mismo salt y hace `MERGE` de `profesion_dinardap` en `nomina_features` (columna añadida con `ALTER TABLE`).

Incremental (solo cédulas nuevas), por tandas, sin bloquear nada. Universo ~1,2 M cédulas únicas (~2 días de reloj en tandas); para la tesis basta la muestra. Los 503 son throttling manejable (no inestabilidad).

## 12. Testing (data sintética, nunca real)

- Fixture de una **plantilla xlsx sintética** que imita la hoja real.
- Tests: la anonimización **elimina** cédula/nombres; el hash es **determinista** con salt fijo; la cuarentena captura filas inválidas; la composición **suma 100%**; el enlace plantilla↔estudio matchea por `id_hash + numero_proceso`; la reconciliación del fijo marca discrepancias.

## 13. Destino BigQuery

Dataset nuevo en **us-central1**, proyecto no-productivo: `act-cicd-stage-prueba` (a confirmar permiso de escritura al crear; plan B `act-poc-simulador`). Tabla `nomina_features`. Nunca escribir en `actuafastv2` (producción; solo lectura).

## 14. Reutilización de `iess-scrapper`

Se **copian los módulos mínimos autocontenidos** (evita arrastrar Playwright): `dinardapService.py` → `dinardap_client.py`; mapeos de columnas de la plantilla (`column_mappings.py`, `mappingUtil.py`) → `composicion.py`. Se sincronizan a mano si cambian (son estables). El cliente actuafast (`plantilla_client.py`) se adapta del patrón existente.

## 15. Decisiones registradas

- Naturaleza: producto modular (no research descartable).
- Grano: persona-estudio.
- Fuente primaria: estudios BQ; plantilla solo para composición.
- DINARDAP: Fase 2 separada, tras escribir la base.
- Integración iess-scrapper: copiar módulos mínimos.
- IESS scraper: descartado (no viable masivo).
- Vectorización/clustering: fase posterior, fuera de este pipeline.
- Tesis usa el universo completo; `--muestra` solo como utilidad de desarrollo.
