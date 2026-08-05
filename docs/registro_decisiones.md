# Registro de decisiones — Benchmarking Salarial

Bitácora de las decisiones de diseño y método, con la evidencia y las fuentes que las sustentan.
Existe para dos propósitos: que el proyecto no reabra discusiones ya cerradas, y que la tesis
pueda citar el porqué de cada elección metodológica.

Cada entrada registra: **contexto y evidencia**, **decisión**, **criterio** (con fuentes cuando
la decisión es metodológica), **alternativas descartadas** y **reversibilidad**.

Las decisiones anteriores a esta bitácora viven en `HANDOFF.md` §5 y en los specs de
`docs/superpowers/specs/`.

---

## D-001 — Pérdida silenciosa de composición por concurrencia de descargas

**Fecha:** 2026-08-05

### Contexto y evidencia

La composición salarial (comisiones / horas extras / otros) no existe en la fuente BigQuery de
estudios actuariales; solo se obtiene descargando la *plantilla modificada* de cada estudio vía la
API de ActuaFast. Es el eje de segmentación del modelo (spec de clustering §5).

Tras ~7.400 estudios procesados, la tabla `benchmarking_tesis.nomina_features` mostraba composición
en apenas **63 de 1.375 estudios de 2025 (4,6%)**. Se sondearon 100 estudios reales contra la API
para distinguir "la plantilla no existe" de "el pipeline la pierde":

| Año  | Plantilla disponible | Nota                        |
|------|----------------------|-----------------------------|
| 2025 | 25/25 (100%)         |                             |
| 2024 | 26/29 (90%)          | 1×404, 2×400                |
| 2023 | *no sondeado*        | pendiente de medir          |
| 2022 | 0/33 (404)           |                             |
| 2019 | 0/13 (404)           |                             |

Y se aisló la causa de la pérdida repitiendo la descarga de los mismos 20 estudios a distinta
concurrencia:

```
concurrencia = 8  ->  descarga OK  4/20   (16 SSLError)
concurrencia = 2  ->  descarga OK 20/20   (0 fallos)
parseo (parsear_plantilla) -> 20/20 OK
```

El parser no tiene ningún problema. `descargar_plantilla` solo reintenta códigos HTTP 5xx; una
`SSLError` es una **excepción**, así que escapa del bucle de reintentos, la captura el `except`
de `_una_plantilla`, se imprime "estudio omitido" y el estudio se pierde. Con el valor por defecto
`descargas_concurrentes = 8` se perdía ~80% de las plantillas.

El daño se agrava porque el estado de reanudación es la propia tabla destino: un estudio escrito
con composición NULL queda marcado como *hecho* y no se vuelve a visitar.

### Decisión

1. Reintentar también ante excepciones de red (`SSLError`, timeouts, `ConnectionError`), no solo
   ante 5xx.
2. Bajar la concurrencia por defecto a un valor verificado como seguro.
3. Borrar de la tabla destino las filas con `anio_valoracion >= 2024` y reprocesarlas.
4. Medir la cobertura real de plantilla por año —incluido 2023, aún sin sondear— y dejarla
   registrada como dato de la tesis.

### Consideración

Un fallo de red que se traga silenciosamente el 80% de la variable principal es peor que un fallo
ruidoso. La resiliencia de lote (`_composicion_estudios` omite el estudio en vez de tumbar la
corrida) es correcta como política, pero necesita **contabilidad**: cuántos estudios se omitieron
y por qué motivo, para que la degradación sea visible y no haya que descubrirla por casualidad.

### Reversibilidad

Total. Los datos de origen no se tocan; reprocesar es idempotente.

---

## D-002 — Orden de construcción del núcleo: evaluación primero

**Fecha:** 2026-08-05

### Contexto

El spec de clustering (`2026-08-04-clustering-arquetipos-design.md`) describe cinco subsistemas
—representación, modelo de nivel, cuatro familias de clustering, etiquetado LLM y validación— más
una matriz de cinco experimentos. No cabe en un solo plan de implementación. Quedan ~14 semanas
hasta la entrega de noviembre 2026.

### Decisión

Descomponer el núcleo en sub-proyectos secuenciales, cada uno con su spec y su plan, en este orden:

| # | Sub-proyecto |
|---|---|
| 0 | Arreglo de la pérdida de composición y reproceso de 2024–2025 (D-001) |
| 1 | **Banco de validación + baseline** — splits por empresa, ω² intra-empresa con bootstrap por empresa, escalera de nulos, y la comparación CARGO vs k-means sobre representación mínima |
| 2 | Representación completa (residualización, gate, ILR, pesos de bloque) |
| 3 | Modelo de nivel |
| 4 | Las cuatro familias de clustering (E3) |
| 5 | Etiquetado LLM y mapeo ISCO-08 |

### Criterio

La tesis no afirma *"construí un clustering"*, afirma *"este grupo de comparación mide mejor que el
CARGO, y lo demuestro con rigor"*. **La contribución es la medición, no el algoritmo.** De ahí que
el instrumento de medida deba existir antes que lo que se va a medir: cada decisión de modelado
posterior se justifica con un número producido por el mismo banco, y no por una métrica elegida
después de ver el resultado (lo que el spec §9 llama *garden of forking paths*).

