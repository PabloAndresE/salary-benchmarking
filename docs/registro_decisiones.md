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

### Enmienda (2026-08-05, misma sesión): la premisa se pone a prueba, no se asume

Al revisar la decisión surgió una objeción de fondo: *si la composición resulta ser sobre todo horas
extras, y las horas extras dependen de la política de la empresa más que del rol, ¿vale la pena
sostener toda esta arquitectura? ¿No sería mejor prescindir de la composición y entrenar sobre una
muestra mucho mayor?*

**Medición sobre las filas con composición disponibles** (41 empresas, 4.325 personas — indicativo,
no concluyente):

| Componente | Varianza explicada por la empresa | Varía **dentro** de la empresa |
|---|---|---|
| Horas extras | 28,1% | 71,9% |
| Comisiones | 35,4% | 64,6% |
| *(referencia: log-sueldo, EDA)* | *34%* | *66%* |

La política de empresa pesa, pero **la mayor parte de la variación ocurre entre personas de la misma
empresa**, que es la señal de rol que se busca. El efecto empresa sobre las horas extras (28%) es
además *menor* que el efecto empresa sobre el propio sueldo (34%). La residualización del spec §5
está diseñada para retirar ese 28%.

Queda una duda que este número no resuelve: ese ~72% intra-empresa ¿es sistemático por rol, o es
circunstancia individual (alguien trabajó más horas ese mes)? Solo el modelo lo dirá.

**La decisión D-003 es robusta a esa incertidumbre**, y conviene dejarlo escrito:

- si la composición resulta **fuerte** → imputarla contamina el eje principal → **no imputar**;
- si resulta **débil** → imputarla rellena ruido y mantiene el riesgo del cluster artefacto →
  **no imputar**.

**Enmienda acordada:** el sub-proyecto 1 construye **dos baselines**, no uno, medidos con la misma
balanza y sobre el mismo held-out:

| | Representación | Universo de ajuste |
|---|---|---|
| **Baseline A** | con composición | 2024–2025 (~1,3 M filas) |
| **Baseline B** | sin composición | todos los años (~3,5 M filas) |

Si B iguala o supera a A, la composición no aporta y media arquitectura del spec (ILR, gate,
residualización, IPW) se puede retirar **con evidencia**. Si A gana, queda demostrado el aporte de
la composición. Es el experimento **E1/E2** del spec §10, adelantado de la semana ~12 a la ~4, y
cuesta poco porque el banco ya está construido.

Argumento adicional que sostiene mantener la composición: **el tamaño de muestra no es el cuello de
botella**. 1,3 M de filas y ~6.900 empresas sobran para estimar del orden de 50 grupos; pasar a
3,5 M no mejora la recuperación de clusters. Y como el 88% de las empresas se repiten entre años,
los años viejos aportan sobre todo repetición del mismo panel, no empresas nuevas. El intercambio
sería perder la variable principal a cambio de datos que no hacen falta.

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

---

## D-004 — Criterio de éxito pre-registrado: A o B

**Fecha:** 2026-08-05

### Contexto

El spec §9 exige pre-registrar qué resultado cuenta como éxito antes de mirar el test, para evitar
el *garden of forking paths*. La comparación arquetipo vs CARGO admite cuatro desenlaces:

| | Qué pasó |
|---|---|
| **A** | A igual cobertura, el arquetipo se equivoca menos que CARGO |
| **B** | Se equivocan igual, pero CARGO responde por ~60% de la gente y el arquetipo por el 100% |
| **C** | CARGO es mejor donde tiene etiqueta; el arquetipo rescata al resto (complementarios) |
| **D** | El arquetipo no gana en ningún lado |

### Decisión

**Éxito = A o B.** El escenario **C se reporta como hallazgo principal si ocurre, sin disfrazarlo de
victoria**; el escenario D se reporta como resultado negativo.

### Consideración

C es un desenlace plausible y probablemente el más probable: el EDA ya identificó "dos mundos" —
etiquetas estandarizadas que funcionan bien (guardia CV 0,17; perchador 0,10) frente a etiquetas
rotas (vendedor 0,79; docente 0,62). Es perfectamente posible que el arquetipo no mejore nada en
los cargos ya limpios y arrase en los sucios. Dicho con números, eso es un resultado excelente y
accionable ("para estos cargos use la etiqueta, para estos otros el arquetipo"), pero **no es la
afirmación que la tesis pre-registra**, y no debe presentarse como si lo fuera.

---

## D-005 — Métrica primaria: error de predicción fuera de muestra, no varianza explicada

**Fecha:** 2026-08-05

### Contexto y evidencia

Para decidir si el arquetipo supera al CARGO hay dos formas de medir:

1. **Dispersión intra-celda** (ω² / CV): ¿la gente del mismo grupo gana parecido?
2. **Error de predicción fuera de muestra**: tapado el sueldo de una persona, ¿se acierta su nivel
   salarial usando solo su grupo y personas de *otras* empresas (leave-company-out)?

La forma 1 tiene un sesgo estructural: **más celdas mejoran la métrica aunque las celdas no
contengan información**. Es el mismo artefacto que el EDA ya documentó con el placebo de bandas
aleatorias (el colapso bajaba de 2,7% a 2,2% solo por trocear). CARGO tiene **55.920 etiquetas
distintas en 2025** frente a las ~50 celdas de un arquetipo: la comparación directa es inválida.

