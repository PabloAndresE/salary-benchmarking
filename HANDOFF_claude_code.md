# Handoff — Benchmarking Salarial (para Claude Code)

Documento de contexto para retomar el proyecto en Claude Code. Contiene el qué, el porqué de las decisiones ya tomadas, y qué construir. **Léelo completo antes de escribir código.**

---

## 1. Qué es el proyecto

Sistema de **benchmarking salarial** con doble naturaleza: es un trabajo de titulación (Maestría en IA, USFQ) y simultáneamente un producto empresarial para clientes externos. **La arquitectura es de producto empresarial; la tesis es un consumidor de ese producto, no al revés.**

**Problema que resuelve:** en las nóminas, la columna CARGO no es confiable — las empresas usan denominaciones por defecto del catálogo del IESS, colapsando roles distintos bajo una misma etiqueta (una "SECRETARIA" que en realidad es gerente administrativa comparte etiqueta con una secretaria real, con miles de dólares de diferencia salarial). Sin cargos confiables, el benchmarking salarial directo es inválido.

**Solución:** pipeline que (1) agrupa colaboradores por clustering no supervisado sobre variables de nómina, y (2) usa un LLM para asignar una denominación de cargo interpretable a cada cluster, habilitando benchmarking sobre cargos reclasificados.

**Evidencia preliminar** (nómina real, sector educativo, n=1.619): solo 2 etiquetas colapsadas (CV>0.5) pero cubren el 40% de los empleados. El 1% de las etiquetas contamina al 40% de la población.

## 2. Restricciones que gobiernan el diseño

- **Presupuesto:** ~330 horas (16 semanas, 20 h/sem), entrega noviembre 2026. Alcance mínimo en todo; lo robusto va al backlog post-defensa.
- **Privacidad (LOPDP Ecuador):** datos de nómina son sensibles. La anonimización ocurre como primer paso tras cargar (o tras el enriquecimiento opcional). Nada aguas abajo de la capa `clean` contiene identificadores. Data real JAMÁS entra al repositorio (tests usan data sintética).
- **Stack:** GCP. Pipeline offline en Cloud Run jobs; capa servida en BigQuery; API en Cloud Run; LLM vía Vertex AI (los datos no salen del proyecto GCP).
- **Dualidad:** el núcleo es producto; los experimentos de tesis (`research/`) importan el núcleo, nunca reimplementan lógica.

## 3. Arquitectura — dos planos que se tocan solo por BigQuery

**Plano offline (pipeline):** nóminas origen → [enriquecimiento opcional] → anonimización → validación + features → clustering → etiquetado LLM → escribe resultados a BigQuery (pre-agregados, con supresión de celda mínima).

**Plano online (servir):** API FastAPI (única pieza que lee BigQuery) → front. El MVP Streamlit consume la API, NO BigQuery directo. El clustering nunca corre por una petición del front.

El núcleo (`src/benchmarking/`) es lógica de dominio pura que ambos planos importan.

## 4. Estructura objetivo del repositorio

```
benchmarking-salarial/
├── pyproject.toml               # paquete instalable (src layout), deps, versión
├── README.md
├── Makefile                     # make test / lint / run-ingesta
├── .github/workflows/ci.yml     # lint + pytest en cada push
├── Dockerfile.pipeline          # imagen jobs offline
├── Dockerfile.api               # imagen servicio online
│
├── src/benchmarking/            # NÚCLEO — todo importable
│   ├── config/
│   │   ├── settings.py          # pydantic-settings: config tipada, validada al arrancar
│   │   └── esquema_plantilla.yaml
│   ├── adquisicion/
│   │   ├── almacen.py           # abstracción GCS/local (YA EXISTE, ver §6)
│   │   └── registro.py          # trazabilidad de fuentes (registro.jsonl)
│   ├── ingesta/
│   │   ├── validacion.py        # nivel archivo (rechazo) + nivel fila (cuarentena)
│   │   ├── anonimizacion.py     # hash SHA-256+salt, drop de nombres — LA frontera
│   │   ├── enriquecimiento.py   # cliente API Registro Civil (feature flag, apagado)
│   │   └── features_base.py     # derivadas de nómina
│   ├── representacion/          # vector base + bloques de embeddings condicionales
│   ├── clustering/              # 4 familias tras interfaz común
│   ├── etiquetado/              # Vertex AI, mapeo ISCO-08
│   ├── benchmarking/            # estadísticas + supresión de celda mínima
│   └── cli.py                   # entrypoints: benchmarking ingestar|clusterizar|...
│
├── api/
│   ├── main.py                  # FastAPI app
│   ├── rutas/                   # benchmark.py, cargos.py
│   ├── auth.py                  # auth básica (MVP); multi-tenant robusto = backlog
│   ├── repositorio.py           # ÚNICA pieza que consulta BigQuery
│   └── modelos.py               # esquemas Pydantic = contrato con el front
│
├── app_streamlit/               # MVP tesis: llama a la API
├── tests/                       # espejo de src/, pytest, data sintética en fixtures/
├── infra/                       # IaC: buckets, BigQuery, Cloud Run, service accounts
└── research/                    # LA TESIS: experimentos/, notebooks/, registro_experimentos.md
```