El corolario práctico: si el tiempo se agota, lo que queda terminado es una medición rigurosa de
algo simple —que es un resultado de tesis defendible— y no media representación muy buena sin
evidencia de que sirva.

### Alternativas descartadas

- **Rebanada vertical delgada** (pipeline completo pero flojo, incluido etiquetado). Da una demo
  temprana y descubre pronto los problemas de integración, pero la validación nace débil y es fácil
  que se quede débil, que es justo donde aprieta un tribunal.
- **Por capas, en orden del spec** (representación → nivel → clustering → etiquetado → validación).
  No se sabría si la composición separa algo hasta la semana 12, sin margen de reacción.

---

## D-003 — Universo de ajuste: no imputar composición en cohortes con falta sistemática

**Fecha:** 2026-08-05

### Contexto y evidencia

Tres universos que conviene no confundir:

| Universo | Qué es | Tamaño |
|---|---|---|
| **Ajuste** | filas de las que el modelo aprende los arquetipos | decisión de esta entrada |
| **Asignación** | filas que reciben un arquetipo | 4,66 M (todo) |
| **Evaluación** | filas donde se compara arquetipo vs CARGO | donde hay cargo y sueldo |

Calidad de los datos por año (fuente: `estudios_actuariales`, `es_ultima_version`):

| Año  | Filas   | Empresas | Cargo utilizable | Sueldo > 0 | Composición |
|------|---------|----------|------------------|------------|-------------|
| 2025 | 617.557 | 5.985    | 96,4%            | 93,7%      | ~100%       |
| 2024 | 722.976 | 6.137    | 77,8%            | 72,1%      | ~90%        |
| 2023 | 644.679 | 5.917    | 64,6%            | 78,4%      | sin medir   |
| 2022 | 609.477 | 5.887    | 60,4%            | 78,2%      | 0%          |
| 2021 | 565.277 | 5.846    | 60,9%            | 77,5%      | 0%          |
| 2020 | 547.992 | 5.617    | 54,8%            | 66,3%      | 0%          |
| 2019 | 554.767 | 5.700    | 13,9%            | 59,5%      | 0%          |
| 2018 | 381.000 | 5.345    | 0,5%             | 56,2%      | 0%          |

Solapamiento entre los dos años con composición: **5.238 de 5.985 empresas (87,5%)** y **478.522 de
598.345 personas (80,0%)** de 2025 están también en 2024. No son dos años independientes: es el
mismo panel medido dos veces.

### El marco: falta esporádica vs falta sistemática

La literatura de meta-análisis de datos individuales (IPD) distingue dos regímenes que suelen
confundirse bajo la etiqueta genérica de "datos faltantes": una variable es **sistemáticamente
faltante** si está *completamente* ausente en algunos clusters, y **esporádicamente faltante** si
está *parcialmente* ausente. Los datos de este proyecto caen en ambos regímenes a la vez:

| Cohorte   | Composición   | Régimen         |
|-----------|---------------|-----------------|
| 2024–2025 | falta ~5–10%  | **esporádica**  |
| 2018–2023 | falta 100%    | **sistemática** |

La distinción es material: en el régimen esporádico el imputador aprende de otras personas del
mismo estrato que sí tienen el dato; en el sistemático no hay nada dentro del estrato de donde
aprender, y la imputación es extrapolación pura desde otras cohortes.

### Decisión

1. **Ajustar** sobre 2024–2025, aplicando **imputación + indicador de faltante** tal como fija el
   spec §5 — porque ahí la falta es esporádica, el único régimen donde imputar es defendible.
2. **No extender el ajuste** a 2018–2023, donde la composición falta al 100% por cohorte.
3. **Corregir el sesgo de selección** de esa restricción con **IPW**, como ya prescribe el spec §8
   (`missing ~ año + segmento + ciiu + n_empleados + provincia`, balance observado-vs-faltante y
   análisis de sensibilidad).
4. **Asignar a los 4,66 M**, incluidas las filas sin composición y las filas sin cargo. La
   asignación sin composición **no** pasa por imputar: el GMM **marginaliza las dimensiones
   ausentes** vía EM con faltantes (spec §7) y devuelve la asignación con **menor confianza**,
   explícita y reportable.

### Criterio

**1. La transportabilidad se asume, no se verifica.** Imputar una covariable sistemáticamente
ausente asume implícitamente que las asociaciones son similares entre estudios, y el sesgo derivado
de violar ese supuesto es difícil de razonar cualitativamente; las simulaciones muestran
sensibilidad monótona a las diferencias de estructura causal entre estudios. Aquí eso significa
afirmar que la relación *{cargo, centro, edad, antigüedad, sector, tamaño} → composición* es estable
a lo largo de cuatro años del mercado laboral ecuatoriano, **sin una sola fila de 2018–2023 con la
que contrastarlo**: un supuesto no falsable sosteniendo ~65% de los datos de ajuste, sobre el eje
primario del modelo.