La corrección clásica —igualar cardinalidad podando CARGO a sus top-k etiquetas— es inviable con
estos datos. Medido sobre 2025 (576.862 personas con cargo y sueldo válidos):

| Métrica | Valor |
|---|---|
| Etiquetas distintas | 55.920 |
| Cobertura de las 50 más frecuentes | **25,6%** |
| Etiquetas con una sola persona | 32.388 (58% de las etiquetas) |
| Etiquetas con menos de 3 personas | 71,2% |

Podar a 50 celdas dejaría a **429.000 personas (74,4%) en una única celda "otros"**. Eso no es
CARGO con cardinalidad reducida: es un baseline degradado por construcción, contra el que ganar no
demuestra nada. Además, las 50 etiquetas más frecuentes no son homogéneas en calidad —incluyen
tanto las peores (VENDEDOR CV 0,79; DOCENTE 0,62) como las mejores (PERCHADOR 0,10; GUARDIA 0,17)—,
así que el resultado dependería fuertemente de dónde se corte.

La literatura de comparación de particiones respalda el diagnóstico: las métricas no ajustadas no
deben usarse para comparar agrupamientos con distinto número de clusters, y aun las medidas
ajustadas por azar conservan sesgo residual asociado a la cardinalidad.

### Decisión

1. **Métrica primaria:** error de predicción del sueldo de referencia de la celda, **fuera de
   muestra y leave-company-out**, en log-SBU, con intervalos por **bootstrap de empresas**.
   CARGO compite **sin podar**, con sus 55.920 etiquetas intactas.
2. **Co-primaria: la cobertura.** Los dos métodos se abstienen de forma distinta —CARGO no puede
   responder cuando falta la etiqueta (3,6% en 2025, 22% en 2024) o cuando la etiqueta tiene
   demasiado pocos donantes; el arquetipo siempre asigna—. Se reporta la **curva error-cobertura**:
   cada método emite referencia + confianza, se barre el umbral y se grafica error contra fracción
   de personas cubiertas. Sin esto, los escenarios A y B de D-004 son indistinguibles.
3. **El ω² intra-empresa del §9 se conserva como métrica confirmatoria**, con la escalera de nulos
   completa. Se calcula y se reporta; no decide.
4. **La cardinalidad igualada la aporta el nulo "solo-texto"** del §9 (agrupar por similitud
   semántica del título en el mismo número de grupos que el arquetipo), que es un rival de
   cardinalidad igualada bien construido. **No se construye ningún CARGO podado.**

### Criterio

El error fuera de muestra **penaliza la cardinalidad excesiva por sí solo**: una celda con una sola
persona en train produce una referencia inútil para una persona nueva. No hace falta igualar k
porque la métrica lo hace sola — y por tanto no hace falta mutilar al baseline.

Además, coincide con la tarea real del producto ("¿cuál es la referencia de mercado para esta
persona?") y con la práctica de estadística oficial: el programa OEWS del BLS construye estimaciones
salariales por ocupación con donantes, fijando un objetivo de **≥5 donantes** por celda — la misma
cifra que el spec §12 fija como supresión de celda mínima, lo que le da respaldo institucional a un
umbral que de otro modo parecería arbitrario.

### Relación con el panel de tres jueces

No se contradicen sus exigencias: se mantienen la estimación intra-empresa, la validación fuera de
muestra, la escalera de nulos, el bootstrap por empresa y la exclusión del salario del agrupamiento.
Los dos cambios son **quitar la poda de CARGO** (un problema de validez de constructo que el panel
no detectó) y **añadir la cobertura** (que hace visible el escenario B).

### Alternativas descartadas

- **ω² a k igualado como árbitro.** Descartada por el baseline degradado (429.000 personas en
  "otros") y porque, al no medir cobertura, colapsa los escenarios A y B de D-004 en un aparente
  empate.
- **Ambas métricas con ω² al mando.** Obliga igualmente a construir y defender el CARGO podado, y
  duplica el alcance del sub-proyecto 1 sin resolver el problema de fondo.

### Reversibilidad

Alta. Ambas métricas se calculan y se reportan; la decisión solo fija cuál se pre-registra como
árbitro. Lo que **no** es reversible es mirar los resultados antes de fijarla, que es justo lo que
el pre-registro impide.

### Fuentes

- Romano, S., Vinh, N. X., Bailey, J. & Verspoor, K. (2016). *Adjusting for Chance Clustering
  Comparison Measures.* JMLR 17. <https://jmlr.org/papers/v17/15-627.html>
- *Comparing clusterings and numbers of clusters.* arXiv:2002.01822.
  <https://arxiv.org/pdf/2002.01822>
- scikit-learn. *Adjustment for chance in clustering performance evaluation.*
  <https://scikit-learn.org/stable/auto_examples/cluster/plot_adjusted_for_chance_measures.html>
- U.S. Bureau of Labor Statistics. *Occupational Employment and Wage Statistics — Survey Methods and
  Reliability.* <https://www.bls.gov/oes/methods_24.pdf> — objetivo de ≥5 donantes por celda.
- U.S. Bureau of Labor Statistics. *Model-based estimates for the Occupational Employment Statistics
  program.* Monthly Labor Review.
  <https://www.bls.gov/opub/mlr/2019/article/model-based-estimates-for-the-occupational-employment-statistics-program.htm>