## 5. Decisiones de diseño ya tomadas (no reabrir sin motivo)

**Ingesta / preprocesamiento:**
- Plantilla ÚNICA para todas las empresas → un solo parser + validación de esquema.
- Validación en dos niveles: archivo (falta columna / <10 filas → rechazo total); fila (7 sanity checks → cuarentena con `motivo`, nunca eliminación silenciosa).
- Anonimización: `id_hash = SHA-256(salt + cédula)[:16]`, salt desde variable de entorno (NUNCA en código/config). Drop de Nombres/Apellidos. Hash irreversible (no se necesita re-identificar en la tesis).
- Jubilados/no activos: filtrados de `clean` (solo tipo "A" activo por ahora; verificar códigos con más nóminas).
- Componentes de remuneración nulos → 0 (ausencia = no percibe). Filtrar remuneración total ≤ 0.
- Sin zona `raw` propia: el bucket de origen ES la fuente inmutable. El pipeline solo escribe datos anonimizados. `registro.jsonl` guarda origen + sha256 + acuerdo para trazabilidad y para detectar si el origen cambió.
- Manejo temporal: la ingesta acepta cualquier período (registrado en `periodo`). NO hay ventana de filtrado. El manejo temporal vive en la capa de benchmarking (comparar solo dentro del mismo corte de referencia). Deflactar por SBU = backlog.

**Representación (v1, prototipada sobre datos reales):**
- Vector base: `log_remun_total` (solo variante "con salario" de E2), `pct_fijo`, `pct_comisiones`, `pct_extras`, `pct_otros`, `antiguedad_total`, `antiguedad_actual`, `tuvo_salidas`.
- EXCLUIDOS del vector por ser atributos protegidos/proxies: `sexo`, `edad`, `estadoCivil`, `lugarNacimiento`. `sexo` y `edad` permanecen en `clean` solo como variables de análisis para chequeo de fairness post-hoc (verificar que los clusters no correlacionen con ellos).
- Énfasis en COMPOSICIÓN salarial (proporciones) sobre montos: captura actividad, no nivel de ingreso, y es invariante a deriva temporal. Evidencia: 37% de empleados con >5% variable; separa "etiqueta colapsada" (dispersión con ~6% variable) de "rol comercial" (dispersión con ~50% variable).
- Bloques de embeddings condicionales: (a) cargo original; (b) centro de costos cuando exista (100% en piloto, pero suele venir vacío en otras empresas → opcional); (c) `profesion` del Registro Civil vía API propia — segunda etiqueta ruidosa INDEPENDIENTE de CARGO, su divergencia detecta etiquetas colapsadas; (d) sector/tamaño de empresa.
- Texto normalizado (mayúsculas, sin tildes) PERO se preserva el original en columnas `_orig` (el LLM las usa).

**Clustering:** 4 familias — K-means (baseline obligatorio), GMM (soft clustering, score de confianza por colaborador), jerárquico aglomerativo (dendrograma = jerarquía de cargos), HDBSCAN (sin k, detecta ruido). Selección por silhouette + Davies-Bouldin + ARI bootstrap + proporción de asignaciones ambiguas.