**2. Para clustering, la imputación no es neutral: colapsa hacia el centroide.** Este es el
argumento decisivo, y es distinto del anterior. La imputación global, agnóstica a la estructura
latente, se desvía hacia el promedio global y produce valores mal ubicados; cuando los datos
contienen subgrupos con distribuciones distintas, difumina las fronteras entre subgrupos y daña la
recuperación de clusters. La imputación preserva medias y asociaciones, no crea puntos en los
extremos: 2,4 M de filas imputadas se apilarían cerca de la media condicional y **crearían una moda
artificial** que dominaría el espacio de composición. GMM o HDBSCAN encontrarían ahí un cluster que
es un artefacto del imputador — y el *gate* del §5, que enruta "masa fija al piso" frente a
"población con estructura", estaría decidiendo el enrutamiento con valores inventados.

**3. El sesgo de restringir el ajuste sí tiene remedio conocido.** El análisis de casos completos
produce estimaciones sesgadas cuando el mecanismo no es MCAR, y el remedio estándar es IPW: modelar
el mecanismo de falta y ponderar por la inversa de la probabilidad de selección, construyendo una
pseudo-población en la que el sesgo de selección se elimina. Es decir: **restringir el ajuste tiene
corrección diseñada; imputar 2018–2023 no la tiene, porque el supuesto no es verificable.**

### Alternativas descartadas

- **Imputar 2020–2025 completo (~3,7 M filas).** Máxima cobertura y el modelo vería el mundo tal
  como se le va a aplicar. Descartada por los criterios 1 y 2: ~65% del bloque de composición sería
  imputado, y la falta es por cohorte completa, no al azar.

- **Ajustar solo sobre filas con composición real, sin imputar nada.** Deja el eje de composición
  como señal pura, pero contradice el spec §5 y excluye sistemáticamente del ajuste a las empresas
  cuyo estudio no tiene plantilla — justo el sesgo que §8 quiere medir y corregir.

- **Clustering bajo imputación múltiple con consenso de particiones.** Existe metodología correcta
  para esto: se clusteriza cada uno de los *M* datasets imputados y se consensúan las particiones
  resultantes. El paquete **`clusterMI`** (CRAN) implementa exactamente ese flujo —imputación
  múltiple, clustering por dataset y agregación por consenso— y sería el camino riguroso si se
  insistiera en imputar. **Se descarta igualmente**, por dos razones: multiplica el cómputo por *M*,
  y sobre todo **sigue apoyándose en el mismo supuesto de transportabilidad no verificable**. Rigor
  procedimental sobre un supuesto falso no salva el resultado. Se deja constancia porque es la
  alternativa técnicamente seria y conviene poder citarla como considerada y descartada con motivo.

### Hallazgo derivado: el solapamiento como instrumento

El 80% de solapamiento de personas entre 2024 y 2025 se registró primero como un riesgo (fuga entre
train y test, n inflado). Es también un activo: **478.522 personas observadas dos veces permiten un
test de fiabilidad *test-retest*** —asignar arquetipos por separado en cada año y medir si la misma
persona cae en el mismo arquetipo—. Es evidencia de estabilidad más fuerte que un ARI de bootstrap,
porque la re-medición es real y no simulada. No está contemplado en el spec §9 y se propone
incorporarlo.

### Reversibilidad

**Asimétrica, y eso inclina la decisión.** Restringir el ajuste es reversible: si el test-retest y
la validación ponderada por IPW muestran que el modelo transporta bien hacia atrás, se amplía
después. Contaminar el eje de composición con 65% de valores imputados no es reversible: no habría
forma de saber a posteriori cuánto de lo encontrado era el imputador.

### Fuentes

- Resche-Rigon, M. & White, I. R. (2018). *Multiple imputation by chained equations for
  systematically and sporadically missing multilevel data.* Statistical Methods in Medical Research.
  <https://pubmed.ncbi.nlm.nih.gov/27647809/> — origen de la distinción sistemática/esporádica.
- *Transportability of missing data models across study sites for research synthesis.* medRxiv.
  <https://www.medrxiv.org/content/10.64898/2026.03.09.26347913v1> — sensibilidad de la imputación
  cross-site a diferencias de estructura causal.
- *Statistical approaches for systematically missing covariates in individual participant data
  meta-analysis: insights and applications using 5 large cardiovascular trials.* American Journal of
  Epidemiology. <https://academic.oup.com/aje/advance-article/doi/10.1093/aje/kwaf226/8280162>
- *Imputation Meets Clustering: Exploiting Latent Subgroup Structure for Missing Data Recovery.*
  arXiv:2607.06930. <https://arxiv.org/html/2607.06930> — la imputación global difumina las
  fronteras entre subgrupos.
- Seaman, S. R. & White, I. R. (2013). *Review of inverse probability weighting for dealing with
  missing data.* Statistical Methods in Medical Research, 22(3).
  <https://journals.sagepub.com/doi/10.1177/0962280210395740>
- Audigier, V. & Niang, N. *clusterMI: Cluster Analysis with Missing Values by Multiple Imputation.*
  CRAN. <https://cran.r-project.org/web/packages/clusterMI/vignettes/clusterMI.pdf> — alternativa
  considerada y descartada.