**Etiquetado:** Gemini vía Vertex AI, temperatura 0, 3 corridas/cluster para consistencia, salida JSON mapeada a ISCO-08.

**Enriquecimiento externo (condicionado a aprobación legal LOPDP, decisión 23-ago):** ocurre ANTES de la anonimización (requiere cédula). De la respuesta de la API solo se retiene `profesion` + checks de consistencia (sexo/fecha nacimiento vs. nómina → cuarentena si divergen). NUNCA se persiste ni cachea respuesta identificada. Flag apagado por defecto.

## 6. Código que ya existe (migrar a la estructura nueva)

Tres archivos ya construidos y probados contra la nómina real (actualmente scripts sueltos, hay que migrarlos al paquete):

- `adquisicion.py` → dividir en `src/benchmarking/adquisicion/almacen.py` (clase `Almacen`, abstracción GCS/local con misma interfaz) + `registro.py`. Comandos actuales: `procesar` (origen → ingesta → clean + registro) y `listar`.
- `ingesta.py` → dividir en `src/benchmarking/ingesta/{validacion,anonimizacion,features_base}.py`. La función `ingestar()` orquesta; retorna dict con rutas y conteos.
- `config.yaml` → repartir entre `settings.py` (runtime: salt env var, umbrales) y `esquema_plantilla.yaml` (contrato de columnas de la plantilla).
- `diagnostico_cargos.py` (experimento) → `research/experimentos/`.

*(Estos archivos se adjuntan junto a este handoff.)*

## 7. Matriz experimental (tesis — vive en research/)

- **E1:** ¿aporta el embedding del cargo original? (representación con vs. sin bloque de texto)
- **E2:** anti-circularidad — ¿los clusters capturan actividad o solo nivel de ingreso? (con vs. sin sueldo total)
- **E3:** comparación de las 4 familias × 2 mejores representaciones
- **E4:** consistencia y corrección del etiquetado LLM (acuerdo entre corridas + con expertos)
- **E5 (condicional):** ¿mejoran las restricciones semi-supervisadas? Usar **must-links** (no semillas de clase, por riesgo de fragmentación por granularidad) derivados de etiquetas confiables. Gate pre-registrado: ≥10 grupos-semilla cubriendo ≥15% de empleados en dataset multi-empresa. Diagnóstico preliminar (1 nómina): 40 grupos, 30% — cruzado, pendiente ratificación.

## 8. Qué construir primero (orden sugerido)

1. **Scaffold del repo:** `pyproject.toml` (src layout, Python 3.11+), estructura de carpetas, `Makefile`, CI mínimo, `README`. Dependencias base: pandas, pyarrow, pyyaml, pydantic, pydantic-settings, google-cloud-storage. Dev: pytest, ruff.
2. **Migrar el código existente** (§6) al paquete, manteniendo el comportamiento. Verificar que sigue procesando la nómina igual.
3. **Tests con data sintética:** generar un `nomina_sintetica.xlsx` (fixture) que imite la plantilla; test de que la anonimización elimina identificadores, de que cuarentena captura filas inválidas, de que el hash es determinista con salt fijo.
4. **`settings.py` con pydantic-settings:** config tipada, validada al arrancar, con el salt desde entorno.
5. A partir de ahí, seguir el cronograma: `representacion/` (Fase 2), luego `clustering/`, etc.

## 9. Principios de trabajo (importantes)

- **Alcance mínimo siempre.** Ante la duda, la versión más simple que funcione; lo demás al backlog. 330 horas es poco.
- **La frontera de privacidad es sagrada.** Ningún módulo posterior a `anonimizacion` debe poder ver identificadores. Si un diseño lo permitiría, está mal.
- **El núcleo no conoce API ni front.** Lógica de dominio pura, sin dependencias hacia afuera.
- **Config sobre código.** Umbrales, listas y decisiones parametrizables van a config, no hardcodeados.
- **Data real nunca al repo.** Ni como ejemplo, ni en tests, ni en notebooks commiteados.
- Este es un proyecto de una sola persona con tiempo escaso: preferir código legible y directo sobre abstracciones ingeniosas.
