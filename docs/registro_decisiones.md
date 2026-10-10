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

### Ejecución (2026-08-05)

**Cobertura de plantilla por año, medida contra la API** (sondeo directo, 160 estudios):

| Año | Plantilla disponible |
|---|---|
| 2025 | 25/25 (100%) |
| 2024 | 26/29 (90%) |
| 2023 | **0/26** |
| 2022 | 0/33 |
| 2021 | 0/18 |
| 2020 | 0/16 |
| 2019 | 0/13 |

Queda cerrado: **la composición existe sólo en 2024–2025**. El universo de ajuste de D-003 no
admite ampliación hacia atrás.

**Concurrencia óptima, medida con el cliente ya arreglado** (20 estudios de 2025 por nivel):

| Hilos | ok | perdidos | peticiones HTTP | estudios/s |
|---|---|---|---|---|
| 2 | 20 | 0 | 20 | 0,54 |
| **4** | **19** | **0** | **20** | **0,80** |
| 6 | 17 | 3 | 41 | 0,28 |
| 8 | 13 | 7 | 67 | 0,16 |

A partir de 6 hilos el servidor corta conexiones, los reintentos se multiplican y el rendimiento
se desploma. El valor anterior (8) no sólo perdía datos: **también era 5× más lento**.

**Cambios aplicados** (commit *«fix(plantilla_client): reintentar ante caida de conexion; concurrencia 8 -> 4»*):

1. `descargar_plantilla` reintenta ante `RequestException` (SSL / conexión / timeout) y agota en
   `DescargaFallida`, distinta de `404 → None`. Espera inyectable para tests rápidos.
2. `_una_plantilla` devuelve `(montos, motivo)` y `_composicion_estudios` acumula un `Counter`:
   `ok / sin_plantilla / fallo_descarga / fallo_parseo`, con aviso destacado si hubo pérdidas.
3. `descargas_concurrentes` 8 → 4, con la tabla de medición documentada en `settings.py`.

**Dos bugs adicionales, descubiertos al desplegar:**

- Commit *«fix(infra): el job no fija --concurrencia»* — el job de Cloud Run pasaba `--concurrencia=8` por `--args`, lo que habría pisado
  el valor medido y reintroducido la pérdida. Se retira el flag: la concurrencia tiene una sola
  fuente de verdad (`settings.py`).
- Commit *«fix(empaque): incluir esquema_plantilla.yaml en el paquete instalado»* — la primera ejecución del job murió al importar, con `FileNotFoundError` sobre
  `esquema_plantilla.yaml`: `setuptools` no copia archivos no-`.py`, y en local no se nota porque
  se ejecuta desde `src/`. Bug preexistente que nadie había visto porque el job se creó el 4-ago y
  nunca se había ejecutado. Se añade `package-data` y un **smoke en el Dockerfile**
  (`benchmarking --help`) para que un dato de paquete ausente rompa el *build* y no una corrida de
  ocho horas.

**Reproceso:** `DELETE ... WHERE anio_valoracion >= 2024` → 173.736 filas eliminadas (2.150
estudios de 2025 que se habían escrito con composición en sólo 6.194 filas). Los años 2016–2018
(355.187 filas) se conservan: esos estudios no tienen plantilla, así que su composición NULL es
correcta y reprocesarlos no cambiaría nada.

### Segundo hallazgo: el enlace perdía las cédulas con cero inicial (sesgo geográfico)

Con las descargas ya arregladas (99,8% de plantillas obtenidas), el primer lote mostró composición
en sólo el **49,5% de las filas**. La causa resultó ser un segundo bug, independiente:

```
cédulas en la base BigQuery : ['1724894736', '0928066398', '0104110309', ...]
cédulas en la plantilla     : ['926442096',  '1003422241', '1715781884', ...]
                                ^ falta el cero inicial
```

La plantilla guarda las cédulas **sin el cero inicial** (en algún punto pasaron por un formato
numérico); la base sí lo conserva. El enlace era por texto exacto, así que **fallaba toda cédula de
las provincias 01-09**: Azuay, Bolívar, Cañar, Carchi, Cotopaxi, Chimborazo, El Oro, Esmeraldas y
Galápagos.

**Verificación sobre 6 estudios reales (1.397 personas):**

| Estudio | Personas | Antes | Después | Techo |
|---|---|---|---|---|
| 143255 | 527 | 75,1% | 90,5% | 90,5% |
| 140179 | 225 | 18,7% | 91,1% | 91,1% |
| 139370 | 309 | 91,6% | 93,9% | 93,9% |
| 141103 | 66 | **7,6%** | 93,9% | 93,9% |
| 140828 | 201 | 30,3% | 87,6% | 87,6% |
| 142728 | 69 | 55,1% | 66,7% | 66,7% |
| **Total** | **1.397** | **59,1%** | **89,9%** | **89,9%** |

El arreglo **alcanza el techo exacto en los seis casos**: tras normalizar, se enlazan todas las
personas que la plantilla contiene. El hueco restante no es un defecto — la plantilla simplemente
lista menos gente que la base del estudio.

**Lo importante no es el 31% recuperado, sino su forma.** La columna "antes" va de 7,6% a 91,6%
según cuánta gente de esa empresa tenga cédula de provincia 01-09. Es decir: la composición habría
faltado **de forma sistemática por provincia**, no al azar. Ajustar los arquetipos con eso habría
introducido un sesgo geográfico indetectable a posteriori — y habría contaminado justo el eje
principal del modelo (§5 del spec de clustering).

**Arreglo** (commit *«fix(enlace): normalizar la cedula para el join; separar rechazo 4xx de perdida»*): `_ced_key()` normaliza para el join (quita el `.0` espurio de las columnas
leídas como float; rellena con ceros a 10 sólo si el valor es enteramente numérico, dejando intactos
los RUC de 13 dígitos y los pasaportes). Se usa **exclusivamente como llave de enlace**:
`identificacion` no se toca, y el `id_hash` sigue calculándose sobre el valor original. Hay un test
que fija esa invariante — si el hash cambiara, las personas dejarían de ser comparables con las
filas ya escritas y se rompería el test-retest de §6.5 del spec del banco.

También se separa **`PlantillaRechazada`** (4xx distinto de 404) de `DescargaFallida`: un 400 es
determinista y no se recupera reintentando, así que contarlo como pérdida llenaba de ruido el
marcador.

### Efecto combinado de los arreglos

| | Plantillas descargadas | Personas enlazadas | Filas con composición |
|---|---|---|---|
| Antes | 4,6% | 59,1% | **~2,7%** |
| Después | 99,8% | 89,9% | **86,7%** *(medido en el primer lote real)* |

Factor de mejora: **~32×** sobre la variable que el spec de clustering define como eje de
segmentación.

**Detalle de orden que conviene recordar:** el segundo bug sólo era visible una vez arreglado el
primero. Mientras el 95% de las plantillas se perdía en la red, no había volumen suficiente para
notar que además el enlace fallaba. Los defectos en cadena se descubren de uno en uno, y conviene
volver a medir después de cada arreglo en lugar de dar el problema por cerrado.

### Lección transversal

Un fallo que se traga en silencio el 80% de la variable principal es peor que un fallo ruidoso. La
resiliencia por lote es correcta como política —un estudio malo no debe tumbar una corrida de 48.000—
pero **exige contabilidad**: sin el conteo por motivo, la degradación sólo se descubre por
casualidad. Vale como criterio para el resto del proyecto: toda omisión silenciosa se cuenta y se
reporta.

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

> **Corrección (2026-08-06, con 2025 completo).** Las cifras de arriba salían de 4.325 personas en
> 41 empresas — los estudios que sobrevivieron al bug de descargas, que no eran una muestra
> representativa. Con el año 2025 íntegro (486.814 filas con composición, 5.269 empresas) los
> números cambian, y en ambas direcciones:
>
> | | Muestra de 41 empresas | **2025 completo** |
> |---|---|---|
> | η² empresa — horas extras | 0,281 | **0,498** |
> | η² empresa — comisiones | 0,354 | 0,388 |
> | η² empresa — log del total | — | 0,388 |
> | Personas con comisiones >5% | 4,6% | **17,2%** |
> | Personas con extras >5% | 64,7% | 40,6% |
> | Personas con otros >5% | 4,7% | 17,8% |
> | Variable alto (<70% fijo) | 5,7% | **21,2%** |
> | Todo fijo (≥99%) | 19,7% | 30,1% |
>
> **A favor de la composición:** las comisiones alcanzan al 17,2% de la gente, casi cuatro veces más
> de lo estimado, y el 21,2% tiene una parte variable sustancial. El eje está mucho más poblado de
> lo que sugería la muestra pequeña, y no se reduce a horas extras.
>
> **En contra:** el efecto empresa sobre las horas extras es del **49,8%, no del 28%** — la mitad de
> la variación en horas extras es política del empleador, y supera al efecto empresa sobre el propio
> salario (38,8%). La objeción original que motivó esta enmienda era más certera que la respuesta
> que se le dio.
>
> **Consecuencias:** (a) la **residualización contra la media empleador×sector** (§5 del spec de
> clustering) pasa de conveniente a **imprescindible** para el bloque de horas extras; (b) las
> comisiones se comportan mejor que las extras (61,2% de variación intra-empresa) y merecen peso
> propio, no diluirse en un bloque único de composición; (c) la comparación de los dos baselines
> gana importancia, porque el margen entre "la composición aporta" y "la composición es política de
> empresa" es más estrecho de lo que parecía.

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

### Enmienda 1 (2026-08-05, misma sesión): blindaje anti-circularidad explícito

Al revisar la decisión surgió la objeción: *si el árbitro premia acertar el sueldo, ¿no acabamos
agrupando por sueldo en vez de por cargo?*

La respuesta corta es que la métrica no entra al modelo: los grupos se construyen sin el sueldo, se
congelan, y el sueldo aparece solo al calificar. Pero **hay una puerta trasera real**: si la métrica
se usa para *decidir* la granularidad, la familia o los pesos, el ajuste queda indirectamente
optimizado contra el sueldo, y se llega a bandas salariales disfrazadas de roles.

Nota importante: **este riesgo es idéntico con ω²** — una partición construida a propósito como
bandas de sueldo maximizaría las dos métricas. Por tanto no es un argumento a favor ni en contra de
D-005; se gestiona aparte.

**Se añade al pre-registro, de forma explícita:**

1. La perilla de granularidad (k en k-means/GMM, altura de corte en jerárquico, tamaño mínimo de
   grupo en HDBSCAN) y la familia se eligen **por estabilidad** —reproducibilidad de la partición
   entre submuestras de empresas, medida con ARI— **nunca por el acierto salarial**.
2. El **techo supervisado** (partición construida agrupando directamente por sueldo) se reporta
   siempre: fija la escala para interpretar el resultado propio y actúa como alarma si el arquetipo
   se le acerca demasiado.
3. El **test de validez externa** (predecir ISCO-08 desde el arquetipo) es la prueba directa de que
   los grupos son ocupaciones y no bandas de sueldo: una banda salarial no puede distinguir un
   soldador de un contador que ganan lo mismo. Requiere construir una referencia ISCO sobre una
   muestra — etiquetado por experto y/o cargos de texto específico e inequívoco.

### Enmienda 2 (2026-08-05, misma sesión): resuelve también la comparación entre familias

El spec §7 deja anotado un pendiente sobre HDBSCAN: *"k variable complica el 'k-igualado' de §9 (se
maneja aparte)"*. La métrica de D-005 lo resuelve sin apaños:

- Las cuatro familias terminan con **distinta cardinalidad** (p. ej. k-means 50, GMM 45, jerárquico
  60, HDBSCAN 73). Bajo ω² esa comparación es inválida por la misma razón que lo es contra CARGO;
  bajo error fuera de muestra es válida, porque el exceso de celdas se penaliza solo.
- El **ruido de HDBSCAN** (personas que no caen en ningún grupo) encaja de forma natural como
  **abstención**, y cuenta contra su cobertura — el mismo trato que recibe CARGO cuando falta la
  etiqueta. Bajo ω² habría que elegir entre excluir esas personas (regalándole a HDBSCAN los casos
  fáciles) o asignarlas a una celda artificial (castigándolo de más).

Es decir, la métrica sirve a la vez para el experimento principal (arquetipo vs CARGO) y para el
**E3** (comparación entre las cuatro familias), sin instrumentos distintos para cada uno.

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

---

## D-006 — Decisiones de implementación del banco de validación

**Fecha:** 2026-08-07

### Contexto

Al convertir el spec del banco en plan de implementación aparecieron dieciséis decisiones que el
spec no fijaba. Se revisaron una por una. Tres se apartaban del spec; las demás eran criterio o
mecánica. Las que se resolvieron midiendo sobre datos reales llevan su cifra.

| # | Decisión | Motivo |
|---|---|---|
| 1 | **Mediana** con leave-company-out, eficiente en numpy; curva de **8 umbrales** en vez de 30 | ver abajo |
| 2 | Nulo solo-texto con **embeddings**, no TF-IDF | ver abajo |
| 2b | Embeddings de **Vertex AI**, versión fijada en `settings.py` y usada como clave de caché | coherente con el spec §8; los datos no salen del proyecto GCP |
| 3 | ω² sobre residuo **intra-empresa**, no modelo mixto | ver abajo |
| 4 | Abstención si hay **<5 donantes o <3 empresas** donantes | 5 donantes de una sola empresa no son mercado; el empleador explica el 39% del salario |
| 5 | La perilla de la curva es el **número de donantes** | única perilla que `CARGO` y el arquetipo pueden compartir; `CARGO` no emite confianza propia |
| 6 | **MAE y RMSE**, con MAE como principal | la mediana minimiza el error absoluto: estimador y métrica emparejados |
| 7 | **Mínimo una empresa por estrato** en el test | rescata 5 de 70 estratos por 0,1 punto de tamaño |
| 8 | Roles sintéticos separados por **composición**, con sueldos solapados | si se separaran por sueldo, una partición por bandas salariales aprobaría el examen del banco |
| 14 | k de los baselines **por estabilidad** (ARI entre submuestras), no fijo | elegir k por acierto salarial es la puerta trasera de D-005 |
| 15 | Reducción del bloque de texto por **varianza explicada al 80%** | criterio que no mira el resultado, en vez de un número convencional |

Las mecánicas 9–13 y 16 se aceptaron sin cambios: dependencias de producción y no de desarrollo
(fue el bug del YAML que costó dos despliegues), backend `Agg` para correr sin pantalla,
`pythonpath` con `tests`, marco de evaluación restringido a filas con cargo utilizable, test-retest
de extremo a extremo, y hash del split dentro del pre-registro.

### Las tres que se apartaban del spec

**Mediana frente a media en espacio logarítmico.** La propuesta inicial era la media de los
logaritmos —que es la media geométrica en niveles, robusta a la asimetría— porque la mediana con
leave-company-out obliga a recalcular por cada par (celda, empresa), y `CARGO` tiene 55.920 celdas.

Medido sobre 498.653 personas y 10.270 celdas, la diferencia entre media y mediana por celda es
**0,0533 en log** (mediana de las diferencias 0,029; p90 0,143; máximo 1,36). Con un error esperado
del orden de 0,30, es un sexto de la magnitud que se pretende medir: **no es despreciable**.

Y sobre todo **no es neutral entre métodos**: la diferencia aparece justo en las celdas mezcladas,
donde la media se desplaza hacia la cola y la mediana no. Es decir, **la media castiga más a las
particiones que mezclan** — y la que mezcla es `CARGO`. Habría sido un sesgo a favor de la hipótesis
propia.

Se implementa la mediana. La curva baja a 8 umbrales (1, 2, 3, 5, 8, 12, 20, 30), que la dibujan
igual de bien y dividen el costo por cuatro.

**ω² residualizado frente a modelo mixto.** El spec §9 pedía modelo mixto; la diferencia práctica es
el encogimiento de las medias de empresas pequeñas hacia la global. Medido sobre 2025:

| Tamaño en la muestra | Empresas | % de personas |
|---|---|---|
| menos de 10 | 1.348 | **1,2%** |
| 10 a 99 | 3.350 | 22,1% |
| **100 o más** | 1.245 | **76,6%** |

Con el 76,6% de la gente en empresas de 100 o más, el encogimiento apenas mueve nada. Se
residualiza, se documenta esta tabla como justificación, y el ω² sigue siendo confirmatorio.

**Un nulo solo-texto débil.** Se descartó TF-IDF por la razón contraria a la habitual: no por ser
peor técnicamente, sino porque **produce un rival más flojo del necesario**. Agrupa por ortografía y
no por significado: junta VENDEDOR con VENDEDORA, pero no CHOFER con CONDUCTOR. Vencer a un rival
flojo no demuestra nada.

### Patrón que conviene retener

Tres de estas decisiones —media en vez de mediana, TF-IDF en vez de embeddings, y en su momento la
poda de `CARGO` (D-005)— apuntaban en la **misma dirección: favorecer la hipótesis propia**. Ninguna
se eligió con esa intención; todas eran la opción más simple o más barata.

Es un sesgo que aparece solo y hay que buscarlo activamente. Ante dos opciones defendibles,
**preguntarse cuál favorece al resultado que uno quiere, y desconfiar de esa.**

---

## D-007 — La compuerta de E5 pasa: el semi-supervisado es viable

**Fecha:** 2026-08-07

### Contexto

El spec §10 deja E5 (restricciones semi-supervisadas por *must-links*) como experimento
**condicional**, con una compuerta pre-registrada: **≥10 grupos-semilla cubriendo ≥15% de los
empleados**. El diagnóstico disponible era de una sola nómina (40 grupos, 30%), marcado como
"pendiente ratificación".

### Medición (1,3 M de filas de 2024–2025, `en_clean`)

Grupo-semilla = etiqueta de cargo presente en ≥3 empresas con ≥10 personas:

| Especificidad | Grupos | Cobertura |
|---|---|---|
| 1 palabra | 666 | 19,6% |
| 2 palabras | 1.161 | 17,0% |
| **3 o más palabras** | **2.511** | **29,0%** |

Restringiendo a las etiquetas más específicas —3 o más palabras, las de menor riesgo de ser cajón de
sastre— salen **2.511 grupos y 29% de cobertura**, frente a los 10 grupos y 15% exigidos. Pasa por
dos órdenes de magnitud.

*(Salvedad: el número de palabras es un sustituto tosco de "etiqueta fiable" — "SOLDADOR" es de una
palabra y es específico; "TRABAJADOR EN GENERAL" son tres y es basura. La definición correcta usa la
coincidencia entre dos etiquetas independientes, ver D-008. Aun con el sustituto burdo, pasa.)*

### Decisión y consecuencia

E5 deja de ser un experimento condicional del final. Los *must-links* aportan **lo que faltaba: un
criterio para elegir pesos de bloque y representación que no toca el salario**.

Esto corrige una afirmación anterior de esta misma sesión. Se había argumentado que en un problema
no supervisado no existe criterio objetivo para seleccionar variables, porque el único natural —qué
predice el salario— está prohibido por circularidad. Con *must-links* sí existe: **qué
representación respeta mejor las restricciones**. Es no circular y está anclado en información real.

Se mantiene el diseño del spec: **must-links, no semillas de clase**, para no imponer la granularidad
(¿soldadores como un grupo, o TIG separado de MIG?), que es justo lo que el clustering debe
descubrir.

---

## D-008 — Rescatar el cargo de la plantilla y cachear el XLSX crudo

**Fecha:** 2026-08-07

> ❌ **La premisa de la primera mitad de esta decisión resultó FALSA.** Medido el 2026-08-11:
> `cargo` y `cargo_plantilla` son **la misma cadena en el 100% de los casos** (4.323 personas, cero
> excepciones). No son dos etiquetas independientes: el estudio actuarial se construye a partir de
> la plantilla, así que el campo `cargo` es una copia. Ver **D-010**.
>
> **El caché en GCS —la segunda mitad— sigue siendo válido y está en producción.**

### Contexto

`parsear_plantilla` extrae el cargo de la plantilla, pero `_una_plantilla` solo conserva
`identificacion`, `comisiones`, `extras` y `otros`: **el cargo escrito por el empleador se
descarta**.

Es una **segunda etiqueta del mismo puesto, independiente de la del estudio actuarial**. El handoff
§5 ya describía ese mecanismo, planteándolo con la `profesion` del Registro Civil: *"segunda etiqueta
ruidosa INDEPENDIENTE de CARGO, su divergencia detecta etiquetas colapsadas"*. La plantilla la ofrece
gratis y ya se está descargando.

Con dos etiquetas independientes: **coinciden → etiqueta fiable → buen must-link** (D-007);
**divergen → etiqueta colapsada o mal capturada → descartar**.

### El problema de fondo que revela

El pipeline descarga cada plantilla, extrae cuatro columnas y **tira el archivo**. Cada vez que se
descubra que hacía falta una columna más son ~10 horas de re-descarga. Ya va a pasar con el cargo;
sin arreglarlo, volverá a pasar con el sexo o el centro de costo.

### Decisión

1. `_una_plantilla` conserva también el **cargo de la plantilla** (`cargo_plantilla`).
2. `descargar_plantilla` **cachea el XLSX crudo en GCS**, con clave `(numero_proceso, id_version)`.
   Las descargas posteriores leen del caché.
3. Al terminar la corrida actual, borrar 2024–2025 y reprocesar: **la última vez que esto cuesta
   diez horas**. A partir de ahí, cambiar lo que se extrae cuesta minutos.

### Consideración

El caché no es una optimización de rendimiento: es lo que convierte "qué columnas extraemos" en una
decisión **reversible**. Mientras la fuente sea una API que hay que volver a golpear, cada omisión se
paga en horas — y eso empuja a querer decidirlo todo por adelantado, que es justo lo que no se puede
hacer en investigación.

---

## D-009 — Revisión por panel de jueces: siete correcciones aceptadas

**Fecha:** 2026-08-07 · **Informe completo:** [`revision_jueces.md`](revision_jueces.md)

### Contexto

Cuatro revisiones independientes del diseño del núcleo —metodólogo estadístico, aprendizaje de
representación, práctica de compensaciones, y tribunal de tesis— con el encargo explícito de atacar
la idea. Ninguno vio el informe de los otros.

### Lo que invalidó

**D-007 queda anulado en su uso previsto.** Dos jueces demuestran, por vías independientes, que los
must-links definidos como *"la misma etiqueta de cargo"* tienen distancia de texto exactamente 0 y
por tanto el criterio converge al nulo solo-texto. No pueden arbitrar entre bloques. La compuerta de
E5 sigue pasando (2.511 grupos, 29%), pero el criterio hay que rehacerlo con must-links entre
**cadenas distintas** y con cannot-links.

**El §7 del spec de clustering contradice al §3 principio 4.** El principio dice que la selección de
modelo no usa la métrica salarial; el §7 afina el peso de bloque contra dispersión salarial en
held-out. Y el pre-registro cubre dos de los tres elementos que D-005 Enmienda 1 enumeró: los pesos
quedaron fuera.

### Decisión: se aceptan las siete correcciones

| # | Corrección | Dónde |
|---|---|---|
| 1 | Ponderar la referencia salarial **por empresa**, no por persona | spec del banco §5 |
| 2 | **Normalización MFA** (primer valor singular) en vez de peso de bloque afinado | spec de clustering §5, §7 |
| 3 | Escribir `preregistro.md` cerrando los **tres** elementos, pesos incluido | nuevo |
| 4 | Rehacer los must-links: entre cadenas distintas, con cannot-links | D-007 |
| 5 | Escribir el enmarque de novedad frente a Job2Vec, Djumalieva y TWICE | marco teórico |
| 6 | Medir la ruta de servicio (título → arquetipo) sobre empresas held-out | nuevo |
| 7 | Sacar `edad` del modelo de nivel y anclarlo a definición externa (NCS del BLS) | spec de clustering §6 |

**Prioridad 1 es bloqueante:** cambia todos los números del banco, así que tiene que estar antes de
producir el primero. Ninguna de las siete toca el pipeline de ingesta.

### Correcciones de enmarque

- *"El CARGO no sirve"* pasa a *"el CARGO **tal como se captura en los estudios actuariales
  ecuatorianos** no sirve"*: Torres et al. (2018) miden el título del puesto en ≈1/5 de la varianza
  del log-salario sobre datos administrativos limpios.
- El η²_empresa de 0,34–0,39 **probablemente está sobreestimado** por sesgo de movilidad limitada, y
  es uno de los números que sostiene el leave-company-out. Cuantificarlo o acotarlo.

### El patrón, otra vez

D-006 registró que tres decisiones independientes favorecían la hipótesis propia sin intención.
**D-007 fue la cuarta**, y dos jueces lo señalaron con esas palabras. El sesgo no se corrige
detectándolo una vez: hay que buscarlo activamente en cada decisión.

---

## D-010 — `cargo` y `cargo_plantilla` son la misma columna: no hay segunda etiqueta

**Fecha:** 2026-08-11

### La medición

Con `cargo_plantilla` ya poblado en el reproceso, sobre 4.323 personas de 100 estudios de 2025 con
ambas columnas presentes y `en_clean`:

| | |
|---|---|
| Cadenas idénticas | **100,0%** |
| Cadenas distintas | 0,0% |
| Pares distintos | **0** |

Inspección directa de los valores crudos: `cargo`, `cargo_norm` y `cargo_plantilla` coinciden
carácter a carácter, incluidas cadenas largas como
`TRABAJADORES DE PRODUCCION: PESADORES DE CAJAS, ANOTADORES Y ESTIBADORES DE CAJAS PARA CONGELACION,
TOLVERO, CLASIFICACION`.

### Por qué

**El estudio actuarial se construye a partir de la plantilla que sube el cliente.** El campo `cargo`
de la base de estudios no es una etiqueta independiente: es una copia de la de la plantilla. Nunca
hubo dos fuentes.

### Cómo se llegó al error

La premisa de D-008 —*"segunda etiqueta del mismo puesto, independiente de la del estudio
actuarial"*— venía del handoff §5, que planteaba ese mecanismo con la `profesion` del Registro Civil
(que **sí** sería independiente) y se trasladó a `cargo_plantilla` **sin verificarlo**.

Se reforzó con una inferencia descuidada: en un smoke test se vio
`'ASESORA COMERCIAL LINEA ESTETICA'` en una plantilla y se supuso que el estudio diría el genérico
`'ASESOR COMERCIAL'`. **Nunca se compararon las dos columnas para la misma persona.** La medición
costaba una consulta y se hizo cuatro días tarde, con tres decisiones ya construidas encima.

### Qué se cae

- **El detector de fiabilidad por coincidencia entre etiquetas.**
- **La fuente de must-links entre cadenas distintas que iba a rescatar a D-007.** Sigue sin haber
  criterio no circular para pesos de bloque desde esta vía.
- **La justificación principal de D-008.**
- **Parte del análisis de dos jueces.** Ambos calificaron `cargo_plantilla` como "el activo
  infravalorado del proyecto" y "la única fuente no circular de restricciones informativas y de
  cannot-links". Partieron de una premisa falsa suministrada en el encargo; el error es propio, no
  suyo. Anotado en `revision_jueces.md`.

### Qué se salva

- **El caché en GCS.** Vale por sí solo: convierte cualquier cambio futuro sobre qué extraer de la
  plantilla en minutos en vez de horas. Está lleno y en producción.
- **Las tablas sectoriales del Ministerio del Trabajo.** Su columna de comentarios es un diccionario
  de sinónimos **oficial y entre cadenas distintas** (*"AYUDANTE DE TOPÓGRAFO — INCLUYE CADENERO,
  PERFILERO, NIVELADOR, PRISMERO, MOCHILERO"*). No dependía de la premisa falsa, y ahora es **la
  única vía viable** para must-links informativos.
- **La `profesion` del Registro Civil** (handoff §5, flag apagado pendiente de aprobación legal).
  Esa sí sería una etiqueta genuinamente independiente, porque viene de otra fuente.

### Consecuencia sobre el diseño

La corrección 4 de D-009 —rehacer los must-links— **pierde una de sus dos fuentes**. Queda solo el
catálogo sectorial, lo que sube la prioridad de parsear el Acuerdo MDT-2019-395 (249 páginas) para
extraer la estructura ocupacional y los sinónimos.

Y refuerza la opción de resolver el peso de bloque **sin restricciones**, por normalización MFA
(corrección 2), que no depende de tener must-links de ninguna clase.

### Confirmado por el equipo (2026-08-11)

El equipo de ActuaFast lo ratificó de forma independiente: **ambos campos son exactamente iguales**,
porque el estudio actuarial se construye a partir de la plantilla. Ya no es "medido sobre 100
estudios, pendiente de reconfirmar": es un hecho verificado por dos vías —la medición y el
conocimiento de cómo se construyen los estudios—, y queda **cerrado**.

**Consecuencia:** `cargo_plantilla` se retira del pipeline en la próxima limpieza. No hace falta
esperar a reconfirmar nada. Cuesta una línea y no corre prisa; se deja hasta que termine el
reproceso en curso para no mezclar lotes con y sin columna.

### Lección

Es D-006 desde otro ángulo. Allí el patrón era *elegir* la opción que favorece la hipótesis; aquí es
**no verificar una premisa cómoda antes de construir encima**. La regla operativa que se deriva:
**toda premisa que habilite una decisión se mide antes de tomar la decisión, no después** — sobre
todo cuando medirla cuesta una consulta.

---

## D-011 — El estimador no estimaba lo que la métrica puntuaba

**Fecha:** 2026-08-11
**Origen:** auditoría de métricas encargada a dos jueces de ML/evaluación sobre el spec del banco,
el plan v2 (tareas 2–6, 9, 11, 12, 14, 15) y D-004/005/006/009/010.
**Estado:** decisión tomada; implementación pendiente (reescritura de las tareas 4, 5, 6, 12, 14, 15).

### Por qué se auditó

El plan v2 estaba en ejecución (tareas 1 y 2 commiteadas). Antes de escribir `referencia.py` se pidió
una revisión adversarial de **la regla de medición**, no del modelo. El razonamiento: una regla torcida
no se detecta midiendo, se detecta auditando la regla — y nueve semanas de resultados medidos con ella
son irrecuperables.

El encargo resultó rentable: **todo lo que se rompió estaba en el plan, no en el código**. Lo único
publicado que hay que tocar es una línea de `evaluacion/datos.py`.

### El defecto central

`predecir()` iba a devolver **la mediana de las medianas de empresa**. Eso estima `median_f(m_f)`: la
paga del *empleador típico*, un voto por empresa. Pero el MAE se evalúa contra la `y` de **personas**,
y su minimizador es la mediana ponderada por persona de la mezcla.

Son cantidades distintas siempre que el tamaño de la empresa correlacione con la paga. La justificación
literal de D-006 #6 —*"la mediana minimiza el error absoluto: estimador y métrica emparejados"*— deja
de ser cierta. **La corrección 1 de D-009 arregló un sesgo real y creó un desemparejamiento que nadie
recalculó**, y su magnitud escala con la heterogeneidad de tamaños dentro de celda, que es distinta en
`CARGO` (celdas pequeñas) y en el arquetipo (celdas enormes). No se sabe a quién favorece.

Agravantes en el propio diseño:

- `min_donantes` cuenta **personas**, pero la varianza del estimador depende del número de **votos**:
  una celda de 500 personas repartidas en 3 empresas pasa el filtro y publica la mediana de 3 números.
- El voto de una empresa con 1 persona pesa igual que el de una con 3.000.

### La decisión: un modelo de dos componentes del que todo cae por derivación

Por celda `c`, sobre `y = log(sueldo / SBU)`:

```
y_fi = mu_c + a_f + e_fi        a_f ~ (0, tau^2)      e_fi ~ (0, sigma^2)
```

`tau^2` es la varianza entre empresas (el efecto empleador: eta^2 ≈ 0,39 medido, ver `mediciones.md`
§3) y `sigma^2` la varianza intra-empresa dentro de celda. **Se estiman una sola vez, globalmente**, no
por celda — el mismo argumento con el que D-006 #3 descartó el modelo mixto para omega^2, y sostenido
por el 76,6% de personas en empresas de ≥100 en la muestra.

**Peso del voto de la empresa `f`:**

```
w_f = 1 / (tau^2 + sigma^2 / n_f)
```

Es el peso inverso-varianza, y es **derivado, no elegido**: cero hiperparámetros, cero puerta trasera
de las que D-005 Enmienda 1 vigila. Interpola exactamente entre las dos posturas del debate que D-009
zanjó a martillazos:

| Régimen | `w_f` tiende a | Equivale a |
|---|---|---|
| `n_f → ∞` | `1/tau^2`, igual para todas | **una empresa, un voto** (D-009 corrección 1) |
| `tau^2 → 0` | `n_f/sigma^2` | **una persona, un voto** (lo anterior a D-009) |

Y lo que resuelve el problema real: **el ratio máximo de pesos está acotado por `1 + sigma^2/tau^2`**,
no por 3.000. La dominancia de una empresa grande desaparece sin tener que descartar el voto de las
pequeñas.

**Referencia:** cuantil ponderado empírico al 50% sobre los votos `m_f` con pesos `w_f`. Conserva la
robustez que motivó elegir mediana sobre media (D-006 #6, sesgo medido 0,0533 en log) y es una línea de
numpy sobre el array que `referencia.py` ya ordena, así que el ahorro de coste que D-009 celebraba
queda intacto.

### Lo que cae del mismo modelo, sin coste adicional

1. **Distribución predictiva.** Como el split es por empresa, la empresa de test **nunca** está en
   train: el objetivo es `y = mu_c + a_nueva + e`, luego `y ~ (mu_c, tau^2 + sigma^2_c)`. Da
   P25/P50/P75 e intervalo — el entregable que el juez de compensaciones pidió y que quedó sin adoptar
   en `revision_jueces.md` §4.
2. **La perilla de confianza correcta.** `s(x) = tau^2 + sigma^2_c`, la anchura predictiva, calculada
   **solo con donantes de train**. Es la varianza condicional que Zaoui, Denis & Hebiri demuestran
   óptima para abstención en regresión, y tiene resolución continua en todo [0,1] tanto para 55.920
   celdas de `CARGO` como para 50 arquetipos.
3. **CRPS como puntuación.** Estrictamente propio, y **generaliza el error absoluto, al que se reduce
   cuando el pronóstico es una masa puntual**. O sea: no rompe nada de lo pre-registrado — el MAE
   actual es su caso degenerado. Su descomposición da fiabilidad + resolución, y la resolución es
   literalmente *"¿esta partición separa mercados?"*.
4. **AUGRC** en vez de comparación a cobertura igualada (ver siguiente sección).

### La curva error-cobertura era degenerada, y con ella el criterio A

Barrer `min_donantes` en (1,2,3,5,8,12,20,30) **personas** no dibuja ninguna curva para el arquetipo:
con k≈50 sobre ~1,3 M de filas la celda media tiene ~26.000 donantes, así que ningún umbral hasta 30
recorta nada. La curva del arquetipo —y las de aleatoria, solo-texto y techo, todas a k igualado— es
**un punto en cobertura 1,0**. Solo `CARGO` tiene curva, y su techo es 60,5%. **No existe ningún punto
del eje donde coexistan**, y el pre-registro exige leerlos "a cobertura igualada".

Defecto adicional del mismo barrido: se hace con `min_empresas=3` fijo, y ≥3 empresas implica ≥3
personas, así que los umbrales 1, 2 y 3 devuelven cobertura idéntica. Quedaban 5 puntos útiles de 8.

**Sustitución — riesgo generalizado.** Se barre `c`, el **coste de no dar respuesta**, no el umbral de
donantes:

```
Riesgo(c) = (1/N) * suma_sobre_TODAS [ |y_i - yhat_i| * 1{acepta} + c * 1{abstiene} ]
```

El denominador es `N` para todos los métodos, así que `CARGO` al 60,5% y el arquetipo al 100% se leen
en la misma escala sin necesidad de intersecar nada. Y `c` es una cantidad de negocio con significado,
no una perilla estadística.

Lo mejor: **el `c` donde se cruzan las dos curvas es la frontera entre los escenarios A y B de D-004**.
Convierte tres desenlaces narrativos en un punto de corte medible.

*(Se descarta AURC, recomendado en una versión previa del mismo informe y retirado por su autor: hay
demostración de que viola monotonicidad por sobreponderación de los fallos de alta confianza.)*

### La justificación institucional del umbral `m=5` se retira

Se citaba OEWS del BLS como respaldo de "mínimo 5 donantes". El auditor sostiene, con cita textual de
`methods_24.pdf`/`methods_25.pdf`, que:

- el "5" gobierna la **imputación por no respuesta** (*"prediction will still proceed if at least 5
  donor units are found"* — establecimientos de los que se copian datos faltantes), **no** la
  publicación;
- OEWS es **employment-weighted** —*"summing the hourly wages… for all employees in the estimation
  cell and dividing by the total employment in the cell"*—, es decir, **la convención opuesta** a "una
  empresa, un voto";
- el propio documento cierra la puerta: *"the specific screening criteria are not listed in this
  publication"*.

**⚠️ NO VERIFICADO POR CUENTA PROPIA.** `bls.gov` devuelve HTTP 403 a todo acceso automatizado desde
este entorno (probadas `oes-technical-notes.htm`, `2024/may/methods_24.pdf`,
`current/methods_statement.pdf`, vía navegador headless y vía fetch) y el presupuesto de búsqueda web
de la sesión está agotado. **Las citas de arriba proceden del informe del juez y no se han contrastado
contra el PDF primario.**

**Y aun así la consecuencia es la misma: la cita se retira.** Una cita que no se puede abrir no puede
sostener una decisión de método en una tesis, sea correcta o no. Se elimina de `D-005 §Criterio`,
`D-006 #4`, `spec §5`, `spec §13` y `docs/preregistro.md`. **Pendiente:** abrir el PDF a mano y cerrar
este punto en un sentido o en el otro.

### Qué reemplaza al umbral

**El criterio pasa a ser la anchura predictiva, no el conteo.** Un conteo de donantes no dice nada
sobre la precisión: 500 personas de 3 empresas homogéneas dan una referencia más precisa que 20
personas de 10 empresas dispares, y la regla anterior prefería la segunda. Con `tau^2 + sigma^2_c` el
umbral se declara en unidades interpretables —*"no publico si el IC al 80% supera ±X% en dólares"*—,
que es una decisión de producto, pre-registrable, y que no mira `y_test`.

Los conteos se conservan **degradados a suelos de sanidad**, por razones que no son de precisión:

- **≥3 empresas donantes** — identificabilidad de `tau^2` (con 2 empresas no se separa la varianza
  entre de la de dentro) y confidencialidad (con 2 donantes, cada uno deduce al otro).
- **ninguna empresa con más del 80% de las personas donantes** — regla de dominancia. Es
  estrictamente superior a `e ≥ 3` para lo que D-006 #4 quería resolver: `e ≥ 3` no impide que una
  empresa con el 95% de la gente domine si hay otras dos con una persona cada una. Con los pesos
  inverso-varianza es redundante, y se mantiene como red.

Precedente citable para ambos: **QCEW**, no OEWS — suprime la celda con menos de tres establecimientos
o donde uno supere el 80% del empleo. **Advertencia de uso que debe ir en el texto de la tesis:** es
una regla de *disclosure*, no de estimación, y la fuente localizada es secundaria (Rachel Justis,
*"What Do You Mean the Data Are Suppressed?"*, InContext 9(7), Indiana Business Research Center, 2008
— **▫ tampoco verificada**). Se cita como *"la preocupación por dominancia de un empleador es estándar
en estadística oficial"*, nunca como *"el BLS respalda ponderar por empresa"*.

### La regla de abstención tiene efecto distributivo no medido

Las celdas que no alcanzan donantes **no son un subconjunto aleatorio**: son ocupaciones raras,
empresas pequeñas, provincias fuera de Pichincha y Guayas, y probablemente ocupaciones feminizadas de
baja densidad. Al bajar la cobertura, el riesgo de un subgrupo puede empeorar aunque el riesgo global
mejore (Shah et al., ICML 2022).

Traducido: **el banco puede reportar un MAE excelente mientras la referencia se degrada justo para
quien más la necesita.** Y hoy no puede detectarlo — `SQL_MARCO` no cargaba `sexo`, lo que además
hacía imposible la auditoría Oaxaca que el spec de clustering §9 promete.

**Corregido en el acto:** `sexo` añadido a `SQL_MARCO`. Se reporta error **y** cobertura por subgrupo
**a lo largo de toda la curva**, no solo el agregado. No es un extra: es verificación obligatoria de la
regla de abstención.

### Los otros tres defectos

**El techo no era un techo.** `techo_supervisado(df, k)` corría k-means sobre `y` de **todo el df, test
incluido**. Al definir la celda por la propia `y` de la persona, el MAE colapsa al error de
cuantización de 50 bins (~0,01–0,03). Dos consecuencias: la frase-resultado *"el arquetipo recorre el
__% de la distancia entre CARGO y el techo"* tenía un denominador inalcanzable por construcción, y **la
alarma anti-circularidad moría** —nada puede acercarse a un techo que escapa del efecto empresa usando
la etiqueta—.

El propio número lo prueba: con eta^2_empresa = 0,388 y el efecto empresa inobservable bajo
leave-company-out, `Var(error) ≥ 0,388 · Var(y)` para **cualquier** partición; en desviación estándar
el mejor método posible llega a `raíz(0,388) = 0,623` del MAE aleatorio. **Todo el rango dinámico de la
métrica primaria es el 37,7% del piso**, y el techo que teníamos estaba en ~3%. Sustitución: LightGBM
sobre observables legítimos entrenado en train. El k-means sobre `y`, ajustado **solo en train**, se
renombra *oráculo* y queda como bandera roja, nunca como denominador.

**La inferencia no podía decidir A ni B.** Tres fallos compuestos: (a) `informe.comparar()` emitía dos
IC independientes, y el pre-registro exige el IC **de la diferencia** — leer solapamiento es el error
de Schenker & Gentleman, y aquí cuesta especialmente caro porque el error está dominado por `a_f`, que
es idéntico para los dos métodos y **se cancela en la diferencia pareada**; (b)
`ic_bootstrap_empresas` llamaba a `predecir()` **fuera** del bucle, tratando `mu_c` como fija cuando en
la mayoría de celdas de `CARGO` se estima con 3–5 empresas; (c) dos personas de empresas distintas en
la misma celda comparten `mu_c`, y agrupar solo por empresa de test no lo captura. Sustitución:
bootstrap de dos etapas con números aleatorios comunes (train → votos → test → MAE de todos los
métodos con la misma réplica) y diferencia pareada sobre la intersección.

**Los baselines A/B contaminaban el test bloqueado.** La tarea 15 los evaluaba *"sobre el mismo
held-out"* en la semana ~4, y de ahí se decidía si retirar media arquitectura. Es selección sobre el
conjunto bloqueado: **exactamente el fallo que `revision_jueces.md` §3 denunció para los pesos de
bloque y que se aceptó como corrección 3 de D-009 — y reapareció dos secciones más abajo sin que nadie
lo viera.** A vs B se decide en CV agrupada por empresa dentro del 80% de train; el 20% se toca una
vez, al final.

### Alternativas descartadas

| Opción | Por qué no |
|---|---|
| **Hodges-Lehmann** como estimador robusto | Estima la **pseudomediana** —mediana de (X1+X2)/2—, que iguala a la mediana poblacional **solo bajo simetría**. Asumir simetría en salarios no es defendible, y cambiar el estimando es justo el pecado que este D-011 corrige. Vale como chequeo de robustez, no como estimador. |
| **AURC** para comparar métodos con cobertura distinta | Viola monotonicidad (Traub et al. 2024). Sustituido por AUGRC. |
| **Mantener la mediana simple de medianas** | Es el defecto central. |
| **`min_donantes` como criterio de abstención** | No es una función de confianza: mover `m` mueve la subpoblación, no ordena predicciones por incertidumbre. |
| **Volver a ponderar por persona** | Reintroduce la dominancia que D-009 corrección 1 eliminó. El peso inverso-varianza da ambos límites sin elegir ninguno. |

### Carencias registradas, no todas adoptadas

Nueve huecos señalados. Se adoptan como parte de las tareas reescritas: sesgo con signo por decil de
`yhat`; **MAE intra-empresa** (descomponer `e_fi = e_barra_f + (e_fi - e_barra_f)`, porque `e_barra_f`
es impredecible bajo LOCO e **idéntico para todos los métodos** — ahí vive el ~62% de la sd del error y
solo diluye la señal); `sexo` y desglose por subgrupo; **masa en el SBU** (con `sueldo_bajo_sbu` en
cuarentena, `y ≥ 0` está censurada con masa puntual: si supera el 50% en muchas celdas, la mediana de
casi cualquier celda es 0 —incluida la aleatoria— y el piso de la escalera sube hasta tocar al
arquetipo); **MDE pre-registrado** (calibrar con `sintetico` reasignando x% al azar y comprobar
respuesta monótona); **ganador por etiqueta** (D-004 declara C el desenlace más probable y no había
ninguna métrica que lo operacionalizara: si ocurre C, esto *es* el entregable).

Quedan fuera de la primera pasada, anotadas: **variante anclada a la empresa** (`yhat_fi = mu_c` +
mediana del residuo de los *otros* empleados de su empresa — no es circular y **es lo que el producto
hace**, porque el cliente entrega su nómina); **curva de aprendizaje** (el ranking entre clases de
modelo se cruza con `n`, Perlich et al. 2003, y la debilidad de `CARGO` son celdas escasas);
**test-retest sobre la entrega y no sobre la etiqueta** (si la referencia se mueve tanto como el error,
el producto no sirve aunque el MAE sea bueno).

### Límite que hay que declarar en la tesis

No existe referencia canónica para *"bootstrap de dos niveles con train fijo y test clusterizado
remuestreado"*. Bates, Hastie & Tibshirani muestran precisamente que ese estimando no es lo que
estiman los métodos estándar. La construcción es defendible; **se describe explícitamente y no se
presenta como práctica establecida**. Escribirlo así es más fuerte que fingir una cita.

### Fuentes

**⚠️ Estado de verificación:** ninguna de las referencias de abajo se ha contrastado contra el
documento primario en esta sesión (403 de `bls.gov`, presupuesto de búsqueda web agotado). Proceden del
informe del juez. **Verificar antes de citar en el texto de la tesis**, con el mismo criterio ✅/▫ de
`estado_del_arte.md`.

- ▫ Zaoui, Denis & Hebiri (2020). *Regression with reject option and application to kNN*. NeurIPS 33.
  — la regla óptima de abstención en regresión umbraliza la varianza condicional.
- ▫ Gneiting & Raftery (2007). *Strictly proper scoring rules, prediction, and estimation*. JASA
  102(477), 359–378. — CRPS; §4.2 generaliza el error absoluto.
- ▫ Gneiting & Ranjan (2011). JBES 29(3), 411–422. — la identidad CRPS = 2·integral de pinball es de
  aquí, **no** de G&R 2007. *(Corrección de una cita que ya estábamos usando mal.)*
- ▫ Hersbach (2000). *Weather and Forecasting* 15(5), 559–570. — descomposición fiabilidad/resolución.
- ▫ Traub et al. (2024). NeurIPS, spotlight. — AURC viola monotonicidad; AUGRC.
- ▫ Shah, Bu, Lee, Das, Panda, Sattigeri & Wornell (2022). *Selective regression under fairness
  criteria*. ICML, PMLR 162, 19598–19615.
- ▫ Schenker & Gentleman (2001). *The American Statistician* 55(3), 182–186. — el solapamiento de IC
  no implica no-significancia.
- ▫ Nadeau & Bengio (2003). *Machine Learning* 52, 239–281. — subestimación de varianza.
- ▫ Bates, Hastie & Tibshirani (2024). JASA 119(546), 1434–1445. — sub-cobertura de los IC de CV.
- ▫ Cameron, Gelbach & Miller (2011). JBES 29(2), 238–249. — clustering en dos direcciones.
- ▫ Dietterich (1998). *Neural Computation* 10(7), 1895–1923. — diseños pareados.
- ▫ Hodges & Lehmann (1963). *Ann. Math. Statist.* 34(2), 598–611. — pseudomediana.
- ▫ Perlich, Provost & Simonoff (2003). JMLR 4, 211–255. — el ranking entre clases de modelo se cruza
  con el tamaño muestral.
- ▫ Brown & Medoff (1989). JPE 97(5), 1027–1059. — prima por tamaño de empresa. El propio juez advierte
  que **no verificó** ninguna fuente que la establezca *dentro de celda ocupacional*, que es el
  condicionamiento que el argumento necesita.
- ▫ Card, Cardoso, Heining & Kline (2018). JOLE 36(S1), S13–S70. — referencia para acotar cuánto de
  nuestro eta^2_empresa = 0,388 es sesgo de movilidad limitada.
- ▫ Rachel Justis (2008). InContext 9(7), Indiana Business Research Center. — regla de supresión de
  QCEW. **Fuente secundaria** describiendo práctica del BLS.
- ⚠️ BLS, OEWS `methods_24.pdf` / `methods_25.pdf` — **inaccesible desde este entorno**. Ver arriba.

### Enmienda 1 — `sigma2` por celda (2026-08-11, al implementar)

La versión original de D-011 estimaba `tau2` y `sigma2` **globales**. Al implementar la Tarea 5 se
midió que eso rompe la propia lógica de la decisión: con `sigma2` global, lo único que hace variar
`sd_pred` entre celdas es el conteo de donantes, así que **la anchura predictiva era el conteo de
donantes disfrazado** — justo lo que este D-011 quitaba.

Medido sobre un marco con dispersión real variando 12× entre celdas: `sd_pred` variaba 1,06× y su
correlación con el error real era **−0,384**. La perilla de confianza apuntaba al revés.

**Corrección:** `sigma2_c` por celda, con encogimiento empirical-Bayes sobre `log s²_c`. Sigue sin
parámetros libres —la varianza de muestreo de `log s²_c` es `2/df_c`, la varianza entre celdas sale
por momentos y el peso es `w_c = V/(V + 2/df_c)`—, y las celdas con pocos grados de libertad se van
al global solas. Con ello: rango de `sd_pred` 2,38×, correlación con el error real **+0,656**,
y `σ_c` estimado correlaciona 0,993 con el real.

`tau2` se queda global, y es un **límite declarado**: estimar la varianza entre empresas por celda
necesita muchas empresas, y en `CARGO` la celda típica tiene 3–5. Con ese `df` el encogimiento la
devolvería al global de todos modos.

Detalle relevante para la tesis: Zaoui et al. hablan de la varianza **condicional**. Implementarla
como una constante global es una lectura literal que vacía el criterio. Es un caso de *"la cita era
correcta y la implementación no"*, y encaja con la lección de abajo.

### Lección

Es la tercera vez que aparece el mismo patrón, y ahora con una variante nueva.

D-006 lo nombró: *elegir* la opción que favorece la hipótesis. D-010: *no verificar* una premisa
cómoda antes de construir encima. D-011 añade: **una corrección puede crear un defecto nuevo, y nadie
vuelve a mirar lo que la corrección tocó.** D-009 corrección 1 arregló la ponderación y desemparejó el
estimador de la métrica. D-009 corrección 3 prohibió seleccionar sobre el test, y dos secciones más
abajo la tarea 15 lo volvía a hacer.

La regla operativa que se deriva: **toda corrección aceptada se reaudita como si fuera una decisión
nueva** — porque lo es.

Y una segunda, del defecto 5: **una cita que no se puede abrir no sostiene nada.** El valor de citar
está en que el lector pueda verificarlo; si el autor no pudo, el lector tampoco.


---

## D-012 — No hace falta normalizar los cargos antes de agrupar

**Fecha:** 2026-08-11
**Pregunta:** ¿conviene normalizar las etiquetas de cargo con un LLM antes de clusterizar, o los
embeddings ya se encargan?

### La medición

`mediciones.md` §14, sobre 668 etiquetas reales con `text-multilingual-embedding-002`:

| Pares que se diferencian sólo en… | Similitud |
|---|---|
| el **rango** | **0,857** |
| el **área** | 0,764 |

Un gerente y un auxiliar del mismo área se parecen más que dos jefes de áreas distintas. Y el
tamaño del salto jerárquico casi no cambia la similitud: 0,861 con un escalón, 0,843 con cuatro.

### La decisión

**No se añade un normalizador de etiquetas.** El razonamiento tiene tres partes:

1. Los embeddings **sí** resuelven los sinónimos. Es justamente por eso que reconocen el área con
   cualquier rango.
2. Lo que no resuelven es el **nivel** — y un normalizador de sinónimos tampoco lo resolvería.
   Fusionar `VENDEDOR = ASESOR COMERCIAL` no dice quién manda. Sería trabajo, coste y una caja
   negra en la tesis para un problema que ya está resuelto.
3. El rival `solo_texto` **ya cumple el papel** de "CARGO normalizado": agrupa por significado, con
   los sinónimos fusionados, a cardinalidad igualada. Si el arquetipo le gana, limpiar las
   etiquetas no habría salvado a `CARGO`.

### Lo que sí queda establecido

El **modelo de nivel** (sub-proyecto 3) pasa de suposición a requisito con evidencia. Sus fuentes,
por orden de preferencia:

- **Léxico de rango**: 38,6% de las personas lo llevan escrito. Determinista, gratis, auditable.
- **Catálogo sectorial del MDT**: niveles A–E oficiales por contenido de puesto. Citable.
- **LLM de nivel**, sólo si hace falta para el resto. Aquí sí es defendible, y por una razón que no
  aplicaba al normalizador: *"¿está `JEFE` por encima de `AUXILIAR`?"* es conocimiento verificable,
  y **se puede validar contra el 38,6% donde la respuesta se conoce** antes de aplicarlo al resto.

### El control anti-sesgo

Si en algún momento se normalizan las etiquetas para el arquetipo, **`CARGO NORMALIZADO` entra como
rival**. Normalizar sube mucho la cobertura de `CARGO` —hoy su techo es 66,6% precisamente por tener
65.081 etiquetas dispersas—, y usar la versión limpia sólo de nuestro lado sería amarrarle una mano
al rival: el patrón de D-006, séptima aparición evitada.

### Alternativa descartada

**LLM que fusione etiquetas similares.** No es circular —no ve salarios—, pero es una
transformación irreproducible que el tribunal no puede auditar, y resuelve el problema equivocado.
El catálogo del MDT ofrece sinónimos **oficiales** entre cadenas distintas para el caso de que
hicieran falta.

---

## D-013 — La premisa central era falsa, y el eje que sí paga es el nivel

**Fecha:** 2026-08-12
**Origen:** una pregunta del director del proyecto — *"sacamos la composición pero en el EDA nunca
analizamos nada de eso para ver si efectivamente es relevante"*. No lo habíamos medido.
**Evidencia:** `mediciones.md` §15, scripts en `research/experimentos/e1_premisa/`.
**Estado:** decisión tomada. Reformula el alcance del proyecto y el enunciado de la tesis.

### El hueco

El EDA se hizo con la composición del pago disponible en el **2,7%** de las filas: no había con
qué analizarla. Se adoptó como hipótesis central **por eliminación** —se descartaron sector,
tamaño y antigüedad, y quedó ella— y como no estaba en los datos, era **infalsable en ese
momento**. Se recuperó al 80% (D-001, D-008), se midió que es un rasgo estable entre años y cuánto
de ella explica el empleador… y nunca se midió lo único que sostenía la tesis.

Es el patrón de D-010 a escala de proyecto: **una premisa que no se podía comprobar se volvió el
cimiento.**

### Lo medido

| | R² fuera de muestra | Reduce la sd |
|---|---|---|
| Placebo | −0,0002 | — |
| **Composición** | **+0,0042** | **0,21%** |
| Antigüedad | +0,0114 | 0,57% |
| **Rango jerárquico** (ω², dentro de área) | **+0,2462** | **13,2%** |

Y la descomposición del error de `CARGO`: τ = 0,2917 entre empresas, σ = 0,1423 intra empresa,
ruido irreducible sd 0,3253 frente a 0,3700 real → **techo de mejora por agrupar mejor: 12,1%**
(14,4% fuera de la zona pegada al SBU; ver la enmienda al final de esta decisión). Concentrado en el 34% de gente
que está en celdas de 1–2 empresas, donde el 44,6% del error es error de estimación.

### La decisión

**1. La composición sale del centro y se reporta como resultado negativo**, con su placebo y su
pre-registro. La afirmación se enuncia **estrecha**: *la composición no aporta información
intra-empresa e intra-etiqueta sobre el sueldo base.* No "la composición no importa" — sobre
compensación total es mecánicamente casi todo, y el diseño residualiza contra la empresa, que
determina entre el 39% y el 50% de la propia composición.

**2. El eje de nivel pasa a ser la pieza central.** ω² de 0,246 frente a 0,004, escalera monótona
de cinco escalones y un recorrido de 2,11× en salario entre el nivel 1 y el 5. Fuentes por orden:
léxico de rango (34,5% de las personas, gratis y auditable), catálogo MDT-2019-395 (niveles A–E
oficiales **por contenido de puesto**, no por sueldo) y un clasificador para el resto, **validado
contra el 34,5% donde la verdad se conoce**.

**3. El diagnóstico de `CARGO` cambia de naturaleza.** No está semánticamente roto: está
**estadísticamente delgado**. Mediana de 2 personas y 1 empresa por etiqueta, techo de cobertura
66,6%. Mejorar el benchmarking es un problema de **estimación en áreas pequeñas** —tomar fuerza
prestada de un vecindario ocupacional— y no de encontrar la variable que faltaba.

Eso ancla el estimador de D-011 en una literatura establecida en vez de dejarlo como invención
casera: Fay & Herriot (1979, *JASA*) y Rao & Molina, *Small Area Estimation* (Wiley, 2.ª ed. 2015).
▫ verificar paginación antes de citar.

**4. El enunciado de la tesis se reformula:**

> ¿Cuánto error de un benchmark salarial es reducible por elegir mejor el grupo de comparación, y
> qué precisión cuesta la taxonomía dura que vende la industria?

Con ese enunciado, cada objeción se invierte. La ganancia modesta deja de ser el resultado y pasa a
ser una medición dentro de un presupuesto que nosotros cuantificamos —3–5% sobre un techo de 12,1%
es entre el 25% y el 41% de todo lo disponible—. Y **un modelo simple pasa a ser una virtud
metodológica**: uno complicado confundiría el techo con la capacidad del método.

### Arquitectura descartada por medición

Pierden su objeto, y se reportan como capítulo de arquitectura descartada (tres páginas cuestan
1/50 de lo que cuesta construirla):

- Transformación ILR y todo el aparato CoDa sobre la composición.
- Compuerta de masa fija.
- IPW por falta sistemática de composición (D-003).
- Restricciones semi-supervisadas y RCA (D-007).
- Los **pesos de bloque**, y con ellos la razón de ser de la normalización MFA (D-009 corrección 2,
  Tarea 8 del plan). El módulo queda construido y probado; deja de ser central.

### Alternativas descartadas

| Opción | Por qué no |
|---|---|
| **Mantener la composición como eje** y esperar que el banco la rescate | 0,21% fuera de muestra con placebo en cero. No hay nada que rescatar, y construir para exprimirla cuesta semanas |
| **Declarar la tesis fracasada** | El instrumento, la descomposición del error y la ceguera jerárquica de los embeddings son contribuciones reales. Lo que falló es una hipótesis, y falló *medida* |
| **Normalizar cargos y agrupar por texto** (la alternativa simple) | Captura el eje de área y **pierde el de nivel**, que vale 13,2%. Medido: los embeddings dan 0,857 entre rangos frente a 0,764 entre áreas, así que fusionan puestos que difieren 2,11× en pago |
| **Mapear al catálogo MDT en vez de inducir** | No se descarta: **se incorpora**. El MDT pasa a ser fuente del eje de nivel y rival medido en la escalera. Era la objeción más peligrosa y se convierte en insumo |

### Consecuencia de proceso, y es la que más urge

Los tres hallazgos de esta entrada **se midieron en scripts temporales y no estaban en el
repositorio**. Un evaluador externo lo detectó grepeando los números: cero coincidencias. Estaba
documentada con detalle la arquitectura que se descartó y no lo que se va a defender.

Regla que se deriva: **un número que no se puede reproducir no se defiende.** Toda medición que
sostenga una afirmación de la tesis vive en `research/experimentos/` con su script y su salida
commiteados, el mismo día en que se mide.

### Lección

D-006 fue *elegir* la opción que favorece la hipótesis. D-010, *no verificar* una premisa cómoda.
D-011, *no reauditar* lo que una corrección tocó. D-013 añade la más incómoda de las cuatro:

**una hipótesis que no se puede falsar con los datos que hay no es un cimiento, es una apuesta** —
y trece semanas de arquitectura se construyeron sobre ella antes de que alguien preguntara si era
cierta.

El correctivo no es desconfiar más: es **ordenar el trabajo para que la premisa se mida primero**,
aunque medirla exija arreglar el pipeline antes. En este proyecto eso habría significado hacer D-001
y D-008 —recuperar la composición— y **medir §15.1 inmediatamente después**, antes de escribir una
línea de spec de clustering.

---

### Enmienda 2 (2026-09-22): el techo es 12,1%, no 10,9%

Al rastrear la cifra para la tesis se vio que `04` y `05` daban techos distintos —10,9% y 12,1%—
sobre **el mismo `train` de 847.046 filas**. No eran dos alcances: era una agregación inconsistente
en `04`.

```
04:  actual = Σ(sd_c · n_c) / Σn_c                  <- media de DESVIACIONES
     ideal  = √( Σ(irr_c · n_c) / Σn_c )            <- raíz de media de VARIANZAS

05:  actual = √( Σ((irr_c + est_c) · n_c) / Σn_c )
     ideal  = √( Σ( irr_c          · n_c) / Σn_c )
```

Por la desigualdad de Jensen, la media de desviaciones es menor que la raíz de la media de
varianzas. Por eso `04` obtiene `sd_actual = 0,3651` donde el cálculo consistente da `0,3700`, y el
techo encoge de 12,1% a 10,9%.

**Vale el 12,1%.** Se corrige en `mediciones.md` §15.2, en esta decisión y en la tesis. `04` se deja
como está, con su salida original: reescribir una corrida pasada para que cuadre con la conclusión
de hoy es exactamente lo que este registro existe para impedir.

Dos avisos sobre cómo citar el número:

- Es una reducción de **desviación**, no de varianza. En varianza el mismo resultado es 22,7%.
- Mide el techo de **engrosar** la celda, no el de **clasificar** mejor: la descomposición supone
  que la celda asignada es la correcta y solo está mal estimada.

## D-014 — La ocupación latente tampoco tiene material, y el eje que faltaba es el sector

**Fecha:** 2026-08-20
**Origen:** tras D-013, la pregunta abierta era **qué sustituye a la composición**. La dirección
propuesta era inferir la ocupación real desde varias señales ruidosas, porque el título del cargo
miente. Cinco mediciones para comprobarlo.
**Evidencia:** `research/experimentos/e1_premisa/` scripts `06`–`10`, con salidas commiteadas.
**Estado:** decisión tomada. Añade un eje al arquetipo y cierra una dirección de investigación.

### Lo medido

**La ocupación latente con varias vistas no tiene de dónde salir.**

| Vista, dentro de empresa y fuera de muestra | R² |
|---|---|
| Cargo (texto) | **+0,367** |
| Composición + antigüedad | +0,083 |
| Centro de costo, por caracteres | **−0,130** |
| Centro de costo, por significado (embeddings) | **−0,059** |
| **Todo menos el cargo** | **+0,059** |

El centro de costo es **peor que no predecir nada**, y no era un artefacto de TF-IDF: `09` se
escribió para rescatarlo leyéndolo por significado y sólo pasó de −0,123 a −0,059. Es vocabulario
privado de cada empresa —`CC-402`, `BODEGA 3`— que no transfiere entre empleadores.

La vista sin texto es **84% redundante** con el texto: sobre el cargo añade +0,015.

**Y el detector de etiquetas mal puestas falla su propio criterio.** `08` marcó el **88,5%** de la
gente como "desacuerdo" —eso no es un detector, es ruido— y en los marcados **gana la etiqueta
original** (0,1203 frente a 0,2727), que es exactamente lo contrario de lo que el test exigía.
Ejemplos: `DOCENTE → OBRERO AGRICOLA`, `DOCENTE → GERENTE GENERAL`.

**El sector sí parte las etiquetas anchas.**

| Sobre las 381 etiquetas de ≥300 personas | Reduce la varianza | Reduce la sd |
|---|---|---|
| etiqueta × **sector** | 24,7% | **13,2%** |
| etiqueta × sector × tamaño | 32,6% | 17,9% |
| etiqueta × **placebo** | 1,7% | 0,9% |

Aplica al **71,3%** de esa gente (205 de 298 etiquetas con más del 10% de su varianza recortada).

**Y hay un tercer modo de fallo de la etiqueta que no estábamos atacando.** El reparto del error:

| Grupo | Gente | % de la varianza |
|---|---|---|
| Genéricas (≥300 personas) | 50,4% | 30,4% |
| Medianas | 20,6% | 30,1% |
| Fragmentadas (<3 empresas) | 34,0% | 37,8% |

Sabíamos que la etiqueta **se fragmenta** y se arregla fusionando. También **se agrega de más**, y
eso se arregla al revés: **partiendo**.

### Las decisiones

**1. La ocupación latente con múltiples vistas se cierra como resultado negativo**, con su placebo
y sus scripts. Enunciado estrecho: *en estos datos no existe una segunda vista de la ocupación
independiente del título del cargo.* No "el título del cargo no miente" — miente, y `10` lo
cuantifica por otra vía; lo que no hay es **otra señal con la que corregirlo**.

**2. El sector entra como segundo eje del arquetipo**, no como control. Pasa de
`rol-familia × nivel` a `rol-familia × nivel × sector`, al menos dentro de las etiquetas anchas.
Y entra en la escalera de rivales: **`CARGO × sector`** es un baseline obvio, barato y honesto que
hay que batir.

**3. El anclaje a la empresa del cliente se separa como línea propia.** `06` mide −12,8% de MAE
—más que el 12,1% que da agrupar mejor— y sube a −14,6% en empresas con más de 100 compañeros con
referencia. Pero **no mejora la cobertura** y **responde otra pregunta**: equidad interna, no nivel
de mercado. Va a capítulo aparte o se descarta explícitamente; lo que no puede es quedar como nota
al pie, porque es el número más grande del expediente.

### El aviso de lectura que hay que arrastrar al texto

**`07` mide la composición en 2,4% y D-013 en 0,21%. No se contradicen:** `07` residualiza sólo
contra la empresa, `03` contra empresa **y** cargo. Esa diferencia *es* el hallazgo — la
composición parecía informativa porque hacía de proxy de la ocupación. Sin esa frase explícita, en
la tesis es una contradicción que se encuentra en cinco minutos.

### El error de estadístico, y por qué se registra

La versión original de `10` §2 calculaba el ω² del sector **agrupando las 381 etiquetas**. Eso mide
*"¿hay un efecto de sector igual para todas?"* y da **0,019**: casi nada. Su lectura impresa
concluía que el sector no parte las genéricas y que ése era *"el límite mayor de la tesis"*.

La pregunta útil es otra: *"cuando comparo un `VENDEDOR`, ¿ayuda saber su sector?"*. Eso es una
**interacción**, y medida así da **13,2% de sd**. Un `OBRERO` es otra cosa según el sector
(ω² 0,43) y un `TRABAJADOR AGRICOLA` es el mismo en todas partes (0,02): promediar ese efecto entre
etiquetas lo borra.

Se corrigió **en el script**, no sólo en la conversación, y se volvió a correr. Es la regla de
D-013: un número que no se puede reproducir no se defiende — y una lectura equivocada guardada
junto al número correcto es igual de peligrosa.

### Límite declarado

Lo de `10` es **descomposición de varianza, no R² fuera de muestra**. El placebo descuenta el
artefacto de grados de libertad —0,9% frente a 13,2%, así que la señal es real— pero **falta la
validación held-out** que sí tiene `03`. Antes de que el sector entre al spec como eje, hay que
medirlo fuera de muestra. Anotado en pendientes.

### Y una advertencia sobre sumar los números

`13,2%` del nivel, `13,2%` del sector y `12,1%` del techo **no se suman ni se comparan
directamente**: tienen denominadores distintos. El techo de `04` es sobre el error de predicción
fuera de muestra que queda **después** de `CARGO`; los otros dos son descomposiciones de varianza
de la señal, y parte de esa señal `CARGO` ya la captura (sus cadenas suelen llevar el rango dentro).
Reconciliarlos en una sola contabilidad es tarea pendiente, y hacerlo mal sería el error más caro
que queda por cometer.

### Lección

D-013 dijo que una hipótesis infalsable no es un cimiento. D-014 añade el corolario barato:
**la segunda hipótesis también se mide antes de construir**, y esta vez se hizo — cinco scripts y
cuatro días, frente a las trece semanas que costó la primera.

Lo que no cambió es el otro patrón: los cinco scripts se midieron y **no estaban versionados**, seis
días después de escribir la regla que lo prohíbe. La regla no falla por desconocimiento, falla por
no estar en el flujo. Corregido: los scripts, sus salidas y el README van en el mismo commit.

---

## D-015 — Las grafías del mismo puesto se juntan, y el enlace decide el resultado

**Fecha:** 2026-09-04
**Origen:** `ANALISTA DE RIESGO CREDITICIO` competía en la base contra seis grafías del mismo
puesto, cada una con una o dos empresas, y se contestaba por analogía pagando castigo de distancia
semántica contra sus propias hermanas.
**Evidencia:** `research/experimentos/e2_nivel/` scripts `05`–`07`, con salidas commiteadas.
**Estado:** decisión tomada y montada en `producto/base_referencia.py`.

### Lo medido

**Primera medición: fusionar EMPEORA.**

| Umbral | Efecto | IC 95% | Cobertura directa |
|---|---|---|---|
| >0,99 | −0,0007 | [−0,0038, +0,0024] | 58,6% |
| >0,97 | −0,0034 | [−0,0088, +0,0001] | 62,3% |
| **>0,95** | **+0,0154** | [+0,0095, +0,0206] | 67,4% |

Con eso bastaba para descartar la idea. **Y habría sido el resultado equivocado.**

**La inspección cambió el sujeto de la frase.** `06` miró los grupos concretos y el problema no era
fusionar sino **cómo**: union-find encadena `A~B~C~D` y produjo un grupo de **1.758 títulos** con
`ASISTENTE CONTABLE` y `AUXILIAR DE LIMPIEZA` dentro. El candado de escalón no lo frenaba porque
sólo actuaba con **ambos** títulos con palabra de rango, y `GESTOR DE TALENTO HUMANO` —sin nivel
léxico— hacía de puente entre `JEFE`(4) y `GERENTE`(5).

**Con enlace completo el efecto se da vuelta.** Un grupo vale sólo si **todos** sus pares superan
el umbral:

| | Efecto | IC 95% | Grupo mayor | Cobertura directa |
|---|---|---|---|---|
| simple >0,95 | **+0,0154** | [+0,0095, +0,0206] | 1.758 | 67,4% |
| **completo >0,95** | **−0,0030** | [−0,0075, −0,0000] | **27** | **64,1%** |
| completo >0,97 | −0,0017 | [−0,0063, +0,0016] | 22 | 59,9% |
| completo >0,93 | −0,0005 | [−0,0056, +0,0052] | 33 | 66,1% |

Sólo **18 uniones de 15.870** las rechazó el candado de escalón: el daño nunca vino de pares malos
sino de la cadena que los conectaba.

### Las decisiones

**1. Fusión por enlace completo a 0,95.** A 0,93 la cobertura sube pero el efecto vuelve a cero.

**2. La ganancia se reporta como COBERTURA, no como precisión.** El −0,0030 roza el cero y así hay
que leerlo: neutro, quizá un pelo mejor. Lo que se compra son **6,4 puntos** de gente contestada
con datos de su propio puesto en vez de por analogía.

**3. Al consultar se descarta el GRUPO propio entero, no sólo la etiqueta exacta.** Si la celda no
llega a `MIN_EMPRESAS`, sus hermanas comparten estadísticos y entrarían como "vecinas a distancia
cero", colando por la puerta de atrás la celda que el suelo de confidencialidad acaba de rechazar.

### Lo que esto enseña sobre el método

`05` solo, sin `06`, habría cerrado el tema con *"fusionar empeora, descartado"*. Ese resultado era
publicable, reproducible y **falso en su conclusión**: lo malo era el algoritmo, no la idea. La
regla que sale de aquí es que **un resultado negativo sobre una implementación no es un resultado
negativo sobre la hipótesis** — hay que mirar los objetos concretos antes de cerrar.

---

## D-016 — La banda habla de EMPRESAS, con `tau` por celda y cuantiles empíricos

**Fecha:** 2026-09-04
**Origen:** una objeción en voz alta durante la revisión: *"`tau` y `sigma` representan la variación
de un cargo específico, ¿y usan el mismo par para los 65.081?"*. La respuesta era que sí.
**Evidencia:** `research/experimentos/e3_varianza/` scripts `01`–`05`, con salidas commiteadas.
**Estado:** decisión tomada y montada. **Es el defecto más grave encontrado en el producto.**

### Lo medido

**`tau` varía 8,3× entre cargos, y no es ruido.** Sobre las 704 celdas con 20+ empresas (45,2% de
la gente):

```
tau por celda   p05=0,080  p50=0,322  p95=0,663          global = 0,2917
```

Test-retest partiendo las empresas de cada cargo en dos mitades al azar: las dos mitades
**correlacionan a 0,78** (Spearman 0,77). Corregida la atenuación, la fiabilidad de `tau_c` es
**~0,88**. El patrón sigue al escalón jerárquico y tiene causa mecánica —el salario mínimo comprime
desde abajo—: `AUXILIAR DE LIMPIEZA` 0,073 contra `GERENTE GENERAL` 0,951.

**Esto añade algo a D-013:** el nivel no sólo mueve la media 2,37× — **escala la varianza 13×**.

**La banda que se entregaba no contenía al 50%. Contenía entre el 18% y el 98%.**

| Cargo | Debería contener | Contenía |
|---|---|---|
| `GERENTE GENERAL` | 50% | **18,3%** |
| `CONTADOR` | 50% | 34,7% |
| `AUXILIAR DE LIMPIEZA` | 50% | 92,4% |
| `TRABAJADOR AGRICOLA` | 50% | **98,0%** |

En dólares: el mercado de gerentes generales va de $500 (p05) a $13.712 (p95) y se entregaba una
banda de **$2.436 – $3.775**. De 20 personas, 4 caían dentro.

**Son dos defectos, no uno.** `tau_c` arregla la deformación **entre cargos** (recorrido entre
quintiles 54,7 → 23,4 puntos, CRPS −8,6%) y deja intacto un sesgo global: todo sale demasiado
ancho. La causa es que el centro se estima de forma **robusta** (mediana de votos) y la dispersión
**no** (raíz de una varianza). Y como la forma cambia por cargo, recalibrar el multiplicador
`0,6745` no puede arreglarlo: un solo número no describe a la vez un pico y una cola larga.

```
AUXILIAR DE LIMPIEZA   p25=$475  p50=$475  p75=$485      <- un pico
GERENTE GENERAL        p05=$500          p95=$13.712     <- una cola
```

### La decisión

**1. La banda dice *"la mitad de las EMPRESAS paga entre X e Y"***, no de las personas. Es lo
coherente con el centro, que ya era la mediana de votos por empresa, y es la pregunta del cliente
que decide su política salarial.

**2. De ahí sale que `sigma` NO entra en la banda.** El nivel de una empresa es `mu + u_f`, con
varianza `tau_c²`; `sigma²` separa a dos personas de la misma nómina y no mueve el nivel de la
empresa.

**3. `tau` y `sigma` por celda**, con el mismo empirical Bayes sin parámetros libres que ya usaba
`sigma`. Y entran también en los **pesos** `w_f`: sin eso, `W` sale idéntico para dos cargos con
dispersión 13× distinta.

**4. Cuantiles empíricos donde hay 10+ empresas.** Umbral 10 y no 5 porque F≥5 gana el pinball por
un 0,7% que casi seguro es ruido, y F≥10 gana las dos coberturas y está más lejos del dato crudo.

Medido sobre votos de empresa apartados: deformación entre quintiles **50,5 → 13,5 → 4,3 puntos**,
pinball medio **0,1290 → 0,1207**.

### El número que este registro daba mal

Medida contra **personas**, la cobertura global salía 68,7%; contra **empresas**, 53,5%. Buena parte
de aquella descalibración aparente era el desajuste de definición, no un defecto del método. El
problema de fondo no cambia: el 53,5% es la media de errores que se cancelan (Q1 81,3%, Q5 30,8%).

### Límite declarado

**La cobertura deja de ser métrica válida con masa puntual.** `TRABAJADOR AGRICOLA` tiene cuartiles
reales $470–$472: la banda los reproduce **exactos** y aun así cubre el 90,3%, porque más del 90%
de esa gente cobra el mismo número. Ninguna banda de ancho positivo contiene exactamente el 50%.
En esos cargos manda el pinball.

---

## D-017 — La confianza mide lo bien que se conoce el CENTRO, no el ancho del mercado

**Fecha:** 2026-09-04
**Origen:** con la banda ya corregida (D-016), el **100,00%** de las celdas directas seguía
saliendo ALTA. La etiqueta no distinguía nada.
**Evidencia:** `research/experimentos/e3_varianza/06`, con salida commiteada.
**Estado:** decisión tomada y montada.

### El diagnóstico, que es algebraico y no empírico

La etiqueta comparaba el ancho de la banda contra el suelo del cargo. Pero en la rama directa el
suelo **es** casi todo el ancho:

```
CONTADOR:   var = tau²      + sigma²    + 1/W
                  0,085026    0,020229    0,000122
                    80,7%       19,2%        0,1%
```

El 99,9% del ancho son dos números iguales para los 65.081 cargos. Desarrollando a primer orden,
`veces ~ 1 + 0,557·r` con `r = (1/W)/(tau²+sigma²)`, y salir de ALTA exige `W < 21,1`. Como cada
empresa aporta al menos 9,50, hacen falta **menos de 2,2 empresas** — y `MIN_EMPRESAS` es 3.

**Con 3 empresas o más era aritméticamente imposible salir de ALTA.** Y medido sobre 5.168 celdas
da exactamente eso: **100,00%** en ALTA, con la peor de todas en 1,175 veces el suelo contra un
corte de 1,25. No era una curiosidad empírica: estaba forzado.

### Lo medido

La alternativa es la varianza de **nuestra** estimación, que es todo lo que no es dispersión del
mercado:

```
directo       var_centro = 1/W
por analogía  var_centro = Σ(peso²/W) + Σ(peso·dist) + penal_nivel
```

Validado estimando la referencia sobre **dos mitades disjuntas de empresas** y midiendo cuánto se
separan:

| | Spearman con el movimiento real | ALTA | MEDIA | BAJA |
|---|---|---|---|---|
| hoy (ancho/suelo) | +0,367 | **100,0%** | 0,0% | 0,0% |
| **nueva (1/W)** | **+0,576** | 17,6% | 45,5% | 37,0% |
| …y cuánto se mueven | | **3,8%** | **13,3%** | **31,8%** |

La vieja mete el 100% en ALTA. La nueva separa **8 a 1**.

### Las decisiones

**1. La etiqueta sale de `var_centro`.** El ancho del mercado ya lo comunica la banda; lo que la
etiqueta añade es si el número del medio es fiable.

**2. Los cortes pasan a ser en dólares** (ALTA ≤5%, MEDIA ≤15%) y no en veces-el-suelo, porque la
pregunta ya tiene unidades interpretables: las decisiones salariales se mueven en escalones de ~5%.

**3. Se quita la condición de que ALTA exija respuesta directa.** `var_centro` ya incluye el
castigo de distancia semántica; exigirlo además lo contaría dos veces. Que la respuesta venga por
analogía se dice en `base`.

### Límite medido y declarado

**`1/W` se queda CORTO**, de un 15% a un 40% según el tramo (obs/pred va de 0,96 en el primer decil
a **1,42** en el último). Ordena bien pero es optimista. La causa probable es que el modelo supone
la celda homogénea y `CONTADOR` mezcla empresas grandes y pequeñas. **No se corrige con un factor
porque ese factor no está medido.**

### La corrección de lectura que hay que arrastrar

En la revisión se dijo que *"`SCRUM MASTER` con 14 empresas salía igual de ALTA que `CONTADOR` con
823, y eso se corrigió"*. **No es exacto.** Se corrigió el criterio —de contar empresas a medir el
ancho— pero el resultado para ese caso era el mismo, y ahora se sabe que lo era para casi todos. La
etiqueta sólo discriminaba en la rama por analogía. La corrección de verdad es ésta, D-017.

---

## D-018 — El tamaño de empresa no estrecha la banda, pero corrige un sesgo grande en el centro

**Fecha:** 2026-09-04
**Origen:** viendo la banda de ±95% de `GERENTE GENERAL`, la pregunta natural: si sabemos el
tamaño, el sector y la provincia de la empresa, ¿no conviene condicionar por ahí?
**Evidencia:** `research/experimentos/e3_varianza/` scripts `07`–`09`, con salidas commiteadas.
**Estado:** medido. **Decidido que sí aplica, pero NO montado**: exige dos decisiones de producto.

### Lo medido, en tres pasos

**1. Segmentar TODO pierde.** Diseño jerárquico (celda fina cuando aguanta, si no el cargo):

| Definición | cob50 | pinball | ancho | incert |
|---|---|---|---|---|
| cargo (hoy) | 50,3% | **0,1255** | 28,2% | 10,4% |
| cargo × tamaño | 49,9% | 0,1284 | 27,5% | 12,7% |
| cargo × sector | 49,8% | 0,1289 | 27,3% | 13,2% |
| cargo × provincia | 49,8% | 0,1288 | 27,4% | 12,6% |

La banda se estrecha 0,7 puntos y la incertidumbre del centro sube 2,3. **El tamaño casi no explica
el ancho.**

**2. Segmentar SELECTIVAMENTE tampoco.** Doble partición anidada de empresas —`tr_a` ajusta, `tr_b`
decide cargo a cargo por pinball, `ts` puntúa una sola vez—:

| Variante | Cargos | pinball |
|---|---|---|
| cargo (hoy) | 0 | 0,1255 |
| selectivo | 93 | 0,1253 |
| **PLACEBO (al azar)** | **118** | 0,1258 |

−0,0002 contra hoy. Y el aviso más duro: **el placebo eligió más cargos (118) que la selección real
(93)**. A nivel de cargo individual la decisión está dominada por ruido, y **sin el placebo esto se
habría reportado como una mejora.**

**3. Pero la pregunta era otra.** El pinball evalúa la **banda**, que mezcla centro y anchura. Lo
que falla es el **centro**:

| Sesgo de la referencia de hoy | PEQUEÑA | MEDIANA | GRANDE | recorrido |
|---|---|---|---|---|
| nivel 1 | +6,9% | +8,3% | +6,1% | 10,1% |
| nivel 4 | −16,4% | −8,4% | +9,6% | 26,1% |
| **nivel 5** | **−32,8%** | −16,6% | **+22,2%** | **55,0%** |

Por cargo es peor: `GERENTE GENERAL` va de **−56,0%** en pequeñas a **+81,9%** en grandes. A una
empresa pequeña se le dice que su gerente cobra un 56% por debajo del mercado; a una grande, que el
suyo cobra un 82% por encima. **Las dos afirmaciones son falsas.**

**Y segmentar lo arregla:**

| | HOY | SEGMENTADA |
|---|---|---|
| nivel 5 | −32,8% / −16,6% / +22,2% (55,0 pts) | −0,6% / −5,8% / +9,0% (**14,8 pts**) |
| `GERENTE GENERAL` | −56,0% / −15,8% / +81,9% | −12,1% / +6,9% / +17,9% |
| `CONTADOR` | −23,8% / −3,5% / +20,5% | +0,2% / +4,6% / +2,2% |
| `CHOFER` | +11,0% / +5,7% / +2,7% | +13,4% / +8,3% / +0,9% |

`CHOFER` no tenía nada que arreglar y no se estropea.

### Las decisiones

**1. El tamaño NO entra para estrechar la banda.** Medido dos veces, con placebo. Cerrado.

**2. El tamaño SÍ entra para corregir el centro de los cargos altos**, por **lista explícita** de
cargos. La selección automática está descartada: elige sobre ruido.

**3. No se monta hasta resolver dos cosas de producto:** pedirle el segmento al cliente, y fijar
qué cargos entran.

### El número que este registro daba mal

Se dijo que *"el 56% de los datos son empresas GRANDES"*. Eso es **por filas**. Por **empresas**
—que es la unidad que vota— las grandes son el **20,9%** y una de cada cinco es pequeña o micro. El
sesgo no viene de que dominen el conteo: viene de que la mediana de un mercado tan asimétrico no
representa a nadie en los extremos.

### Límite declarado

**El 26–34% de las empresas no tiene `segmento` asignado**, y ese grupo paga distinto del resto. Si
se monta la segmentación, ese tercio es el problema, no las bandas.

---

## D-019 — El suelo cuenta empresas y también tiene que contar personas

**Fecha:** 2026-09-04
**Origen:** al repasar qué decisiones estaban aplicadas en el producto se vio que
`evaluacion/referencia.py` define `SUELO_SHARE = 0,80` —la regla de dominancia del QCEW,
D-011— y que `producto/base_referencia.py` no la aplicaba. Parecía un hueco de
confidencialidad.
**Evidencia:** `research/experimentos/e3_varianza/` scripts `10` y `11`, con salidas
commiteadas.
**Estado:** decisión tomada y montada.

### Lo primero que se midió resultó no ser el problema

**La regla de dominancia se cumple sola.** Sobre las 5.168 celdas directas:

| | celdas dominadas | peso de la empresa mayor |
|---|---|---|
| por PERSONAS | 198 (3,8%) | — |
| **por PESO en la mediana** | **0 (0,0%)** | p50 20,3% · p95 35,4% · **máx 67,7%** |

Nunca llega al 80%, y no por suerte: `w_f = 1/(tau_c² + sigma_c²/n_f)` está acotado por
`1/tau_c²`, así que por muchos empleados que tenga, una empresa no puede dominar la mediana
ponderada. La regla del QCEW existe porque ellos agregan por cabezas; **el estimador
inverso-varianza la satisface por construcción.** Se registra como propiedad verificada, no
como pendiente — y **no se añade la regla**, que habría sido código muerto.

### El hueco real es otro

`MIN_EMPRESAS = 3` protege contra que **una empresa** se reconozca en el número. No dice
nada de **personas**: tres empresas con una persona cada una son tres personas, y la
mediana de sus tres votos **es el sueldo de una de ellas**.

| Personas en la celda | Celdas directas | % |
|---|---|---|
| **3–4** | **297** | **5,7%** |
| 5–9 | 1.278 | 24,7% |
| 10–19 | 1.169 | 22,6% |
| 20+ | 2.424 | 46,9% |

### El umbral sale de un barrido, no de la costumbre

| Suelo | Cobertura directa | Pierde | MAE global | Personas protegidas | Coste por afectado |
|---|---|---|---|---|---|
| 3 | 62,4% | 0,0% | 0,2372 | 0 | *no-op* |
| 5 | 62,2% | 0,2% | 0,2372 | 1.781 | +0,0139 |
| **10** | **61,0%** | **1,4%** | **0,2372** | **17.669** | **+0,0049** |
| 15 | 59,6% | 2,8% | 0,2375 | 32.022 | +0,0138 |
| 20 | 58,3% | 4,1% | 0,2382 | 46.983 | +0,0264 |
| 30 | 56,9% | 5,5% | 0,2386 | 71.694 | +0,0258 |

**Un suelo de 3 sería inútil**: con 3 empresas ya hay 3 personas por construcción.

### La decisión

**`MIN_PERSONAS = 10`**, junto al suelo de empresas. Tres razones convergen:

1. **El MAE global no se mueve** (0,2372, idéntico a no tener suelo). A partir de 15 sube.
2. **Es donde menos pierde la gente afectada**: +0,0049 contra +0,0139 en 5 y +0,0264 en
   20. Las celdas de 5–9 personas son justo las que la analogía contesta casi igual de bien.
3. **No bloquea ni una banda empírica.** Las 3.391 celdas que publican cuartiles reales
   —las más expuestas— sobreviven intactas hasta el umbral 15.

**No es pérdida de cobertura de respuesta**: se sigue contestando siempre. Lo que cambia es
que esas 17.669 personas se contestan por analogía en vez de publicar una mediana que es el
sueldo de alguien.

### Lo que enseñó sobre el método

El defecto que motivó la revisión —la regla de dominancia ausente— **no existía**. Medirlo
en vez de aplicarlo directamente ahorró código muerto y, de paso, destapó el hueco de
verdad, que estaba al lado y era invisible desde la misma pregunta. Es el mismo patrón de
D-015: la primera lectura de un problema suele ser la equivocada.

### Un test que el cambio dejó obsoleto, y por qué importa

`test_la_confianza_sale_del_intervalo_y_no_del_conteo` afirmaba *"menos datos, intervalo más
ancho"*. Con D-016 y D-017 eso es **falso**: el ancho de la banda mide el mercado —que puede
ser estrecho con pocos datos— y lo que crece al tener menos empresas es `incert_centro`. El
test se reescribió sobre la magnitud correcta en vez de relajarse.

---

## D-020 — Dos bandas, y una lectura que mira la banda en vez de un porcentaje fijo

**Fecha:** 2026-09-08
**Origen:** una revisión de la lógica de cálculo buscando *"la misma forma del error de `tau`
y `sigma`"* — un parámetro que varía tratado como constante, algo que se calcula y se tira,
una cantidad correcta usada para otra pregunta. Aparecieron dos.
**Evidencia:** verificación sobre la nómina de demo y sobre la base completa (65.081 celdas),
con los tests que lo fijan.
**Estado:** decisión tomada y montada.

### A. La lectura de mercado usaba cortes fijos

`comparacion.py` clasificaba con ±5% y ±15%, iguales para todos los cargos. **Es
literalmente el error de `tau` global:** un umbral que tiene que escalar con la dispersión
del puesto, escrito como constante.

Medido sobre la nómina de demo, **cuatro de los diez cargos marcados "muy por encima"
estaban DENTRO de su propia banda**:

| Cargo | `vs_mercado` | Lectura vieja | Banda | ¿Dentro? |
|---|---|---|---|---|
| `GERENTE GENERAL` | +15,4% | muy por encima | ±95,0% | **sí** |
| `CONTADOR` | +15,4% | muy por encima | ±37,2% | **sí** |
| `JEFE DE BODEGA` | +15,2% | muy por encima | ±30,6% | **sí** |
| `VENDEDOR` | +15,7% | muy por encima | ±28,9% | **sí** |
| `AUXILIAR DE LIMPIEZA` | +15,4% | muy por encima | ±2,1% | no |
| `TRABAJADOR AGRICOLA` | +15,5% | muy por encima | ±0,2% | no |

Lo incómodo: **la banda ya estaba bien calculada desde D-016 y la etiqueta no la miraba.**
Es el mismo patrón de "se calcula y se tira" que tenía `sigma_c` antes de D-016.

**La decisión:** la lectura sale de dónde cae el sueldo dentro de la banda de su cargo.

```
< p10          muy por debajo
p10 - p25      por debajo
p25 - p75      EN LINEA        <- el 50% central del mercado
p75 - p90      por encima
> p90          muy por encima
```

*"En línea"* pasa a significar **dentro del 50% central del mercado**, que es una frase que
el cliente puede comprobar, en vez de *"a menos del 5% de un número"*.

Efecto en el resumen que lee un gerente, sobre la misma nómina —construida a +15% uniforme:

```
antes:  Puestos MUY POR ENCIMA (8)
ahora:  Puestos MUY POR ENCIMA (1)   <- solo TRABAJADOR AGRICOLA
```

**Ocho falsas alarmas se convierten en una real.** Para casi todos los cargos, +15% es un
sueldo alto pero normal; para uno cuyo mercado entero va de $470 a $472, no lo es.

### B. El detalle comparaba una PERSONA contra una banda de EMPRESAS

D-016 decidió que la banda dice *"la mitad de las **empresas** paga entre X e Y"*. Correcto
para la hoja `por_puesto`. Pero `detalle` tiene **una fila por persona** y le ponía al lado
esa misma banda.

Son poblaciones distintas: la de personas incluye además la dispersión **dentro** de cada
nómina.

```
banda de empresas = raiz(tau_c^2          + 1/W)
banda de personas = raiz(tau_c^2 + sigma_c^2 + 1/W)
```

**La decisión:** se calculan y se guardan las dos, por cuantiles empíricos donde hay 10+
empresas y por modelo debajo. `detalle` lleva la de personas; `por_puesto` la de empresas y
compara contra la **mediana** de la empresa, que es su voto — la misma unidad con la que se
construyó.

Verificado sobre las 5.377 celdas con las dos bandas empíricas:

| Personas por empresa | Celdas | `ancho_personas / ancho_empresas` |
|---|---|---|
| ~1 | 129 | **1,00×** |
| 1,5–4 | 3.388 | 1,09× |
| 4–20 | 1.626 | 1,14× |
| 20+ | 234 | **1,19×** |

El cociente **crece monótonamente** con la gente por empresa, que es exactamente lo que
predice el modelo: cuanta más gente tiene una empresa, más suaviza su mediana la dispersión
interna. Y donde hay una persona por empresa las dos bandas coinciden, porque el voto de la
empresa *es* el sueldo de una persona.

### Lo que enseña sobre el método

Los dos defectos son de la **misma familia** que `tau`/`sigma`, y ninguno se veía desde una
métrica agregada: el pinball no los detecta porque los dos están en la capa de presentación,
después del estimador. Se encontraron leyendo el código con una pregunta concreta —*"¿dónde
más hay una constante que debería variar?"*— y no midiendo.

Queda una tercera de la misma forma **sin comprobar**: `lambda` es un solo escalar para los
65.081 cargos. `tau` se comprobó y varía 8,3×; `sigma` se comprobó y varía; `lambda` no se
ha mirado. Anotado en pendientes.

---

## D-021 — `lambda` por escalón, y la lección de haber medido con la métrica equivocada

**Fecha:** 2026-09-08
**Origen:** la revisión de la lógica de cálculo (D-020) dejó una tercera sospecha de la
misma forma: `lambda` era un solo escalar para los 65.081 cargos, mientras `tau` y `sigma`
ya se habían comprobado y varían.
**Evidencia:** `research/experimentos/e3_varianza/` scripts `12`, `13` y `14`.
**Estado:** decisión tomada y montada.

### Qué es `lambda`, para que el registro se lea solo

El embedding mide parecido entre títulos como una similitud coseno, que está en unidades de
texto. Lo que hace falta está en unidades de dinero, y `lambda` es el **tipo de cambio**:
cuánta diferencia de pago hay que esperar por unidad de distancia semántica.

```
var_j = 1/W_j + lambda·(1 − sim_j)          peso_j ∝ 1/var_j
```

Hace dos cosas: decide **a quién se escucha** y fija **el ancho del intervalo**.

### Lo medido

**Varía 18× y es real** (`12`). Test-retest partiendo las empresas en dos mitades:
**Pearson +0,563, Spearman +0,627** — entre el de `tau` (0,780) y el de `sigma` (0,484).

```
nivel 1   0,368      nivel 3   2,212      nivel 5   6,505      global   1,938
nivel 2   1,038      nivel 4   3,340
```

Misma causa mecánica que `tau`: abajo el salario mínimo comprime y dos cargos parecidos
pagan casi igual; arriba, `GERENTE DE FINANZAS` y `GERENTE DE OPERACIONES` están cerca en el
texto y lejos en el sueldo.

**Y usarlo por escalón mejora** (`14`), con el criterio declarado antes de correr:

| | pinball | MAE | cob 50% | ancho |
|---|---|---|---|---|
| global | 0,1424 | 0,3061 | 76,0% | 55,6% |
| **por escalón** | **0,1338** | 0,3047 | 72,8% | 49,4% |
| PLACEBO | 0,1427 | 0,3061 | 76,3% | 56,0% |

```
por escalón − global = −0,00856   IC 95% [−0,01083, −0,00589]   MEJORA
PLACEBO     − global = +0,00032   IC 95% [+0,00024, +0,00041]   no lo reproduce
```

**El placebo es la parte convincente.** Barajando las etiquetas de escalón entre cargos y
re-estimando, los cinco `lambda` **colapsan al global**: 1,95 / 1,92 / 1,93 / 2,05 / 2,04.
La señal vive en el escalón, no en tener cinco grupos en vez de uno.

### La lección de método, que vale más que el resultado

`13` midió esto mismo con **MAE y cobertura por separado** y dio **−0,0015 (0,5%)**. Con
pinball da **−0,0086 (6,0%)**: un factor de **12**.

La razón es simple una vez vista: **`lambda` actúa sobre todo en el ANCHO, y el MAE no ve el
ancho.** Estaba midiendo con un instrumento ciego a la mitad del efecto, y con ese número
esto se habría descartado por marginal.

Reportar MAE y cobertura por separado tiene además un problema de método: el MAE premia el
centro y la cobertura se puede ensanchar a voluntad, así que quedan dos números y libertad
para elegir cuál pesa **después** de verlos. Una regla de puntuación **propia** los integra
en un número que empeora si se miente en cualquiera de los dos. **Es la regla que el propio
proyecto ya usaba en D-016 y D-017, y aquí me la salté.**

De aquí salen dos reglas para lo que queda:

1. **Lo que se entrega son cuantiles, así que se puntúa con pinball.** El MAE sólo como
   secundaria.
2. **El criterio se declara antes de correr**, y el placebo no es opcional cuando se llevan
   catorce experimentos en la misma familia.

### La decisión

**`lambda` por escalón léxico**, estimado con la misma regresión por el origen restringida a
los pares de cada nivel. Si el título no declara rango se usa la media de los `lambda` de
sus vecinos que sí lo declaran — sin pesos, porque los pesos dependen de `lambda` y usarlos
sería circular.

Por escalón y no por celda, a diferencia de `tau_c` y `sigma_c`: el patrón es monótono en el
nivel, así que agrupar casi no pierde y gana mucha estabilidad — `lambda_c` por celda sale
de ~25 pares y el **15,8%** de esas estimaciones son negativas por ruido.

### Coste conocido, no resuelto

La ganancia entera viene del **nivel 1** (−0,0244, y es el 70% de la gente contestada por
analogía). Los niveles **4 y 5 empeoran**: +0,0027 y +0,0146, con la cobertura del nivel 5
alejándose del objetivo (51,9% → 68,4%).

Sospecha concreta y comprobable: `lambda` se estima de diferencias **al cuadrado** y la
distribución de pago del nivel 5 tiene cola larguísima, así que unos pocos pares extremos
pueden estar inflando `lambda_5`. Un estimador robusto —diferencias absolutas o ajuste
recortado— daría un `lambda_5` menor. Anotado en pendientes.

**No se revierte para recuperar la calibración del nivel 5.** Si dos errores se estaban
cancelando, arreglar uno y dejar el otro visible es preferible a mantener los dos
escondidos: un modelo bien especificado y visiblemente imperfecto se defiende, uno
accidentalmente calibrado se cae en cuanto alguien pregunta por qué.

---

## D-022 — El sector no entra, ni para la banda ni para el centro. Y se retira lo de D-014

**Fecha:** 2026-09-08
**Origen:** al inventariar qué variables usa el modelo y cuáles no, apareció que **D-014
había decidido que el sector entra como segundo eje del arquetipo** y que esa decisión
nunca se implementó ni se retiró. Y que sólo se había medido para la banda.
**Evidencia:** `research/experimentos/e3_varianza/07` (banda) y `16` (centro).
**Estado:** decisión tomada. **Cierra la que D-014 dejó abierta.**

### Lo que D-014 decidió, y con qué condición

> *«El sector entra como segundo eje del arquetipo, no como control. Pasa de
> `rol-familia × nivel` a `rol-familia × nivel × sector`.»*

Con 24,7% de reducción de varianza dentro de las etiquetas anchas y placebo de 1,7%. Pero
el propio D-014 puso el freno:

> *«Lo de `10` es descomposición de varianza, no R² fuera de muestra. Antes de que el
> sector entre al spec como eje, hay que medirlo fuera de muestra.»*

Esa medición se hizo en dos partes, y las dos dicen que no.

### Para la BANDA: pierde (`07`)

| Definición | pinball |
|---|---|
| cargo (hoy) | **0,1255** |
| cargo × sector | 0,1289 |
| cargo × tamaño | 0,1284 |
| cargo × provincia | 0,1288 |

### Para el CENTRO: indistinguible del azar (`16`)

Con el tamaño la conclusión fue justo la contraria —pierde para la banda, arregla el
centro (D-018)—, así que hacía falta la segunda medición. Misma forma: desplazamiento
`(cargo, sector)` con 10+ empresas, 1.065 correcciones sobre 469 cargos, actuando en el
25,5% de los votos apartados.

```
con sector − sin sector = +0,00232   IC 95% [+0,00165, +0,00302]   EMPEORA
PLACEBO    − sin sector = +0,00241   IC 95% [+0,00187, +0,00288]   EMPEORA
```

**El placebo es lo que lo cierra.** Barajar el sector entre empresas hace exactamente el
mismo daño que aplicarlo bien: +0,00241 contra +0,00232. No hay señal en la asignación —
todo el perjuicio viene de meter ruido en la referencia.

### Por qué el sector no sesga el centro y el tamaño sí

| | sesgo de la referencia |
|---|---|
| **tamaño** | PEQUEÑA −34,2% · MEDIANA −15,0% · GRANDE +9,0% |
| **sector** | todos entre +2,6% y +17,3%, y casi todos cerca de +5% |

Los del tamaño tienen **signos opuestos y estructura monótona**. Los del sector son todos
del mismo signo: eso no es un efecto de sector, es un **desplazamiento global** de la
referencia sobre esa población. El «recorrido de 36,4%» lo produce el sector `P` con 33
votos, que es ruido.

Y por escalón tampoco hay subconjunto que rescatar: el nivel 1 mejoraría algo y los
niveles 3, 4 y 5 empeoran.

### Las decisiones

**1. El sector NO entra al estimador.** Ni en la banda ni en el centro. Sigue usándose
para **estratificar la partición train/test**, que es otra cosa: hacer la muestra
representativa, no predecir.

**2. Se retira explícitamente la decisión 2 de D-014.** El arquetipo no pasa a
`rol-familia × nivel × sector`. Se queda en `rol-familia × nivel`, que es lo único que ha
sobrevivido a una validación fuera de muestra.

**3. La descomposición de varianza de D-014 no se contradice: se reinterpreta.** El 24,7%
era ω² dentro de muestra sobre etiquetas anchas. Que una variable explique varianza en la
muestra no implica que mejore la predicción fuera de ella — y aquí no lo hace. Es
exactamente el límite que D-014 se puso a sí mismo, cumplido.

### Lo que enseña sobre el método

Con el tamaño, «pierde para la banda» **no** implicaba «pierde para el centro»: eran dos
preguntas y la segunda tenía otra respuesta. Con el sector, la segunda pregunta da lo
mismo que la primera. **No se podía saber sin medirla**, y saltársela habría dejado a
D-014 en pie por defecto.

---

## D-023 — El rubro entra como **lente de producto**, no como mejora del modelo

**Fecha:** 2026-09-08
**Origen:** decisión de producto de Pablo, sostenida tras ver la evidencia en contra. La
objeción, en sus palabras: *«¿de qué le sirve a una empresa de textiles comparar su nómina
contra una petrolera?»*
**Evidencia:** `e3_varianza/07` (banda), `16` (centro), y el corte por sector de
`research/herramientas/banda_por_tamano.py`.
**Estado:** implementado, **apagado por defecto**. Se activa con `--rubro`.

### Esta decisión va contra la medición, y por eso queda escrita

D-022 midió el sector dos veces y las dos dijeron que no:

| | resultado |
|---|---|
| sector para la **banda** | pinball 0,1289 contra 0,1255 sin él → **pierde** |
| sector para el **centro** | indistinguible de un placebo → **nulo** |

Y hay una explicación de por qué la señal no aparece: **el sector ya está codificado en el
título para los puestos donde importa.** Una petrolera tiene `PERFORADOR` y una textilera
`OPERARIO TEXTIL` — celdas distintas que nunca se comparan entre sí. Lo que las dos
comparten es `CONTADOR`, `CHOFER`, `GUARDIA`: cargos que transfieren de verdad, y ahí pagan
casi lo mismo. Sobre `ASISTENTE CONTABLE` (1.688 empresas) los sectores grandes caen dentro
de un 5% entre sí, y **cada desviación grande viene de un sector con menos de 20 empresas**.

### Por qué se monta igual

Porque **precisión y legitimidad son dos preguntas distintas**, y sólo se había medido la
primera. Un cliente que no acepta el conjunto de comparación no usa el informe, y eso no se
arregla con un pinball mejor. La medición dice que el sector no ayuda a *acertar*; no dice
nada sobre si el cliente *acepta* la comparación.

Lo que se compra es comparabilidad declarada. Lo que se paga está medido y es visible.

### Las cuatro reglas del diseño

1. **El centro sigue a la banda.** Si la banda sale de los votos del rubro, el centro es el
   p50 de esos mismos votos. Publicar un centro global dentro de una banda sectorial
   permitiría que el centro caiga fuera de su propio p25–p75 — la incoherencia que prohíbe
   el test de `_lectura` (commit *«fix(producto): la banda que decide la lectura ahora viaja con ella»*).
2. **`tau_c` y `sigma_c` NO se reestiman dentro del rubro.** Con 10–90 empresas saldrían
   pésimamente estimadas, y ya vienen encogidas de la celda entera (D-016).
3. **El fallback es POR CARGO, no por informe.** Un cliente de manufactura tendrá rubro en
   `CONTADOR` (93 empresas) y mercado entero en `SOLDADOR DE PRECISION` (3). El suelo es de
   confidencialidad —`MIN_EMPRESAS_RUBRO = 10`, `MIN_PERSONAS_RUBRO = 10`, los mismos que
   la banda global— y no se negocia por conveniencia.
4. **El coste se declara, no se esconde.** Menos empresas en la celda del rubro ⇒ `1/W`
   mayor ⇒ la etiqueta de confianza baja sola. Medido sobre la prueba de integración:

   | | global | rubro |
   |---|---|---|
   | empresas detrás | 1.114 | **63** |
   | `incert_centro` | 0,0079 | **0,0338** (4,3× peor) |

   Y `referenciar_archivo` imprime siempre en cuántas filas se pudo aplicar y en cuántas se
   cayó al mercado entero. Si el coste no se ve, la lente engaña.

### Lo que esto NO es

No es una revisión de D-022. **D-022 sigue en pie**: el sector no mejora la precisión y no
entra en la ruta por defecto. Si algún día se enciende por defecto, hace falta una medición
nueva y un criterio declarado antes de correrla.

### Qué falta

- Medir la **cobertura real** sobre la base completa: cuántos pares (celda, rubro) aguantan
  el suelo y qué fracción de personas alcanzan. Si es marginal, la lente es cosmética y hay
  que decirlo en la venta.
- Decidir qué pasa cuando `--rubro` y `--segmento` se piden a la vez. Hoy componen —el
  desplazamiento por tamaño se suma sobre la banda que esté en uso— y **esa combinación no
  está medida**.

---

## D-024 — El estimador de `efecto_nivel` se queda en PROMEDIO. Hipótesis rechazada

**Fecha:** 2026-09-09
**Origen:** al auditar dónde un promedio y una mediana se encuentran en la misma resta,
apareció que `efecto_nivel` estima la escalera con promedios y ese número se suma a `m`,
que es una mediana ponderada.
**Evidencia:** `research/experimentos/e3_varianza/17_efecto_nivel_robusto.py`
**Estado:** **medido y rechazado.** El código no cambia; queda el parámetro `estimador`
para poder volver a probarlo.

### El argumento que hice, y por qué era más flojo de lo que parecía

Una diferencia-de-promedios solo coincide con una diferencia-de-medianas si las dos
distribuciones tienen la misma forma. Los escalones altos tienen cola derecha mucho más
gorda, luego `E[nivel 5] − E[nivel 1]` debería **sobreestimar** la diferencia de medianas,
y el ajuste quedaría sobredimensionado sobre un centro que es mediana.

**La primera mitad del argumento es correcta y está medida.** La segunda no se sostiene:
`mu` en la rama de analogía **ya es una media ponderada** de las medianas de 25 vecinos, no
un objeto puramente mediano. El requisito de "que el estimador case con el funcional" no
aplica tan limpio como lo presenté.

### La medición

**Los dos estimadores sí difieren, y en la dirección predicha** (secundario, no decide):

| nivel | promedio | mediana | dif |
|---|---|---|---|
| 1 | −0,3477 | −0,1466 | +0,2011 |
| 2 | −0,2815 | −0,1403 | +0,1413 |
| 3 | −0,0951 | +0,0000 | +0,0951 |
| 4 | +0,1650 | +0,2137 | +0,0488 |
| 5 | +0,5594 | +0,6763 | +0,1169 |
| **recorrido 1→5** | **2,477×** | **2,277×** | |

El promedio ensancha la escalera un 8,8%. El defecto es real.

**Pero la primaria dice que no importa.** Sobre 7.451 votos de empresas apartadas donde el
ajuste actúa:

| variante | pinball | pareado contra la media | veredicto |
|---|---|---|---|
| **media (hoy)** | **0,1522** | — | |
| mediana | 0,1529 | +0,00069 IC [+0,00049, +0,00086] | **EMPEORA** |
| sin ajuste | 0,1627 | +0,01059 IC [+0,00869, +0,01243] | EMPEORA |
| PLACEBO | 0,1691 | +0,01706 IC [+0,01444, +0,01971] | EMPEORA |

El criterio pre-declarado pedía el IC **entero por debajo de cero**. Está entero por
**encima**. Se rechaza.

Por escalón (parte C) tampoco hay ninguno donde cambiar ayude: las diferencias van de
+0,0031 a −0,0008 y solo el nivel 5 sale marginalmente a favor de la mediana.

### Los dos resultados que valen más que el rechazado

1. **El ajuste de nivel se gana su sitio.** Quitarlo cuesta **+0,0106** de pinball — quince
   veces la diferencia entre los dos estimadores. Era una pieza aplicada sin contraste
   pareado propio y ahora lo tiene.
2. **El placebo es lo peor de todo (+0,0171).** Barajar los escalones es peor que no
   ajustar, lo que confirma que el eje de nivel lleva señal real y no está compensando
   ruido. Es la validación out-of-sample que D-013 dejó pendiente.

### Caveat honesto

La base se construye sobre 4.328 empresas (no las 9.142 del universo), así que la rama de
analogía cubre el **46%** de los votos en vez del 36% de producción. Eso **favorece**
encontrar un efecto del ajuste de nivel, no lo contrario — y aun así la mediana pierde.

### Lo que esto deja abierto

El pendiente de §18 sobre el **sesgo de una pasada** en `efecto_nivel` —centrar por empresa
y luego por área deja sesgo con áreas desbalanceadas— **sigue vivo y es independiente**.
Esta medición cambió el estimador, no el esquema de centrado.

---

## D-025 — Segunda pasada de fusión por **errata**, con la asimetría como criterio

**Fecha:** 2026-09-09
**Origen:** al explicar por qué el agrupamiento es semántico y no léxico apareció que hay
**un** caso donde el léxico gana y lo estábamos perdiendo: los dedazos. `ASITENTE` puntúa
0,92–0,94 contra `ASISTENTE` y no llega al umbral de 0,95.
**Evidencia:** `research/herramientas/erratas.py` sobre la base de 65.181 títulos.
**Estado:** implementado, activo por defecto. **Falta la medición pareada de pinball.**

### Por qué el léxico aquí y no en el agrupamiento

Los embeddings codifican significado y son ciegos a las letras; la distancia de edición es
lo contrario. Para un carácter cambiado, la segunda gana trivialmente. Es el único eje
donde eso pasa, y por eso entra como **segunda pasada** y no tocando `_fusionar`: así no
altera nada de lo que `e2_nivel/07` midió.

### Lo que la inspección evitó

2.887 pares candidatos a distancia 1, y **la mayoría no son erratas**:

| cubo | pares | ¿fusionar? |
|---|---|---|
| ya fusionados semánticamente | 3.909 | ya lo están |
| **errata / plural / tilde / puntuación** | **2.887** | **sí** |
| escalón por dígito (`OPERARIO 1`/`2`) | 1.570 | no — borraría la escalera de antigüedad |
| género (`VENDEDOR`/`VENDEDORA`) | 961 | decisión aparte |
| escalón romano (`ANALISTA I`/`II`) | 188 | no |

### El umbral de asimetría sale de los datos

Medido sobre los candidatos: el lado menor tiene **una** empresa en el 68% de los pares.
Pero la razón mayor/menor mediana es solo **4,0×**, porque hay dos familias:

- **dedazo contra título común** → razón enorme. Es la que interesa: su gente pasa de
  contestarse por analogía a tener datos propios.
- **dos títulos raros a distancia 1** → razón ~1. Ninguno cruza el suelo de 3 empresas ni
  antes ni después, así que fusionarlos no gana nada y sí arriesga fundir dos oficios.

De ahí: **lado raro ≤ 2 empresas, lado común ≥ 10**. Y la absorción es de una sola
dirección, así que no encadena — el destino nunca puede ser absorbido.

### Alcance medido sobre la base real

```
grupos absorbidos                            873
etiquetas que cambian de grupo               956
personas que pasan de ANALOGIA a DIRECTA   4.278
respaldo que ganan, mediana         1 -> 60 empresas
```

### Dos falsos positivos que sólo aparecieron al mirar la base real

Ambos habrían pasado silenciosamente y están fijados con test:

1. **Letra de grado.** `AYUDANTE B DE MANTENIMIENTO` / `AYUDANTE C DE MANTENIMIENTO` y
   `SUPERVISOR C`. Una letra suelta es escalafón, igual que un romano.
2. **Género en plural.** `ENFERMERAS` / `ENFERMEROS`. La primera guarda exigía que la
   vocal fuera la última del título y la S del plural la burlaba.

### Un hallazgo que NO es de esta decisión

`ENFERMERAS` y `ENFERMEROS` **ya estaban en el mismo grupo antes de esta pasada**: los
embeddings los puntúan ≥0,95 y D-015 los fusionó. O sea que **el colapso de género ya
ocurre en producción** para los pares que la semántica junta sola, y la decisión pendiente
sobre género es más amplia de lo que parecía: no es sólo si fusionar los 961 pares
sueltos, sino qué hacer con los que ya están fusionados.

### La medición pareada: **el criterio pre-declarado NO se cumple**

`research/experimentos/e2_nivel/08_fusion_por_errata.py`. Y conviene decirlo antes que los
números: **esta decisión queda adoptada con evidencia más débil que las demás del
registro.** No está validada; está sin contradecir.

El criterio se apartó del guion de los experimentos 15–17 a propósito. Aquéllos declararon
pinball como primaria porque medían cambios en el *estimador*; éste no cambia el
estimador, cambia a qué celda pertenece un título. Así que:

```
PRIMARIA      cobertura directa sobre los titulos que la absorcion toca
GUARDARRAIL   pinball pareado: basta con que NO empeore
SE ADOPTA si  (1) sube la cobertura  (2) el guardarrail no empeora
              (3) el PLACEBO SI empeora    <- la pieza que discrimina
```

**(1) Primaria — se cumple, y es inequívoca.** Sobre los 57 títulos afectados en las
empresas apartadas:

| | directa | personas |
|---|---|---|
| sin erratas | 0,0% | 0 |
| con erratas | **100,0%** | 308 |

*(El «empresas detrás» que baja de 220 a 50 no es pérdida de respaldo: en la rama de
analogía esa cifra es la suma sobre los 25 vecinos deduplicados, y en la directa es una
celda real. No son la misma unidad.)*

**(2) Guardarraíl — se cumple, y todo indicador puntual mejora:**

| | pinball | \|sesgo\| | cob 50% |
|---|---|---|---|
| sin erratas | 0,1319 | 4,0% | 75,0% |
| con erratas | **0,1165** | **2,4%** | **43,8%** |
| PLACEBO | 0,1484 | 6,9% | 70,3% |

La cobertura del 50% central pasa de desviarse **25 puntos** del nominal a desviarse **6**:
las bandas de la analogía estaban demasiado anchas y la respuesta directa las calibra.

**(3) Placebo — NO se cumple.**

```
con erratas - sin erratas = -0,01476   IC 95% [-0,03307, +0,00958]   sin efecto
PLACEBO     - sin erratas = +0,01768   IC 95% [-0,00172, +0,04537]   sin efecto
```

Las estimaciones puntuales van exactamente en las direcciones predichas —el real mejora,
el placebo empeora, con una brecha de 0,032— pero ningún IC excluye el cero.

### Por qué falla, y en qué se distingue de un resultado negativo

**64 votos utilizables.** No hay potencia, y es estructural: la intervención afecta a cosas
raras por definición. Sobre `tr` (4.328 de 9.142 empresas) se absorben 513 grupos en vez de
los 873 del universo, y de ésos sólo 57 aparecen en las nóminas apartadas.

Esto **no** es «el placebo reprodujo la mejora», que sería condenatorio. Es que con n=64 no
se distingue nada. Es un fallo de potencia, no de dirección.

Y un **error de diseño del experimento**: debió incluir el contraste directo entre real y
placebo, que es el más agudo de los tres y compara justo lo que difiere. Se comparó cada
uno contra el control por separado, que es la forma menos potente de hacerlo.

### Por qué se deja montado a pesar de todo

Tres razones, y ninguna es que el resultado saliera bien:

1. La primaria es **mecánica**: la gente afectada pasa de analogía a datos propios, y eso
   no depende de ningún contraste.
2. El guardarraíl **no empeora**, y todos los indicadores puntuales apuntan a favor.
3. La regla es **conservadora por construcción**: absorbe sólo grupos de ≤2 empresas dentro
   de otros de ≥10, en una dirección, sin encadenar, con dígitos, romanos, letras de grado
   y género excluidos. El modo de fallo está acotado.

### Qué falta

- **Repetir con potencia**: varias particiones de empresas para multiplicar los votos
  afectados, y el contraste directo real-contra-placebo. Son 3 bases por partición, así que
  5 particiones son ~7 horas de máquina. Hasta entonces esto no está validado.
- La decisión sobre **género**, con su propio registro — y ahora se sabe que es más amplia:
  incluye los pares que la fusión semántica ya junta sola.

---

### Nota posterior (2026-09-29): el escalón ya no se protege

La Enmienda 5 de D-036 decide que el grado (dígito, romano o letra suelta) no hace distinto el
puesto, y lo borra en la capa 0. Revierte lo que aquí se excluyó como «escalón por dígito»,
«escalón romano» y «letra de grado». La escalera de antigüedad pasa a la banda. La fusión por
errata en sí no cambia.

## D-026 — Las grafías de género se fusionan, y la brecha queda visible

**Fecha:** 2026-09-09
**Origen:** al implementar D-025 apareció que `ENFERMERAS` y `ENFERMEROS` ya compartían
grupo mientras `ENFERMERA` y `ENFERMERO` no. Al inventariarlo, la inconsistencia resultó
ser general.
**Evidencia:** `research/herramientas/genero.py`, y la medición del coste en
`research/experimentos/e2_nivel/09_fusion_por_genero.py`.
**Estado:** implementado y activo. La medición del coste está declarada y corriendo.

### El argumento NO es estadístico, y conviene decirlo primero

Una celda del modelo es una cadena de texto. Para que `ENFERMERA` y `ENFERMERO` acaben en
la misma celda tiene que superarse el coseno de 0,95 — y medido sobre las 65.181 celdas:

| | pares |
|---|---|
| ya fusionados por semántica | **690** (48%) |
| sueltos, en celdas distintas | **738** (52%) |

**Casi una moneda al aire, y sin patrón.** Ni siquiera es singular contra plural: 21% de
plurales entre los fusionados y 17% entre los sueltos. El comportamiento de hoy no es una
decisión; es dónde cayó el coseno.

La consecuencia: **dos personas con el mismo oficio reciben referencias distintas según
cómo tecleó el título su empleador.** Y como el título es un **proxy de género**, al ser la
unidad de agrupamiento el modelo termina segmentando por género sin que nadie lo haya
decidido — justo lo que la regla de *«`sexo` nunca es una variable»* existe para impedir.

> **Fusionar no mete el género en el modelo: saca el proxy que ya estaba dentro.**

### Cómo difieren las celdas que hoy están sueltas

114 pares inequívocos con 10+ empresas en ambos lados:

```
mediana -3,3%   ·   p25/p75  -13,0% / +1,9%   ·   |desvío| mediano 7,5%
el femenino paga menos en 76 de 114 (67%)

ENFERMERA / ENFERMERO   -21,3%      SECRETARIA / SECRETARIO   -7,5%
COCINERA  / COCINERO    -13,6%      ADMINISTRADORA / ...      +9,8%
PSICOLOGA / PSICOLOGO   -12,8%      ASESORA COMERCIAL / ...  +16,5%
```

**No es uniforme**: en un tercio de los pares el femenino paga más. Lo constante es que
son *distintas*.

### Lo que estas cifras NO son

**No son la brecha salarial.** Las dos celdas son empleadores distintos —`ENFERMERA` tiene
240 empresas y `ENFERMERO` 67, con poco solape— y no hay control por empresa, tamaño,
sector, provincia ni antigüedad. Podría ser enteramente composición. La brecha de verdad es
la descomposición Oaxaca de **D-011**, que usa la columna `sexo` y sus controles.

Lo que sí son, independientemente de la causa: la prueba de que **la celda a la que caes
depende de una convención de redacción de RR.HH.**

### El diseño

Tercera pasada, después de la semántica y de las erratas. **Sin regla de asimetría**, al
revés que D-025: allí el lado raro era un dedazo y había que absorberlo; aquí las dos
grafías son legítimas y a menudo ambas pobladas (`CONTADORA` 777 empresas, `CONTADOR` 865).
Sobrevive como identificador el grupo con más empresas.

Alcance sobre la base real:

```
657 pares juntados · grupos 51.942 -> 51.285 · 921 etiquetas cambian de celda
213.011 personas en alguna celda afectada
344 etiquetas pasan de contestarse por analogía a tener datos propios
```

### La brecha se guarda, no se borra

Fusionar da una referencia justa, pero si el número se limitara a promediar las dos
grafías, la diferencia que había dejaría de poder mirarse. Se calcula **antes** de
recalcular los estadísticos y viaja en la respuesta como `brecha_grafia`.

**Con suelo de 10 empresas en los dos lados**, y ese suelo es un defecto que la inspección
atrapó antes de que saliera: sin él se publicaban `PERCHADORA +80,0%` y `OPERARIA
PRODUCCION +365,8%`, calculadas sobre **una** empresa. Ruido presentado como diagnóstico.
Por debajo del suelo la fusión se hace igual —esa es la parte que corrige el proxy— pero no
se reporta nada.

### La medición mide el COSTE, no si conviene

El verbo importa. La decisión ya está tomada y no la resuelve el pinball: aunque fusionar
empeorara algo la precisión, el argumento del proxy seguiría en pie. Lo que la medición
puede hacer es acotar lo que se paga, y —esto sí es decisivo— comprobar que la regla
identifica **oficios equivalentes**: si juntar `ENFERMERA` con `ENFERMERO` costara lo mismo
que juntar dos celdas al azar del mismo tamaño, no estaría reconociendo nada, estaría
mezclando.

De ahí el criterio declarado antes de correr:

```
PRIMARIA       pinball pareado sobre los votos donde la fusion actua. Aqui pinball SI es
               la primaria correcta —al reves que en D-025— porque fusionar cambia el
               CENTRO de gente que ya tenia respuesta directa.
DISCRIMINANTE  contraste DIRECTO real contra placebo, que es lo que a D-025 le falto.

SE REVISA si (a) el IC 95% del coste queda entero por encima de +0,005 —mas de lo que
vale la fusion semantica entera (D-015: -0,0030)—, o (b) el real NO sale claramente mas
barato que el placebo.
```

Y esta vez hay potencia: 114 pares con respaldo, frente a los 57 títulos y 64 votos que
dejaron D-025 sin concluir.

### El resultado: se cumplen las tres condiciones

`research/experimentos/e2_nivel/09_fusion_por_genero.py`. 213 títulos afectados,
**1.036 votos** de empresas apartadas — la potencia que a D-025 le faltó.

| | pinball | \|sesgo\| | cob 50% | ancho |
|---|---|---|---|---|
| sin género | 0,1417 | 5,7% | 50,2% | 85,6% |
| **con género** | **0,1379** | **3,9%** | **49,6%** | **81,4%** |
| PLACEBO | 0,1690 | 24,5% | 51,7% | 117,5% |

```
con genero - sin genero = -0,00386   IC 95% [-0,00665, -0,00100]   MEJORA
PLACEBO    - sin genero = +0,02749   IC 95% [+0,02153, +0,03330]   EMPEORA

DISCRIMINANTE
con genero - PLACEBO    = -0,03134   IC 95% [-0,03859, -0,02467]   el real es MAS BARATO
```

**No cuesta: gana.** Y la mejora (0,0039) es **mayor que la de la fusión semántica entera**
(D-015: −0,0030), que es la pieza central del método.

**Y juntar al azar duele siete veces más.** Con 187 uniones aleatorias de tamaño
comparable, el sesgo salta del 5,7% al 24,5%. Eso es lo que había que demostrar: la regla
está reconociendo **el mismo oficio**, no mezclando celdas. Si sólo importara juntar, el
placebo habría dado lo mismo.

El patrón lo confirma por otro lado: con género la banda **se estrecha manteniendo la
cobertura** en el nominal (85,6% → 81,4% de ancho, 50,2% → 49,6% de cobertura), mientras el
placebo la ensancha un 37% y sube la cobertura a 51,7%. **Estrechar sin perder cobertura es
la firma de haber unido dos celdas que eran una; ensancharla es la de haber unido dos que
no lo eran.**

### Un placebo vacío estuvo a punto de pasar por validación

La primera corrida inyectó **5** uniones en vez de 187, y salió idéntica al control. El
discriminante decía entonces *«el real es más barato que el placebo»* con un IC precioso —
y no significaba nada, porque sólo repetía *«el real es mejor que el control»*.

El fallo: se agrupaban las fuentes por destino y se exigían dos, pero `tocados` sólo
contiene los títulos que **cambian** de grupo, y el superviviente no cambia. Cada destino
tenía una sola fuente y se saltaba.

Es el mismo tipo de fallo que dejó a D-025 sin discriminante, y **el modo más fácil de
auto-engañarse en este diseño**: un placebo que no hace nada produce un contraste que
parece favorable. Ahora hay un `assert` que exige que el placebo cubra al menos el 80% de
las uniones reales.

### Cómo llega la brecha al cliente

Va en `por_puesto` —es propiedad del cargo, no de la persona— con corte en 5%, y **el
resumen la dice** en vez de dejarla en una columna:

```
En 1 puesto(s), la grafia femenina y la masculina del titulo estaban en
celdas distintas y pagaban distinto. La referencia que se entrega ya las unifica:
  ENFERMERA                                 -21.3% la femenina
NO es una brecha salarial medida: compara dos GRAFIAS escritas por empresas
distintas, sin controlar por empresa, sector ni antiguedad.
```

Esa última frase no es adorno: sin ella, un −21,3% junto a `ENFERMERA` se lee como brecha
salarial medida, y no lo es.

### Estado final

**Adoptado, con las tres condiciones pre-declaradas cumplidas.** Es la decisión mejor
sostenida de las tomadas hoy: el argumento de principio (sacar el proxy de género del
modelo) y la medición apuntan en la misma dirección, cosa que no pasó ni con el rubro
(D-023, medición nula) ni con las erratas (D-025, placebo sin potencia).


---

## D-027 — Al cliente NO se le quita de su propio mercado. Se le dice cuánto pesa

**Fecha:** 2026-09-10
**Origen:** petición directa — «excluir al cliente de su propio mercado». Si la empresa
del cliente participó en los estudios con que se construyó la base, su propio sueldo
entra en la mediana que le sirve de referencia: se está comparando contra sí mismo.
**Evidencia:** `research/experimentos/e4_producto/01_influencia_del_cliente.py`, sobre
train (863.656 filas, 5.770 empresas, 141.889 pares celda–empresa).
**Estado:** implementado y activo, en la forma barata. La exclusión exacta queda
**descartada por medición**, no por dificultad.

### El problema es real y la petición era la correcta

El caso extremo se ve sin estadística: un cargo respaldado por tres empresas, una de
ellas el cliente. Le decimos «estás en la mediana» y lo está porque **él es** la mediana.
Cuanto más estrecho el cargo, más circular la lectura.

### Lo que bloquea la exclusión exacta

El centro de cada celda es una **mediana ponderada de los votos por empresa**. De una
mediana no se resta un voto: con `m` y `W` guardados no hay forma de recuperar `m` sin la
empresa *f*. Haría falta guardar la lista de votos —el sueldo mediano de **cada** empresa
en **cada** cargo, 141.889 pares—, y eso convierte el artefacto en una tabla de *«qué paga
la empresa X por el cargo Y»*.

Y sería identificable. Al implementar `meta_ruc` escribí en `_padron` que los índices del
padrón eran opacos porque salían de una permutación sembrada. **Es falso, y lo comprobé:**
con el `.npz` y el repositorio delante —la semilla está en el código— se reconstruye el
mapa RUC→índice para las 6.722 empresas, las 6.722. La permutación solo estorba a quien
mire el archivo sin el código. El control de verdad es que el `.npz` no sale del servidor;
el corolario es que ahí dentro no pueden entrar sueldos por empresa.

Antes de pagar ese precio había que saber qué se compraba.

### La medición

**Criterio declarado antes de correr:** se compara |Δm| contra `sd(centro) = √(τ²_c + 1/W)`,
que es la barra de error que el informe **ya** muestra. Se construye la exclusión exacta
si y solo si la mediana de |Δm|/sd supera **0,20** en las celdas que pasan el suelo de
banda empírica (emp ≥ 10).

| empresas en la celda | pares | mediana \|Δm\|/sd | p90 | peso del cliente (p50) |
|---|---|---|---|---|
| 3–5 | 990 | **0,247** | 0,903 | **33,2%** |
| 5–10 | 1.930 | 0,150 | 0,478 | 14,7% |
| 10–20 | 4.004 | 0,070 | 0,241 | 7,2% |
| 20–50 | 9.031 | 0,026 | 0,112 | 3,2% |
| 50–200 | 13.395 | 0,007 | 0,041 | 1,2% |
| 200+ | 3.480 | 0,0005 | 0,011 | 0,3% |

**Primaria: 0,0118 sobre emp ≥ 10.** El criterio era 0,20. No está cerca. En dólares,
quitar una empresa mueve la referencia un **0,39%**. Corregir eso sería corregir ruido —y
pagarlo con una tabla de sueldos por empresa.

**Donde sí importa es debajo del suelo:** con 3 a 9 empresas el desplazamiento es del
16,8% de la barra (**5,4% en dólares**) y el cliente pesa entre el 15% y el 33% del
mercado.

### Lo que se construyó

1. **Pertenencia, exacta.** `grupos_de_empresa(ruc)` dice qué celdas respalda el cliente,
   leyendo el padrón. Sin dato nuevo: el padrón ya estaba.
2. **Influencia, `1/empresas`.** También medido: los pesos inverso-varianza dentro de una
   celda salen casi uniformes, así que `1/n` reproduce el peso real con un 0,3%–4% de
   error mediano y **predice el desplazamiento igual de bien que el peso exacto**
   (Spearman 0,593 contra 0,594). La alternativa —guardar personas por empresa y celda—
   no compraba nada.
3. **Se dice, cargo por cargo y en la cabecera.** `tu_empresa` y `tu_influencia` en
   `por_puesto`; en `mercado`, cuántos cargos están afectados y cuántos de ésos caen bajo
   las 10 empresas, con el peor nombrado.

El umbral de 10 de la nota no es elegido, es el de la tabla: por encima, 0,39%; por
debajo, 5,4%.

### Lo que esto NO es

No es exclusión. El cliente sigue dentro de su referencia y el informe lo dice en vez de
presentar la comparación como independiente. Si algún día se decide que la exclusión
exacta vale el coste, la medición de arriba es el argumento en contra y hay que rebatirla
con otra, no con una intuición.

### Un defecto encontrado de paso

Normalizar la clave del padrón destapó que, **sin fusión**, el padrón se indexaba por el
nombre del cargo mientras `empresas_de` lo buscaba por número de grupo. No fallaba:
devolvía vacío, y `empresas_analizadas` —la tarjeta más visible del informe— salía en cero
sin que nada lo dijera. Producción siempre usa fusión, así que nunca mordió. Corregido y
con test.


---

## D-028 — El RUC se resuelve contra el registro del país, no contra la base

**Fecha:** 2026-09-10
**Origen:** al confirmar el contrato del front —«el front te pasa RUC y tú sacas tamaño,
sector y año»— salió que la tabla RUC→industria se llenaba desde el propio marco.
**Evidencia:** conteos sobre `act-actuafast.actuafastv2.scvs_balances_anuales` y sobre
`demo/base_v12.npz`.
**Estado:** implementado y activo. Base reconstruida.

### El defecto

`meta_ruc` se llenaba desde el `marco`, o sea solo con empresas que aportaron estudios
actuariales:

| | RUCs | |
|---|---|---|
| registro SCVS (último balance por RUC) | 221.794 | |
| en la base | 6.722 | 3,0% |
| con CIIU utilizable | 4.735 | **2,1%** |

Se le pedía el RUC al cliente para no poder decirle **ni su sector ni su tamaño en 98 de
cada 100 casos**. Y el informe caía al mercado entero sin explicar por qué: el fallback
por rubro está pensado para «este cargo no tiene respaldo sectorial», no para «no sé
quién eres».

Es además el cliente equivocado el que quedaba fuera. Quien ya aportó estudios es cliente
viejo; quien llega nuevo —el que compra— es justo el que no está.

### La corrección

`construir` acepta `scvs`, el padrón de la Superintendencia que `leer_scvs` ya devolvía.
De ahí sale `meta_ruc`. Resultado sobre `base_v12.npz`:

| | |
|---|---|
| `meta_ruc` | **221.794** (segmento 100%, CIIU 99,99%) |
| `pad_ruc` | 6.722 |
| coste | +1,3 MB sobre 181, carga 2,0 s |

**Son dos preguntas distintas y ahora las contestan dos tablas distintas.** `pad_ruc`
dice *si aportaste datos* —y de ahí sale el aviso de espejo de D-027—; `meta_ruc` dice
*quién eres*. Que estuvieran mezcladas fue lo que hizo pasar el defecto: la misma tabla
servía para «¿estás en el mercado?» y para «¿cuál es tu industria?», y la primera pregunta
imponía su cobertura a la segunda.

`tam` y `ciiu` **no** se tocan: describen el mercado comparado y alimentan la tarjeta de
tamaños del informe, así que una empresa del registro que no aportó datos no puede
engordarla. Con test.

### El segmento se propaga, no se calcula

Viene ya clasificado de SCVS, que es la **misma** clasificación con la que se armaron las
celdas. Derivarlo de `n_empleados` con cortes propios pondría al cliente en un segmento
medido con otra regla que las celdas contra las que se lo compara, y el ajuste por
segmento (D-018) dejaría de significar lo que dice. Los cuatro valores del registro
—`MICROEMPRESA`, `PEQUEÑA`, `MEDIANA`, `GRANDE`— normalizan sin pérdida: 0 de 314.985
filas se pierden.

### Lo que sigue sin resolverse

**1.987 de las 6.722 empresas de la base (30%) no están en el registro SCVS.** No es un
problema de formato del join —se comprobó contra la tabla directamente—: no presentan
balances ahí. Probablemente sector público, fundaciones y personas naturales. Para ésas
el RUC sigue sin resolver sector ni tamaño, y ninguna fuente que tengamos lo arregla.


---

## D-029 — El sector se **enseña** al nivel fino y se **compara** al nivel de sección

**Fecha:** 2026-09-15
**Origen:** un cliente con CIIU `G4761.03` (librería y papelería) veía en el front
«Comercio al por mayor y al por menor; reparación de vehículos» y, con razón, no se
reconocía.
**Evidencia:** `research/experimentos/e3_varianza/18_rubro_a_division.py` y
`19_cascada_ciiu_completa.py`, más la descomposición de varianza de abajo.
**Estado:** implementado y activo. Base `base_v13.npz`.

### El diagnóstico no era el que parecía

No había ningún código equivocado. `G4761.03` y «comercio… reparación de vehículos» son
la misma cosa: lo segundo es el nombre oficial de la **sección** G, y el producto compara
a nivel de sección. El front mostraba *contra qué te comparamos* con la etiqueta de
*quién eres*. Son dos hechos distintos y estaban fundidos en uno.

### Entonces, ¿por qué no comparar más fino?

Se midió la escalera entera. Métrica: pinball en q=0,25 y q=0,75 sobre la banda de
empresas, pareado por empresa apartada.

| | diferencia | IC 95% | |
|---|---|---|---|
| cascada división → sección (`18`) | +0,00059 | [+0,00017, +0,00098] | peor, +0,42% |
| cascada clase → grupo → división (`19`) | +0,00094 | [+0,00048, +0,00146] | **peor, +0,67%** |

Monótono: cuanto más fino, peor. Y en `19` la cascada solo baja cuando el nivel fino
aguanta el suelo por sí mismo, así que la sospecha de que `18` fuera un contraste injusto
—comparar en votos donde la división siempre tiene menos empresas— queda descartada.

### El mecanismo, que es lo que lo hace creíble

De la varianza **entre empresas** del pago por un mismo cargo, ¿cuánto explica la
división CIIU? Sobre las 237 celdas más favorables (≥40 empresas, ≥3 divisiones):

```
explicado por la division   0,389
lo mismo, barajada          0,325   <- inflacion mecanica de partir en grupos chicos
señal neta                 +0,064
```

**Seis puntos.** Lo que una empresa paga por un contador depende de la empresa —tamaño,
política, margen— mucho más que de si vende libros o repuestos. Y esos 6 puntos de
homogeneidad se pagan con muestra: de 46 empresas por celda a 16.

### En términos de producto

| | |
|---|---|
| cargos cuyo veredicto cambia de lado | 415 de 23.241 = **1,79%** |
| para un cliente de 150 cargos | 2,7 cargos |
| en esos 415, ¿quién acierta? | la **sección**, +9,2% de pinball, IC [+0,0005, +0,0116] |
| alarmas nuevas / alarmas que se apagan | 226 / 189 |
| ancho de banda | 47,3% → 47,0% (se estrecha en el 49%: moneda al aire) |

**La banda no se estrecha: se desplaza.** Los veredictos no cambian porque el sector dé
una banda más ajustada, sino porque la recentra sobre 16 empresas apoyándose en 6 puntos
de señal. Movimiento grande, información poca.

### La decisión (revisada — ver el apartado final)

> **Nota:** lo que sigue describe la primera decisión, que fue *el veredicto sale siempre
> de la sección*. Se revisó al medir una regla mejor: ver **«El veredicto sí baja de
> nivel, con umbral de fiabilidad»** al final de esta entrada.

Se separa **lo que se enseña** de **lo que se calcula**:

```
Tu industria:  G4761.03
Referencia:    $1.296   ← seccion G, 323 empresas   (de aqui sale el veredicto)
Tu sector:     $1.478   ← division G47, 49 empresas  (+14,0%, informativo)
```

El ejecutivo ve el número de su sector —que es lo que pedía— **con su muestra al lado**,
que es la información que hoy no tiene y que con la cascada tampoco tendría. El veredicto
se sigue calculando donde hay con qué.

Es más honesto que las dos alternativas puras: hoy se le escondía su sector, y con la
cascada se le daría un número de 16 empresas sin decirle que son 16.

### Cómo queda montado, y por qué así

Las tablas de banda por rubro se guardan a **cuatro niveles** (clase, grupo, división,
sección) en un solo índice: el código lleva su nivel en la longitud, así que las claves
no chocan. **Las entradas de sección salen idénticas a las de antes** —hay test— o sea
que ningún informe ya emitido cambia en silencio.

`NIVEL_VEREDICTO = 1` es la única línea que decide de dónde sale el diagnóstico. Si algún
día se decide pagar el 0,67%, cambiarla a `3` es todo: las tablas finas ya están. Pero la
constante lleva al lado el precio medido, para que esa decisión se tome sabiéndolo.

### Lo que sigue abierto

El **segmento del último año declarado es inestable**: 23.923 de 188.562 empresas (12,7%)
cambian de segmento entre sus dos últimas declaraciones, y 1.879 tienen caídas de
plantilla imposibles. El propio RUC que originó esta decisión declara 2 empleados en 2025
y 193 en 2024, así que lo clasificamos MEDIANA cuando es GRANDE. Eso alimenta
`ajuste_seg` (D-018). Sin resolver.


### El veredicto sí baja de nivel, con umbral de fiabilidad

**Lo que estaba mal en la decisión anterior.** Se midió la cascada usando
`MIN_EMPRESAS_RUBRO = 10` como criterio para bajar de nivel. Ese es un suelo de
**confidencialidad** —por debajo no se publica un dato sin identificar empresas— y se
estaba usando como si fuera uno de **fiabilidad**. Son cosas distintas y confundirlas es
lo que hizo perder a la cascada.

**La regla correcta**, propuesta desde el negocio: bajar al nivel más fino que supere un
umbral de respaldo, subiendo cuando no llegue. Clase → grupo → división → sección, y la
sección solo como último recurso.

**Exploración** (sobre los votos de `19`, nueve umbrales):

| T | votos que bajan | diferencia vs sección | |
|---|---|---|---|
| 10 | 15,2% | +0,00094 [+0,00048, +0,00146] | peor |
| 15 | 8,7% | +0,00034 [+0,00002, +0,00076] | peor |
| 20 | 5,5% | +0,00011 [−0,00013, +0,00040] | nulo |
| 30 | 2,6% | +0,00007 [−0,00004, +0,00018] | nulo |

Elegir el umbral mirando el resultado es ajustar a ruido, así que se confirmó aparte.

**Confirmación** (`e3/20`, partición nueva con semilla `20260915`, criterio y margen
declarados antes de correr):

```
cascada con T>=30
  votos que bajan de nivel   1.181 (5,4%)
  diferencia vs hoy         -0,00002   IC95 [-0,00027, +0,00020]
  criterio: techo < +0,00020            -> SE CONFIRMA
  veredictos que cambian     83 (0,38%)
```

**Adoptado: `MIN_EMPRESAS_VEREDICTO = 30`.**

**Qué NO es.** No es una mejora: el efecto es cero por construcción y ningún umbral lo
vuelve positivo. Es la forma de que el veredicto salga del sector del cliente —cosa que
el negocio pide y que es razonable pedir— sin pagar precisión por ello.

**Dos honestidades sobre la confirmación.** El techo quedó en +0,00020 con un margen de
+0,00020: pasa por el canto. Y en la partición nueva **el suelo de 10 tampoco salió
peor** (+0,00059, IC [−0,00007, +0,00121]), o sea que el efecto es más pequeño que la
variación entre particiones. La lectura honesta es *«a partir de 20-30 no hace daño»*, no
*«encontramos el punto exacto donde deja de doler»*.

**Pendiente, medido como secundaria y sin confirmar.** El umbral sobre la incertidumbre
(`1/W_fino <= 2 · 1/W_sección`) mueve el doble de votos —10,4% contra 5,4%— sin empeorar,
y es el criterio correcto: 30 empresas no valen lo mismo en `AUXILIAR DE LIMPIEZA` que en
`GERENTE GENERAL`, donde los sueldos van de $500 a $13.000. Se eligió después de ver los
datos, así que necesita su propia confirmación antes de entrar.

**Sobre la librería que originó todo esto** (`G4761.03`), 5 de sus 8 cargos pasan a
compararse contra su división y 3 se quedan en sección porque su división no llega a 30
empresas:

```
CONTADOR                  $1.296 -> $1.478   division  49 empresas  +14,0%
GERENTE GENERAL           $3.110 -> $3.382   division  34           +8,7%
VENDEDOR                  $  524 -> $  500   division  65           -4,5%
AUXILIAR DE LIMPIEZA      $  487 -> $  487   seccion   92            0,0%   (division: 12)
CAJERO                    $  513 -> $  513   seccion  112            0,0%   (division: 16)
```

---

## D-030 — El contexto en el embedding se midió y **no se adopta**

**Fecha:** 2026-09-17
**Origen:** buscar `TECNICO DE DIALISIS` en `/puestos` sugería `ASISTENTE EN DISEÑO`.
**Evidencia:** `research/experimentos/e1_premisa/10_contexto_en_el_embedding.py`.
**Estado:** medido, **negativo en la primaria**. El modelo se queda como está.

### El diagnóstico, que sí es sólido

Sobre los 65.181 títulos de la base:

| | p50 | p90 | p99 | max |
|---|---|---|---|---|
| pares **al azar** | 0,588 | 0,693 | **0,780** | 0,955 |
| mismo puesto (fusión) | 0,970 | 0,991 | 0,997 | 1,000 |

Dos cargos **sin ninguna relación** llegan a 0,78 en el percentil 99, y el 8,6% de los
pares al azar pasan de 0,70. Los candidatos malos puntuaban 0,74–0,79: están dentro del
rango del azar. Con títulos de una a tres palabras en español,
`text-multilingual-embedding-002` no separa el sinónimo de la rima — `DENTISTA` puntúa
0,752 con `TELEFONISTA` y 0,763 con `ODONTOLOGA`.

### La hipótesis y su medición

Embeber el título dentro de una frase en vez de desnudo. Dos plantillas declaradas antes
de correr, `T1_larga` (funciones y responsabilidad) y `T2_corta` (`"Cargo: {}"`, como
control).

**Primaria** — pinball q=0,25/0,75 sobre la banda de empresas, pareado por empresa
apartada, 38.450 votos sobre 1.442 empresas:

```
pinball desnudo   0,13683
T1_larga   dif -0,00057   IC95 [-0,00126, +0,00014]   sin diferencia
T2_corta   dif -0,00031   IC95 [-0,00081, +0,00021]   sin diferencia
```

**Ninguna se adopta.** Los dos intervalos cruzan el cero.

**Secundaria** (no decide): aciertos en pares sinónimo/rima — desnudo **2/5**, T1 **4/5**,
T2 **3/5**. `DENTISTA`–`ODONTOLOGA` pasa de 0,763 a 0,943.

### El confundido que hubo que neutralizar

Con contexto **todos** los cosenos suben, así que `UMBRAL_FUSION = 0,95` deja de
significar lo mismo. Sin corregirlo, la variante nueva fusionaría mucho más y se estaría
midiendo la agresividad de la fusión disfrazada de calidad del embedding. Se igualó por
**cuantil**: 0,95 → 0,9804 (T1) y 0,9634 (T2), con grupos casi idénticos (33.836 / 33.284
/ 33.781).

### Qué se aprende

**El contexto ayuda al vecindario y no mueve las bandas.** Tiene sentido: la banda de un
cargo depende de cuántas empresas lo respaldan mucho más que de cuál es su vecino más
cercano.

**Y el control hizo su trabajo.** `T2_corta` también mejora los pares y también da nulo en
pinball, así que el efecto **no vive en la redacción concreta** de la plantilla. Si solo
`T1_larga` hubiera funcionado, habría que sospechar ajuste a los cinco pares.

**`CHOFER`/`CHEF` falla en las tres variantes.** Ese no es un problema de contexto.

### Lo que queda abierto

Usar contexto **solo en `/puestos`**, manteniendo dos juegos de embeddings: el buscador
mejoraría y el producto no se tocaría. No está medido así y no se propone todavía.

### Un error de método que casi se publica al revés

La primera versión de `juntar()` emparejaba los tres vectores de pinball **por posición**.
Cada variante corre en su propio proceso y consulta BigQuery por separado, y **BigQuery no
garantiza el orden de las filas entre consultas**: se estaba comparando el voto de una
empresa contra el de otra. La salida decía `T1_larga PEOR +0,00641` donde la unión por
`(empresa, cargo)` da `-0,00057 sin diferencia` — **signo opuesto**. Corregido y anotado
en el código.

---

## D-031 — Tres relajaciones de la fusión por errata, y el placebo que D-025 no tuvo

**Fecha:** 2026-09-21
**Origen:** en el desplegable del front, escribir `Vendedo` ofrecía `VENDEDRO`, `VENDEROA`,
`VEDEDOR` y `VENEDOR` —una empresa cada una— **encima** de `VENDEDOR`, que tiene 767.
**Evidencia:** `research/experimentos/e2_nivel/10_erratas_transposicion_y_largo.py`.
**Estado:** adoptado. Base `base_v15.npz`.

### El diagnóstico: tres causas distintas, no una

| grafía | emp | largo | lev | damerau | por qué se escapó |
|---|---|---|---|---|---|
| `VENDEDRO` | 1 | 8 | 2 | 1 | **transposición**: Levenshtein la cuenta como dos |
| `VEDEDOR` | 2 | 7 | 1 | 1 | **largo 7 < 8** |
| `VENEDOR` | 1 | 7 | 1 | 1 | largo 7 < 8 |
| `VENDEROA` | 1 | 8 | 2 | 2 | **errata DE una errata** (`VENDERORA`) |

Las tres relajaciones:

- **A, transposición.** Intercambiar dos letras contiguas es el dedazo más común y
  Levenshtein lo ve como dos errores. Damerau como uno.
- **B, el suelo de largo sobre la grafía COMÚN.** Existe porque con palabras cortas un
  carácter cambia el significado (`SUB`/`SUR`), pero aplicárselo a la **rara** descarta
  pares seguros: `VEDEDOR` tiene 7 letras y 2 empresas, su común `VENDEDOR` tiene 8 y 767.
  El riesgo está en que las **dos** sean cortas y frecuentes, y de eso ya se ocupa el
  suelo de 10 empresas del lado que absorbe.
- **C, varias pasadas.** En una sola, el par `(VENDERORA, VENDEROA)` se evalúa leyendo el
  grupo *original* de `VENDERORA` —su grupito de una empresa—, falla el suelo del lado
  común, y cuando `VENDERORA` se absorbe ya es tarde. Queda huérfana **por orden de
  ejecución, no por la regla**. No es encadenar a ciegas: el destino sigue exigiendo 10
  empresas *en cada vuelta*, así que nunca se pasa por un grupo raro.

### La medición

Criterio de D-025: sube la cobertura, no empeora el guardarrail, **y el placebo sí lo
empeora**.

| variante | absorciones | cobertura | pinball | IC 95% | |
|---|---|---|---|---|---|
| hoy | 528 | 52,3511% | | | |
| A_transp | 567 | +0,0104% | −0,00001 | [−0,00004, +0,00001] | no empeora |
| B_largo | 534 | +0,0026% | −0,00001 | [−0,00003, +0,00000] | no empeora |
| C_cadena | 546 | +0,0078% | +0,00001 | [+0,00000, +0,00001] | **EMPEORA** |
| **ABC** | **592** | **+0,0208%** | **−0,00001** | [−0,00004, +0,00002] | **no empeora** |
| ABC_plac | 641 | +0,0208% | +0,00130 | [+0,00081, +0,00180] | **EMPEORA** |

**El placebo discrimina, que es lo que D-025 no consiguió.** Mandar las *mismas*
absorciones a destinos al azar cuesta **+0,00130**, cien veces más que la regla real. La
distancia de edición está eligiendo bien el destino: no da lo mismo dónde caiga la gente.

### Lo que esto NO es

**No es una mejora del modelo.** 592 absorciones contra 528 sobre 65.181 títulos, y el
pinball no se mueve. Esas celdas tienen una o dos empresas: pesan casi nada en el agregado.
Es un arreglo del **desplegable** —la lista que ve el usuario— y como tal el listón
correcto no era «demuestra que mejora» sino «demuestra que no estropea».

### La letra pequeña, para que nadie la lea como validada

**`C_cadena` por sí sola sale EMPEORA**: +0,00001 con IC [+0,00000, +0,00001]. Es la
quinta cifra decimal —un 0,007% sobre un pinball de 0,137— pero el intervalo excluye el
cero y **el criterio declarado era por variante**. Se adopta dentro del conjunto por
decisión de producto, pagando ese coste a cambio de cazar la familia de `VENDEROA`.
Juzgarlo «por el conjunto» después de ver que el conjunto sale mejor habría sido mover la
portería.

### Un hallazgo lateral que reordena prioridades

Ninguna de esas grafías llega al umbral **semántico**:

```
VENDEROR  vs VENDEDOR   coseno 0,7177
VENDERDOR vs VENDEDOR   coseno 0,6966
VENDERORA vs VENDEDORA  coseno 0,8670     (umbral de fusion: 0,95)
```

**El embedding no reconoce una errata de una letra.** Las nueve grafías de ese grupo las
unió la regla ortográfica, no el modelo. Para este tipo de ruido la distancia de edición
hace todo el trabajo — lo contrario de lo que uno supondría, y coherente con D-030: el
embedding importa menos de lo que parece.

---

## D-032 — Umbral **relativo** para la fusión por errata. Mide bien y **no se adopta**

**Fecha:** 2026-09-23
**Origen:** D-031 dejó el tope de la grafía rara en un número fijo (`max_raro` empresas). Un
tope fijo trata igual a un común de 12 empresas que a uno de 767, cuando lo que dice que
algo es una errata no es su tamaño absoluto sino **su tamaño frente al del común**.
**Evidencia:** `research/experimentos/e2_nivel/12_umbral_relativo_de_errata.py`.
**Estado:** medido y **NO adoptado**. La regla pasa el criterio; no paga.

### La regla

Una sola línea cambia respecto de hoy: el tope de la grafía rara pasa a ser el mayor entre
el fijo de siempre y una fracción del común.

```python
tope = (max_raro if frac is None
        else max(max_raro, frac * emp_por_grupo.get(comun, 0)))
```

`R05` es `frac = 0,05`; `R10` es `frac = 0,10`. Nunca aprieta —el `max` garantiza que no
puede absorber menos que hoy—, sólo suelta donde el común es grande.

### Lo medido

Criterio declarado antes de correr: sube la cobertura, el IC de `R05` **no** queda entero
sobre cero, y el de `R05_plac` **sí**.

| variante | absorciones | pinball | dif vs hoy (IC 95%) | cobertura | |
|---|---|---|---|---|---|
| hoy | 593 | 0,13471 | — | 55,4% | |
| **R05** | **641** | 0,13481 | **+0,00004** [−0,00003, +0,00012] | 55,5% | no empeora |
| R10 | 667 | 0,13480 | +0,00004 [−0,00003, +0,00012] | 55,5% | no empeora |
| R05_plac | 641 | 0,13630 | **+0,00119** [+0,00058, +0,00174] | 55,5% | **EMPEORA** |

**Los tres criterios pasan.** El placebo discrimina con holgura: mandar las *mismas* 641
absorciones a destinos al azar cuesta **30 veces más** que la regla real. Y `R05` y `R10`
dan el mismo pinball hasta la quinta cifra, que es justo lo que se le pide a un umbral
relativo: que el resultado no dependa de dónde se ponga la raya.

### Por qué no se adopta, si pasa

Pasar el criterio y merecer entrar en el producto no son lo mismo, y aquí conviene no
confundirlos.

El criterio de D-031 era **«demuestra que no estropea»**, porque aquello arreglaba el
desplegable. Este cambio no arregla ningún desplegable roto: no salió de una queja, salió
de mirar la regla y notar que un tope fijo es teóricamente feo. Las 48 absorciones que
añade sobre 65.181 títulos son celdas de una o dos empresas y el pinball se mueve **hacia
arriba** —+0,00004, dentro del ruido, pero el signo es el que es.

Un cambio sin problema que resolver, cuyo efecto medido es indistinguible de cero y de
signo adverso, no entra. **Queda medido y archivado**, no descartado: si aparece una queja
concreta que este tope relativo resuelva, la medición ya está hecha y la regla es una
línea.

---

## D-033 — Candado de **seniority** en la fusión semántica. Adoptado

**Fecha:** 2026-09-23
**Origen:** 48 pares de la banda 0,93–0,97 juzgados a mano (`13a`). De los 12 juzgados como
puestos DISTINTOS, el motivo era casi siempre una marca de antigüedad que el léxico de
rango no ve: `SUPERVISOR CALIDAD` / `SUPERVISOR DE CALIDAD SR`, `CHEF DE COCINA` / `SOUS
CHEF DE COCINA`, `GERENTE DE INGENIERIA` / `GERENTE CORPORATIVO DE ING.`
**Evidencia:** `research/experimentos/e2_nivel/14_candado_de_seniority.py`.
**Estado:** **adoptado**. Requiere reconstruir la base para surtir efecto.

### Por qué un léxico aparte y no dentro de `RANGOS`

`SR` no es un escalón: un `SUPERVISOR DE CALIDAD SR` sigue siendo supervisor. Meterlo en
`RANGOS` rompería la escalera —medida sobre cinco escalones— y el `lambda` por nivel. Va
en `SENIORIDAD`, y **sólo sirve para impedir la fusión**, nunca para mover a nadie de
escalón.

### La selección de palabras, hecha contra los 48 ANTES de escribir el candado

| conjunto | caza (de 12 `no`) | rompe (de 36 `sí`) |
|---|---|---|
| solo `SR`/`JR` | 2 | 1 |
| + `SOUS` | 3 | 1 |
| **+ `CORPORATIVO`** | **5** | **1** |
| + `GENERAL` | 5 | 3 |
| + números y romanos | 5 | 4 |

`GENERAL` fuera: `SUPERVISOR DE ETIQUETADO` y `SUPERVISOR GENERAL DE ETIQUETADO` se
juzgaron el mismo puesto. Los números tampoco: de los escalones por dígito ya se ocupa
`_es_errata`. Sumado al candado de escalón que ya existía, los dos cubren **8 de los 12
`no` con 2 falsos positivos** sobre los 36 `sí` —los dos son del candado viejo, ninguno de
éste.

### Lo medido

Criterio declarado antes de correr: se adopta si el IC de la diferencia pareada **no** queda
entero sobre cero y la cobertura **no** cae más de 0,5 puntos.

| variante | grupos | pinball | dif vs hoy (IC 95%) | cobertura |
|---|---|---|---|---|
| hoy | 35.788 | 0,13471 | — | 55,4% |
| **candado** | 35.973 | 0,13465 | **−0,00002** [−0,00004, −0,00001] | 55,4% |
| candado_general | 36.011 | 0,13466 | −0,00000 [−0,00003, +0,00003] | 55,4% |

**Pasa los dos.** Pero el número agregado no es la evidencia interesante, porque está
diluido: el candado mueve el valor de 32.155 de los 34.435 votos, y sólo 1.017 de ellos
llevan marca de seniority. Partido por ahí:

| subconjunto | n | efecto | IC 95% pareado por empresa |
|---|---|---|---|
| cargos **CON** marca de seniority | 1.017 | **−0,000725** | **[−0,001274, −0,000221]** |
| cargos **SIN** marca | 33.418 | −0,000014 | [−0,000034, +0,000007] |

**El efecto está donde el candado actúa, y en ningún otro sitio.** Sobre los cargos tocados
el intervalo excluye el cero; sobre los 33.418 restantes cruza el cero, es decir el cambio
de partición no produce daño colateral.

### El placebo que el diseño dijo que no existía, existía

El fichero declara que un candado no admite placebo de permutación: una **fusión** tiene
destino que barajar, un candado sólo impide uniones. Es cierto para la permutación, pero
**el grupo sin marca es un control interno**: recibe exactamente el mismo cambio de
partición y ninguna intervención dirigida. Que ahí el efecto sea indistinguible de cero
mientras en el tratado excluye el cero es la separación que se quería. Corrige la nota del
docstring, que decía que este contraste no se podía construir.

### Lo que el contraste `GENERAL` NO demostró

El diseño esperaba que `candado_general` saliera peor y confirmara así que la selección de
palabras aportaba. **No lo hace:** sobre los cargos con marca da −0,000819
[−0,001391, −0,000305], estadísticamente indistinguible del candado bueno. El pinball no
tiene resolución para separar los dos conjuntos.

Dicho claro: **la exclusión de `GENERAL` está justificada por los 48 juicios humanos —3 `sí`
rotos contra 1—, no por esta medición.** El contraste salió no concluyente y se registra
como tal.

### La letra pequeña

Un candado **separa**, así que su fallo es el contrario del de una fusión: no contamina una
celda, la deja delgada. `TECNICO ESPECIALISTA EN MANTENIMIENTO` y `TECNICO DE
MANTENIMIENTO SR.` se juzgaron iguales y este candado los separa. Es el único falso
positivo medido, y se paga a cambio de cinco aciertos.

Todo medido sobre `train`. El 20% de test sigue sin tocarse.

---

## D-034 — Tres árbitros contra 48 juicios. **No se afina nada**, y la razón es el tamaño

**Fecha:** 2026-09-23
**Origen:** en la banda 0,93–0,97 los umbrales no separan —`SUPERVISOR PRODUCCION` /
`SUPERV. PRODUCCION` puntúa 0,941 y `INGENIERO BACK-END` / `INGENIERO FRONT-END` puntúa
0,940— y hace falta juicio. La pregunta era si merecía la pena entrenar un modelo para eso.
**Evidencia:** `research/experimentos/e2_nivel/13a_sacar_pares_ambiguos.py` y `13b_comparar_arbitros.py`.
**Estado:** **no concluyente por diseño insuficiente**. No se adopta ningún árbitro y no se
afina nada.

### Los tres árbitros

| | |
|---|---|
| **coseno** | el bi-encoder que ya decide hoy, corte en 0,95. Línea base |
| **cross congelado** | `mDeBERTa-v3-base-xnli`, inferencia natural en los dos sentidos, sin una sola etiqueta nuestra. **No supervisado** |
| **generativo** | Gemini en Vertex, sólo como techo. No es candidato: no es determinista y mete red en la construcción de la base |

Ninguno ve sueldos. Los tres reciben dos cadenas de texto, que es la regla
anticircularidad: un árbitro que decidiera mirando lo que paga cada lado optimizaría la
agrupación contra el salario por la puerta de atrás.

### Lo medido

| árbitro | acuerdo | en los `sí` | en los `no` | dice `sí` |
|---|---|---|---|---|
| coseno | 28/48 | 20/36 | 8/12 | 24/48 |
| generativo | 24/48 | 13/36 | **11/12** | 14/48 |
| cross congelado | 20/48 | 9/36 | **11/12** | 10/48 |

### La lectura que casi me trago

«El cross empata al generativo en los `no`, 11 de 12, y encima es determinista y offline.»

**Es falsa.** El cross contesta `no` **38 de 48 veces** cuando la verdad es `no` 12 de 48.
Una moneda que dijera `no` a ese mismo ritmo, **sin leer el texto**, acertaría 9,5 de los
12 por puro sesgo. La última columna no mide detección.

Contra esa moneda —misma tasa de `sí`, texto ignorado, 20.000 simulaciones—:

| árbitro | observado | esperado por sesgo | p |
|---|---|---|---|
| coseno | 28/48 | 24,0 | 0,159 |
| generativo | 24/48 | 19,0 | 0,075 |
| cross congelado | 20/48 | 17,0 | 0,189 |

**Ninguno de los tres se separa de una moneda sesgada.** Los tres apuntan en la dirección
buena y ninguno llega.

### Por qué eso no es un fracaso de los modelos

Con n=48 no podía llegar. Si las tasas observadas del cross fueran las verdaderas
(sensibilidad 0,25, especificidad 0,92), **la potencia de este diseño es del 17%**:

```
N= 48  17%      N=100  41%      N=200  63%      N=400  92%
```

El experimento estaba mal dimensionado antes de correrlo, y eso debió calcularse al
elegir 48. Es el mismo error de D-025 —criterio sin potencia— en otra forma.

### La decisión

**No se afina nada.** Afinar un modelo contra 48 juicios que no distinguen un modelo de una
moneda es afinar contra ruido, y produciría un número bonito sin contenido.

**El cuello de botella son las etiquetas, no el modelo.** Si se quiere responder esta
pregunta hay que juzgar ~400 pares. Con eso se decide *y además* se tiene con qué
entrenar, en ese orden. Hasta entonces el coseno se queda, no porque haya ganado sino
porque nadie ha demostrado ganarle.

### Una reserva sobre el generativo, que ya estaba dicha antes de ver el número

Su 11/12 salió con un prompt que le da **tres motivos para decir NO y prácticamente
ninguno para decir SÍ**. Su sesgo hacia el `no` es al menos en parte mío. Un prompt no es
una evaluación de un modelo, y ese número no debe citarse como «lo que puede un
generativo».

### Nota de ingeniería

`mDeBERTa-v3-base` en CPU tarda **~10 s por par** en esta máquina (12 hilos). Las 96
pasadas son ~17 minutos, y dos corridas anteriores murieron por tope de tiempo del
envoltorio antes de imprimir nada. No era la red: era el cómputo.

> **Corrección (2026-09-23, commit `c885afb`): no era el cómputo, era el tipo de dato.** El
> checkpoint viene en float16 y transformers 5 lo carga tal cual; en CPU el fp16 va ~10×
> más lento. Medido en lotes de 16 con 4 hilos: **954 ms/par en fp16, 90 ms/par en fp32**.
> Forzando `dtype=torch.float32` las probabilidades se mueven como mucho 0,0085, así que
> ningún AUC publicado cambia. Aparte, con acceso al Hub `from_pretrained` se quedaba
> colgado más de 10 min con los modelos ya descargados: hay que correr con
> `HF_HUB_OFFLINE=1`.

### Enmienda 1 (2026-09-23, mismo día): el árbitro cross estaba mal montado. Se retracta la conclusión sobre la inferencia natural

**Origen:** objeción del director del trabajo, en voz alta: *«yo creo que estás armando el
cross-encoder congelado mal, usa un cross-judge para medir si lo hiciste bien y
corregirte»*. Tenía razón.
**Evidencia:** `research/experimentos/e2_nivel/13c_arbitros_sin_umbral_fijo.py`.

### El defecto

Al cross se le puso un corte de **0,5** sobre la probabilidad de implicación, exigido
además **en las dos direcciones**. Ese número no salió de ninguna parte: el coseno
competía con su 0,95 calibrado en producción y el cross con un 0,5 puesto a dedo.

La comprobación de cordura que debió hacerse **antes** de interpretar nada —juzgar al
juez sobre casos de respuesta conocida— lo deja a la vista:

| par | verdad | entailment |
|---|---|---|
| `CONTADOR` / `CONTADOR` | idéntico | 0,966 |
| `CONTADOR` / `CONTADORA` | mismo puesto | **0,395** |
| `SECRETARIA` / `SECETARIA` | errata | 0,740 |
| `GERENTE GENERAL` / `CONSERJE` | opuesto | 0,001 |

**El corte de 0,5 rechaza `CONTADOR`/`CONTADORA`**, un par que el producto fusiona a
propósito (D-026). El modelo está sano: en NLI de libro de texto acierta 0,996 / 0,999 /
0,999 y el mapeo de etiquetas era correcto. Lo que estaba roto era mi regla de decisión.

**El corte óptimo real está en 0,003.** Puse 0,5, unas 170 veces más alto. En pares
difíciles las probabilidades de implicación viven pegadas a cero —mediana 0,50, mínimo
0,0007— y exigir el mínimo de las dos direcciones las hunde más. De ahí salía el «contesta
`no` el 79 % de las veces»: era el umbral, no el juicio del modelo.

### La medición corregida, sin umbral

El AUC no depende del corte, así que compara árbitros en igualdad de condiciones.

| árbitro | AUC | IC 95 % | permutación vs 0,50 | mejor corte |
|---|---|---|---|---|
| coseno | 0,601 | [0,410, 0,781] | p = 0,153 | 36/48 |
| **cross media** | **0,755** | **[0,588, 0,895]** | **p = 0,005** | 38/48 |
| cross mín (el de `13b`) | 0,725 | | | 38/48 |
| cross máx | 0,701 | | | 38/48 |

### Lo que se retracta

**«La inferencia natural no es la forma correcta de plantear esta pregunta» era falso.**
El cross-encoder congelado ordena estos pares claramente mejor que el azar —AUC 0,755, IC
excluye 0,50, p = 0,005— **sin una sola etiqueta nuestra**. Ahí hay señal real.

**El «20/48» de `13b` no medía el modelo, medía mi umbral.** Queda retirado como lectura
del cross-encoder.

### Lo que NO se retracta

**El cross sigue sin ganarle al coseno de forma demostrable:** la diferencia es +0,154 con
IC 95 % [−0,077, +0,389] y P(cross > coseno) = 0,90. Apunta a favor y no llega.

**Y el coseno aquí está medido en su peor terreno**, por construcción: los 48 pares se
sacaron de la banda 0,93–0,97, donde su propia variación es mínima. Su AUC de 0,601 no es
su AUC en general; es lo que le queda dentro de la zona donde ya se sabía que no separa.
No se lea como «el coseno ordena mal».

**Y el diagnóstico de potencia sigue en pie:** n = 48 es poco para decidir esto.

### Lo que cambia en la recomendación

D-034 concluía «no se afina nada» con un tono de *no hay nada que rascar*. **Eso cambia de
signo.** Un cross-encoder congelado que saca AUC 0,755 en la banda donde el coseno no
separa es evidencia **a favor** de invertir en esta vía, no en contra.

La conclusión operativa es la misma pero por la razón opuesta: **hay que juzgar ~400
pares.** Antes era «para descartar»; ahora es **«para explotar»** —con 400 se decide y
además se tiene con qué afinar—. El orden no cambia: primero las etiquetas, después el
modelo.

### La lección de método

Un modelo congelado se trae con un umbral que hay que calibrar, y yo lo traté como si
viniera calibrado. La regla que faltaba: **antes de interpretar el resultado de un árbitro
nuevo, pasarlo por casos de respuesta conocida** —idéntico, errata, opuesto— y mirar si
sus puntajes caen donde deben. Diez segundos de comprobación habrían ahorrado una
conclusión equivocada y firmada.

Vale también para lo que viene: el siguiente candidato natural no es un NLI sino un
**cross-encoder de reranking**, que puntúa «cuánto tiene que ver A con B» en vez de «A
implica B». Ese no se ha probado.

### Enmienda 2 (2026-09-23, mismo día): el reranking no gana, y el examen de cordura es necesario pero no suficiente

**Origen:** al cerrar la Enmienda 1 quedó dicho que el NLI era una elección mía y no
obviamente la correcta, y que el candidato natural sin probar era un cross-encoder de
**reranking** —que puntúa «cuánto tiene que ver A con B» en vez de «A implica B»—. El
director pidió traerlo y medirlo igual.
**Evidencia:** `research/experimentos/e2_nivel/13d_rerankers.py`.

### El examen de cordura, hecho y declarado ANTES de ver ningún AUC

| modelo | veredicto |
|---|---|
| `BAAI/bge-reranker-base` | **PASA.** Orden exacto: idéntico 9,72 > errata 7,94 > género 4,92 > seniority 3,89 > área 0,21 > opuesto −0,82 |
| `cross-encoder/mmarco-mMiniLMv2` | **FALLA.** Pone `SUPERVISOR CALIDAD`/`SUPERVISOR DE CALIDAD SR` —distintos— en lo más alto (2,38), por encima de `CONTADOR`/`CONTADOR` idéntico (−0,23), y hunde la errata (−1,61) |

`mmarco` quedó descalificado como candidato antes de medirlo, y se midió igual.

### Lo medido

| árbitro | AUC | IC 95 % | permutación vs 0,50 |
|---|---|---|---|
| **cross NLI media** | **0,755** | [0,594, 0,894] | **p = 0,003** |
| bge-reranker máx | 0,674 | [0,495, 0,834] | p = 0,037 |
| bge-reranker media | 0,660 | [0,470, 0,831] | p = 0,051 |
| coseno (producción) | 0,601 | [0,417, 0,776] | p = 0,148 |
| mmarco *(descalificado)* | 0,479 | [0,294, 0,674] | p = 0,589 |

Pareado: `bge` vs coseno **+0,059** [−0,157, +0,260]; `bge` vs cross NLI **−0,095**
[−0,306, +0,139].

### La hipótesis era razonable y es falsa

«El NLI es una pregunta prestada y el reranking la propia» sonaba bien y no se sostiene.
**El NLI ordena mejor**, y el reranker no se separa ni del coseno ni del azar.

La explicación probable: **la implicación es asimétrica y aquí eso es justo lo que hace
falta.** `JEFE DE MONTAJE Y SOLDADURA` implica a `JEFE DE MONTAJE` pero no al revés, y esa
asimetría *es* la señal de que uno es más amplio que el otro. Un puntaje de relevancia no
tiene forma de expresar «distintos porque uno es más estrecho». Lo que parecía una
pregunta prestada resulta tener la forma correcta.

### El examen de cordura se valida a medias, y hay que decir las dos mitades

**Funciona como criba.** `mmarco` falló el examen y salió exactamente en el azar (AUC
0,479, p = 0,59). El examen lo predijo con seis parejas, sin gastar los 48 juicios.

**No funciona como ranking.** `bge` pasó el examen con el orden exacto y aun así pierde
contra el NLI. Ordenar bien seis casos fáciles no predice discriminar casos difíciles: son
habilidades distintas.

**El examen es necesario, no suficiente.** Descarta modelos rotos; no elige entre modelos
sanos. Esto **acota la lección de la Enmienda 1**, que lo dejaba sonando más potente de lo
que es: comprobar casos conocidos habría evitado la conclusión falsa de `13b`, pero no
habría bastado para elegir árbitro.

### Dónde queda esto

El mejor candidato congelado sigue siendo el **cross-encoder NLI**, con AUC 0,755 y p =
0,003, sin una sola etiqueta nuestra. El reranking se descarta como vía. El coseno de
producción se queda donde está.

Y no cambia el cuello de botella: los cuatro intervalos son anchísimos con n = 48.
**~400 pares juzgados** siguen siendo el paso que desbloquea todo lo demás.

### Enmienda 1 (2026-09-23, mismo día): el guion declaró NO CONCLUYENTE y no lo vi

**Origen:** al revisar qué resultados habían quedado guardados apareció, en la salida del
propio experimento, una línea que la redacción de arriba ignora.

```
  votos donde R05 CAMBIA la rama: 11
    POCOS: el placebo no discriminaria. NO CONCLUYENTE.
  votos donde R10 CAMBIA la rama: 16
    POCOS: el placebo no discriminaria. NO CONCLUYENTE.
```

El fichero declaró **antes de correr** que con menos de 30 votos cambiando de rama se
declara NO CONCLUYENTE, como pasó en `11`. El guardarraíl **disparó**, y arriba escribí
«pasa los tres criterios». Leí la tabla final y me salté la línea de encima.

### Al adjudicarlo, el guardarraíl resulta ser una falsa alarma

El guardarraíl existe para no cantar un resultado cuando el placebo no tiene potencia. Aquí
sí la tenía, y se comprueba comparando las huellas:

| | votos con valor movido | cambian rama |
|---|---|---|
| R05 | 33.061 | 11 |
| R05 placebo | 33.020 | 11 |

**Huella prácticamente idéntica y daño 30 veces mayor en el placebo** (+0,00119 contra
+0,00004). Con la misma cantidad de gente movida, mandar las absorciones a destinos al
azar cuesta treinta veces más que mandarlas a los que elige la regla. Eso es exactamente
lo que un placebo tiene que demostrar.

**El guardarraíl usó el estadístico equivocado.** «Cambios de rama» aproxima mal la
potencia: mide a cuánta gente se le cambia la *fuente* de la respuesta, no a cuánta se le
cambia el *valor*. En `11` las dos cosas iban juntas —5 votos, nada se movía—; aquí no.

### Qué se corrige y qué no

**La conclusión no cambia:** `R05` sigue sin adoptarse, por lo que dice el cuerpo de
D-032 —no resuelve ninguna queja, el efecto es indistinguible de cero y de signo adverso—.

**Lo que se corrige es el proceso.** Un guardarraíl pre-registrado que dispara hay que
**adjudicarlo por escrito**, aunque se concluya que fue falsa alarma. Saltárselo sin verlo
y llegar por casualidad a la misma conclusión no es haber acertado: es no haber mirado.

**Y queda una tarea para el diseño:** el criterio de potencia de `11` y `12` debe pasar de
contar cambios de rama a contar **votos con el valor movido**, que es lo que de verdad
determina si el placebo puede discriminar.

---

## D-035 — Etiquetas de plata con un LLM: la rúbrica v3 y `gemini-3.8-flash` pasan contra 200 juicios

**Fecha:** 2026-09-25
**Origen:** D-034 cerró con «el cuello de botella son las etiquetas, no el modelo». Juzgar a
mano los ~10.000 pares que harían falta para ajustar el cross no es viable; la propuesta
es que los etiquete un LLM y validar antes ese montaje contra juicios humanos.
**Evidencia:** `research/experimentos/e2_nivel/13e_lote_de_400.py` (el patrón de oro),
`rubrica_mismo_cargo.md` (v1 → v3) y `15_piloto_llm.py` (el piloto). Las respuestas y los
juicios son CSV con títulos de clientes y no se versionan (regla LOPDP del `.gitignore`).
**Estado:** **adoptado para generar etiquetas de entrenamiento.** No toca el producto.

### Por qué no contradice D-034

D-034 descartó al generativo **como árbitro del producto**: no es determinista y mete red en
la construcción de la base. Aquí no decide nada en el producto. Etiqueta una vez, fuera de
él, los datos con los que se ajustará el cross; lo que llegaría al producto es ese cross,
local y determinista.

Y la reserva de D-034 —su 11/12 salió de un prompt con tres motivos para decir `no`— es
justo lo que este diseño corrige: el LLM recibe la misma rúbrica que el juez humano, y se
mide contra él antes de usarlo.

### El montaje

- **Patrón de oro:** los 400 pares de `13e`, juzgados a mano y a ciegas (sin `sim`),
  partidos en 200 `calibra` / 200 `prueba` antes de la primera etiqueta. En `calibra`, el
  72 % son `si`.
- **La rúbrica**, cinco pasos en orden. La v1 salió de los 48 de `13a`; la v2 se cerró
  contra los 400 (un verificador mecánico de los pasos 1, 2, 3 y 5 reproduce las 400
  etiquetas salvo dos que lee mal). En la revisión se corrigieron 13 etiquetas con el
  autor; el valor juzgado queda en `mismo_v1`.
- **El LLM:** `gemini-3.8-flash`, un par por petición (sin arrastrar los anteriores), en
  los dos órdenes A/B y B/A, temperatura 0, salida JSON con esquema. Solo ve los dos
  títulos.

### La compuerta, fijada antes de ver una respuesta

El acierto no sirve: con 72 % de `si`, contestar siempre `si` acierta el 72 %. Se usa
**kappa**, que descuenta el acuerdo por azar. En los dos órdenes: **kappa ≥ 0,60**
(«sustancial», Landis y Koch 1977), **recall de `no` ≥ 0,70** y **coherencia A/B = B/A ≥
0,90**. Solo se puntúa `calibra`; el guion no tiene opción para puntuar `prueba`.

### Lo medido, en `calibra`

| | v2 | **v3** |
|---|---|---|
| kappa A/B · B/A | 0,640 · 0,662 | **0,790 · 0,802** |
| recall de `no` | 0,93 · 0,95 | 0,77 · 0,77 |
| coherencia | 0,970 | **0,995** |
| kappa por estrato: bajo · banda · alto | 0,29 · 0,67 · 0,84 | **0,53 · 0,83 · 1,00** |
| desacuerdos | 33 (29 separa de más) | **16** (13 junta de más, 3 separa de más) |

### La v2 pasaba, pero con la medición inflada

La v2 usaba **34 títulos de `calibra` como ejemplos, con su respuesta**, y el LLM los veía.
Se habían tomado de `calibra` para proteger `prueba`, sin ver que así se contaminaba la
mitad con la que se decide. En la v3 todos los ejemplos son inventados, y se comprobó por
búsqueda que ninguno coincide con un título de los 400. **La v3 mejora aun sin esa ayuda.**

### Qué arregló la v3, y qué no se puede arreglar

La v2 separaba de más, y siempre en el paso 4: el juez junta dos títulos que comparten la
función principal aunque la segunda sea otra, y el texto era más estricto que eso. La v3
reescribe el paso 4 alrededor de la función principal compartida, y en la duda dice `si`.

El sesgo cambió de sentido: ahora junta algo de más. Pero la mayoría de esos 13 son casos en
los que **el propio juez no es uniforme**: `SUPERVISOR DE PLANTA` / `… Y PROYECTO` es `no` y
`JEFE DE DESARROLLO Y PROCESOS` / `… Y GESTION` es `si`, con la misma estructura. Ninguna
regla escrita reproduce las dos cosas. Por eso **se congela la v3 aquí**: otra vuelta
ajustaría el ruido de 200 pares y no generalizaría a 10.000.

### Alternativas descartadas

- **Pegar los pares en un chat** (Gemini o Claude): gratis con la suscripción, pero no
  valida el montaje que etiquetará los 10.000, cada par ve los anteriores, no deja registro
  reproducible y, en el nivel gratuito, las conversaciones pueden usarse para entrenar.
- **`gemini-2.5-pro`**: medido solo en la muestra de coste; piensa ~5 veces más por
  respuesta (977 frente a 199 tokens) y no hace falta si Flash pasa.
- **Modelos `preview` o alias `-latest`**: cambian por detrás; los 10.000 no serían
  reproducibles.
- **Seguir iterando la rúbrica**: ver arriba.

### Límites que hay que declarar

- **La v2 y la v3 se escribieron viendo también `prueba`.** Las reglas se ajustaron a las
  400 etiquetas, así que el acuerdo en `prueba` saldrá algo optimista.
- **No se conoce el acuerdo del juez consigo mismo** en el paso 4, que es el techo real del
  kappa. Se puede acotar re-etiquetando a ciegas ~50 pares de `calibra`.
- **Un solo juez humano.**
- **Pendiente de documentar:** el permiso para mandar los títulos a Gemini y el nivel de la
  cuenta (gratuito o de pago), que decide si Google puede usar lo enviado.

### Reversibilidad

Total. Cada respuesta guarda el hash de la rúbrica con que se pidió, así que otra versión
no se mezcla con esta y el piloto se puede repetir entero por unos céntimos.

### Siguiente

`prueba` se juzga **una sola vez** con la v3 y queda cerrada hasta la comparación final.
Después, los ~10.000 pares y la curva de aprendizaje del cross ajustado.

---

## D-036 — El eje de la tesis pasa a ser el juez de «mismo cargo». Arquitectura y prerregistro

**Fecha:** 2026-09-25
**Origen:** decisión del autor: el aporte de IA de la tesis está en decidir qué cargos son el
mismo y agruparlos, no en medir el techo del 12 % de error del benchmark. Se discutieron
cuatro arquitecturas propuestas por Gemini, y de todas se tomaron piezas (ver abajo).
**Evidencia:** `research/experimentos/e2_nivel/17_lineas_base_agrupamiento.py` (líneas
base, solo `calibra`). Diagrama: <https://claude.ai/artifact/2xH4KY8WVVo9AkKoaeSfZW>
(privado). Inventario de archivos: `docs/inventario_arquitectura_juez.md`.
**Estado:** **diseño registrado antes de entrenar.** H1 queda fija aquí; nada de lo que
sigue se ha medido contra `prueba`. **La Enmienda 1, al final, cambia la selección de
modelo a `calibra` y añade el oro lejano y la capa A0; la Enmienda 2 amplía `prueba` a 600
pares y añade H1b; la Enmienda 3 fija cómo se entrena B; la Enmienda 4 deja
`prueba` en 591; la Enmienda 5 hace que el grado (número, romano o letra) no separe,
revierte esa parte de D-025 y deja `calibra` en 191 y `prueba` en 555.**

### El cambio de eje

La pregunta de la tesis deja de ser «¿cuánto error del benchmark se puede reducir?» y pasa a
ser:

> ¿Se puede aprender un juez de «mismo cargo» que supere a la similitud de embeddings sobre
> títulos ruidosos en español, aprovechando que la relación es asimétrica (un orden de
> generalidad), y convertir sus juicios en grupos consistentes a escala?

El benchmark salarial no desaparece: queda como **capítulo de utilidad aguas abajo**, medido
con el protocolo de siempre (pinball en q = 0,25/0,75, partición por empresa, placebo). No
tiene que ganar por mucho; tiene que mostrar que acertar más pares no es irrelevante para la
banda.

Lo que ya estaba escrito se reutiliza: el resultado negativo de la composición motiva el
problema, la ceguera jerárquica (D-012) motiva el castigo por nivel, y la consolidación por
coseno 0,95 con enlace completo (`07`) es la línea base.

### La hipótesis de fondo

«Ser el mismo cargo» no es un puntaje de similitud: es una **equivalencia que sale de un
orden parcial de generalidad**. Dos cargos son el mismo cuando cada uno incluye al otro.
Viene de la Enmienda 2 de D-034: el NLI le gana al reranker porque la implicación es
asimétrica (`JEFE DE MONTAJE Y SOLDADURA` implica `JEFE DE MONTAJE`, no al revés).

### La arquitectura

| capa | qué hace | cómo | se mide con |
|---|---|---|---|
| **0** | registros → cargos únicos | la normalización de hoy (género, erratas, `nivel_lexico`) | — |
| **A · recuperar** | k vecinos por cargo; no decide | bi-encoder ajustado de forma contrastiva **con plata** o destilado de B; variante con n-gramas de caracteres | Recall@K |
| **B · juzgar** | P(mismo) por par | `mDeBERTa-v3-base-xnli` ajustado con plata; el par entra en los dos órdenes; P(mismo) = P(A⊑B)·P(B⊑A); cabeza auxiliar del motivo (paso de la rúbrica); peso extra en la pérdida cuando el error confunde nivel; aumento solo con erratas sintéticas | AUC, calibración |
| **C · agrupar** | grupos transitivos | correlation clustering sobre log-odds de P(mismo); sin «ruido» descartado; nombre = medoide | F1 por pares, kappa, estabilidad |

**Las direcciones no se supervisan.** La plata dice sí/no, no «A es más estrecho». Solo se
supervisa el producto; cada dirección queda latente y arranca de un NLI que ya es asimétrico.
Que signifiquen algo es H3, no un supuesto. Así no se toca la rúbrica v3 congelada.

**Qué datos tocan qué.** La plata `entrena` ajusta B; la plata `valida` elige época e
hiperparámetros; B se destila en A; el oro `calibra` solo fija el umbral de C; el oro
`prueba` se abre **una vez**, con todo congelado. El oro nunca entrena.

### El flujo de un cargo nuevo (nómina de un cliente)

La base no se reagrupa. Cada título no exacto pasa por A (índice precalculado) y B, y se
asigna al grupo que maximiza Σ log-odds de P(mismo) con sus miembros: la versión incremental
del criterio de C. Tres ramas: **directa** (grupo claro), **referencia más general** (el
nuevo es más estrecho que un grupo; se trata como analogía de un vecino y nunca sale ALTA;
solo si H3 se sostiene) y **analogía** (var = 1/W + λ(1 − P(mismo)), con λ reestimado). Los
títulos nuevos van a una cola y entran en la siguiente reconstrucción: la nómina de un cliente
no redefine los grupos contra los que se le compara.

### Qué cambia en las bandas

La fórmula no cambia; cambia **quién vota en cada celda**. Fusionar de más mete empresas de
otro nivel, estira la banda y mueve el centro; separar de más deja celdas bajo 10 empresas,
sin cuantiles empíricos y con menos confianza. A vigilar: τ<sub>c</sub> y σ<sub>c</sub> se
reestiman; posible doble castigo entre P(mismo) y la penalización de nivel del vecindario
(medir con y sin); más cobertura directa mejora por construcción, así que el placebo es
obligatorio.

### Prerregistro

**H1 (comparación principal, la única confirmatoria).** B supera al coseno preentrenado en
AUC sobre `prueba`.
- **Puntaje de B:** P(mismo) del modelo elegido en plata `valida`, sin mirar el oro.
- **Comparadores:** coseno de `base_v15` y NLI congelado (media de las dos direcciones, `13c`).
- **Etiqueta:** columna `mismo` de `13e_para_juzgar.csv` (v3); `duda` fuera.
- **Prueba:** bootstrap pareado por par, 10.000 remuestreos, IC 95 % de ΔAUC.
- **Se adopta** si el IC 95 % de AUC(B) − AUC(coseno) queda entero sobre 0. Contra el NLI
  congelado se reporta la diferencia con su IC, sin criterio de adopción.
- **Potencia declarada:** con ~200 pares, la potencia es limitada (D-034: 63 % para el
  efecto del cross congelado). Un resultado nulo se leerá como «no demostrado», no como
  «no funciona».

**H2 (secundaria).** Con el mismo juez, correlation clustering supera a las componentes
conexas en kappa sobre `calibra`, y las componentes conexas percolan (grupo mayor ≫ el de
correlation clustering).

**H3 (exploratoria).** Las direcciones de B recuperan el orden de generalidad en un conjunto
pequeño de pares de dirección evidente, armado antes de mirar las salidas de B.

**Secundarios, descriptivos:** tabla factorial juez {coseno, A, B} × algoritmo {HDBSCAN,
componentes conexas, Leiden, correlation clustering}; Recall@K; ablaciones de B (sin motivo,
sin peso por nivel, simétrico, interacción tardía tipo ColBERT); curva de aprendizaje de 500 a
10.000; aprendizaje activo simulado (azar contra incertidumbre, LLM de oráculo); asignación
dejando uno fuera; utilidad aguas abajo en las bandas.

### Líneas base medidas hoy (`17`, solo `calibra`, 200 pares, 72 % `si`)

**El F1 del `si` engaña con esta tasa base.** Decir `si` a todo da F1 ≈ 0,84. Por eso la
métrica de agrupamiento que se reporta es **kappa**, con F1 al lado.

| método sobre coseno | t | prec | rec | F1 | kappa | grupo mayor |
|---|---|---|---|---|---|---|
| componentes conexas | 0,90 | 0,715 | 0,958 | 0,819 | −0,032 | **21.101** |
| componentes conexas | 0,94 | 0,760 | 0,660 | 0,706 | 0,112 | 296 |
| componentes conexas | 0,95 | 0,808 | 0,438 | 0,568 | 0,125 | 32 |
| pivote (corr. clust.) | 0,93 | 0,768 | 0,438 | 0,558 | 0,073 | 18 |
| pivote (corr. clust.) | 0,95 | 0,810 | 0,326 | 0,465 | 0,088 | 7 |
| HDBSCAN, PCA-32, mcs = 2 | — | 0,830 | 0,507 | 0,629 | **0,183** | 24 (41 % ruido) |
| HDBSCAN, PCA-32, mcs = 5 | — | 0,721 | 0,986 | 0,833 | 0,006 | **45.183** |
| Leiden (modularidad) | 0,94 | 0,766 | 0,660 | 0,709 | 0,128 | 154 |
| HDBSCAN, UMAP-10, mcs = 2 | — | 0,778 | 0,340 | 0,473 | 0,063 | 100 (26 % ruido) |
| HDBSCAN, UMAP-10, mcs = 5 | — | 0,715 | 0,611 | 0,659 | −0,012 | 360 (29 % ruido) |

Estabilidad (ARI contra un 80 % de los grupos, media de 3):

| método | t = 0,93 | t = 0,95 |
|---|---|---|
| componentes conexas | 0,625 | 0,927 |
| **pivote** | **0,918** | **0,961** |
| Leiden | 0,506 | 0,920 |
| HDBSCAN PCA, mcs = 2 | 0,797 | |
| HDBSCAN UMAP, mcs = 2 (UMAP reajustado) | 0,347 | |

Curva completa en `salidas/17_lineas_base.txt`. Lectura:

- **Sobre el coseno, el mejor kappa es 0,18.** Lo saca HDBSCAN con mcs = 2 a costa de
  dejar como ruido el 41 % de los grupos. Lo demás queda por debajo de 0,13. El algoritmo
  cambia cuánto se junta, no si se junta bien. Es la línea base que tiene que batir B, y la
  razón de que el juez sea el centro de la tesis y no el algoritmo.
- **La percolación se reproduce a nivel de grupo:** 21.101 grupos en uno con componentes
  conexas a 0,90, y 45.183 con HDBSCAN mcs = 5. Los dos tienen F1 alto y kappa nulo.
- **La receta estándar, UMAP + HDBSCAN, es la peor aquí:** kappa 0,06 y −0,01, y la menos
  estable (ARI 0,347). UMAP deforma las distancias finas que esta tarea necesita. Cierra la
  objeción «¿por qué no hicieron lo de BERTopic?».
- **Leiden no aporta sobre las componentes conexas:** a 0,95 da exactamente lo mismo, y a
  0,93 es menos estable (0,506).
- **El pivote es el más estable** con el mismo grafo (0,918 a 0,93, contra 0,625 de las
  componentes conexas y 0,506 de Leiden): un apoyo temprano, en el coseno, para la elección
  de C.
- AUC del coseno en estos pares: 0,616.

**Recall@K** de los pares `si` (rango del mejor de los dos sentidos): @10 = 0,92, @20 =
0,96, @25 = 0,97. En el estrato bajo (0,90–0,93) cae a @10 = 0,62 y @20 = 0,81, con n = 16.

**Tamaño:** 50.296 grupos; con k = 20, ~503.000 pares únicos × 2 direcciones × 0,09 s ≈
25 h de CPU para construir la base. Viable una vez, no para iterar: hace falta GPU o k = 10
(~12,6 h) para la reconstrucción.

### Lo que se tomó y lo que se descartó de las propuestas de Gemini

| propuesta | se tomó | se descartó, y por qué |
|---|---|---|
| retrieve & rerank contra catálogo | Recall@K; peso por nivel; aumento con erratas; F1 por pares | **el catálogo**: no existe, y ESCO es demasiado grueso para la rúbrica; **el grafo de conocimiento hecho a mano**: la descomposición nivel + área se aprende en la cabeza de motivo; **la capa fonética**: el transformer ya aguanta erratas y D-026 ya resolvió el género (queda como línea de ablación); **permutar palabras**: rompe `ASISTENTE DE GERENCIA` / `GERENTE ASISTENTE`, su propio ejemplo |
| clustering no supervisado (UMAP + HDBSCAN) | HDBSCAN como línea base; estabilidad por remuestreo; n-gramas de caracteres; nombre por medoide | **la premisa «no hay etiquetas»**: hay 400 de oro y 10.000 de plata; **agrupar en el espacio del coseno**: es el que falla en 0,93–0,97 (D-034), y la tabla de arriba lo confirma; **silueta y Davies-Bouldin**: miden compacidad en el mismo espacio, son circulares |
| semi-supervisado con aprendizaje activo | curva de aprendizaje; aprendizaje activo **simulado**; ajuste contrastivo del bi-encoder | **entrenar con los 400 de oro**: deja sin con qué medir; **aprendizaje activo humano**: las etiquetas las pone el LLM; **pares elegidos por AL como prueba**: están sesgados |
| métrica ajustada + componentes conexas | Leiden y componentes conexas como columnas; bi-encoder ajustado como competidor | **componentes conexas como método**: es enlace simple y percola (`06`, y la tabla de arriba); **H2 de Gemini**: cambia espacio y algoritmo a la vez; **«datos sintéticos»**: son etiquetas de un LLM sobre pares reales |

### Límites que hay que declarar

- **El oro no ve nada por debajo de 0,90 de coseno.** `13e` muestreó solo 0,90–1,01. El
  Recall de A por debajo de 0,90 no se puede medir con este oro; hace falta un estrato nuevo
  para eso.
- **El oro son pares entre grupos distintos de hoy.** Mide «¿deberían fundirse estos dos
  grupos?», no la calidad de los grupos que ya existen.
- **La plata tiene techo.** Kappa del LLM de 0,53 en el estrato bajo; B difícilmente supere
  al LLM contra el juez. El argumento es igualarlo siendo local, determinista y barato.
- **Un solo juez humano**, y la rúbrica v3 se escribió viendo también `prueba` (D-035).
- **Las líneas base no se afinaron.** HDBSCAN (PCA-32 y UMAP-10) y Leiden corrieron con un
  solo juego de hiperparámetros cada uno. Afinarlos contra `calibra` sería optimista; queda
  dicho que un HDBSCAN afinado podría subir algo.

### Referencias

- Reimers, N. y Gurevych, I. (2019). *Sentence-BERT*. EMNLP.
- Thakur, N. et al. (2021). *Augmented SBERT*. NAACL.
- He, P., Gao, J. y Chen, W. (2023). *DeBERTaV3*. ICLR.
- Khattab, O. y Zaharia, M. (2020). *ColBERT*. SIGIR.
- Vendrov, I. et al. (2016). *Order-Embeddings of Images and Language*. ICLR.
- Vilnis, L. et al. (2018). *Probabilistic Embedding of Knowledge Graphs with Box Lattice
  Measures*. ACL.
- Bansal, N., Blum, A. y Chawla, S. (2004). *Correlation Clustering*. Machine Learning 56.
- Ailon, N., Charikar, M. y Newman, A. (2008). *Aggregating Inconsistent Information:
  Ranking and Clustering*. JACM 55(5).
- Traag, V., Waltman, L. y van Eck, N. (2019). *From Louvain to Leiden*. Scientific Reports 9.
- Campello, R., Moulavi, D. y Sander, J. (2013). *Density-Based Clustering Based on
  Hierarchical Density Estimates*. PAKDD.
- Decorte, J.-J. et al. (2021). *JobBERT: Understanding Job Titles through Skills*. arXiv
  2109.09605.
- Ein-Dor, L. et al. (2020). *Active Learning for BERT: An Empirical Study*. EMNLP.
- Lowell, D., Lipton, Z. y Wallace, B. (2019). *Practical Obstacles to Deploying Active
  Learning*. EMNLP.

Datos bibliográficos a verificar antes de citarlos en la tesis.

### Reversibilidad

Total para el código: nada de esto toca el producto hasta que B gane H1. El cambio de eje sí
obliga a reescribir el resumen, «La reformulación» y la defensa del modelo simple en
`docs/tesis/tesis.tex`, y a reorientar `docs/estado_del_arte.md` hacia la literatura de
normalización y similitud de títulos de cargo.

### Siguiente

1. Terminar `etiquetar` sobre el lote de 10.000 (al escribir esto hay 4.830 respuestas guardadas) y juzgar
   `prueba` con la v3.
2. Entrenar B por pasos: simétrico, luego direccional, luego motivo y peso por nivel.
3. Destilar A; completar la tabla factorial; utilidad aguas abajo.
4. En paralelo: literatura para la novedad; más oro o un segundo anotador sobre una muestra.

### Enmienda 1 (2026-09-25, antes de entrenar): selección en `calibra`, oro lejano y recuperación por unión de fuentes

**Origen:** revisión del prerregistro con otra sesión de Claude y con el autor, antes de
ajustar un solo peso. Todo lo que sigue se registra **antes** de ver cualquier resultado de B.
**Evidencia nueva:** la tabla de rangos de abajo (medida sobre `base_v15`) y el recuento de
incoherencias de la plata (`salidas/16_respuestas_llm.csv`, ya completa: 20.000 respuestas,
cero errores).

#### El hallazgo que motiva la mitad de esta enmienda

El Recall@25 = 0,97 de `17` solo describe la franja que el oro ve (coseno ≥ 0,90). Con
sinónimos de palabras distintas —pares elegidos para ilustrar, **no juzgados**— la
recuperación por coseno no funciona:

| par | coseno | rango del grupo entre los vecinos |
|---|---|---|
| `JEFE DE TALENTO HUMANO` / `JEFE DE RECURSOS HUMANOS` | 0,881 | 46 |
| `GUARDIA` / `AGENTE DE SEGURIDAD` | 0,706 | 122 |
| `CHOFER` / `CONDUCTOR` | 0,588 | 1.601 |
| `VENDEDOR` / `ASESOR COMERCIAL` | 0,683 | 2.076 |
| `MENSAJERO` / `MOTORIZADO` | 0,589 | 11.131 |

Ninguno está hoy en el mismo grupo, y con k = 20–25 ninguno llegaría al cross.

**Esto corrige en parte a D-012**, que concluía que «los embeddings sí resuelven los
sinónimos». Los resuelven para variaciones cercanas del mismo texto, no para sinónimos de
vocabulario distinto. D-030 ya lo había visto de lado (`DENTISTA` puntúa 0,752 con
`TELEFONISTA` y 0,763 con `ODONTOLOGA`).

#### Lo que cambia

**1. La selección de modelo se hace en `calibra`, no en la plata `valida`.** Reemplaza la
frase de D-036 «la plata `valida` elige época e hiperparámetros». Elegir con la plata es
elegir el modelo que mejor imita a Gemini.
- `prueba` sigue cerrada: elegir con ella invalidaría H1.
- Con 200 pares (144 `si`, 56 `no`) y AUC ~0,75, el IC 95 % del AUC es de **±7 puntos**
  (Hanley y McNeil). Por eso la grilla es chica y se fija aquí: **w ∈ {1, 2, 3} × aumento
  {con, sin}**, seis configuraciones, con el peso del motivo fijo en 0,3. w = 1 es el control.
- Las diferencias entre configuraciones se miden con bootstrap pareado. **Regla de
  desempate:** si la mejor no le gana a la más simple con un IC que excluya el cero, se
  elige la más simple.
- La plata `valida` se reporta al lado. Si elige otro modelo, eso mide cuánto se aleja
  Gemini del juicio humano.
- **La calibración por temperatura también se hace en `calibra`**, porque la probabilidad
  tiene que reflejar el juicio humano.
- Costo declarado: `calibra` pasa a tener cuatro usos (líneas base, umbral de C, selección y
  calibración). Sus números serán optimistas; la vara es `prueba`.

**2. Los pares en que Gemini se contradijo entre órdenes no se descartan.** Son **139 de
10.000 (1,39 %)**, no «la mitad de la señal». Probablemente son la frontera. Entran al
entrenamiento con **etiqueta blanda 0,5** y se juzgan a mano con la rúbrica v3 y a ciegas.
Juzgados, **sirven para entrenar, no para evaluar**: están elegidos por ser difíciles para
Gemini y son una muestra sesgada.

**3. Aumento de datos, las dos formas como filas de la ablación:**
- **Erratas** solo con los patrones medidos en `10` (letra cambiada, borrada o transpuesta).
  Se mantienen porque el cross sí las verá: el 1,0 % de la plata (98 pares) difiere en una
  sola errata, y los títulos de un cliente no pasan por la fusión por errata.
- **Permutación controlada**: mover los modificadores de seniority (`SR`, `JR`, `I`, `II`) e
  intercambiar segmentos unidos por `Y` o coma, **sin mover la palabra que nombra el
  puesto**. En la plata hay 244 pares con las mismas palabras en otro orden, los 244 `si`;
  la permutación libre fabricaría `GERENTE ASISTENTE` = `ASISTENTE GERENTE`.

**4. El kappa de Gemini se declara por estrato** (v3, `calibra`): **bajo 0,53** (n = 30),
banda 0,83, alto 1,00; global 0,79/0,80. No es un acuerdo moderado en general: es menos
fiable justo en el estrato donde el producto hoy no fusiona.

**5. Oro por debajo de 0,90, como requisito.** Sin él no se puede medir si A mejora el
recall, que es su razón de ser. Al azar no sirve: casi todos los pares lejanos son `no`.
Se hace por **agrupación de candidatos** (el *pooling* de TREC):
1. unos 100 grupos ancla al azar, con respaldo suficiente;
2. candidatos de varias fuentes por ancla: vecinos de coseno hasta el rango ~500, los que
   proponga Gemini sobre el catálogo y, cuando existan, los de A;
3. juicio humano ciego de todo lo propuesto, más una muestra al azar del resto;
4. partición `calibra` / `prueba` **antes** de juzgar.

El recall que sale es **relativo** a lo agrupado, y así se reporta.

**6. Positivos lejanos en el entrenamiento de A y de B.** La plata de `16` sale de 0,90–1,01
y no tiene ningún `CHOFER` / `CONDUCTOR`. Sin positivos lejanos, el adaptador no puede
aprender sinónimos que nunca vio, y el cross juzgaría pares distintos de los que vio al
entrenar. Se sacan del mismo agrupamiento, con **grupos ancla disjuntos de los de
evaluación**.

**7. Capa nueva, A0: una descripción por título, solo para recuperar.** Gemini escribe una
descripción corta de cada título («conduce vehículos de la empresa»), se embebe, y la
recuperación pasa a ser la **unión** de los vecinos del título, los de la descripción y, más
adelante, los del adaptador.
- **D-030 no la bloquea:** su plantilla fija dio nulo en la banda pero mejoró los pares
  (2/5 → 4/5), y con el eje de D-036 lo que manda son los pares.
- **Nunca entra al juez.** Una descripción puede borrar el nivel («gestiona la bodega» vale
  para jefe y auxiliar). Como solo agrega candidatos, lo peor que puede costar es cómputo.
- Reproducible con la disciplina de D-035: versión fija, temperatura 0, caché y hash de la
  instrucción.
- Si Gemini falla, la recuperación sigue solo con el título.
- Se mide cuántos pares nuevos aporta cada fuente, con un tope de k por fuente.
- **Queda condicionada al permiso** para mandar títulos a Gemini (pendiente desde D-035).
- En la ablación: solo título, solo descripción, unión.

**8. C: el costo solo cuenta pares observados.** Los pares que no pasaron por el cross, que
son casi todos, pesan cero. Tratarlos como `no` castigaría justo los sinónimos que la
recuperación perdió.

```
costo = Σ sobre pares observados de  [ si cortado × log-odds  +  no juntado × |log-odds| ]
```

El pivote se corre con **~20 semillas** y se queda la de menor costo, más una **búsqueda
local** que mueve cada cargo al grupo que más baja el costo hasta que ninguno mejora (Elsner
y Schudy 2009, a verificar). Se reportan dos estabilidades: ARI entre semillas y ARI contra
un 80 % de los datos. **Nota sobre `17`:** su pivote sobre el coseno trata lo no observado
como `no` y usa una sola semilla. Es aceptable como línea base, pero no es la regla de C, y
se rehará con esta regla para que la comparación sea justa.

**9. Plantilla de entrada del cross, fija desde ya:** la misma que usó `13c`, para que el AUC
0,755 del NLI congelado siga siendo comparable. Se documenta en el guion de entrenamiento.

**10. Lo que se discutió y no se adopta:**

| propuesta | por qué no |
|---|---|
| clasificador ordinal de nivel sobre el embedding | ya medido y descartado: `e2_nivel/01` (98,9 % solo por leer la palabra; 58 % de los títulos sin rango al nivel 1) y `02` (tapar el rango tampoco). El embedding es ciego al nivel (D-012). Sí vale ampliar el léxico de rango con Gemini, validado contra el 38,6 % donde se conoce |
| bandas por «familia × nivel» | la plata marca `no` cuando cambia el nivel, así que ni A ni C aprenden familias; haría falta otra etiqueta. `e2_nivel/04` ya eligió cómo entra el nivel (título completo + corrección de escalón) |
| componentes conexas o Louvain para agrupar | percolan y no usan los `no` (`17`: 21.101 grupos en uno; Leiden empata a 0,95 y es menos estable a 0,93) |
| diccionario de corrección palabra por palabra y lematización | pisa D-025/D-031/D-032 (reglas de errata medidas con placebo) y D-026 (la brecha de género tiene que quedar visible). Puede entrar como rival medido, no como reemplazo |
| hacer oro de `calibra`/`prueba` con las contradicciones | `calibra` y `prueba` ya existen y se fijaron antes de juzgar; las contradicciones son una muestra sesgada |
| re-afinar la rúbrica si el acuerdo baja de 80 % | ya se midió (D-035) y la v3 está congelada |

**11. Aparte, como decisión de producto:** la normalización tiene que ser la misma al
construir y al consultar. Hoy `referenciar()` busca el título exacto y, si no está, va al
vecindario sin pasar por la fusión por errata: `VENDEROR` de un cliente cae por analogía. Se
propone una sola función, reusando `_distancia1` y `_es_errata`, que al consultar mapee un
título nuevo a un título de la base con ≥ 10 empresas si es errata suya. Se medirá
reinyectando como «de cliente» los títulos que la pasada de erratas absorbió, y se
registrará como decisión propia al implementarla.

#### Lo que no cambia

H1, H2 y H3 siguen como están. H1 sigue midiéndose una sola vez sobre `prueba` con los 400
de `13e`. El oro lejano del punto 5 **no entra en H1**: mide el Recall de A, que es un
secundario.

#### Orden de trabajo que resulta

1. Juzgar `prueba` con la v3 y los 139 incoherentes.
2. Entrenar B por pasos con la grilla de arriba (con la plata que ya hay).
3. En paralelo: diseñar el agrupamiento del oro lejano y, si hay permiso, la capa A0.
4. Rehacer la línea base de C con la regla del punto 8.

### Enmienda 2 (2026-09-25, antes de abrir `prueba` y de entrenar): `prueba` pasa a 600, H1b y la operación

**Origen:** revisión con otra sesión de Claude y con el autor. El punto que decide es la
potencia de H1, medida hoy.
**Evidencia:** `research/experimentos/e2_nivel/19_potencia_h1.py` (solo `calibra`) y
`20_ampliar_prueba.py` (los 400 pares nuevos, aún sin juzgar).

#### 1. Con 200 pares, H1 sale inconclusa aunque B sea mejor

`19` corre el NLI congelado sobre los 200 de `calibra`, con la plantilla fija, y lo compara
con el coseno por bootstrap pareado estratificado (10.000 remuestreos):

| | AUC | diferencia con el coseno | IC 95 % |
|---|---|---|---|
| coseno | 0,688 | | |
| NLI congelado, media de las dos direcciones | 0,748 | +0,061 | [−0,039, +0,159] |

El medio ancho del IC 95 % **de la diferencia** con 200 pares es **±0,099**, no los ±7 puntos
de un AUC suelto. Potencia de H1, aproximación normal con el error estándar escalado por
raíz(200/n):

| efecto real de B | n = 200 | 400 | 600 | 800 |
|---|---|---|---|---|
| +0,061 (lo que ya da el NLI sin entrenar) | 23 % | 40 % | 56 % | 68 % |
| +0,075 | 32 % | 56 % | 73 % | 85 % |
| +0,10 | 51 % | 80 % | 93 % | 98 % |
| +0,15 | 85 % | 99 % | 100 % | 100 % |

**Decisión: `prueba` pasa de 200 a 600 pares.** Con 600 se detecta una mejora de ~+0,08 con
~80 % de potencia. No se baja a 400: con el plazo de diciembre, la carga de juicio cabe (ver
el punto 8).

#### 2. Los 400 pares nuevos (`20`)

- **Mismo marco que `13e`:** pares entre grupos distintos de `base_v15` con coseno
  0,90–1,01, del censo de `16`, con los mismos estratos y los cuatro tramos de la banda.
- **Excluidos:** cualquier par que toque un grupo de la plata (los 139 incoherentes están
  dentro), porque B se entrena con esos cargos; y los pares ya juzgados de `13e` y `13a`.
- **El estrato alto está agotado.** De 126 pares con coseno ≥ 0,97 en todo el censo quedan
  6 tras las exclusiones. Se toman los 6 y los 54 que faltan pasan a la banda, que es la
  regla de `16`. Composición de los 400: bajo 60, banda 334 (84/84/83/83 por tramo), alto 6.
- **Juicio ciego con la v3 congelada**, en 8 lotes de 50, sin `sim`, estrato ni partición.
  Estos pares **no se usaron para escribir la rúbrica**, así que atenúan el límite de
  D-035 de que la v3 se escribió viendo `prueba`.

**La comparación principal es sobre los 600 juntos, pase lo que pase.** Se reporta además el
AUC por estrato y por separado en los 200 originales y en los 400 nuevos. Si el AUC del
coseno difiere entre las dos mitades con un IC que excluya el cero, se declara la
heterogeneidad, pero la vara no cambia. Queda fijado ahora para que no se decida viendo los
números.

Composición de los 600: bajo 90, banda 474, alto 36. Hay menos alto que en `13e` y más
banda, la zona difícil.

#### 3. H1 queda bilateral

No se pasa a una prueba unilateral. Declararla ahora, después de ver +0,061 en `calibra` y
una tabla de potencia, se leería como un ajuste hecho a medida (unilateral al 0,05 es
bilateral al 0,10). Con 600 pares no hace falta.

#### 4. H1b (secundaria): B contra el NLI congelado

La pregunta interesante para la tesis no es si B le gana al coseno —el NLI sin entrenar ya
va +0,061 adelante— sino **si ajustar aporta sobre el modelo sin ajustar**. D-036 ya pedía
reportar esa diferencia sin criterio de adopción; aquí se le pone número a su potencia con
600 pares:

| efecto de B sobre el NLI | potencia |
|---|---|
| +0,03 | ~18 % |
| +0,05 | ~41 % |

Es conservadora: B parte del NLI y sus puntajes estarán correlacionados, lo que achica el
error de la diferencia. **No se promete significancia.** Si sale inconclusa, se reporta como
tal.

#### 5. La plantilla del cross y una corrección que sube la vara

**Plantilla fija:** `«El puesto de trabajo es {Título}.»`, con el título en formato de
título, la de `13c`. Es la que dio AUC 0,748 en `calibra` y 0,755 en los 48.

**Corrección:** D-036 decía «AUC del coseno en estos pares: 0,616». Ese número salió de
`17`, que compara los **representantes de grupo** y no los títulos juzgados. **Sobre los
títulos juzgados, el AUC del coseno es 0,688.** Las métricas de agrupamiento de `17` siguen
valiendo porque trabajan por grupo. **La línea base es más alta de lo que decía D-036, así
que el margen que tiene que ganar B es más chico**, y se corrige antes de entrenar para que
no parezca que la meta se movió.

#### 6. El oro lejano, en dos fases y con tope

Juzgar a mano 100 anclas con candidatos hasta el rango 500 serían decenas de miles de
juicios. El diseño queda así:

1. **50 anclas** al azar con respaldo suficiente.
2. **Tope por fuente y ancla:** los 50 primeros del coseno, los 50 primeros de la
   descripción (A0) y hasta 20 que proponga Gemini. Sin repetidos, ~100 por ancla, ~5.000
   pares.
3. **Gemini filtra** los ~5.000 con la rúbrica v3.
4. **Juicio humano de todos los `si` de Gemini** y de una **muestra estratificada de sus
   `no`**, sobremuestreando los que vienen de la descripción y los de rango de coseno alto,
   que es donde viven los sinónimos perdidos. El 5 % al azar no alcanza: con ~240 pares y
   pocos sinónimos perdidos, el factor de corrección tendría un error enorme.
5. Los recalls se corrigen con el inverso de la probabilidad de inclusión
   (Horvitz-Thompson), y se parte en `calibra`/`prueba` antes de juzgar.

Juicio estimado: ~500 pares. **Tres límites declarados:** el recall es relativo a lo
agrupado; depende de la muestra de `no` de Gemini; y **la fuente Gemini la filtra Gemini**,
así que su recall sale inflado frente a las otras. A favor: Gemini junta de más (kappa por
estrato, D-035), así que probablemente se le escapan pocos.

#### 7. Operación del producto

- **Latencia:** consultar un título nuevo cuesta una llamada a Gemini y ~50 pases del cross,
  varios segundos en CPU. Si Gemini falla o tarda, se recupera **solo por título** y la
  descripción se completa en segundo plano. **El informe dice qué fuentes se usaron**,
  porque repetir la consulta con la descripción lista puede dar otra respuesta.
- **Deriva:** los títulos nuevos se asignan a grupos existentes y no se reagrupan en el
  momento. Se reconstruye todo con C cada 3 a 6 meses, junto con el reentrenamiento del
  adaptador. Entre reconstrucciones, un título queda solo cuando unirse a cualquier grupo
  cuesta más que quedarse aparte: el criterio de C, sin umbral nuevo.
- **Versiones:** cada base lleva versión, y se reporta cuánto cambió respecto de la anterior
  (ARI entre versiones y cargos cuya banda se movió más que su propia incertidumbre).

#### 8. Carga de juicio y orden de trabajo

| qué | pares | horas (20–30 s por par) | bloquea |
|---|---|---|---|
| **los 400 nuevos de `prueba`** | 400 | ~2,5–3,5 | **H1** |
| los 139 incoherentes | 139 | ~1 | el entrenamiento de B (mejora, no bloquea) |
| oro lejano | ~500 | ~3–4 | el Recall de A (secundario) |
| **total** | ~1.040 | **~6,5–8,5 h** | |

El ritmo de 20–30 s por par es un supuesto: se cronometra el primer lote de 50.

**Aclaración:** los 200 originales de `prueba` **ya tienen juicio humano** (los 400 de `13e`
están completos). Lo que D-035 llama «juzgar `prueba` con la v3» es correr **Gemini** sobre
`prueba` una sola vez con `15_piloto_llm.py`, para reportar su acuerdo con el juez; no es
trabajo a mano ni abre `prueba` para elegir modelo. La Enmienda 1 lo nombraba igual y debe
leerse así.

---

### Enmienda 1 de D-035 (2026-09-29): lo que costó de verdad, y a qué proyecto

**Origen:** el informe de facturación de Google Cloud del 25 al 29 de septiembre.

| | |
|---|---|
| **proyecto** | `act-poc-gemini`, con facturación activa: nivel **de pago**. Resuelve la mitad del pendiente de D-035; el permiso para mandar títulos de clientes sigue sin estar por escrito |
| **total** | **86,31 USD**, todo el día 25 (85,71 de la API de Gemini) |
| **entrada de `gemini-3.8-flash`** | 53,66 USD: ~71,5 M de tokens a 0,75 USD/M |
| **salida y pensamiento** | ~32 USD: ~8,5 M de tokens a 3,75 USD/M |
| **ahorro por caché** | **0,00**: la rúbrica, ~3.000 de los 3.009 tokens de cada petición, se cobró entera las ~20.800 veces |

Incluye el piloto v2 y v3, `prueba` y los 10.000. **Contra lo que contaron los guiones**
(~65 M de entrada) sobran ~6 M, un 9 %. La explicación probable, sin confirmar, es la corrida
que se congeló (`2c195e3`): peticiones que el servidor procesó y cobró sin que la respuesta
llegara, y que se volvieron a pedir. La previsión de 181 USD que muestra el informe es una
extrapolación de ese día, no gasto.

**Para la tesis:** etiquetar 10.000 pares costó unos 86 USD con el piloto incluido, frente a
~28 h de juicio a mano al ritmo medido en `13e`.

**Si se repite** (una v4, más plata, la capa A0): dos tercios del gasto fueron la rúbrica
repetida. El modo por lotes o una caché explícita de la instrucción son la primera palanca,
antes que cambiar de modelo. Y hace falta una alerta de presupuesto en el proyecto.

### Enmienda 3 (2026-09-29, antes de la corrida real): cómo se entrena B, y qué queda fijo

**Origen:** escribir el guion de entrenamiento obliga a decidir detalles que las enmiendas 1
y 2 no fijaban. Se registran aquí antes de correrlo en el servidor.
**Evidencia:** `research/experimentos/e2_nivel/21_paquete_entrenamiento.py`,
`22_entrenar_cross.py` y `requirements-cross.txt`.

#### 1. Qué ve el entrenamiento

Solo el paquete de `21`: la plata (8.500 `entrena` / 1.500 `valida`), los 139 incoherentes
**ya con juicio humano** (87 `si`, 52 `no`; no queda ninguna etiqueta blanda) y `calibra`.
`21` comprueba contra los 600 pares de `prueba`, por grupos y por títulos, y se detiene si
alguno aparece. `22` se niega a correr si el manifiesto no lo certifica, y no tiene ninguna
opción para leer `13e_*` ni `20_*`. No viajan sueldos: la señal de nivel (`dificil`) ya va
calculada.

#### 2. Tres decisiones nuevas, aprobadas por el autor

- **Tres semillas por configuración de la grilla.** Con 200 pares en `calibra`, dos
  semillas de la misma configuración pueden diferir tanto como dos configuraciones. Se
  elige por el **AUC medio** de las tres y se guarda la semilla **más cercana a la media**,
  no la mejor, para no quedarse con un golpe de suerte.
- **Aumento:** una copia con errata real (letra cambiada, borrada o transpuesta, en palabras
  de 5 letras o más, nunca la primera) en el **30 %** de los pares, más una copia permutada
  en todos los pares donde aplique la permutación controlada (3.109 de 8.500). Es un valor
  de partida, no medido.
- **Pasos 1 y 2** (simétrico y direccional): una semilla y sin aumento. Son la ablación
  que mide cuánto aporta la dirección.

#### 3. Detalles fijados en el guion

| qué | valor |
|---|---|
| probabilidad de inclusión | la salida `entailment` del NLI; se arranca de 0,748, no de cero |
| simétrico al evaluar | media de los dos órdenes |
| cabeza de motivo | lineal sobre el `[CLS]` medio de los dos pases; peso 0,3; ignora los pares sin paso conocido |
| peso w | sobre los 2.665 pares `dificil` |
| optimizador | AdamW, 2·10⁻⁵ (cabeza de motivo 10⁻⁴), decaimiento 0,01, lotes de 32, 10 % de calentamiento, recorte de gradiente 1,0 |
| épocas | hasta 4; se queda la de mayor AUC en `calibra` |
| longitud máxima | 64 tokens |
| precisión | bf16 en GPU; la comprobación inicial siempre en fp32 |
| desempate | bootstrap pareado estratificado, 2.000 remuestreos |

#### 4. Comprobación antes de entrenar

`22` evalúa el modelo **sin entrenar** sobre `calibra`, en fp32 y con la plantilla fija, y
se detiene si no da el **0,748 ± 0,005** de `19`. Si la plantilla, el tokenizador o el
modelo cambiaran, se vería aquí y no después de entrenar.

#### 5. Reproducibilidad

- **El modelo, fijado:** revisión `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`, y `22`
  exige el SHA-256 de `model.safetensors` (`7c8e29f1…4a8541`).
- **Las librerías:** `requirements-cross.txt`, con versiones exactas (torch 2.14.0,
  transformers 5.17.0, tokenizers 0.23.2, …).
- **Semillas fijas y algoritmos deterministas de PyTorch.**
- **Una ficha por corrida** en `resultados.json`: commit de git (y si había cambios sin
  commitear), versiones, CUDA, GPU, hashes del modelo y de los datos.

**Límite declarado:** en GPU el entrenamiento no es idéntico bit a bit entre máquinas
(sumas en otro orden, redondeo de bf16). Lo que sí es exacto es la **evaluación del modelo
guardado**, y H1 se corre sobre esos pesos congelados, en cualquier máquina.

#### 6. Qué sale

`salidas/22_modelos/elegido/` (el modelo de H1, con su temperatura), el representante de
cada configuración y de los pasos 1 y 2 en `corridas/`, y `resultados.json`. Los números de
`calibra` que reporta son **optimistas**: `calibra` también eligió la época, la semilla y la
configuración. La vara sigue siendo `prueba`, que se corre aparte.

### Enmienda 4 (2026-09-29, antes de abrir `prueba`): 9 pares de `prueba` quedan fuera por duda

**Origen:** al revisar el estado del repo apareció que `20_para_juzgar.csv` difería del
commiteado en `26cb1d3`. El autor volvió sobre 10 pares de los 400 nuevos y marcó 9 como
`duda` en `mismo` (antes: 8 `si` y 1 `no`); en el décimo (#119) solo añadió la nota
«jerarquia», sin cambiar el juicio.

**Decisión del autor:** esos 9 pares **quedan fuera de `prueba`**, en vez de forzarles un
`si`/`no`. `prueba` pasa de 600 a **591**: 200 de `13e` y 391 de `20`. Los 9 son 4 del
estrato bajo y 5 de la banda. Por eso los 391 nuevos quedan en bajo 56, banda 329 y alto 6.

**Por qué es legítimo ahora y no después:** todavía no se abrió `prueba` ni hay un modelo
entrenado. Nadie vio cómo puntúa ningún juez esos pares. Desde que corra H1, ningún juicio
de `prueba` se puede tocar.

**Lo que hay que declarar:**
- Quitar los pares que el juez humano no sabe resolver deja `prueba` algo más **fácil**.
  Afecta igual a B y al coseno, porque la comparación es pareada, pero los AUC absolutos
  salen algo optimistas.
- La potencia prácticamente no cambia (591 frente a 600).
- La rúbrica pedía elegir y anotar la duda en `nota`. Estos 9 no la siguen; se deja
  constancia de la excepción.

Los guiones ya tratan cualquier valor que no sea `si` o `no` como fuera del conjunto, así
que no hace falta cambiar código. La comparación principal de H1 es sobre los **591**.

### Enmienda 5 (2026-09-29, antes de abrir `prueba` y de entrenar): el número de grado ya no separa

**Origen:** decisión del autor. Un número que marca el grado dentro del cargo
(`AUXILIAR 1` / `AUXILIAR 2`, `QUIMICO I` / `QUIMICO II`, `NIVEL 2`) no hace distinto el
puesto: **la normalización (capa 0) lo borra.** Reemplaza la excepción del grado del paso 1
de la rúbrica v3, que decía `no` cuando el ordinal estaba en los dos títulos con valor
distinto. Lo ya etiquetado se corrige.
**Evidencia:** `research/experimentos/e2_nivel/23_correccion_grado.py`, y `19`, `21` y `22`
vueltos a correr.

#### 1. Qué es un grado, y la corrección

Un número del 1 al 9 suelto (también `04`, `# 3` o `1.` al principio), un romano del I al X
suelto, un dígito pegado al final de una palabra (`CONTABLE1`) y `NIVEL` / `LEVEL` /
`GRADO` / `CATEGORIA` justo antes de uno de ellos. Los números de dos cifras no se tocan.

La corrección es **mecánica y en un solo sentido**: un `no` pasa a `si` cuando, borrados los
grados, los dos títulos tienen las mismas palabras (sin conectores y en cualquier orden, que
ya eran ruido en la v3). Si queda otra diferencia, no se decide por regla: el par va a
`23_revisar_grado.csv`. Un `si` y una `duda` nunca se tocan.

| conjunto | pares | `no` → `si` |
|---|---|---|
| `13e` `calibra` | 200 | 4 (#104, #188, #350, #396) |
| `13e` `prueba` | 200 | 2 (#111, #290) |
| `20` `prueba` | 400 | 9 (#46, #53, #56, #61, #88, #113, #185, #217, #314) |
| `18` incoherentes | 139 | 2 (#66, #76) |
| `13a` | 48 | 0 |
| plata de Gemini (`16`), pares coherentes | 10.000 | 137 (117 `entrena`, 20 `valida`), todos con motivo `p1` |

En los juicios humanos, `mismo` se corrige en su sitio y la etiqueta de antes queda en
`mismo_v3`, como `mismo_v1` en la v2. Las respuestas de Gemini no se tocan: `21` aplica
`23_correcciones_plata.csv` al armar el paquete, con `origen = gemini_grado` y motivo
`ninguno`. Se comprobó que en el paquete solo cambian esas 139 etiquetas (137 + los 2 de `18`)
y 4 de `calibra`.

**Al revisar `20` apareció que los juicios ya mezclaban criterios:** 4 `no` con número en un
solo título (#56, #113, #217, #314), que la v3 ya trataba como ruido, y 3 `si` con grado
distinto (#190, #329, #364), que la v3 marcaba `no`. El criterio nuevo vuelve coherentes los
siete.

#### 2. Los pares que fusiona la capa 0 salen de la evaluación

Corregir la etiqueta no basta. El NLI sin entrenar da **0,001** a `AUXILIAR 1 DE
CONTABILIDAD` / `AUXILIAR 2 DE CONTABILIDAD`, y con la etiqueta en `si` su AUC en `calibra`
cae de 0,748 a 0,711 por cuatro pares. Pero esos pares **nunca llegan al juez**: la capa 0 los
fusiona antes. Dejarlos sería medir al juez en lo que ya hace la normalización, y B, que
aprende de los 137 corregidos de la plata, ganaría una ventaja que no es suya.

**Decisión del autor (opción B):** un par que, borrado el grado, queda con las mismas
palabras, **sale de `calibra` y de `prueba`**, sea `si` o `no`. Están en
`23_fuera_por_capa0.csv`, sacados de los títulos sin mirar ningún puntaje, y los leen `19`,
`21` y el guion de H1.

| | antes | fuera | queda |
|---|---|---|---|
| `calibra` | 200 | 6 | **194** (142 `si` / 52 `no`) |
| `prueba` (`13e` + `20`, sin las 9 `duda`) | 591 | 31 (7 + 24) | **560** |

En la plata se quedan los 323 pares que la capa 0 fusionaría (275 `entrena`, 48 `valida`):
enseñan que el grado no separa, por si la capa 0 no atrapa alguna forma.

#### 3. La vara, medida otra vez en `calibra`

| en `calibra` | n | coseno | NLI congelado | NLI − coseno |
|---|---|---|---|---|
| v3 (Enmienda 2) | 200 | 0,688 | 0,748 | +0,061 [−0,039, +0,159] |
| corregido, con todo (opción A, descartada) | 200 | 0,694 | 0,711 | +0,017 |
| **corregido, sin lo que fusiona la capa 0** | **194** | **0,694** | **0,7285** | **+0,035 [−0,064, +0,137]** |

- **El candado de `22` pasa a `AUC_BASE = 0,7285`**, y la prueba `--rapido` en GPU lo
  reproduce (0,7285).
- **La ventaja del NLI congelado sobre el coseno baja de +0,061 a +0,035.** Parte de lo que
  el NLI sin entrenar le ganaba al coseno era separar grados. H1 se sigue midiendo igual,
  pero el efecto de referencia de la tabla de potencia es menor. Con 560 pares, H1 tiene
  ~91 % de potencia para un efecto de +0,10, ~70 % para +0,075 y ~21 % para el +0,035 del
  NLI sin entrenar (`19`, ee escalado de 194 a 560).
- La rúbrica pierde casi toda la clase `p1` como motivo de `no` en la plata: de 129 en
  `entrena` quedan unos 10. La cabeza de motivo lo ve así.

#### 4. Lo que queda pendiente, y lo que hay que declarar

- **14 pares** con grado distinto y otra diferencia, en `23_revisar_grado.csv` (12 de la
  plata, 1 de `20` y 1 de `18`), **juzgados a mano el mismo día** con la rúbrica v3 y el grado
  borrado. `20` #237 lo juzgó el autor solo, sin ver ninguna lectura del modelo, porque es de
  `prueba`: `si`. En los otros 13 el autor confirmó una lectura propuesta: 18#93 sigue `no`
  (el «2» son años de experiencia y `CONTADOR` es otro oficio), y los 12 de la plata pasan a
  `si` (códigos de sede u oficina, `COORDINADOR` / `COORDINATOR`, `ASISTENTE` / `AUXILIAR` del
  mismo nivel, y dos escalas con números de dos cifras). Dos quedan `si` con duda: 16#6165
  (`MAQUINISTA # 3` / `#2`, que en marina mercante pueden ser rangos certificados) y 16#5325
  (`AYUDANTE DE RUTA` con licencia E frente a C). La plata suma así 149 correcciones (137 por
  regla y 12 por revisión).
- **Dos correcciones discutibles**, aplicadas por la regla y a declarar: `20` #46
  (`PROF/TITULO III` / `IV NIVEL BASICO`), donde el romano puede ser el nivel del título
  académico y no un grado, y `13e` #290 (`PROFESOR TITULAR AGREGADO 1` / `2`), un escalafón
  universitario con sueldos distintos. **Decisión del autor: se quedan como la regla los
  dejó** (`si` y fuera de `prueba`), sin lista de excepciones, por coherencia con la
  normalización, que borra el número en los dos casos. **Fusionar grados puede mezclar
  bandas**, y la utilidad aguas abajo lo tiene que medir.
- **La rúbrica v4** (`rubrica_mismo_cargo_v4.md`, 2026-09-30) escribe la regla nueva en el
  paso 1; la v3 queda congelada para la plata. **La capa 0 del producto todavía no borra el grado.** `quitar_grado` en `23` es el
  borrador de la regla. Llevarla a `nivel.py` y reconstruir la base (v16) es una decisión de
  producto aparte: cambia los grupos de los que salen todos los conjuntos, y se hace después
  de H1.
- **El piloto de Gemini (D-035) se midió con la v3.** Su acuerdo con el juez (kappa 0,79)
  queda como estaba; no se repite el piloto porque la corrección es mecánica.
- **`calibra` y `prueba` se tocan antes de abrir `prueba`**, como en la Enmienda 4, y sin
  mirar ningún puntaje de `prueba`. Desde que corra H1, ningún juicio ni exclusión de
  `prueba` se puede tocar.

#### 5. Añadido el mismo día: las letras de grado, y lo que esto revierte de D-025

**Esta enmienda revierte parte de D-025.** Al revisar la fusión por errata, D-025 excluyó a
propósito el «escalón por dígito» (`OPERARIO 1` / `2`, 1.570 pares) y el «escalón romano»
(`ANALISTA I` / `II`, 188) porque «borraría la escalera de antigüedad», y fijó con test la
«letra de grado» (`AYUDANTE B` / `C`) como escalafón. La Enmienda 5 decide lo contrario: el
grado no hace distinto el puesto. **La escalera no se pierde, cambia de sitio:** deja de estar
en el nombre del cargo y tiene que recogerla la banda, con la antigüedad (`producto/
antiguedad.py`). Medir si la banda de una celda fusionada mejora al ajustar por tramo de
antigüedad queda como trabajo de producto, después de H1.

**Decisión del autor: las letras de grado también se borran.** La regla de `23` pasa a
tratar como grado una letra **suelta entre espacios o entre paréntesis** (`AYUDANTE B`,
`PLANIFICADOR (R)`), salvo `E`, `Y`, `O`, `U`; la `A` solo al final (`SOLDADOR A`, no
`ASISTENTE A GERENCIA`); nunca junto a `&` (`COORDINADOR M & R` / `M&P` son siglas de áreas
distintas, juzgado `no`), ni tras `LICENCIA` o `TIPO` (`LICENCIA C` es un tipo de licencia).
Una letra pegada a `.`, `/` o `&` (`T.A`, `COORDINADOR/A`, `T&L`) no es grado. La primera
versión de la regla, sin estas guardas, habría pasado `M & R` / `M&P` a `si`; se vio al medir
y no llegó a aplicarse.

**Qué cambia:**
- **Etiquetas: nada.** Todos los pares del oro que solo difieren en una letra ya eran `si`,
  porque la v3 trataba las letras como código (paso 1). La plata queda idéntica.
- **La evaluación:** salen los pares que la capa 0 fusionaría ahora. `calibra` pasa de 194 a
  **191** (salen #141, #142, #193, los tres `si`) y `prueba` de 560 a **555** (salen 13e #220,
  #339 y 20 #157, #229, #326, los cinco `si`): 191 de `13e` y 364 de `20`, 433 `si` / 122 `no`
  (con 20 #14 ya juzgado, abajo).
  La lista está en `23_fuera_por_capa0.csv` (45 pares: 9 de `calibra`, 36 de `prueba`).
- **La vara en `calibra` (191):** coseno 0,690, NLI congelado **0,7259**, diferencia +0,036
  [−0,067, +0,137]. `AUC_BASE` de `22` pasa a 0,7259, y `--rapido` lo reproduce en GPU.
- **Un par nuevo de `prueba` para juzgar a mano:** `20` #14 (`COORDINADOR DE VENTAS - B` /
  `COORDINADOR SUPERVISOR VENTAS P BB`), antes `no`. **Juzgado `si` por el autor, solo y sin
  ninguna lectura del modelo, el 2026-09-30**, antes de abrir `prueba`.

**El primer entrenamiento queda sustituido.** La corrida completa de `22` (commit `1bdc855`)
eligió época, semilla, configuración y temperatura con los 194 pares de `calibra`. La plata no
cambia, pero `calibra` sí, así que se reentrena desde cero con los 191. Sus números quedan como
referencia, no como el modelo de H1: elegida w = 1 sin aumento, semilla 20261001, época 1,
AUC 0,9232 en `calibra` (194), T = 1,70; ablación 0,937 (paso 1) / 0,931 (paso 2) / 0,923
(paso 3), y casi todas las corridas eligieron la época 1. Guardados en
`22_modelos/primer_entrenamiento_1bdc855/` (resultados, registro y puntajes de cada corrida).

**Comprobado con esos puntajes antes de reentrenar:** sobre los 191 pares, todas las
configuraciones bajan ~0,001, el orden no cambia, la simple sigue elegida y el representante
de cada configuración es la misma semilla. Lo que no se puede comprobar es la época (solo se
guardó la mejor de cada corrida), y la temperatura cambiaría un poco. Se reentrena igual
(decisión del autor), para que el modelo de H1 quede elegido entero con la `calibra`
definitiva y sin salvedades; cuesta una hora de GPU.

**Un fallo de `23` que se corrigió de paso:** si un par salía de la lista de revisión (porque
la regla pasaba a cubrirlo), su juicio a mano se perdía al reescribir el archivo. Le pasó a
16#5325 y se recuperó del commit anterior. Ahora esos juicios se conservan con
`vigente = no`.

### Enmienda 6 (2026-09-30, antes de abrir `prueba`): cómo se corre H1

**Origen:** escribir el guion de H1 obliga a fijar tres detalles que el prerregistro no
cerraba del todo. Aprobados por el autor antes de abrir `prueba`.
**Evidencia:** `research/experimentos/e2_nivel/24_h1_prueba.py`.

1. **Bootstrap pareado por par**, como dice el texto de H1: 10.000 remuestreos de los pares
   con reemplazo, los dos jueces sobre el mismo remuestreo, IC 95 % por percentiles, semilla
   fija. No estratificado por clase (lo que usó `19` para la potencia): así lo decía H1, y es
   algo más conservador. **Límite:** un mismo título puede aparecer en varios pares, así que
   los pares no son del todo independientes y el IC puede quedar algo estrecho.
2. **El cross-encoder se evalúa en fp32**, no en bf16 como durante el entrenamiento, para que
   la medición sea exacta en cualquier máquina. La diferencia observada en `calibra` es de
   ~0,0005 (0,9227 frente a 0,9232 con el primer entrenamiento).
3. **Gemini sobre `prueba` va aparte** (`15_piloto_llm.py`, una vez, rúbrica v3 congelada):
   mide la calidad de la plata, no H1, y depende de la API y del permiso LOPDP, pendiente
   desde D-035. `24` no depende de ninguna red.

**Lo que hace `24`:** antes de leer `prueba` comprueba que el repo esté limpio, que el
cross-encoder elegido venga del paquete vigente y de la `calibra` de 191, que no quede ningún
par de `prueba` por juzgar, que el NLI congelado dé el `AUC_BASE` en `calibra`, y que no exista
ya `24_h1.txt` (**`prueba` no se abre dos veces**). Luego puntúa a la vez el cross-encoder
elegido, el NLI congelado, el coseno y los 8 modelos de la ablación, y reporta H1, H1b, los
estratos, las dos mitades (`13e` / `20`) con la heterogeneidad del coseno, la ablación y la
calibración. `--ensayo` corre lo mismo sobre `calibra`, sin leer `prueba`; se probó con el
primer entrenamiento y el modo real se detuvo en el primer candado, como debe.

### Resultado del entrenamiento del cross-encoder (2026-09-30, antes de abrir `prueba`)

**Evidencia:** `salidas/22_modelos/resultados.json` y `corrida.log` (commit `1d776f0`, repo
limpio, `calibra` de 191, 20 corridas, ninguna retomada). Es el cross-encoder de H1.

| en `calibra` (191; optimista: eligió época, semilla y configuración) | AUC |
|---|---|
| coseno | 0,6897 |
| NLI congelado | 0,7259 |
| paso 1, simétrico (1 semilla) | 0,9366 |
| paso 2, direccional (1 semilla) | 0,9296 |
| **paso 3, elegido: w = 1, sin aumento, semilla 20261001, época 1** | **0,9222** |

- **Grilla:** w1 sin aumento 0,9244 · w2 sin 0,9257 · w3 sin 0,9268 · w1 con 0,9219 · w2 con
  0,9186 · w3 con 0,9180 (media de 3 semillas, sd ≤ 0,005). La mejor por media, w = 3 sin
  aumento, no le gana a la simple: IC 95 % [−0,011, +0,021]. **Queda la simple.**
- **El aumento no ayuda:** peor con cada w, y tarda el doble.
- **Época:** 17 de 20 corridas eligieron la 1; después `calibra` baja mientras `valida` (la
  plata de Gemini) sube. Más épocas acercan el cross-encoder a Gemini y lo alejan del juicio
  humano. Límite declarado: con la mejor en la época 1, una tasa de aprendizaje menor o una
  evaluación a mitad de época quizá sirvieran; no se prueba, porque se elegiría con los mismos
  191 pares.
- **Ablación:** ni la dirección ni la cabeza de motivo mejoran en `calibra` (0,937 / 0,930 /
  0,922), dentro del ruido de 191 pares. Dato para H3, no veredicto.
- **Calibración:** T = 1,70 (salía sobreconfiado); ECE 0,040 → 0,025.
- **Por estrato** (cross-encoder frente a coseno): alto 1,00 / 0,40 (n = 29), banda 0,91 / 0,65
  (132), bajo 0,89 / 0,57 (30).
- **Coincide con el primer entrenamiento** (`1bdc855`, `calibra` de 194): misma configuración,
  mismas semillas representantes, y **los mismos pesos bit a bit**: el SHA-256 de
  `elegido/model.safetensors` es `040b4dc4a6c5…` en los dos. Con semillas fijas, algoritmos
  deterministas y la misma GPU (H200, CUDA 13.0), el entrenamiento se reproduce exacto; el
  límite de la Enmienda 3 (no idéntico entre máquinas distintas) sigue en pie.
- **Ensayo de `24` sobre `calibra`** (no lee `prueba`): los cinco candados pasan; el
  cross-encoder en fp32 da 0,9227 (0,9222 en bf16 durante el entrenamiento).

Un incidente sin efecto en el resultado: en una primera relanzada quedaron dos procesos del
entrenamiento en la misma terminal (uno suspendido); se detuvieron los dos y se entrenó desde
cero una sola vez.

### Resultado de H1 (2026-09-30): `prueba` abierta una vez

**Evidencia:** `salidas/24_h1.txt` y `24_puntajes_prueba.csv`, de `24` sobre el commit
`12b7787` (repo limpio), cross-encoder `completo_w1_sin_aum_s20261001` (SHA-256
`040b4dc4a6c5…`), fp32. `prueba`: 555 pares (433 `si` / 122 `no`; 191 de `13e`, 364 de `20`).

| juez | AUC en `prueba` |
|---|---|
| coseno (el producto) | 0,6211 |
| NLI congelado | 0,8125 |
| **cross-encoder ajustado** | **0,8902** |

- **H1 se adopta.** Cross-encoder − coseno = **+0,269, IC 95 % [+0,202, +0,337]**, entero sobre
  cero (bootstrap pareado por par, 10.000 remuestreos).
- **H1b:** cross-encoder − NLI congelado = **+0,078, IC 95 % [+0,038, +0,118]**. Sin criterio de
  adopción registrado, pero el IC no toca el cero: el ajuste con la plata aporta sobre el
  modelo sin ajustar. La potencia prevista para +0,05 era ~40 %; el efecto fue mayor.
- **Por estrato:** alto 0,969 (n = 34, solo 2 `no`), banda 0,908 (439), **bajo 0,748** (82). El
  estrato bajo, donde el producto hoy no fusiona, sigue siendo el difícil; ahí el coseno da
  0,454, peor que el azar.
- **Por mitad:** `13e` 0,892 y `20` 0,903. El coseno no difiere entre mitades (IC de la
  diferencia [−0,104, +0,115]): sin heterogeneidad.
- **`calibra` era optimista, como se esperaba:** 0,922 allí frente a 0,890 aquí. En cambio el
  NLI congelado y el coseno se movieron en sentidos opuestos entre `calibra` y `prueba`
  (0,726 → 0,813 y 0,690 → 0,621): con 191 pares, `calibra` es ruidosa.
- **Ablación (descriptiva):** paso 1 simétrico 0,896, paso 2 direccional 0,907, paso 3
  elegido 0,890; las 6 configuraciones entre 0,878 y 0,901. Ni la dirección, ni la cabeza de
  motivo, ni w, ni el aumento muestran una ganancia consistente: en `calibra` el orden era otro.
  Para H3 y para la arquitectura, lo que funciona es ajustar el NLI con la plata; lo demás no
  se distingue del ruido.
- **Calibración:** ECE 0,108 sin temperatura y 0,067 con T = 1,70. Transfiere solo en parte
  (en `calibra` quedaba en 0,025). Importa para el correlation clustering, que usa log-odds.

**Límites que se declaran con el resultado:** un solo juez humano; `prueba` solo cubre pares
con coseno 0,90–1,01 (no mide los sinónimos lejanos); un mismo título puede aparecer en varios
pares; la regla del grado (Enmienda 5) se decidió antes de abrir, pero después de ver `calibra`.

**`prueba` ya está abierta.** Desde aquí, ningún juicio, exclusión ni modelo se ajusta mirándola;
todo lo que se mida después sobre ella es exploratorio.

---

## D-037 — La capa 0 borra el grado: cuarta pasada de fusión y la misma regla al consultar

**Fecha:** 2026-09-30
**Origen:** la Enmienda 5 de D-036 decidió que el grado (número, romano o letra suelta) no hace
distinto el puesto, y lo aplicó a las etiquetas y a la evaluación. Quedaba el producto: la base
`base_v15` sigue separando `AUXILIAR 1` de `AUXILIAR 2`. Decisión del autor, tras H1.
**Evidencia:** `src/benchmarking/producto/nivel.py` (`quitar_grado`, `clave_grado`,
`mismo_salvo_grado`), `base_referencia.py` (`_fusionar_grado`, `_por_grado`) y sus tests.
**Estado:** **código listo y probado; la base no se ha reconstruido.** Falta `base_v16` y su
medición, en la máquina que tiene los datos.

### Qué hace

1. **Cuarta pasada de fusión**, después de la semántica, la de erratas (D-025) y la de género
   (D-026), con la misma forma que esas dos: une los grupos cuyas celdas son el mismo título
   salvo el grado, si alguna lo lleva. Sin asimetría, como en género: sobrevive el grupo con
   más empresas. `grado=False` la apaga y `mapa_grado` inyecta uniones para el **placebo**.
2. **Al consultar:** si el título del cliente no está en la base, se busca el mismo título
   salvo el grado (`AUXILIAR 3 DE CONTABILIDAD` → `AUXILIAR 1 DE CONTABILIDAD`). La columna
   nueva `cargo_base` dice con qué título se emparejó; `base` no cambia, porque la lee la API.

### La regla es la de la evaluación, más una guarda

Es la misma que corrigió las etiquetas y armó `prueba` (`23_correccion_grado.py`), para que
lo que H1 excluyó por «la capa 0 lo fusiona» sea lo que el producto de verdad fusiona. Se
comprobó sobre los **10.987 pares etiquetados** (oro, plata y los 48 de `13a`): cero
diferencias. La guarda añadida —la primera palabra, la que nombra el puesto, tiene que
coincidir— evita `GERENTE ASISTENTE 1` = `ASISTENTE GERENTE 2`, y no excluye ninguno de los
433 pares de la plata ni de los 182 de la evaluación que la regla junta.

### Lo que falta, y cómo se mide

1. **Reconstruir la base (`base_v16`)** con la pasada activa, donde están los datos. Contar
   cuántos grupos se unen y cuántas personas pasan de analogía a datos directos, como en D-025.
2. **Medición pareada de pinball con placebo**, el protocolo de siempre: base con y sin la
   pasada, y una con uniones al azar del mismo tamaño (`mapa_grado`). Si fusionar al azar
   costara lo mismo, la regla no estaría identificando puestos equivalentes.
3. **La escalera que marcaba el grado:** medir si la banda de las celdas fusionadas mejora al
   ajustar por tramo de antigüedad (`producto/antiguedad.py`). Es la razón por la que D-025
   protegía el escalón, y la que hay que contestar ahora.

### Reversibilidad

Total hasta que se reconstruya la base: `grado=False` deja el comportamiento de `base_v15`.
Un test de fusión semántica usaba títulos sintéticos `PUESTO A` / `B` / `C`, que con esta
regla son el mismo puesto; se renombraron (`PUESTO ALFA` / `BETA` / `GAMA`) sin cambiar lo que
comprueba.

---

## D-038 — Cross-encoder v2: el paso 4 afinado, `calibra` rejuzgada y etiquetas donde falla

**Fecha:** 2026-09-30
**Origen:** tras H1 (D-036), el autor quiere mejorar el cross-encoder: (1) etiquetas humanas en
la zona difícil y (3) ensamble. Antes, un análisis de errores.
**Evidencia:** `research/experimentos/e2_nivel/25_analisis_errores.py` (solo `calibra` y
`valida`; `prueba` no se mira).
**Estado:** **en curso.** Rúbrica v5 escrita y `calibra` lista para rejuzgar a ciegas. El
prerregistro de la v2 (qué se entrena, qué se compara, con qué examen) se escribe **antes** de
entrenarla.

### Lo que dijo el análisis de errores

- **Los pasos 1–3 ya están aprendidos:** con escalón distinto, cero errores en `calibra` y 2
  de 278 en `valida`; con seniority distinta, cero en `calibra`; el grado, las erratas y el
  género, prácticamente sin errores.
- **Casi todo el error es el paso 4, y en una dirección: juntar de más.** En `calibra`, 10 de 11
  errores; casi todos con la misma palabra de puesto y otra función (`SUPERVISOR DE PLANTA` /
  `… Y PROYECTO`). En `valida`, junta 37 de los 57 `no` que Gemini dio por el paso 4, con
  falsos amigos léxicos (`PRODUCTO` / `PRODUCCION`, `PROCESOS` / `PROCESAMIENTO`).
- **Y parte de ese error es del oro, no del modelo.** En `calibra`, para el mismo tipo de par
  (misma palabra de puesto y una función añadida, sin escalón ni seniority), 45 `si` y 2 `no`.
  Los dos `no` contradicen la regla del paso 4 de la v3/v4. Probablemente vienen de juicios
  hechos con la v1/v2, más estrictas.
- **Gemini, con la v3, es muy permisivo en el paso 4:** 99 % `si` con función añadida, 93 % con
  acotación, 88 % con una función por otra.

### Rúbrica v5 (decisiones del autor)

- **Función añadida: nunca separa**, aunque sea otro oficio (`JEFE DE MONTAJE` = `JEFE DE
  MONTAJE Y SOLDADURA`, que la v3/v4 separaba).
- **Una función por otra: mismo si es la misma área con otro nombre**, distinto si son áreas o
  departamentos distintos; los falsos amigos léxicos separan.
- **Ámbito:** `NACIONAL` y `LOCAL` no son marca (coherente con los 139); `INTERNACIONAL`,
  `LATAM` y `GLOBAL` se suman a `REGIONAL` y `ZONAL`.

`rubrica_mismo_cargo_v5.md`, vigente para juzgar a mano. La v3 sigue congelada para la plata;
la v4 queda como registro del grado.

### `calibra` se rejuzga entera y a ciegas

El autor propuso corregir las inconsistencias de `calibra`. Corregir solo los pares donde el
modelo falló sesgaría las etiquetas hacia el modelo e inflaría su AUC. **Se rejuzgan los 191,
en orden aleatorio, sin `sim`, sin la etiqueta anterior y sin predicción** (`26`). La etiqueta
anterior queda en `mismo_v4`. Si cambia, cambia por la regla. **`prueba` no se toca**: su
resultado (H1) queda como está, y se declara que parte de su error medido es la ambigüedad del
paso 4 que la v5 resuelve.

### Lo que falta, en orden

1. Rejuzgar `calibra` (~1,5 h) y aplicar (`26 aplicar`), y luego `21`, `19` y el `AUC_BASE`.
2. Llevar la v5 a la plata. **No es mecánica:** se probó la regla «un título contiene al
   otro → `si`» y confunde una función añadida con un modificador que cambia el sentido
   (`COORDINADOR DE VENTA` / `… POST VENTA`, `… RIESGOS FINANCIEROS` / `… NO FINANCIEROS`,
   `SUPERVISOR` / `ASST SUPERVISOR`); y `TRANSPORTE INTERNACIONAL` es una función, no un
   ámbito. La regla solo propone: de los 1.862 pares de la plata de esos tipos, **60 (0,6 % de
   la plata)** tienen una etiqueta distinta de la que daría la v5, y van a juicio humano a
   ciegas (`27_plata_v5.py`, `27_revisar_v5.csv`). El 97 % ya cumple la v5. `21` aplica las
   correcciones al final, después del grado y de los 139.
3. Armar `prueba 2` (~400 pares nuevos, juzgados a ciegas con la v5, congelados) y el lote de
   entrenamiento de la zona difícil, sin cruces entre ellos.
4. Prerregistro de la v2 (esta decisión, antes de entrenar): cross-encoder v2 contra v1 en
   `prueba 2`, con el ensamble como variante.

### `calibra` rejuzgada y la plata con la v5 (2026-09-30)

**`calibra`, a ciegas con la v5 (`26`):** 191 pares. El autor dejó un par sin juzgar (#320) y
lo contestó aparte. Primer resultado: 20 cambios (18 `no` → `si`, 2 `si` → `no`).

**Revisión de consistencia (`28`), independiente del modelo.** Aplicando mecánicamente los
pasos 2 y 3 de la rúbrica a **todos** los `si` de `calibra` (no a los errores del
cross-encoder) salieron 7 pares con niveles o marcas distintas (`COORDINADOR` / `DIRECTOR`,
`SUPERVISOR` / `SUPERVISOR JEFE`, `CORPORATIVO`...), los 7 `no` antes de rejuzgar. El autor
los atribuye a descuido y los devuelve a `no`. Un octavo del paso 5 (`ASISTENTE
ADMINISTRATIVO DE GERENCIA` / `ASESOR ADMINISTRATIVO`) lo mantiene en `si`, por decisión
propia.

**`calibra` definitiva: 148 `si` / 43 `no`.** Frente al juicio anterior (v4) cambian **13**:
11 `no` → `si` (casi todos de función añadida: `SUPERVISOR DE PLANTA` / `… Y PROYECTO`,
`GERENTE DE ABASTECIMIENTO` / `… PLANEACION DE ABASTECIMIENTO`) y 2 `si` → `no`. La
etiqueta anterior queda en `mismo_v4` de `13e_para_juzgar.csv`.

**`CORPORATIVO` sigue separando.** El autor se preguntó si debería. D-033 lo decidió con 48
pares juzgados, sin sueldos. Queda como está (rúbrica, D-033 y la plata coinciden) hasta
medir con la base si `X CORPORATIVO` paga distinto de `X`, empresa contra empresa: pendiente
de producto, con `base_v15`.

**La plata, con la v5 (`27`):** los 60 candidatos juzgados a mano; **49 cambian** (46 de
función añadida pasan a `si`, 1 de `NACIONAL` a `si`, 2 de ámbito a `no`). En 11 de los 60 la
regla mecánica se habría equivocado (`POST VENTA`, `NO FINANCIEROS`, `ASSISTANT MANAGER`,
`SEMISENIOR`...). Aparecieron dos huecos del léxico del producto: rangos en inglés
(`ASSISTANT`, `MANAGER`) y `SEMISENIOR`. Pendiente de producto.

**La vara nueva en `calibra`:** coseno 0,644, NLI congelado **0,7346** (`AUC_BASE` de `22`).
Como dato descriptivo, el cross-encoder v1 da 0,976 en esta `calibra` (0,923 con la anterior):
8 errores en vez de 11, y ya no en una sola dirección (4 juntan de más, 4 separan de más).
Es optimista (v1 se eligió con la `calibra` anterior, muy parecida) y no dice nada de
`prueba`: muestra que buena parte de lo que parecía error del modelo era inconsistencia del
oro en el paso 4.

### `prueba 2`, armada antes de entrenar la v2 (2026-09-30)

**Evidencia:** `research/experimentos/e2_nivel/29_prueba2.py`.

400 pares nuevos, el examen de la v2. Mismo marco que `20` (censo de `16`, coseno 0,90–1,01,
entre grupos distintos). Excluidos: cualquier par que toque un grupo de la plata, los ya
juzgados (`13e`, `13a`, `20`) y los que la capa 0 fusiona por el grado (598). Comprobado: cero
pares con grupos de la plata y cero ya juzgados.

**Composición:** bajo 60, banda 340 (111 / 111 / 110 / 8 por tramo), alto 0. El estrato alto y
el tramo alto de la banda (0,96–0,97) se agotaron en `20`; por la regla de `16` y `20`, lo que
un tramo no llena pasa a los demás. Mediana del coseno 0,942 (0,947 en `20`): algo más
difícil que `prueba`. La comparación v2 / v1 es sobre los mismos pares y no se sesga, pero se
declara. 764 grupos distintos: algunos grupos aparecen en más de un par.

**Se juzga a ciegas con la rúbrica v5**, en 8 lotes de 50, sin `sim`, estrato ni tramo, y
**antes de entrenar la v2**. El lote de entrenamiento de la zona difícil excluirá los grupos de
`prueba 2`.

### Lote de entrenamiento de la zona difícil (2026-09-30)

**Evidencia:** `research/experimentos/e2_nivel/30_lote_entrenamiento.py`.

400 pares para juzgar a mano con la v5 y **entrenar** la v2 (mejora 1). Del censo de `16`, sin
ningún grupo de `prueba 2`, `prueba`, `calibra` ni `13a` (comprobado: cero grupos en común), sin
pares que ya estén en la plata y sin los que la capa 0 fusiona por el grado. Solo la **zona
difícil** del análisis de errores: la misma palabra de puesto, sin nivel ni marcas de
seniority o ámbito distintas, y con palabras distintas (41.155 candidatos, 89 % del estrato
bajo).

**Selección:** 240 del estrato bajo y 160 de la banda; en cada uno, la mitad donde el
cross-encoder de H1 duda (P calibrada más cerca de 0,5; mediana 0,50) y la mitad al azar
(mediana 0,95). Cada grupo como mucho dos veces. La mitad al azar evita que el lote quede
sesgado solo hacia lo que el modelo no sabe; la mitad por duda es la que más enseña.

**Se juzga a ciegas con la v5.** Cómo entran al entrenamiento (partición, peso frente a la
plata) se fija en el prerregistro de la v2, antes de entrenar.

### Prerregistro del cross-encoder v2 (2026-09-30, aprobado por el autor antes de entrenar)

1. **Solo cambian los datos.** Arquitectura y configuración, las de la v1: direccional, cabeza
   de motivo, w = 1, sin aumento, mismos hiperparámetros. La ablación de H1 mostró que esas
   piezas no importan; fijarlas deja que la comparación mida el efecto de las etiquetas.
2. **Datos de entrenamiento:** la plata con sus correcciones (grado 149, v5 49, los 139 a mano)
   **más los 400 pares del lote de la zona difícil (`30`), todos en `entrena`.** `valida`
   sigue siendo la plata de Gemini; la validación humana es `calibra`.
3. **Grilla: solo el peso de las etiquetas humanas, `w_humano` ∈ {1, 3}**, tres semillas cada
   uno (las de la v1). Elección en `calibra` (191, rejuzgada con la v5) con la regla de la v1:
   `w_humano = 3` solo gana si le gana a `1` con un IC 95 % sobre cero (bootstrap pareado
   estratificado); si no, queda `1`. Época y semilla como en la v1. Temperatura reajustada en
   `calibra`. Candado del NLI congelado: 0,7346. `w_humano` pesa sobre los pares con juicio
   humano del lote y de los 139.
4. **`prueba 2`, antes de abrirla:** los 400 juicios del autor con la v5, más la revisión de
   consistencia de los pasos 2-3 (como `28`, sin mirar ningún modelo); `duda` fuera (como en la
   Enmienda 4); se congela con un commit **antes de entrenar la v2**.
5. **Hipótesis:**
   - **H4 (confirmatoria): AUC(v2) − AUC(v1) en `prueba 2`.** Bootstrap pareado por par,
     10.000 remuestreos, IC 95 % bilateral. **Se adopta la v2 si el IC queda entero sobre
     cero.** Un nulo se lee como «no demostrado», y la v1 sigue siendo la referencia.
   - **Réplica de H1:** v1 − coseno en `prueba 2`, con el criterio de H1.
   - **H4b (secundaria):** v2 contra NLI congelado y contra coseno, con IC, sin criterio.
   - **Descriptivos:** el **ensamble** (media de las P de las tres semillas de la
     configuración elegida) contra la v2 sola; AUC por estrato; calibración (ECE); errores por
     tipo de par (como `25`).
   - v1 es exactamente el cross-encoder de H1 (SHA-256 `040b4dc4a6c5…`), sin reajustar nada.
6. **Potencia:** v1 y v2 estarán muy correlacionadas, lo que achica el error de la diferencia,
   pero el efecto esperado es pequeño (quizá +0,01 a +0,03). **No se promete significancia.**
7. **`prueba 2` se abre una sola vez**, con un guion como `24`: candados que no la leen,
   todos los jueces a la vez, y se niega a correr dos veces.
8. **Código:** `22` guarda también los pesos de las tres semillas de la configuración elegida
   (para el ensamble) y admite la grilla de `w_humano`; `21` añade el lote a la plata. No cambia
   ningún número de la v1.

### `prueba 2` juzgada y congelada (2026-09-30, antes de entrenar la v2)

400 pares juzgados a ciegas por el autor con la v5 (uno quedó en blanco, #7, y lo contestó
aparte: `si`). Revisión de consistencia con los pasos 2-3 sobre todos los `si`, sin mirar
ningún modelo (`28 --conjunto prueba2`): 9 avisos; el autor devolvió 6 a `no` (niveles
distintos y marcas de seniority) y mantuvo 3 en `si` porque la regla leía mal: un espacio mal
puesto (`INSPECTOR/S UPERVISOR`), `CORPORATIVAS` como nombre de área (`SOLUCIONES
CORPORATIVAS`) y `LOGISTICA INTERNACIONAL` como función, no ámbito. La etiqueta de antes de la
revisión queda en `mismo_original`.

**`prueba 2` final: 332 `si` / 68 `no`, sin `duda`.** Queda **congelada con este commit**:
desde aquí ninguna etiqueta, exclusión ni criterio se toca, y se abre una sola vez con el
cross-encoder v2 ya entrenado y congelado.

### Lote de entrenamiento juzgado, y el paquete de la v2 (2026-09-30)

Los 400 pares de `30`, juzgados a ciegas por el autor con la v5: **366 `si` / 34 `no`**. Sin
conflictos con los pasos 2-3 (el lote se eligió sin ellos). En la mitad elegida por la duda del
cross-encoder v1, el autor dijo `si` en el 88 % y la v1 acierta el 50 % (azar); en la mitad al
azar, 94 % `si` y la v1 acierta el 92 %. En la zona difícil el autor junta más de lo que la v1
se atreve: es lo que la v2 tiene que aprender.

**Paquete de la v2 (`21`):** plata de 10.400 (8.900 `entrena` / 1.500 `valida`): la de Gemini con
el grado (149) y la v5 (49) corregidos, los 139 a mano y los 400 del lote (`humano_lote`).
`calibra` 191 (148 / 43). Comprobado que no viaja nada de `prueba` ni de `prueba 2`.

### Resultado del entrenamiento del cross-encoder v2 (2026-09-30, antes de abrir `prueba 2`)

**Evidencia:** `salidas/22_modelos_v2/resultados.json` y `22_modelos_v2.log` (`22 --grilla v2`,
commit `db0a28b`, repo limpio, 6 corridas, ninguna retomada).

| en `calibra` (191; optimista: eligió época, semilla y configuración) | AUC medio (3 semillas) |
|---|---|
| NLI congelado / coseno | 0,7346 / 0,6438 |
| **v2, `w_humano = 1`** | **0,9843** (sd 0,002) |
| v2, `w_humano = 3` | 0,9873 (sd 0,001) |

- **Elección: `w_humano = 1`.** `3` no le gana con IC sobre cero ([−0,001, +0,013]): queda la
  simple, por la regla prerregistrada. Representante: semilla 20260930 (0,9841), SHA-256
  `ed6979378599…`.
- **Épocas:** ahora la mejor es la 1, 2 o 3 (en la v1 casi siempre la 1). Con etiquetas más
  cercanas al criterio del autor, entrenar más ya no aleja de él.
- **Calibración:** T = 1,21; ECE 0,025 → 0,018.
- **Por estrato** (v2 frente a coseno): alto 0,98 / 0,41, banda 0,99 / 0,62, bajo 0,95 / 0,69.
- Las tres semillas quedan en `semillas/` para el ensamble. Respaldo en
  `/home/pencalada/respaldo/22_modelos_v2/`, verificado.

El 0,984 no se compara con el 0,976 de la v1 sobre la misma `calibra` como si fuera un
resultado: la v2 se eligió con ella. **La comparación es H4, en `prueba 2`.**

### Permiso para Gemini con títulos de clientes (2026-09-30)

El autor declara tener el permiso para mandar títulos de clientes a Gemini, pendiente desde
D-035. Habilita la capa A0 (descripciones) y a Gemini como fuente de candidatos del oro lejano.
Pendiente: dejar referenciado el documento del permiso, sin datos personales.

### Resultado de H4 (2026-09-30): `prueba 2` abierta una vez

**Evidencia:** `salidas/31_h4.txt` y `31_puntajes_prueba2.csv`, de `31` sobre `48b4549` (repo
limpio). v1 `040b4dc4a6c5…`, v2 `ed6979378599…`, fp32. `prueba 2`: 400 pares (332 `si` / 68 `no`).

| juez | AUC en `prueba 2` |
|---|---|
| coseno | 0,565 |
| NLI congelado | 0,820 |
| **cross-encoder v1** | **0,977** |
| **cross-encoder v2** | **0,985** |
| ensamble de las 3 semillas de la v2 | 0,987 |

- **H4: no demostrada.** v2 − v1 = +0,008, IC 95 % [−0,003, +0,021]. El IC cruza el cero:
  **la v1 sigue siendo el cross-encoder de referencia**, como fija el prerregistro.
- **H1 se replica, y con más margen:** v1 − coseno = **+0,412, IC [+0,334, +0,489]**.
- **H4b:** v2 − NLI congelado = +0,166 [+0,115, +0,223]; v2 − coseno = +0,420.
- **El ensamble no aporta:** +0,002 sobre la v2 sola, IC [−0,003, +0,009].
- **Por estrato:** bajo v2 0,964 / v1 0,948 / coseno 0,564; banda v2 0,988 / v1 0,981 / 0,531.
- **Calibración y errores (descriptivo, P calibrada, umbral 0,5):** v1 ECE 0,071, junta mal 8/68,
  separa mal 18/332; **v2 ECE 0,027**, junta mal 7/68, **separa mal 10/332**. La v2 ordena casi
  igual, pero sus probabilidades son más fiables y se equivoca menos al decidir.

**Lectura.** Las dos versiones ya ordenan casi perfecto en `prueba 2`, y queda poco margen de
AUC que ganar. Lo que las etiquetas humanas cambiaron es la calibración. **El AUC de la v1 en
`prueba 2` (0,977) es muy superior al de `prueba` (0,890)** aunque `prueba 2` tiene coseno algo
más bajo: `prueba 2` se juzgó con la v5, con el paso 4 consistente, mientras que `prueba` arrastra
la inconsistencia del paso 4 que encontró `25`. **Parte del error medido en H1 era ruido de las
etiquetas, no del modelo.** Se declara en la tesis: los dos exámenes miden cosas algo distintas,
y los dos confirman H1.

---

## D-039 — La v1 queda como resultado confirmatorio; la v2 es el juez operativo

**Fecha:** 2026-10-01
**Origen:** H4 no demostrada (D-038): en `prueba 2` la v2 no le gana a la v1 en AUC con IC sobre
cero. Pero lo que viene —correlation clustering (capa C), el flujo de un cargo nuevo, el producto—
no usa solo el orden de los puntajes sino las **probabilidades**, y ahí la v2 es claramente
mejor. Decisión del autor.
**Estado:** adoptada.

### Qué se decide

- **Para la tesis, el resultado confirmatorio es el de la v1:** H1 en `prueba` (+0,269) y su
  réplica en `prueba 2` (+0,412). Nada de esto cambia.
- **El juez operativo es la v2** (`22_modelos_v2/elegido/`, SHA-256 `ed6979378599…`, T = 1,21):
  el que alimenta el correlation clustering, el diagnóstico de recall del bi-encoder y, en su
  momento, el producto.

### Por qué, y con qué salvedad

En `prueba 2`, con P calibrada y umbral 0,5 (descriptivo): ECE **0,027** frente a 0,071; separa
de más **10** de 332 frente a 18; junta de más 7 de 68 frente a 8. El correlation clustering usa
los log-odds de P(mismo): una probabilidad mejor calibrada es una entrada mejor, aunque el orden
sea casi el mismo.

**Es una elección exploratoria, no confirmada:** H4 no respalda a la v2 en AUC, y la ventaja de
calibración se ve en el mismo `prueba 2` que ya se abrió, sin criterio fijado de antemano. Se
declara así en la tesis. Si la capa C se evalúa con un oro nuevo, se puede comparar ahí con la v1
como control.

### Reversibilidad

Total: la v1 sigue guardada y respaldada; cambiar de juez es cambiar una ruta.

---

## D-040 — La capa 0 es una sola función de texto; criterios fijados antes de medir

**Fecha:** 2026-10-01
**Origen:** el autor revisa la normalización antes de reconstruir la base (`base_v16`). Principio:
**la capa 0 solo hace transformaciones de texto, deterministas y auditables, en una sola función
que se usa igual al construir y al consultar.** Nada semántico pasa ahí: eso lo decide el
cross-encoder.
**Estado:** **criterios registrados antes de mirar ningún número** (este commit). Las
mediciones y su resultado van debajo, en apartados posteriores.

### Orden de la capa 0

1. **Limpieza de texto:** lo que hace `_norm` (mayúsculas, sin tildes, espacios), más quitar la
   puntuación, más quitar el código o la numeración al inicio (`09.01 ANALISTA DE COSTOS`,
   `1. JEFE DE COMPRAS`, `3 LANCHERO`): es formato de planilla, no grado.
2. **Erratas:** como D-025/D-031, y **el diccionario que sale de la construcción también se aplica
   al consultar** (hoy un título de cliente con errata no se corrige).
3. **Género:** como D-026.
4. **Grado real, al final del título** (`AUXILIAR 2`, `QUIMICO II`, `AYUDANTE C`), **opción (a):**
   solo junta títulos idénticos salvo el grado, sin conectores ni orden. Sujeto al criterio A.
5. **Léxico de nivel** (criterio C).

**La fusión por coseno ≥ 0,95 (D-015) sale de la capa 0 si se cumple el criterio B.** Es el
embedding decidiendo donde nadie lo revisa: sus errores no los ve el cross ni el clustering, y al
consultar no se aplica igual que al construir. Los conectores y el orden («clave dura») siguen
fuera; se pueden medir aparte.

Lo medido antes de fijar esto, solo descriptivo, sobre los 50.296 grupos de `base_v15`, con las
reglas en orden: el código o la numeración al inicio une 127 grupos, la puntuación 262, el grado al
final (opción a) 1.340. La D-037 tal como estaba unía además unas 250 familias solo por conectores
u orden, efecto secundario que la opción (a) elimina.

### Criterio A — ¿el grado es un escalón salarial? (decide si se activa el paso 4)

- **Familias:** títulos idénticos (tras la limpieza) salvo un grado **ordinal** al final: números
  1–9 y romanos I–X. Las letras no tienen un orden fiable: se reportan aparte, sin decidir.
- **Medida:** para cada par de grados consecutivos de una familia, la diferencia de sueldo en log
  (grado mayor − grado menor). **Decide la versión DENTRO DE EMPRESA** (las mismas empresas con los
  dos grados, con los datos crudos de BigQuery, al reconstruir). La versión entre empresas sobre
  `base_v15` (centros de celda) es solo un adelanto y no decide.
- **Tres resultados** (IC 95 % por bootstrap de familias):
  - **Escalón:** diferencia media ≥ 5 % y el IC entero sobre cero → **no se fusiona.**
  - **Equivalente:** el IC entero dentro de ±5 % → **se fusiona.**
  - **Inconcluso:** cualquier otro caso → **no se fusiona**; esas celdas pueden agregarse solo
    cuando tienen pocos datos, como las inclusiones. La falta de evidencia no termina en fusión.
- **Consecuencia si no es «equivalente»:** el cross-encoder se entrenó con los pares de grado como
  `si` (las 149 correcciones y ~320 pares de la plata que la capa 0 fusionaría) y la evaluación los
  excluyó (Enmienda 5 de D-036). Habría que revertir la Enmienda 5 y la v5 en ese punto, pasar esos
  pares a `no`, sumarlos a la evaluación y **reentrenar**. Se quiere saber antes de seguir
  invirtiendo en el cross-encoder v2.

### Criterio B — ¿sale la fusión por coseno (D-015)?

- Todos los pares que la fusión semántica unió en `base_v15` (coseno ≥ 0,95 dentro del mismo
  grupo: 24.654) pasan por el cross-encoder v2 (juez operativo, D-039), con P calibrada.
- **Revisión a ciegas, mezclada:** 50 pares rechazados (P < 0,5) y 50 aceptados, al azar,
  barajados y sin marcar cuál es cuál. El autor juzga los 100 con la rúbrica v5.
- **Se confirma, y D-015 se enmienda, si:** el cross-encoder rechaza **al menos el 1 %** de los
  pares **y** al menos la mitad de los 50 rechazados revisados son de verdad distintos. Entonces
  esos pares los resuelven el cross-encoder y el clustering. Umbral bajo a propósito: sacarla cuesta
  poco, porque el cross y el clustering vuelven a juntar lo equivalente, y un 1 % ya son ~250
  fusiones malas que nadie revisa. Los 50 aceptados dicen además si el cross acepta lo que no
  debería.

### Criterio C — el léxico de nivel (aprobado tal cual)

- Se añaden a `RANGOS`: `SUBJEFE` (3), `ASESOR` (1), `EJECUTIVO` (1), `CONSULTOR` (2), `ENCARGADO`
  (3), `ASSISTANT` (1), `MANAGER` (5; `ASSISTANT MANAGER` = 4); y `SEMISENIOR` a la seniority.
  Medido sobre las 24.654 fusiones por coseno: cada uno bloquearía entre 0 y 16 (< 0,1 %). Ninguno
  es ambiguo por volumen (umbral: más del 1 %).
- Se alinea con la rúbrica: `TECNICO` y `ESPECIALISTA` solo cuentan como rango si abren el título;
  lo que va tras `DE`/`DEL` no cuenta.
- Confirmado: el candado solo bloquea cuando los dos títulos tienen nivel conocido y distinto
  (`VENDEDOR` / `ASESOR COMERCIAL` no se bloquea: `VENDEDOR` no tiene nivel).

### base_v16

Una sola reconstrucción con todo. Reporte de cambio **por regla**: cuántas fusiones aporta cada
una, % de personas que cambia de grupo, cuánto se mueve la mediana por banda y qué bandas se mueven
más de un 5 %. Las enmiendas (D-015, el criterio de D-037, el léxico) se registran antes de
reconstruir.

### Mediciones de D-040, primera parte (2026-10-01)

**Criterio B, primera condición: se cumple.** De las 24.654 fusiones por coseno de `base_v15`, el
cross-encoder v2 rechaza **727 (2,95 %)**, por encima del 1 % (`32_fusion_coseno_cross.py`).
Ninguno de los 727 es un par que la capa 0 de texto juntaría igual: todos dependen solo de D-015.
Mediana de P en los pares unidos 0,991; percentil 5, 0,934. **La segunda condición la decide la
revisión a ciegas** de 50 rechazados y 50 aceptados barajados (`32_revisar_coseno.csv`).

**Criterio A, adelanto entre empresas (no decide):** 31 familias con dos o más grados ordinales en
grupos distintos y celdas de al menos 3 empresas. Diferencia media +2,7 %, IC 95 % [−4,3 %,
+10,0 %]; el grado mayor paga más en el 45 % de las familias. Lectura con los tres resultados:
**inconcluso**. Se excluyeron 18 familias cuyos grados ya compartían grupo (y por tanto centro:
`m` es del grupo); la primera versión del adelanto las incluía y daba +1,1 %, sesgado hacia cero.
**Aviso:** con tan pocas familias, también la versión dentro de empresa puede salir inconclusa, y
por el criterio eso significa **no fusionar el grado** y revisar la Enmienda 5 (etiquetas,
evaluación y reentrenamiento). Se sabrá al reconstruir con BigQuery.

### Capa 0 a nivel de palabra: lo adoptado y las listas para aprobar (2026-10-01)

**Evidencia:** `34_capa0_palabras.py`, `35_capa0_v2.py` y `36_capa0_listas_y_colapsos.py`.

**Adoptado:**
- **Plural, regla simple:** una palabra de 5+ letras en -S/-ES pasa a su singular si el singular
  existe en la base; no las terminadas en -IS/-US. Une 425 grupos. **spaCy, descartado:** aporta
  54 grupos más que la regla simple, casi todos de género, y en mayúsculas sin tildes funciona mal.

**Ajustado tras medir:**
- **Erratas: se quita la regla de «3 empresas».** En `base_v15` las empresas son por grupo: una
  errata dentro de un grupo grande heredaba sus empresas (`NERERAL` 774, `COODINADORA` 503) y
  quedaba protegida, mientras los oficios raros reales (`CLAVADOR`, `PRORECTOR`, `SUBCONTRALOR`,
  `CUADRADOR`, de 1-2 empresas) seguían corrigiéndose mal. Ninguna regla de frecuencia separa
  «raro pero real» de «errata»: **el filtro es la aprobación del autor.** Quedan: menos de 5
  letras, diccionario es+en, y que el título corregido exista en la base.
- **Abreviaturas:** la expansión puede tener una sola letra más (`BODEG` → `BODEGA`, antes
  `BODEGUERO`); dominio ≥ 80 % con o sin punto; no se expande si es ambigua entre una palabra de
  rango y otra que no lo es (`ADMIN`, `TEC`, `OP`, `DIREC`: 20 casos).
- **Género por palabra,** solo -ERO/-ERA, -OR/-ORA, -IVO/-IVA, -ADO/-ADA, -ICO/-ICA: 385 pares,
  a revisar uno por uno (hay pares que no son género: `LOGISTICA` / `LOGISTICO`, `FISICA` /
  `FISICO`, `ELECTRICA` / `ELECTRICO`).

**Protocolo de aprobación (versión 1 de los diccionarios):** las reglas proponen y el autor
aprueba. Tres listas (`36_aprobar_erratas.csv` 884, `36_aprobar_abreviaturas.csv` 307,
`36_aprobar_genero.csv` 385), con ejemplos de títulos (antes → después), títulos afectados y
personas **estimadas** (la base guarda personas por grupo; se reparten por igual entre los
títulos del grupo; las exactas necesitan los datos crudos), ordenadas por personas con la
cobertura acumulada. **El autor revisa hasta el 95 % de las personas en cada lista (331, 113 y
126 filas); lo que no se revisa no se aplica.** Los diccionarios aprobados se guardan versionados
y se aplican igual al construir y al consultar.

### Colapsos del oro con la capa 0 nueva (2026-10-01)

Pares que la capa 0 convertiría en el mismo título, acumulado regla a regla (las reglas pendientes
se cuentan con todas sus propuestas: es una cota):

| regla | `calibra` (191) | `prueba` (555, H1) | `prueba 2` (400, H4) |
|---|---|---|---|
| texto (código inicial, puntuación) | 4 | 12 | 3 |
| + abreviaturas | 3 | 13 | 4 |
| + plural simple | 9 | 28 | 7 |
| + erratas | 10 | 36 | 10 |
| + género por palabra | 11 | 38 | 14 |
| + grado al final (si el criterio A lo activa) | **12** | **42** | **18** |

**Ninguno de los pares que colapsan es un `no`**: las reglas no juntan, en el oro, nada que el
autor separó. (Que la fila de abreviaturas baje respecto de la de texto en `calibra` es porque la
expansión de un lado deshace una coincidencia accidental del otro.) `prueba` y `prueba 2` **ya se
abrieron** (H1 y H4): esto no cambia esos resultados; decide cómo se leen y qué se evalúa en
adelante. **Qué hacer con estos pares se registra antes de recalcular nada.**

### Qué se hace con los pares del oro que colapsan (2026-10-01, antes de recalcular nada)

Decisión del autor:

1. **H1 (D-036) y H4 (D-038) se quedan como el resultado confirmatorio**, tal cual se registraron.
2. **Sensibilidad (exploratoria y declarada como tal):** H1 y H4 se recalculan sin los pares que
   colapsan con la capa 0 v1. Se reporta, igual que en el original:
   - la **diferencia** frente al coseno (cross-encoder − coseno) con su IC 95 % por bootstrap
     pareado por par, 10.000 remuestreos, no solo el AUC del cross-encoder; y para H4, v2 − v1 con
     el mismo método;
   - **cómo cambia la proporción de `si` y `no`** al sacar los pares.
   Se calcula cuando estén aprobados los diccionarios y decidido el criterio A.
3. **De aquí en adelante, la exclusión va atada a la versión de la capa 0:** «se excluyen los pares
   que colapsan con la **capa 0 v1**», es decir, las reglas adoptadas y los diccionarios que el autor
   apruebe ahora. Si después hay una capa 0 v2, se reporta cuántos pares más colapsan con ella, **sin
   redefinir lo anterior**: cada evaluación dice con qué versión de la capa 0 se excluyó.

### La capa 0, implementada en el producto (2026-10-02)

**Evidencia:** `src/benchmarking/producto/capa0.py`, `nivel.py` (`nivel_rubrica`),
`base_referencia.py` y `tests/test_producto_capa0.py`.

- **Una sola función, `Capa0.atomo(titulo)`**, igual al construir y al consultar. Orden:
  normalización (`_norm`) → abreviaturas (antes de quitar la puntuación) → grado al final
  (**apagado por defecto**, depende del criterio A) → código inicial y puntuación → plural →
  erratas (solo si el título corregido existe en la base) → género por palabra.
- **El grado se detecta sobre las palabras originales,** antes de quitar la puntuación: si no,
  `COORDINADOR M & R` quedaría en `COORDINADOR M R` y la `M` y la `R` se leerían como grados.
- **Diccionarios versionados** en `producto/datos/capa0_v1/`, con solo las filas aprobadas
  (hoy vacíos). `37_exportar_capa0.py` pasa a esos archivos las filas con `aprobar = si` de las
  listas de `36`. El mapa de plural lo genera la construcción desde el vocabulario de la base.
- **En la base:** `construir(..., capa0=...)` agrupa por átomo y guarda la capa 0 (reglas y
  diccionarios) dentro del `.npz`, para que la consulta use exactamente las mismas. Con
  `umbral_fusion=None` se saca la fusión por coseno (criterio B) **sin apagar** las pasadas de
  errata (D-025) y género (D-026), que antes colgaban de ella.
- **El candado de las fusiones usa `nivel_rubrica`** (criterio C) cuando hay capa 0.
  `nivel_lexico` no cambia: alimenta la escalera salarial y `efecto_nivel`, y cambiarlo
  movería estadísticos medidos; si se alinea también ahí, es otra decisión con su medición.
  `SEMISENIOR` entra como marca de seniority propia (0,5).
- **El grado de D-037 queda apagado por defecto** (`grado=False`), y su consulta por grado
  también: la regla vigente es la de la capa 0, pendiente del criterio A.
- **Las bases anteriores siguen funcionando:** `base_v15` carga sin capa 0 y responde igual.
- **Tests:** los cuatro pedidos (`CASERO` ≠ `CAJERO` con la protección del diccionario, una
  errata en dos palabras, una abreviatura, un plural) y ocho más (código inicial y puntuación,
  grado y sus guardas, errata solo hacia títulos que existen, género, nivel de la rúbrica,
  construir y consultar con la misma capa 0, guardar y cargar, y la base sin capa 0). Sin fallos
  nuevos en la suite (292 pasan; los 5 que fallan ya fallaban por dependencias del entorno).

### Criterio B: se confirma, la fusión por coseno sale de la capa 0 (2026-10-02)

Revisión a ciegas del autor de los 100 pares (`32_revisar_coseno.csv`, `32 evaluar`):

| | juzgados distintos de verdad |
|---|---|
| 50 que el cross-encoder rechaza | **30 (60 %)** |
| 50 que el cross-encoder acepta | **0 (0 %)** |

Tasa de rechazo 2,95 % (≥ 1 %) y 60 % de distintos entre los rechazados (≥ 50 %): **el criterio B se
cumple y D-015 se enmienda.** La fusión por coseno ≥ 0,95 deja la capa 0 (`umbral_fusion=None` al
construir `base_v16`); esos pares los resuelven el cross-encoder y el clustering. Lo que juntaba mal
era sobre todo seniority (`SUPERVISOR DE FINANZAS` / `… SR`, `ANALISTA CREDITO` / `… DE CREDITO SR.`,
`… SEMISENIOR` / `… SENIOR`). Y el cross-encoder no aceptó ningún par distinto en la muestra.

### La capa 0 v1: diccionarios aprobados (2026-10-02)

El autor revisó el **100 %** de las tres listas (más allá del 95 % previsto). Tras la revisión de
Claude se corrigieron 9 decisiones antes de exportar: **8 erratas aprobadas pasan a `no`** porque en
la base juntan oficios o palabras distintas (`CLAVADOR` / `LAVADOR`, `PRORECTOR` / `PROTECTOR`,
`SUBCONTRALOR` / `SUBCONTADOR`, `PRESALE` / `PESAJE`, `CUTOVER` / `CUSTOMER`, `MECANISTA` /
`MECANICA`, `SANEADOR` / `PLANEADOR`, `COPASTOR` / `PASTOR`), y **`PAI` → `PAIS` pasa a `no`**
(era un `on` mal escrito; PAI es el Programa de los Años Intermedios del Bachillerato
Internacional). En género, los pares que podían ser disciplinas (`FISICA`, `CLINICA`,
`ESTADISTICA`…) se revisaron contra la base: solo producen concordancias correctas (`ANALISTA
ESTADISTICA` = `… ESTADISTICO`).

**Capa 0 v1** (`producto/datos/capa0_v1/`, `37_exportar_capa0.py`): **848 erratas, 216
abreviaturas y 380 pares de género.** Sobre los 65.181 títulos de `base_v15`, sin grado y sin
fusión por coseno, da **58.911 átomos**.

### Criterio A: el grado ES un escalón salarial; no se fusiona (2026-10-02)

**Evidencia:** `38_grado_dentro_empresa.py` y `salidas/38_grado_dentro_empresa.txt`, sobre
`nomina_features` (2024-2025, `en_clean`, filas evaluables: 1.000.490), con BigQuery. La versión
**dentro de empresa**, la que decide según lo registrado.

- Filas con un grado al final: 35.244 (3,5 %); ordinales 13.418, letras 21.826.
- **Ordinales:** 1.092 contrastes dentro de la misma empresa y año (grados consecutivos de la
  misma familia), en 383 familias. **Diferencia media entre familias: +6,9 %, IC 95 % [+4,7 %,
  +9,1 %].** Media ≥ 5 % y el IC entero sobre cero: **ESCALÓN → el grado no se fusiona.**
- Descriptivo: el grado mayor paga más en el 61 % de las familias y en el 55 % de los
  contrastes; mediana de los contrastes +3,3 %; media ponderada por personas +8,3 %; por salto
  de un grado +4,9 % (n = 961).
- **Letras** (no deciden): 283 contrastes en 98 familias, diferencia absoluta media 13,3 %.
- El adelanto entre empresas (`33`) daba inconcluso (+2,7 %): entre empresas la escala interna se
  diluía, como se anticipó.

**Consecuencias (D-040, criterio A):**
1. La capa 0 v1 **no borra el grado** (`grado=False`, ya por defecto) y D-037 queda sin efecto.
2. Las erratas aprobadas que borran un grado pegado (`TECNICO1`, `CONTABLE2`, `COORDINADOR2`,
   `CORPORATIVA1`…`7`, `CHOFERB`…: 22) contradicen el resultado y deben salir del diccionario.
3. **La Enmienda 5 de D-036 se revierte en lo que toca al grado:** las etiquetas corregidas de
   `no` a `si` por el grado (17 humanas, 149 de la plata, incluidas las 12 revisadas a mano) vuelven a
   su valor anterior; los pares excluidos de `calibra` y `prueba` por la capa 0 de grado vuelven a la
   evaluación; la regla del paso 1 de las rúbricas v4/v5 se revisa. **El cross-encoder se entrenó
   con los pares de grado como `si`: hay que reentrenarlo** con ellos como `no`.
   El plan concreto se registra antes de ejecutarlo.

**Las erratas que borraban un número salen del diccionario (2026-10-02).** Por el criterio A,
19 erratas aprobadas pasan a `no`: las que quitaban un dígito o un romano pegado (`TECNICO1/2/3`,
`CONTABLE1/2/3`, `PROFESIONAL2`, `COORDINADOR2`, `CORPORATIVA1`…`7`, `MOTORIZADO1`,
`PRODUCCIONI`, `SERVICIOS2/5`). Las que quitan una **letra** pegada (`CHOFERB`) se quedan, por
D-041. Capa 0 v1: **829 erratas**, 216 abreviaturas, 380 pares de género.

---

## D-041 — Las letras de grado se fusionan, sin medir. Decisión del autor que se aparta del criterio A

**Fecha:** 2026-10-02
**Origen:** decisión del autor tras el criterio A (D-040). **Se aparta a propósito de la regla del
criterio A**, que manda no fusionar lo inconcluso o no medido.
**Estado:** adoptada.

### Qué se decide

- **La capa 0 fusiona las letras al final del título:** `AYUDANTE A` = `AYUDANTE B` = `AYUDANTE`.
  Con las mismas guardas de siempre (una letra junto a `&` es sigla, tras `LICENCIA`/`TIPO` es un
  tipo, la `A` solo al final, nunca `E`, `Y`, `O`, `U`).
- **Los números no:** `AUXILIAR 1` y `AUXILIAR 2` quedan separados (criterio A: escalón, +6,9 %).
- **Candado de grado numérico,** como el de seniority de D-033: dos títulos con número de grado
  distinto **nunca quedan en el mismo grupo, aunque el cross-encoder diga que sí.** Aplica solo a
  números. Hace falta porque el cross-encoder v2 aprendió que el grado no separa y, sin candado,
  el clustering juntaría lo que el criterio A separa.

### Por qué

Sin fusionar, las letras dejan celdas muy chicas que no sirven para bandas.

### Cuánto afecta (datos de 2024-2025, `nomina_features`)

- **715 títulos** llevan una letra de grado al final; **21.826 personas** (2,2 % de las filas
  evaluables).
- Con la fusión quedan juntos **1.436 títulos en 305 familias** (incluido el título sin letra de
  cada familia): 1.131 grupos menos. Las personas en las celdas que cambian son **185.267 (18,5 %)**,
  porque cuenta a toda la gente de la celda sin letra a la que se suman las variantes con letra.
- Muchas de esas «letras» no son grados sino marcas entre paréntesis (`(A)`, `(F)`, `(R)`,
  `(G)`): género inclusivo o códigos internos. Fusionarlas es coherente con la rúbrica.

### Límite que se declara

En el criterio A, entre letras de la misma familia y empresa, la **diferencia absoluta media de
sueldo es del 13,3 %** (283 contrastes en 98 familias). Sugiere que muchas letras son escalones
internos de cada empresa: **las bandas de esas celdas pueden mezclar niveles.** No se midió si el
grado por letra paga sistemáticamente más (las letras no tienen un orden fiable), así que esta
fusión es una elección de producto, no un resultado.

### Consecuencias

- **Rúbrica v6:** la v5 con dos cambios: el grado numérico separa, y una diferencia solo de letra
  no separa.
- **Etiquetas:** al revertir la Enmienda 5 de D-036, los pares que difieren en número vuelven a `no`;
  los que difieren solo en letra se quedan en `si`. El plan detallado se registra antes de tocarlas.
- **Cross-encoder v3:** se reentrena con eso. Como `prueba` y `prueba 2` ya se abrieron, **lo que mida
  la v3 en ellos es exploratorio.** Si hay tiempo, se evalúa armar un conjunto nuevo de ~200 pares
  con grado para un resultado confirmatorio.

### Implementación (código)

- **Letras:** `capa0.quitar_letra_final`, encendida por defecto (`Capa0(letras=True)`). Usa las
  mismas guardas que el grado: no es letra tras `&` (sigla `M & R`) ni tras `LICENCIA`/`TIPO`; la
  `A` solo cuenta al final; quita también el `NIVEL`/`CATEGORIA` que la precede. **`I`, `V` y `X`
  se leen como romanos, no como letras:** no se fusionan (criterio A).
- **Números:** se quedan en el átomo. `Capa0(grado=True)` los quitaría; queda apagado.
- **Candado de grado** (`capa0.grado_numerico` y `capa0.compatibles`): un título lleva los números de
  grado que tenga, sueltos (1-9 o II-X, y la `I` al final) o pegados al final de una palabra
  (`TECNICO2`), en cualquier posición salvo el código de planilla del inicio (`1. JEFE DE
  COMPRAS` no tiene grado). Dos grupos cuyos números conocidos difieren no se juntan; un título
  sin número no bloquea. Igual que el de seniority de D-033, se lleva **por grupo**: el conjunto
  de números de todos sus títulos. Se comprueba en las cuatro pasadas: átomo de la capa 0, coseno
  (`_fusionar`), errata (D-025) y género (D-026). El clustering con el cross-encoder lo usará
  cuando exista.
- **Solo se enciende con capa 0.** Las bases sin capa 0 (la v15 y anteriores) siguen igual, para
  que lo medido con ellas se pueda reproducir.

### Rúbrica v6

`research/experimentos/e2_nivel/rubrica_mismo_cargo_v6.md`: la v5 con un solo cambio, en el paso 1.
- **El número de grado separa** si está en los dos títulos con valor distinto (`AUXILIAR 1` ≠
  `AUXILIAR 2`). Si está en uno solo, no separa.
- **La letra de grado no separa**, esté donde esté.
- Lo que cuenta como número es lo mismo que reconoce el candado (`capa0.grado_numerico`): se
  comprobaron los ejemplos de la rúbrica contra el código. Un número al principio pasa a ser
  código de planilla y no grado.
- Los pasos 2 a 5 son idénticos a los de la v5 (comprobado con `diff`). Los ejemplos nuevos no
  aparecen en `13e`, `20` ni `29`.
- La capa 0 solo junta la letra **al final** del título; la rúbrica la trata como ruido en
  cualquier posición. No hay contradicción: la capa 0 es la parte conservadora, y lo demás
  (`AYUDANTE B DE MANTENIMIENTO` / `AYUDANTE C DE MANTENIMIENTO`) lo decide el cross-encoder,
  que el candado no frena porque no hay número.

### Plan para revertir la Enmienda 5 en las etiquetas (2026-10-02, registrado ANTES de tocarlas)

**Evidencia:** `research/experimentos/e2_nivel/39_inventario_grado_v6.py` (solo lee; no cambia
ninguna etiqueta), `salidas/39_inventario_grado_v6.txt` y `salidas/39_pares_numero_distinto.csv`.

**Una guarda nueva en el candado, vista al hacer el inventario.** En la plata salen pares como
`COORDINADOR ZONA 1` / `ZONA 2`, `SUPERVISOR DE SECTOR 1` / `2` o `EJECUTIVO ASISTENTE (OFC 1)` /
`(OFC 2)`: ahí el número es la zona o la oficina, no el grado. `capa0.grado_numerico` ya no cuenta
un número que vaya justo detrás de `ZONA`, `SECTOR`, `OFC`, `REGION`, `AGENCIA`, `SUCURSAL`,
`TIENDA`, `PLANTA`, `TURNO`, `LINEA`, `DISTRITO`, `CUADRILLA`, `FRENTE`, `LOCAL`, `SEDE`, `PISO` ni
`MODULO` (`LUGAR_ANTES_DE_NUMERO`). `OFICINA` y `BODEGA` **no** son guarda (`ASISTENTE DE OFICINA 2`
y `AUXILIAR DE BODEGA 1` son grados); `RUTA` tampoco, porque `AYUDANTE DE RUTA 1` / `2` es dudoso.
**Límite:** la lista salió de mirar la plata; se declara así. La rúbrica v6 se lee con la misma guarda.

#### 1. La regla: mecánica y en un solo sentido

Un par cuyos dos títulos llevan número de grado, con valor distinto (`capa0.compatibles` es False),
pasa a `no`. Nada más cambia: un `no` nunca pasa a `si` por esta regla, y las letras y el número en
un solo título no se tocan (siguen como las dejó la Enmienda 5, porque la v6 dice lo mismo). Es la
lectura literal del paso 1 de la v6, que decide en `p1`.

| conjunto | pares | con número distinto | `si` → `no` | de ellos, corregidos por la Enmienda 5 | correcciones de la Enmienda 5 que se quedan `si` |
|---|---|---|---|---|---|
| `calibra` (`13e`) | 200 | 4 | 4 | 4 | 0 |
| `prueba` (`13e`) | 200 | 2 | 2 | 2 | 0 |
| `prueba` (`20`) | 400 | 8 | 8 | 4 | 6 (número en un solo título, y #237) |
| `prueba 2` (`29`) | 400 | 1 | 1 (#169, `AYUDANTE DE RUTA 1 LE` / `2 LC`) | — | — |
| plata `entrena` | 8.900 | 119 | 118 | 117 | 10 |
| plata `valida` | 1.500 | 18 | 18 | 18 | 4 |

- En `prueba` (`20`), 4 de los 8 (#190, #329, #353, #364) **no** venían de la Enmienda 5: ya estaban
  `si` en el juicio original, que mezclaba criterios (lo dice la Enmienda 5, §1). La v6 los pasa a `no`.
- En la plata, el único `si` → `no` que no viene de la Enmienda 5 es #3382 (`... NIVEL 1` /
  `... NIVEL 1 GRADO 3 MEDIO TIEMPO`), que Gemini juzgó `si`. El caso hermano del lote (#100076) ya
  era `no` a mano.
- De los 12 de la plata revisados a mano en la Enmienda 5 (`23_revisar_grado.csv`), vuelven a `no`
  los que tienen número distinto en los dos títulos (p. ej. `ASISTENTE FINANCIERO 3` /
  `AUXILIAR FINANCIERO 1`). La revisión se hizo con el grado borrado; con la v6 decide el paso 1.

#### 2. Cómo se aplica, sin perder la historia

- **Juicios humanos** (`13e`, `20`, `29`): `mismo` toma el valor nuevo y el de antes queda en una
  columna `mismo_v5`, como `mismo_v3` y `mismo_v4`. La nota pasa a `p1 v6`.
- **Plata:** un archivo nuevo, `39_correcciones_v6.csv`, que `21` aplica **al final**, después de las
  de la v5, con `origen` + `_v6` y motivo `p1`. Las respuestas de Gemini y los archivos de `23` y
  `27` no se tocan.
- El guion es re-ejecutable: siempre parte de la columna guardada.

#### 3. La exclusión por la capa 0, rehecha con la capa 0 v1

Por D-040 («la exclusión va atada a la versión de la capa 0»), `23_fuera_por_capa0.csv` (la regla
del grado de la Enmienda 5) se reemplaza por `39_fuera_capa0_v1.csv`: sale de la evaluación el par
cuyos dos títulos dan **el mismo átomo con la capa 0 v1** (letras fuera, números dentro). Los pares
con número distinto **vuelven**, y entran los que ya junta la capa 0 por otras reglas (plural,
erratas, abreviaturas, género, puntuación).

| conjunto | fuera antes (Enmienda 5) | fuera con la capa 0 v1 | vuelven | salen nuevos | etiquetas de los que quedan fuera |
|---|---|---|---|---|---|
| `calibra` | 9 | 13 | 7 | 11 | 13 `si`, 0 `no` |
| `prueba` (`13e`) | 9 | 13 | 6 | 10 | 13 `si`, 0 `no` |
| `prueba` (`20`) | 27 | 32 | 25 | 30 | 32 `si`, 0 `no` |
| `prueba 2` | 0 | 14 | 0 | 14 | 14 `si`, 0 `no` |

La plata no se excluye: los pares que la capa 0 junta siguen enseñando que son el mismo cargo.

#### 4. Qué se mide con eso, y qué no se toca

- **H1 (D-036) y H4 (D-038) no se tocan:** son el resultado confirmatorio, con las etiquetas y la
  exclusión con que se registraron.
- **`calibra`:** con las etiquetas v6 y la exclusión v1 se vuelve a medir la vara (NLI congelado y
  coseno), y el candado de `22` pasa al `AUC_BASE` nuevo **antes** de entrenar.
- **Cross-encoder v3:** mismo protocolo, grilla e hiperparámetros que la v2 (D-039); solo cambian las
  etiquetas (plata con `39_correcciones_v6.csv`) y `calibra`. `prueba` y `prueba 2` siguen sin viajar.
- **Su evaluación en `prueba` y `prueba 2` es exploratoria** (los dos se abrieron): v3 − coseno y
  v3 − v2, con el bootstrap pareado de siempre, con las etiquetas v6 y la exclusión v1, y además con
  las etiquetas y la exclusión originales, para que se vea qué parte del cambio es del juez y qué parte
  de la vara. Se reporta aparte cómo le va en los pares con número distinto.
- **Resultado confirmatorio para el grado (opcional):** un conjunto nuevo de ~200 pares con grado, sin
  solaparse con nada de lo anterior, juzgado a ciegas con la v6. Su análisis se registra antes de
  armarlo.

#### Orden de ejecución

1. Aplicar §2 y §3 (guion `39`, modo escritura). Comprobar que solo cambian los pares de las tablas.
2. Rehacer el paquete (`21`) y la vara de `calibra`; fijar el `AUC_BASE` nuevo en `22`.
3. Reconstruir `base_v16` (capa 0 v1, candado de grado, sin fusión por coseno) con su informe por regla.
4. Entrenar el cross-encoder v3 y evaluarlo (exploratorio).

#### Ejecutado (2026-10-02): paso 1 del orden

`python 39_inventario_grado_v6.py escribir`. Cambió exactamente lo de las tablas:
- Juicios humanos, `si` → `no`: `13e` #104, #111, #188, #290, #350, #396; `20` #46, #53, #88, #185,
  #190, #329, #353, #364; `29` #169. Comprobado contra el commit anterior: en cada archivo solo
  cambian `mismo` y `nota` de esos pares, y aparece `mismo_v5` igual al `mismo` de antes.
- Plata: `39_correcciones_v6.csv`, 136 correcciones (118 `entrena`, 18 `valida`). Aún no las aplica
  `21`: es el paso 2.
- Exclusión: `39_fuera_capa0_v1.csv` (`calibra` 13, `prueba` 13 + 32, `prueba 2` 14).
- **H1 y H4 se protegen:** `24` y `31` leen `mismo_v5` cuando existe. Comprobado: H1 sigue con
  555 pares (433 `si` / 122 `no`) y H4 con 400 (332 / 68), como antes del cambio.

#### Ejecutado (2026-10-02): paso 2, el paquete v6 y la vara de `calibra`

- **`21 --v6`** arma `salidas/21_paquete_v6/` sin tocar `21_paquete/` (el de la v2, que H1 y H4
  comprueban por hash). Comprobado contra `21_paquete`: en la plata cambian exactamente las 136
  etiquetas de `39_correcciones_v6.csv` (todas de 1 a 0) y ninguna otra columna salvo `motivo` y
  `origen`. `calibra`: **187 pares (140 `si` / 47 `no`)**, 13 fuera por la capa 0 v1. Ningún par de
  `prueba` ni de `prueba 2` en el paquete.
- **La vara** (`40_vara_calibra_v6.py`, con las mismas funciones de `22`, CPU, fp32):

  | `calibra` | pares | NLI sin entrenar | coseno | NLI − coseno |
  |---|---|---|---|---|
  | `21_paquete` (control, la de la v2) | 191 | 0,7346 | 0,6438 | +0,091 [−0,015, +0,200] |
  | **`21_paquete_v6`** | **187** | **0,7416** | **0,6225** | **+0,119 [+0,011, +0,233]** |

  El control reproduce el `AUC_BASE` de antes (0,7346), así que la medición es la misma. Con las
  etiquetas v6, el NLI sin entrenar separa mejor (los pares con número distinto vuelven a `no`, y el
  NLI ya les daba puntaje bajo) y el coseno peor (les da puntaje alto).
- **`22`:** el `AUC_BASE` depende del paquete (`21_paquete` 0,7346; `21_paquete_v6` **0,7416**) y se
  detiene si el paquete no tiene uno registrado. Con `21_paquete_v6` escribe en `22_modelos_v3/`:
  la v1 y la v2 no se tocan.

#### Ejecutado (2026-10-02): paso 3, `base_v16`, y paso 4, el cross-encoder v3

**`base_v16`** (`41_base_v16.py`, `demo/base_v16.npz`, no se sube: lleva sueldos y bandas). Capa 0 v1
(letras fuera, números dentro), sin fusión por coseno, candados con el nivel de la rúbrica y el de
grado. Mismos datos que la v15 (1.000.490 filas, 65.181 títulos, todos en común) y mismos vectores.

**Un error encontrado al construirla, y corregido antes del informe.** Con la letra fuera,
`COORDINADOR C` entra en el grupo grande de `COORDINADOR`, y la pasada de erratas (D-025), que compara
el título crudo, absorbía detrás `COORDINADOR DC`, `QC`, `QA`, `TH`, `SAP`…: siglas de área a una
letra de distancia, no dedazos. La guarda de «letra suelta» solo cubría el caso de igual largo.
**Con capa 0, el dedazo tiene que estar en una palabra de 4 letras o más en los dos títulos**
(`PALABRA_MIN_ERRATA`, test incluido). Sin capa 0 (v15) no cambia nada. Absorciones por errata:
472 → 316. El grupo de `COORDINADOR` queda con sus grafías, el género y las letras.

**Informe** (`salidas/41_base_v16.txt`):

| | v15 | v16 |
|---|---|---|
| grupos (65.181 títulos) | 50.296 | **58.051** |
| títulos en grupos de 2 o más | 23.742 | 11.438 |
| grupo más grande | 30 títulos | 81 (grafías de `ASISTENTE ADMINISTRATIVO`) |

- **Capa 0, regla por regla** (títulos que comparten átomo con otro: 10.898 con todo). Lo que se
  pierde al apagar cada regla: plural 2.486, género 2.047, erratas 1.652, letras de grado 556,
  abreviaturas 441. Solo con puntuación y código inicial: 3.035. No suman: hay títulos que necesitan
  dos reglas.
- **Pasadas:** capa 0 6.695 uniones, errata 316, género 119.
- **Candado de grado: no bloqueó ninguna unión.** 2.161 títulos llevan número de grado (12.222
  personas), pero el átomo conserva el número y la errata ya excluye los dígitos. Hoy es una red de
  seguridad; trabaja de verdad cuando el clustering con el cross-encoder junte por significado.
- **Quién cambia de grupo:** 22.564 títulos (34,6 %), 425.451 personas-título de 666.574 (63,8 %;
  una persona que pasó por dos títulos cuenta dos veces). **El grueso es por quitar el coseno:**
  18.431 títulos quedan en un grupo más chico (236.744 personas-título) y 3.530 en uno más grande
  por la capa 0 (160.648).
- **Bandas de los títulos que cambian** (exp(dif) − 1): la mediana del desplazamiento es 0 en las
  cuatro; la mediana del valor absoluto, 2,8 % (p10), 5,0 % (p25), 7,0 % (p50) y 6,1 % (p75). **Alguna
  banda se mueve más del 5 % en 17.300 títulos, 138.797 personas-título (20,8 % del total).** Casos
  grandes: `VENDEDOR / A` y `VENDEDOR (A)` +15 % en p50 (de 7 a 19 títulos); `REPRESENTANTE DE
  NEGOCIOS` −31 % (de 2 a 1); `TRABAJADOR/A AGRICOLA` +10 %.

**Cómo leerlo.** La v16 es solo la capa 0: el texto que es el mismo título escrito de otra forma.
Las uniones por significado que hacía el coseno (D-015) ya no están, y **le tocan al cross-encoder y
al clustering, que todavía no existen.** Por eso muchas celdas quedan más chicas que en la v15 y sus
bandas se mueven. **La v16 no reemplaza a la v15 en el producto** hasta que la base con el clustering
se construya y se mida.

**Cross-encoder v3** (`22 --grilla v2 --paquete salidas/21_paquete_v6`, GPU, commit `0cb97b8`, repo
limpio, 6 corridas, ninguna retomada; pesos en `22_modelos_v3/`, respaldados en
`/home/pencalada/respaldo/22_modelos_v3`, idénticos):
- El juez sin entrenar dio 0,7416, la vara registrada.
- Elegida `w_humano = 1`, como en la v2 (`w_humano = 3` no le gana: IC [−0,001, +0,012]). AUC medio
  en `calibra` (187, optimista) **0,9816** (sd 0,004); el representante, 0,9839. Temperatura
  **T = 1,243**, ECE 0,029 → 0,023.
- No se compara con la v2 en `calibra`: la `calibra` es otra (191 frente a 187, otras etiquetas).
  La comparación es la evaluación exploratoria en `prueba` y `prueba 2`.

#### Evaluación exploratoria del cross-encoder v3 (2026-10-02)

**Evidencia:** `42_v3_exploratorio.py` (commit `13b922b`, repo limpio), `salidas/42_v3_exploratorio.txt`
y `42_puntajes.csv`. **Exploratorio:** `prueba` y `prueba 2` ya se habían abierto. H1 y H4 no cambian.

| conjunto · vara | pares | v3 | v2 | coseno | v3 − coseno | v3 − v2 |
|---|---|---|---|---|---|---|
| `prueba` · original (H1) | 555 | 0,8945 | 0,8962 | 0,6211 | +0,273 [+0,208, +0,339] | −0,002 [−0,009, +0,006] |
| `prueba` · v6 + capa 0 v1 | 546 | 0,8941 | 0,8590 | 0,6099 | +0,284 [+0,218, +0,350] | **+0,035 [+0,010, +0,065]** |
| `prueba 2` · original (H4) | 400 | 0,9875 | 0,9850 | 0,5652 | +0,422 [+0,348, +0,499] | +0,003 [−0,002, +0,008] |
| `prueba 2` · v6 + capa 0 v1 | 386 | 0,9873 | 0,9821 | 0,5603 | +0,427 [+0,350, +0,501] | +0,005 [−0,000, +0,012] |

- **Con la vara original, la v3 empata con la v2** en los dos conjuntos: reentrenar con el grado no
  le costó nada en lo que ya hacía bien.
- **Con la vara v6, la v3 le gana a la v2 en `prueba`** (+0,035, IC sobre cero). **Toda la ventaja
  viene de los pares con número distinto:** sin ellos, v3 − v2 = −0,004 [−0,011, +0,004] en `prueba` y
  +0,003 [−0,001, +0,009] en `prueba 2`.
- **Pares con número de grado distinto** (11: 10 en `prueba`, 1 en `prueba 2`; todos `no` con la v6):
  la v1 y la v2 juntan los 11 (P calibrada mediana 0,97 y 0,99); **la v3 no junta ninguno** (mediana
  0,008; el más alto, `AYUDANTE DE RUTA 1 LE` / `2 LC`, 0,23). El coseno les da 0,94 de mediana.
- **Límite:** son 11 pares, y la v3 aprendió de 136 de la plata con la misma regla mecánica. Que la
  v3 separe el grado en pares nuevos lo diría el conjunto confirmatorio de ~200 pares con grado (§4),
  que sigue siendo opcional.
- **Juez operativo:** la v3 hace lo mismo que la v2 en todo lo demás y además separa el grado, que
  es lo que dice la rúbrica v6. **Propuesta: la v3 pasa a ser el juez operativo** (decisión del autor).

---

## D-042 — La v3 es el juez operativo

**Fecha:** 2026-10-03
**Origen:** decisión del autor, tras la evaluación exploratoria de D-041.
**Estado:** adoptado. Reemplaza a la v2 como juez operativo (D-039).

- **El cross-encoder v3** (`22_modelos_v3/elegido`, sha `a5fb00032d8c`, T = 1,243) pasa a ser el juez
  que se usa de aquí en adelante: el correlation clustering, el producto y los análisis nuevos.
- **Por qué:** con la vara original empata con la v2 en `prueba` y `prueba 2`, y además separa el
  número de grado (0 de 11 pares juntados, frente a 11 de 11 de la v2), que es lo que dice la rúbrica
  v6. La evidencia es **exploratoria** (D-041): `prueba` y `prueba 2` ya estaban abiertos.
- **Lo que no cambia:** H1 (v1, D-036) y H4 (v2 frente a v1, D-038) siguen siendo los resultados
  confirmatorios, con sus jueces y su vara. La v1 y la v2 se conservan (pesos y respaldos).
- **Pendiente opcional:** el conjunto confirmatorio de ~200 pares con grado, para decir con un
  examen nuevo que la v3 separa el grado.

**Corrección de presentación, mismo día.** Al consultar `base_v16`, el nombre de referencia
(`cargo_base`) de un título resuelto por la capa 0 salía con errata (`AYUDANTE DE BODEGA B` →
`ADYUDANTE DE BODEGA`): las celdas del mismo grupo empataban en empresas (el conteo es del grupo) y
ganaba la primera en orden alfabético. Ahora desempata la grafía que ya es el átomo y luego la más
corta. No cambia ningún grupo ni ningún número.

---

## D-043 — ¿Cuánto pierde Vertex como buscador de candidatos? Diagnóstico antes del clustering

**Fecha:** 2026-10-03 (registrado ANTES de medir)
**Origen:** el diseño del correlation clustering usa el coseno de Vertex para proponer qué pares
juzga el cross-encoder v3. Si Vertex no propone un par que sí es el mismo cargo, la v3 nunca lo ve.
Ese es el trabajo del bi-encoder, y esta medición decide si hace falta antes del clustering.

**Por qué no sirve el oro que ya tenemos:** `calibra`, `prueba`, `prueba 2`, la plata y el lote 30 se
muestrearon todos entre pares con coseno ≥ 0,90. Medir con ellos daría 0 % de pérdida por
construcción.

**Diseño:**
1. **Nodos:** los grupos de `base_v16` (capa 0). Cada uno se representa por la celda que ya es su
   átomo, o si no, la más corta. Vector: el de Vertex de ese representante.
2. **Muestra:** 2.000 nodos, sorteados sin reposición con peso por personas (semilla fija).
3. **Buscador independiente de Vertex:** para cada nodo de la muestra, sus 25 vecinos más parecidos
   por TF-IDF de n-gramas de caracteres (3 letras, dentro de palabra) entre los representantes.
4. **Juez:** la v3 (D-042), P calibrada (T = 1,243); `si` si P ≥ 0,5. Los pares que bloquea algún
   candado (nivel de la rúbrica, seniority, número de grado) no cuentan: el clustering nunca los
   juntaría.
5. **Vertex lo propone** si el par está entre los 25 vecinos de Vertex de alguno de los dos y su
   coseno es ≥ el piso. Pisos: 0,80, 0,85 y 0,90.
6. **Pérdida** = de los pares `si` de la v3, la fracción que Vertex no propone; por pares y
   ponderada por las personas del nodo sorteado.
7. **Auditoría humana a ciegas:** 100 pares de los perdidos con el piso 0,90 (sorteados en
   proporción a cuatro tramos: fuera de los 25 vecinos, coseno < 0,80, 0,80–0,85, 0,85–0,90),
   mezclados con 50 pares que la v3 rechazó, juzgados por el autor con la rúbrica v6 sin ver al
   modelo. La fracción de `si` por tramo corrige la pérdida de cada piso.

**Criterio:**
- se elige el **piso más alto** cuya pérdida corregida sea **menor del 5 %** de los `si`;
- si ninguno la cumple (ni 0,80), **el bi-encoder va antes del clustering**;
- si se cumple, el clustering usa Vertex con ese piso y el bi-encoder queda como mejora posterior.

**Límite que se declara:** la pérdida es relativa a lo que encuentran las letras. Los sinónimos sin
letras en común (`CHOFER` / `CONDUCTOR`) no los encuentra ninguno de los dos buscadores; medirlos es
la comparación de bi-encoders, que viene después.

---

## D-044 — Modelo base del bi-encoder: comparación sin entrenar, registrada antes de medir

**Fecha:** 2026-10-03
**Origen:** D-043 midió, sin corregir, que Vertex no propone entre el 47 % y el 76 % de los pares que
la v3 juzga como el mismo cargo. Lo más probable es que el bi-encoder vaya antes del clustering. La
auditoría humana de D-043 queda pendiente: no bloquea esto, y sus 150 pares servirán también para
evaluar el bi-encoder.

**Modelos:** `intfloat/multilingual-e5-base`, `intfloat/multilingual-e5-large`, `BAAI/bge-m3` y
`sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (licencias MIT / Apache, en local).
**Vertex** (`text-multilingual-embedding-002`) es la referencia: no se puede afinar.
**Uso:** el de la ficha de cada modelo (e5: prefijo `query: ` y promedio de tokens; bge-m3: CLS;
mpnet: promedio de tokens), vectores normalizados, el título tal cual como se le dio a Vertex.
Revisión de cada modelo fijada en el informe.

**Métrica principal: recall@100.** Sobre los pares de `43_pares.csv` que la v3 dice `si` (P ≥ 0,5,
sin candado; 27.303), la fracción que queda entre los 100 vecinos más cercanos de alguno de los dos,
buscando sobre los 58.051 nodos de `base_v16`. Sin piso de coseno: las escalas no son comparables
entre modelos; el piso se calibra después para el elegido. Se reportan también recall@25 y la
versión ponderada por personas.
**Secundaria: precisión@25.** De los 25 vecinos que propone cada modelo para los 2.000 nodos de la
muestra de D-043, la fracción que la v3 dice `si`.

**Criterio:** se elige el modelo abierto con **mayor recall@100**. Si la diferencia con el siguiente
tiene un IC 95 % que toca el cero (bootstrap por nodo sorteado, 10.000), gana el más chico. El
elegido se entrena después destilando la v3 aunque sin entrenar no le gane a Vertex; se reporta la
diferencia con Vertex.

**Límites:** la verdad es la v3 (en coseno bajo extrapola, hasta la auditoría de D-043); los pares
salen de un buscador por letras, que favorece a los modelos sensibles a la ortografía, y no miden
sinónimos sin letras en común; es la comparación sin entrenar.

### Resultado (2026-10-03): e5-base

**Evidencia:** `44_bi_encoder_base.py`, `salidas/44_bi_encoder_base.txt`. 27.303 pares `si` de la v3
sobre 1.985 nodos sorteados; búsqueda sobre los 58.051 nodos de `base_v16`.

| modelo | recall@25 | **recall@100** | recall@100 por personas | precisión@25 |
|---|---|---|---|---|
| Vertex (referencia) | 59,8 % | 80,6 % | 85,9 % | 67,6 % |
| **e5-base** (278 M) | 63,0 % | **84,8 %** | 87,7 % | 66,5 % |
| e5-large (560 M) | 63,5 % | 84,7 % | 89,3 % | 67,3 % |
| bge-m3 (568 M) | 61,1 % | 82,0 % | 87,5 % | 68,8 % |
| mpnet (278 M) | 39,5 % | 58,1 % | 65,9 % | 52,1 % |

- e5-base − e5-large: +0,0 % [−0,5 %, +0,5 %]: empate; **gana e5-base, el más chico (criterio).**
- Frente a Vertex, sin entrenar: e5-base +4,2 % [+3,5 %, +4,9 %], e5-large +4,2 %, bge-m3 +1,5 %
  [+0,7 %, +2,2 %], mpnet −22,5 %.
- La precisión@25 es parecida en los cuatro buenos (66–69 %): ninguno propone más ruido.
- **e5-base es el modelo base del bi-encoder**, que se afina destilando la v3. Pesos en
  `modelos/e5-base` (revisión `d12875059715`, fuera del repo).
- Recordatorio de los límites de D-044: la verdad es la v3, y los pares vienen de un buscador por
  letras.

---

## D-045 — El bi-encoder: e5-base afinado reemplaza a Vertex + adaptador. Criterios de entrenamiento

**Fecha:** 2026-10-04 (registrado ANTES de generar datos y de entrenar)
**Origen:** decisión del autor tras D-044.

### 1. Cambio de decisión

La capa A (recuperar candidatos) **deja de ser Vertex con un adaptador** (D-036; el inventario de
arquitectura ponía los embeddings de Vertex como su punto de partida) y **pasa a ser e5-base afinado,
en local**. Razones: sin entrenar ya propone más pares buenos que Vertex (+4,2 de recall@100, D-044);
se puede afinar entero; **nos libera del riesgo de que Google retire `text-multilingual-embedding-002`**
(habría que volver a embeber todo, y un adaptador entrenado sobre ella se perdería); sin costo por
consulta. Vertex queda como línea base. **En la base del producto**, Vertex también da λ, los vecinos
de la analogía y el efecto de nivel: pasar eso a e5 se mide aparte, con pinball y placebo, antes de
cambiarlo.

### 2. Antes de entrenar: auditoría de los positivos lejanos (parte de D-043)

La calibración de la v3 se hizo con pares de coseno ≥ 0,90; un P ≥ 0,9 lejos de ahí no garantiza
nada (en D-043 dijo `si` al 43 % de los pares con coseno < 0,70).
- **Muestra:** 100 pares de `43_pares.csv` con coseno < 0,85, P ≥ 0,9 y sin candado, al azar (hay
  6.297; se excluyen los 38 que ya están en la auditoría de D-043), mezclados con 30 de coseno < 0,85
  y P ≤ 0,2. A ciegas, con la rúbrica v6.
- **Regla:** si el autor dice `si` en el **80 % o más** de los 100 de P ≥ 0,9, los positivos lejanos
  (coseno < 0,85) entran con P ≥ 0,9. **Si no, entran solo los que el autor revise.**
- Los juicios cuentan también para la auditoría de D-043 en los tramos que correspondan.
- Límite: la muestra sale de pares por letras (D-043), no de las fuentes de Gemini; se reporta por
  tramo de coseno.

### 3. Pares de entrenamiento (la v3 pone las etiquetas)

**Positivos** (P ≥ 0,8 y sin candado si coseno ≥ 0,85; los lejanos, según la regla del §2):
a) los 100 vecinos de e5, de Vertex y de TF-IDF; b) **propuestas de Gemini**: para ~5.000 nodos
sorteados con peso por personas, hasta 20 títulos que sean el mismo cargo, buscados en la base con la
capa 0; c) **descripciones (A0)**: una descripción corta por nodo (58.051), embebida con e5, y sus 50
vecinos; d) **pares lejanos**: una muestra del rango 100 a 1.000 de e5 y de Vertex. Se reporta cuántos
positivos aporta cada fuente.
**Negativos:** difíciles (P ≤ 0,2 en esas fuentes, y los pares bloqueados por un candado de nivel,
seniority o grado) y al azar (dentro del lote).
**Gemini:** aprobado, **en modo batch**, con la disciplina de D-035 (versión fija, temperatura 0,
caché, hash de la instrucción). **Antes de usar las descripciones, el autor revisa 30 al azar** para
ver que no salgan genéricas.

### 4. Separación por componentes conectados

Grafo con todos los nodos y una arista por cada par puntuado que la v3 une (P ≥ 0,5); las componentes
conectadas se reparten **80 / 20** con semilla fija. Un par entra solo si sus dos nodos están del
mismo lado. Si la componente mayor supera el **10 %** de los nodos, se repite con aristas P ≥ 0,8 y
luego P ≥ 0,9, y se reporta cuál se usó. **Los cinco casos conocidos van forzados a evaluación**. La
época se elige con una validación sacada de las componentes de entrenamiento.
**Los lotes no llevan dos pares de la misma componente**, para que los negativos dentro del lote no
sean variantes del mismo cargo.

### 5. Evaluación (componentes de evaluación)

- **Principal:** recall@100 de los pares `si` de la v3, buscando sobre los 58.051 nodos; IC 95 % por
  bootstrap de componentes (10.000).
- **Se adopta si:** (i) e5 afinado − e5 sin entrenar tiene el IC entero sobre cero, y (ii) **no queda
  por debajo de Vertex: el límite inferior del IC de e5 afinado − Vertex no baja de −1 punto.**
- **Secundaria:** precisión@25.
- **Los casos conocidos, antes y después:** rango del grupo del otro título entre los vecinos, con
  Vertex, e5 sin entrenar y e5 afinado: `CHOFER` / `CONDUCTOR`, `VENDEDOR` / `ASESOR COMERCIAL`,
  `MENSAJERO` / `MOTORIZADO`, `GUARDIA` / `AGENTE DE SEGURIDAD`, `JEFE DE TALENTO HUMANO` / `JEFE DE
  RECURSOS HUMANOS` (con Vertex: 1.601, 2.076, 11.131, 122 y 46; Enmienda 1 de D-036). Descriptivo:
  son pocos para un criterio, pero se reportan siempre.

### 6. Entrenamiento

Pérdida contrastiva con negativos dentro del lote más los difíciles (MultipleNegativesRanking); lote
256, lr 2e-5, hasta 3 épocas, 3 semillas; repo limpio; pesos respaldados.

### Resultado de la auditoría de los positivos lejanos (D-045 §2, 2026-10-05)

**Evidencia:** `45_auditoria_lejanos.py decidir`, `salidas/45_auditoria_para_juzgar.csv` y
`45_auditoria_lejanos.txt`. 130 pares a ciegas con la rúbrica v6.

- **P ≥ 0,9 (coseno < 0,85): el autor dice `si` en 89 de 100 (89 %, IC 95 % de Wilson [81 %, 94 %]).**
  **Se cumple la regla (≥ 80 %): los positivos lejanos entran con P ≥ 0,9.** Parejo por tramo de
  coseno: < 0,70 86 % (n = 7), 0,70–0,75 88 % (16), 0,75–0,80 87 % (31), 0,80–0,85 91 % (46). Los
  11 errores de la v3 son profesiones parecidas (`SICOLOGO` / `SOCIOLOGO`), títulos ambiguos
  (`MAESTRO` / `MAESTRO DE OBRA 2`) y especializaciones (`CORTADOR` / `CORTADOR DE VISCERAS`).
- **P ≤ 0,2 (coseno < 0,85): el autor dice `si` en 1 de 30 (3 %, IC [1 %, 17 %])**: `GERENTE NACIONAL
  DE POST/VENTA` / `GERENTE DE POSTVENTA 1`, que la v3 rechaza (P 0,10).
- **Correcciones, declaradas.** En el primer recuento el autor tenía 8 `si` en este grupo. Al
  revisarlos con Claude, **4 fueron errores al marcar** (`CADENERO` / `JEFE DE LA CADENA DE
  SUMINISTRO`, `INSPECTOR/A NIVEL #4` / `DIRECTORA DE NIVEL INICIAL`, `SOLDADOR` / `SUPERVISOR DE
  SOLDADOR`, `AYUDANTE DE PERFORACION 2` / `MECANICO PERFORACION`), y **3 se rejuzgaron a `no` ya
  sin ciego**, tras ver la lectura de Claude con la rúbrica (`ANALISTA LOCAL DE CREDITO` /
  `CREDITO`, `ASSOCIATE` / `EXPERT ASSOCIATE`, `ANOTADOR` / `INSPECTOR NOTIFICADOR`). Los 7 llevan
  nota en el archivo. El grupo de P ≥ 0,9 no se tocó.
- **Los negativos difíciles lejanos (P ≤ 0,2) se quedan como en D-045 §3.** Claude propuso sacarlos
  cuando el recuento daba 27 %; con 3 % (IC hasta 17 %) la razón desaparece y no se enmienda.
- Estos juicios cuentan también para la auditoría de D-043 en los tramos que correspondan.

### Enmienda a D-045 §4 (2026-10-05, antes de entrenar): separación por comunidades de Louvain

**Por qué:** las componentes conectadas forman una componente gigante: con aristas P ≥ 0,5, el 93,2 %
de los 58.051 nodos; con 0,8, el 90,1 %; con 0,9, todavía el 84,5 %. La regla registrada se agotó, y
como esa componente contiene los casos conocidos, quedaba forzada entera a evaluación (solo 6.020
nodos para entrenar). Es el encadenamiento que D-015 midió con el enlace simple.

**Medido antes de decidir** (reparto 80 / 20 de prueba, semilla fija):

| separación | grupo mayor | aristas P ≥ 0,9 cortadas | nodos de evaluación con un vecino P ≥ 0,9 en entrenamiento |
|---|---|---|---|
| nodos al azar | — | 31,8 % | — |
| **Louvain, aristas P ≥ 0,9** | **9,7 %** (6.459 comunidades) | **3,8 %** | **39 %** |
| Louvain, aristas P ≥ 0,5 | 14,2 % (840) | 9,8 % | 75 % |

**Decisión del autor:**
1. **La separación es por comunidades de Louvain** (`networkx`, resolución 1,0, peso = P, semilla
   fija) sobre las aristas P ≥ 0,9 sin candado, 80 / 20; las comunidades de los cinco casos conocidos,
   forzadas a evaluación; validación = 10 % de las comunidades de entrenamiento. Reemplaza a las
   componentes conectadas. Los lotes no llevan dos pares de la misma comunidad.
2. **El criterio de adopción no cambia**; el bootstrap es por comunidad.
3. **Control de fuga:** el recall@100 se reporta también solo en los nodos de evaluación **sin ningún
   vecino P ≥ 0,9 en entrenamiento**. Si el afinado gana en general pero no ahí, lo aprendido es
   memoria de vecinos y no sinónimos, y se reporta así.

**Lo que ya dice la v3 de los cinco casos** (todos son candidatos, por las descripciones y Gemini):
`JEFE DE TALENTO HUMANO` / `JEFE DE RECURSOS HUMANOS` 0,91; `GUARDIA` / `AGENTE DE SEGURIDAD` 0,64;
`VENDEDOR` / `ASESOR COMERCIAL` 0,58; `MENSAJERO` / `MOTORIZADO` 0,58; **`CHOFER` / `CONDUCTOR` 0,24**.
Aunque el bi-encoder los acerque, la v3 sola no une `CHOFER` con `CONDUCTOR`: es un límite del juez,
que se retoma en el clustering.

**Reparto resultante (47, 2026-10-05):** los diez títulos de los casos conocidos caen en 7 comunidades
grandes (14.634 nodos), forzadas a evaluación; el reparto queda en nodos **evalúa 27.198 (47 %),
entrena 21.763, valida 9.090**, no 80 / 20. Aristas P ≥ 0,9 cortadas: 9,0 %; nodos de evaluación con
un vecino P ≥ 0,9 en entrenamiento: 37,2 % (el control de fuga se mide sobre el 62,8 % restante).
Positivos de entrenamiento (P ≥ 0,8 cerca, ≥ 0,9 lejos): 210.360 en 366 comunidades.

---

## D-046 — Correlation clustering con la v3 sobre `base_v16` (capa C de D-036). Registrado antes de medir

**Fecha:** 2026-10-05
**Origen:** la fusión por coseno salió de la capa 0 (criterio B de D-040); las uniones por significado
le tocan al juez (v3, D-042) y al clustering. Decisiones del autor.

**Antecedentes del buscador (exploratorio, sin registro previo por decisión del autor):** la
evaluación registrada de D-045 dio «no se adopta», pero su verdad estaba sesgada: incluía los vecinos
de e5 y de Vertex, que aciertan ~100 % de lo que ellos mismos propusieron. Con la verdad corregida
(solo pares por letras o de Gemini) y lotes al azar con máscara de positivos conocidos, el e5
afinado **B** (lr 1e-5, una época; `48_bi_encoder_B3/semilla_1`) da recall@100 65,8 % frente a 61,6 %
(e5 sin entrenar) y 57,3 % (Vertex), precisión@25 86 % frente a 68 %, estable en 3 semillas
(validación 0,658 / 0,656 / 0,653). `49_evaluar_bi_encoder.txt`. Gemini propone solo para los 5.000
grupos sorteados (75 % de las personas); el autor decidió no pagar el resto (~$10 para 3.824 grupos
con ≥ 3 empresas): **límite declarado**.

**Diseño:**
1. **Nodos:** los 58.051 grupos de la capa 0 de `base_v16`, cada uno con su representante (la celda que
   ya es su átomo, o la más corta). Lo que juntó la capa 0 no se separa.
2. **Candidatos:** la unión de los 100 vecinos de B, los 50 vecinos por descripción (e5 sobre la
   descripción de Gemini) y las propuestas de Gemini. Los pares ya puntuados en `47` se reutilizan.
3. **Peso:** log-odds de la P calibrada de la v3 (T = 1,243).
4. **Candados:** nivel de la rúbrica, seniority (D-033) y número de grado (D-041), por cluster: dos
   clusters con valores conocidos distintos no se juntan.
5. **Unión voraz,** de la arista más segura a la menos: dos clusters se juntan si (a) la suma de los
   log-odds entre todos sus miembros es positiva (la v3 puntúa los pares que falten), (b) **ningún par
   entre ellos tiene P < 0,1**, (c) ningún candado lo impide y (d) el cluster no pasa de 60 grupos.

**Criterios de adopción** (para que `base_v17` reemplace a la v15):
- **a. Auditoría ciega:** 100 pares de representantes que el clustering juntó (de grupos distintos),
  mezclados con 100 candidatos que no juntó; rúbrica v6. **Se exige ≥ 90 % de `si` en los juntados.**
- **b. Utilidad:** pinball en q = 0,25 y 0,75, empresas apartadas, contraste pareado por empresa
  (protocolo de D-025 / D-031), `base_v17` frente a `base_v15`: el IC no queda entero sobre cero, **y**
  el placebo (las mismas uniones hacia destinos al azar del mismo tamaño) sí empeora.
- **c. Descriptivo:** el informe de `41` (grupos, quién cambia, bandas).

### Enmienda a D-046 (2026-10-05, tras la primera corrida y antes de auditar): enlace completo

**La primera corrida juntó de más** (`50_clustering.txt`, regla del §5: suma de log-odds > 0 y ningún
par con P < 0,1): de 58.051 grupos, **4.153 clusters**; el **54 % de los grupos y el 80 % de las
personas** quedaron en clusters que llegaron al tope de 60, y el tope frenó 1,7 millones de uniones. Lo
único que paró el crecimiento fue el tope. Los clusters grandes mezclan cosas distintas (`CERAMICA`,
`COMPACTADOR`, `COMPOST`, `COMPRESORES`, `CONDIMENTO`; `AYUDANTE DE EXCAVADORA` con `OPERADOR DE
RETROEXCAVADORA`; `JEFE DE ELECTRICIDAD` con `JEFE DE EMPAQUES AL VACIO`). Es el encadenamiento de
D-015: un par muy seguro compensa a varios dudosos, y la v3 dice `si` a ~50 % de los vecinos. **No se
audita**: con clusters así la auditoría fallaría por construcción.

**Decisión del autor:** la regla de unión pasa a **enlace completo**: dos clusters se juntan solo si
**todos** los pares entre ellos tienen P ≥ 0,5 (con eso la suma de log-odds es positiva por
construcción). Se mantienen los candados y el tope de 60. La caché de puntajes de la v3 se guarda.
Los criterios de adopción (auditoría ≥ 90 % y pinball con placebo) no cambian.

---

## D-047 — Juez v4: la v3 no sabe decir «no» lejos. Rúbrica v7 y un etiquetador LLM sin costo

**Fecha:** 2026-10-05
**Origen:** el correlation clustering de D-046 juntó de más, también con enlace completo (a las
700.000 aristas llevaba las mismas uniones que la regla anterior; se detuvo). La causa es el juez:
la v3, entrenada solo con pares de coseno ≥ 0,90, da «mismo cargo» a pares absurdos (`COMPRESORES`
/ `COMPOSTERA` 0,93; `AYUDANTE DE EXCAVADORA` / `OPERADOR DE RETROEXCAVADORA` 0,91; `CERAMICA` /
`COMPOST` 0,63). Hay que reentrenarlo con pares lejanos etiquetados.

**Etiquetador.** Gemini con la rúbrica completa costaría del orden de $150–300 (≈ 70 M de tokens de
entrada): el autor lo descarta. Se usa un LLM sin costo por consulta. La Universidad sirve
`zai-org/GLM-5.3-Flash` en el propio H200 (API compatible con OpenAI, sin clave; se usa con 8
peticiones a la vez por ser un recurso compartido). También se descargaron Qwen3.5-35B-A3B,
Qwen3.5-122B-A10B y Gemma 4 26B (en `modelos/`, sin usar todavía); Ollama ofrece otros, no probados.

**Validación contra juicios que ya existían** (`51_etiquetador_local.py`; criterio fijado antes de
medir: acierto ≥ 85 % en los 130 pares lejanos de la auditoría de D-045 §2, contando las
contradicciones entre órdenes como fallo, y kappa ≥ 0,79 en `calibra`):

| GLM-5.3-Flash | coherencia | acierto lejos | kappa lejos | kappa cerca |
|---|---|---|---|---|
| sin razonamiento, rúbrica v6 | 93,1 % | 79,2 % | 0,68 | 0,94 |
| con razonamiento, rúbrica v6 | 91,5 % | 76,2 % | 0,74 | 0,91 |
| **sin razonamiento, rúbrica v7** | 89,9 % | 80,8 % | **0,86** | 0,90 |

No pasa el criterio. Con la v7, cuando es coherente en los dos órdenes acierta 93,8 % lejos y
96,5 % cerca; las contradicciones son 14 % y 7 %.

**Rúbrica v7** (`rubrica_mismo_cargo_v7.md`). Al revisar los desacuerdos lejanos, muchos eran entre
el autor y la letra de la v6, no errores del modelo. El autor decidió seis aclaraciones: un título
que no nombra un puesto → `no`; una palabra cortada se reconstruye solo si es seguro, si no → `no`;
entre palabras de puesto distintas solo separa la tabla de niveles (paso 2); la acotación separa
si lleva a otro oficio o sector, o si la palabra genérica es ambigua; la sección no separa, el tipo
de vehículo o licencia y la especialidad sí (paso 4); ser un puesto y apoyarlo son puestos
distintos, sea o no un mando (paso 5). Ejemplos inventados, comprobado que no aparecen en ningún
conjunto juzgado. Se corrigieron 3 juicios de la auditoría de D-045 con nota (`SENIOR 3`, error al
marcar; `OBRERO ENCARTONADO ETIQUETADO` / `OPERADOR DE ETIQUETADO` → `si` y `AUXILIAR DE` /
`AUXILIAR DE PATIO` → `no` por la v7). `calibra` sigue juzgada con la v6: límite declarado.

**Circularidad, declarada:** la v7 se escribió mirando esos 130 pares, así que el 93,8 % es
optimista. **Decisión del autor:**
1. **Regla de uso:** solo cuentan las etiquetas en que GLM es coherente en los dos órdenes; las
   contradicciones se apartan (como los incoherentes de Gemini en D-036).
2. **Validación limpia antes de entrenar:** 100 pares lejanos **nuevos** (no usados para la v7),
   juzgados a ciegas por el autor con la v7. **Se usa GLM si, en los coherentes, coincide con el
   autor ≥ 90 % y es coherente en ≥ 85 % de los pares.** Si no, no se usa.

### Resultado de la validación limpia (52) y decisión (2026-10-06)

**Evidencia:** `52_validacion_glm.py`, `salidas/52_validacion_glm.txt`, `52_validacion_juicio1.csv`
(autor, ciego), `52_validacion_juez2.csv` (segundo juez humano, ciego: recibió la columna vacía y no
vio ningún resultado) y `52_validacion_juez2_corregido.csv` (el del segundo juez con 21 juicios
corregidos por Claude con la v7, cada uno con su regla en la nota: 18 por funciones distintas, uno
por título sin puesto, uno por nivel y uno por ámbito).

- **Regla registrada (contra el autor): GLM no pasa.** Coherente en 80 % (se pedía ≥ 85 %); en los
  coherentes, 71,2 % de acuerdo (se pedía ≥ 90 %). El 93,8 % de antes era optimista: la v7 se ajustó a
  aquellos 130 pares. **No se usan las etiquetas de GLM.**
- **El acuerdo entre dos humanos con la misma rúbrica es bajo:** 66 % (kappa 0,35); 75 % (kappa 0,45)
  con las correcciones. GLM coincide con el autor (71 %, kappa 0,39) tanto como el segundo juez. **El
  criterio de 90 % estaba por encima del acuerdo humano: error de diseño del criterio**, declarado.
- **Precisión de lo que se uniría** en esa zona (pares de coseno < 0,85 de los clusters y candidatos
  semánticos): v3 con P ≥ 0,9 41 % (autor) / 68 % (juez 2) / 55 % (juez 2 corregido); GLM ≈ 50 %;
  v3 y GLM a la vez, 48 %. En la auditoría de D-045 §2 la v3 daba 89 %, pero aquellos pares venían
  del buscador por letras, que es otra población.

**Decisión del autor:**
1. **No se entrena la v4.** Las 10.000 etiquetas de GLM (`53`) quedan como dato descriptivo.
2. **Enmienda a D-046: el clustering se hace solo en la zona confiable de la v3.** Dos clusters se
   juntan solo si **todos** los pares entre ellos tienen coseno de Vertex ≥ 0,90 (la población con que
   se entrenó y evaluó la v3: AUC 0,89–0,99 en `prueba` y `prueba 2`) **y** P de la v3 ≥ 0,5, sin
   candado, sin pasar de 60 grupos; los no-cargos quedan solos. Los criterios de adopción de D-046
   (auditoría ≥ 90 % y pinball con placebo frente a la v15) no cambian.
3. **Los sinónimos lejanos que importan van a un diccionario aprobado por el autor**, como las
   erratas y abreviaturas de la capa 0: las propuestas de Gemini que existen en la base, para los
   cargos con más personas, en una lista para aprobar o rechazar.

### Resultado de D-046 con el clustering en la zona confiable, y decisión (2026-10-06)

**Clustering** (`50_clustering.py agrupar --regla confiable --solo-cargos`): 58.051 grupos de la capa 0 →
**39.261 clusters**; el mayor, 34 grupos; el tope de 60 no se tocó; la v3 puntuó al vuelo solo 141 pares.

**a. Auditoría ciega** (`55`, rúbrica v7, autor): de 100 pares juntados, **95 % `si` con los juicios
ciegos** y 97 % tras revisar 18 juicios con Claude (2 de ellos eran juntados; los cambios llevan nota).
**Cumple (≥ 90 %).** De los 100 cercanos (coseno ≥ 0,85) no juntados, 74–78 % también eran el mismo
cargo: el clustering es conservador.

**b. Pinball** (`54`, 35.223 votos de 1.343 empresas apartadas):

| base | pinball | cobertura directa | frente a v15 |
|---|---|---|---|
| v15 | 0,13513 | 54,3 % | — |
| v16 (capa 0) | 0,13520 | 53,9 % | +0,00016, no se distingue |
| **clustering confiable** | **0,13473** | **58,4 %** | **+0,00004 [−0,00041, +0,00051], no empeora** |
| su placebo | 0,14101 | 56,4 % | +0,00303 [+0,00224, +0,00395], **empeora** |
| clustering + sinónimos | 0,13521 | 58,5 % | +0,00062 [−0,00005, +0,00135] |

**Cumple: la base agrupada no empeora las bandas, el placebo sí, y suma 4 puntos de cobertura directa.**

**Sinónimos** (`56`): el autor revisó 515 pares de las 91 anclas con más personas. Tras la revisión con
Claude quedaron 441 aprobados (columna `cambio` con cada corrección: el ancla restaurada al título de la
base, un par contra la tabla de niveles, seguridad ocupacional frente a vigilancia, y los puentes que
encadenaban oficios: campo con planta, venta con crédito bancario, y los genéricos `AUXILIAR GENERAL`,
`ASISTENTE` y el grupo ambiguo «de servicio»). Aplicados con dos protecciones (un rechazo del autor entre
los grupos, o un candado, impide la unión), unen 39.261 → 39.018. **Frente al clustering solo empeoran
el pinball (+0,00058 [+0,00015, +0,00099]) y suben la cobertura solo 0,1 puntos**: juntan grupos grandes y
heterogéneos de cargos que ya tenían datos propios.

**Decisión del autor:**
1. **`base_v17` = capa 0 v1 + clustering en la zona confiable, sin sinónimos.** Reemplaza a la v15.
2. **Los sinónimos aprobados no fusionan la base: se usan en el buscador de cargos del front
   (`/puestos`)**, para que escribir `CONDUCTOR` sugiera `CHOFER` o `JORNALERO` sugiera `TRABAJADOR
   AGRICOLA`, marcados como sinónimo. Usarlos también como respaldo al consultar un título sin datos
   propios queda como idea a medir aparte.

---

## D-048 — El juez v3 en la consulta, para los títulos nuevos del cliente

**Fecha:** 2026-10-06
**Origen:** decisión del autor: el producto sale ya como versión inicial, y la v3 tiene que trabajar
en cada consulta, no solo al construir la base.

**Cómo funciona** (`producto/juez.py`, `BaseReferencia._asignar_con_juez`). Un título que no está en la
base ni por la capa 0 se juzga contra hasta 10 grupos distintos entre sus vecinos con coseno ≥ 0,90 (la
zona en que la v3 se validó, la misma del clustering de D-046), sin los que bloquea un candado (nivel de
la rúbrica, seniority, número de grado). Si el mejor tiene P ≥ 0,5, el título recibe los datos de ese
grupo (`p_juez` en la salida); si no, sigue por analogía, como antes. El juez puntúa exactamente como al
medirse (plantilla, dos órdenes, P = P(A⇒B)·P(B⇒A), T = 1,243, fp32). El servicio lo carga de `JUEZ`
(por defecto `modelos/juez_v3`); sin pesos o sin `torch`, sigue sin él.

**Medido antes de activarlo** (`54_pinball.py`, protocolo de D-025 / D-031, base agrupada de D-046,
38.450 votos; las tres corridas en el mismo entorno). **Error encontrado y corregido:** la primera
comparación mezclaba corridas de dos entornos de Python, que sortean distinto las empresas apartadas
(solo 324 de 1.343 en común); se descartó y se rehízo con las tres en el mismo entorno.

| | votos donde actúa | pinball donde actúa | pinball, todos | cobertura directa |
|---|---|---|---|---|
| sin juez | — | — | — | 56,5 % |
| **con juez** | 6.628 (17,2 %) | **+0,00081 [−0,00176, +0,00336], no empeora** | +0,00005 [−0,00021, +0,00033] | **64,1 %** |
| placebo (candidato al azar) | 6.628 | **+0,00341 [+0,00112, +0,00576], empeora** | +0,00034 [+0,00007, +0,00059] | 63,6 % |

**Se activa:** no empeora las bandas, el placebo sí (la v3 elige bien el grupo) y suma **7,6 puntos de
cobertura directa**. Costo: la v3 en cada consulta (en GPU, décimas de segundo por título nuevo).

### El buscador de cargos (`/puestos`) con el juez (2026-10-06, decisiones del autor)

Solo afecta a las sugerencias del formulario, no a las bandas.
- **Reorden por el juez:** la v3 juzga los 50 puestos más parecidos por embedding y se ordenan por su P
  (`p_juez`); desde P ≥ 0,9 manda el parecido, para que el título exacto quede primero. Antes, `DENTISTA`
  traía arriba `HIGIENISTA`, `TELEFONISTA` y `EBANISTA` (riman); ahora, lo odontológico.
- **Sinónimos de consulta** (`producto/datos/sinonimos_v1/consulta.csv`, lo llena el autor): un texto
  que no existe en la base → un cargo de la base, que sale primero (`DENTISTA` → `ODONTOLOGO`).
- **Filtro en P ≥ 0,5** (`p_min`, el mismo umbral del juez en la consulta). **Cambia la regla original
  de `/puestos`** («no se filtra nada; el front decide»), ahora que el orden lo da un juez validado.
  Siempre quedan el cargo escrito y los sinónimos; si no queda nada más, las 3 más probables con
  `seguro: false`.
- **Palabra desconocida:** si lo escrito tiene una palabra que no aparece en ningún título de la base
  (`DESTISTA`, `ODONTOLGO`), no se le cree al juez (daba P > 0,9 a `DESTALLE`, `ESTADISTICA`,
  `DISENADOR`): nada es `seguro` salvo el cargo escrito y los sinónimos, y `palabras_desconocidas` lo
  avisa.
- **Grados agrupados para mostrar:** `LABORATORISTA 1`, `2`, `4` salen como una sugerencia con la lista
  `grados` (cada uno con sus empresas y personas) y `cargo_sin_grado`. Cada grado sigue siendo su propio
  puesto con su banda (criterio A de D-040).

### Niveles en inglés y el juez filtra los vecinos de la analogía (2026-10-06, decisión del autor)

**Origen:** `SALES DEVELOPMENT REPRESENTATIVE` (2 empresas, por analogía) salía con referencia $2.282 y banda
p10–p90 de $604 a $8.621: sus 25 vecinos incluían `SALES MANAGER` y `SALES DIRECTOR` ($11.226), y como
`REPRESENTATIVE` no estaba en la tabla de niveles, el ajuste por nivel no podía descontarlos.

**Cambios:** (1) la tabla de niveles (`RANGOS` y `RANGOS_RUBRICA`) suma los equivalentes en inglés y
`REPRESENTANTE` / `REPRESENTATIVE` en el nivel 1; `ASSISTANT MANAGER` = 4 también en el léxico; `HEAD`,
`LEAD` y `OFFICER` no entran (ambiguas). (2) En la analogía, el juez descarta los vecinos con P < 0,5 si
quedan al menos 3.

**Medido** (`54_pinball.py`, 38.450 votos, mismo entorno; placebo = descartar la misma cantidad de vecinos al azar):

| frente a | cambio | pinball donde actúa |
|---|---|---|
| producto hoy | tabla en inglés | +0,00005 [−0,00030, +0,00042], no empeora |
| tabla | + filtro de vecinos por el juez | −0,00167 [−0,00441, +0,00124], no empeora (apunta a mejorar) |
| tabla | placebo del filtro | **+0,00414 [+0,00234, +0,00583], empeora** |

Cumplen el criterio de D-046 / D-048: **se activan.** `demo/base_v18.npz` = la v17 con la tabla nueva (mismos
grupos; cambian el nivel guardado y el efecto por nivel). El SDR queda en $2.050 con banda p10–p90 de $971 a
$4.328 (ancho relativo 0,99 → 0,45). Sigue alta frente a sus pares SDR / BDR: la tabla pone en nivel 1 tanto a
`SALES DEVELOPMENT REPRESENTATIVE` como a `SALES REPRESENTATIVE`. Lo que los distinguiría es un
clasificador de nivel (propuesta D-049, pendiente).

## D-049 — Clasificador de nivel jerárquico: Qwen etiqueta y un modelo pequeño lo aprende. Registrado antes de medir

**Por qué.** El nivel hoy sale de una tabla de palabras (`nivel_lexico`, `nivel_rubrica`). El 56 % de la gente
trabaja en títulos sin palabra de rango, y en los que la tienen la tabla no distingue matices. Ejemplos:
`SALES DEVELOPMENT REPRESENTATIVE` y `SALES REPRESENTATIVE` quedan en el mismo nivel, y `HEAD OF`, `LEAD` y
`OFFICER` no tienen nivel. Sin nivel, la analogía no puede descontar a los vecinos de otro escalón.

**Escala** (la misma de `RANGOS`, para que `efecto_nivel`, `lambda` por nivel y los candados sigan sirviendo):
1 operativo, auxiliar, asistente o de apoyo; 2 técnico o profesional que trabaja solo (analista, contador,
médico, ingeniero); 3 especialista, coordinador o supervisor; 4 jefe o subgerente de un área; 5 gerente,
director o alta dirección. Cuando el texto no lo dice, `no_explicito` con el nivel más probable y los posibles.

**Etiquetas.** Qwen3.5-122B-A10B (fp8, local, sin costo), sin razonamiento, temperatura 0 y salida JSON guiada.
Recibe el título y, si existe, la descripción de Gemini (D-045) y devuelve `nivel`, `explicito` (si/no) y
`posibles` (los niveles que el texto admite). **No ve sueldos.** Etiqueta los 65.181 títulos de `base_v18`.

**Modelo de la consulta.** Un clasificador pequeño entrenado con esas etiquetas: regresión logística sobre el
embedding del título, sin enmascarar el rango porque la etiqueta ya no viene de la palabra. Lo necesita la
consulta, porque un título nuevo no está en la base.

**El sueldo (decisión del autor).** Puede desempatar el nivel, pero no el cargo. Solo en grupos de la base con
≥ 3 empresas, solo cuando Qwen dice `no_explicito`, y solo entre los `posibles` que dio Qwen: se elige el que
deja el sueldo relativo del grupo más cerca de la escalera de su área. Solo alimenta el ajuste por nivel de la
analogía, nunca los candados de agrupación, para que el sueldo no separe ni junte cargos. Va en la base,
nunca en la consulta (un título nuevo no tiene sueldo). En el pinball, el sueldo es solo el de las empresas de
entrenamiento. Esto cambia la regla de `nivel.py` («el nivel nunca por lo que cobra») únicamente en este
desempate. Por eso las pruebas b y c se miden con el nivel **sin** sueldo.

**Criterios (fijados antes de medir):**
- a) **Control:** en los títulos con palabra de rango no ambigua, Qwen coincide con la tabla en ≥ 90 %.
- b) **Escalera:** en los títulos sin palabra de rango, la mediana del sueldo sube en cada escalón del nivel
  de Qwen sin sueldo (IC 95 % > 0 por escalón, bootstrap por empresa). El placebo (niveles permutados) no
  muestra escalera.
- c) **Juicio del autor:** κ ponderado ≥ 0,6 frente a 100 títulos sin palabra de rango que el autor clasifica
  a ciegas, sorteados con peso por personas.
- d) **Uso en el producto:** pinball con el protocolo de D-046 / D-048, más su placebo. Tres variantes: la
  tabla de hoy, el clasificador sin sueldo y el clasificador con el desempate por sueldo. Se adopta la que
  no empeora frente a la tabla (IC no entero sobre cero), siempre que su placebo sí empeore.

Si a, b o c fallan, el clasificador no entra al producto.

### D-049, resultados de la v1 y enmienda (2026-10-06, decisión del autor: el clasificador va al producto)

**v1** (65.181 títulos, 33 min, 0 errores):
- **a) Cumple:** 96,8 % de coincidencia con la tabla en 43.263 títulos con palabra de rango.
- **b) No cumple:** en 19.453 títulos sin palabra de rango (por grupo, sin las erratas de rango), los pasos
  1→2 (+0,63) y 4→5 (+0,63) suben, pero 2→3 (−0,08 [−0,18, +0,04]) y 3→4 (+0,39 [−0,27, +0,67]) no. El
  placebo no muestra escalera. La tabla sí escalona en los títulos con rango (+0,50, +0,20, +0,38, +0,67).
- **c) Cumple:** κ ponderado de 0,77 con el autor. Antes de ver las etiquetas de Qwen, el autor cambió 9 de
  sus 100 juicios por coherencia con la escala; el original está en `61_nivel_para_juzgar_original.csv`.

Diagnóstico de b: el nivel 3 de Qwen sin palabra de rango lo llenan cargos operativos (`INSPECTOR DE
CALIDAD`, `AGENTE DE OPERACIONES TERRESTRES`, `GESTOR DE COBRANZAS`, `MAYORDOMO`), que suben porque la
descripción de Gemini dice «supervisa». Son las palabras que `nivel.py` ya marcaba como ambiguas.

**Enmienda:**
1. **Instrucciones v2:** `INSPECTOR`, `AGENTE`, `GESTOR`, `OFICIAL` y `MAYORDOMO` se clasifican por la función
   (por defecto 1 o 2). «Supervisa» o «coordina» en una descripción genérica no sube el nivel; solo lo
   sube tener personas a cargo dicho en el título.
2. **b pasa a ser descriptivo:** la regla v2 nació de ver estos sueldos, así que b ya no es una prueba
   limpia. La v2 se juzga por a (≥ 90 %), c (κ ≥ 0,6 con los mismos 100 títulos; las discrepancias
   título por título de la v1 no se miraron) y d.
3. **d) Pinball con empresas apartadas**, que no vieron estos datos: la tabla, Qwen v1 y Qwen v2, cada una
   con su placebo de niveles permutados. En los títulos de la base el nivel viene de Qwen; en los que no
   están (la consulta) viene del clasificador pequeño. En este paso el nivel de Qwen reemplaza solo al
   léxico (ajuste por nivel, `lambda` y efecto por nivel); los candados de agrupación siguen con la tabla.
   Se adopta la mejor variante que no empeore frente a la tabla y cuyo placebo sí empeore.
4. El desempate por sueldo se mide después, como otra variante de d.

## D-050 — Capa de idioma: los títulos en inglés se resuelven en su equivalente en español. Registrado antes de medir

**Por qué (decisión del autor).** La base tiene unos 2.500 títulos en inglés (≈ 37.600 personas, sobre todo
de multinacionales) separados de su equivalente en español (`PAYROLL ANALYST` / `ANALISTA DE NOMINA`), y
los clientes también escriben en inglés. El producto va a correr en otra infraestructura, sin los
servicios de la universidad, así que todo debe ser local.

**Cómo:**
1. **Detector:** un título es inglés si al menos la mitad de sus palabras están en una lista versionada
   de palabras de cargo en inglés y ninguna es un conector en español (DE, DEL, Y, LA, PARA…).
2. **Traductor local** `Helsinki-NLP/opus-mt-en-es` (300 MB, CPU): se traduce la frase
   `He works as a <título en minúsculas>.` y se quita `Trabaja como`. Probado en 18 títulos: dentro de
   una frase traduce bien; el título suelto en mayúsculas, no.
3. **Resolución:** la traducción, normalizada, se busca como cualquier título: tal cual, por la capa 0 y
   por el juez (coseno ≥ 0,90, P ≥ 0,5). Si encuentra grupo y ningún candado lo impide entre el original
   en inglés y ese grupo (nivel de la rúbrica, seniority, grado), el título en inglés queda resuelto.
4. **En la base,** el título en inglés entra al grupo encontrado, como los sinónimos (D-047). **En la
   consulta,** un título en inglés que no tiene datos directos propios se busca por su traducción. Se
   muestra el original.

**Criterios (fijados antes de medir):**
- a) **Auditoría ciega del autor:** 50 pares (título en inglés, títulos del grupo asignado), sorteados con
  peso por personas entre los resueltos; ≥ 90 % de «sí» con la rúbrica v7.
- b) **Pinball** con el protocolo de D-046 / D-048, contra el producto vigente en ese momento. El placebo
  asigna cada título en inglés al grupo de otro título resuelto. Se adopta si no empeora donde actúa (IC
  no entero sobre cero) y el placebo sí empeora.

### D-049, resultados de la v2: se adopta (2026-10-06)

| | v1 | v2 |
|---|---|---|
| a) control | 96,8 % | 97,1 % |
| c) κ con el autor | 0,77 | 0,83 |
| b) escalera (descriptiva en la v2) | 2→3 −0,08, 3→4 n. s. | 1→2 +0,65, 2→3 +0,13 [+0,04, +0,27], 3→4 +0,19 [−0,43, +0,46] (3.468 personas en el nivel 4), 4→5 +0,68 |
| d) pinball frente a la tabla, donde actúa (13.804 votos, 36 %) | −0,00277 [−0,00410, −0,00166] | **−0,00334 [−0,00494, −0,00204]** |
| d) placebo (niveles permutados) | +0,01634, empeora | +0,01681, empeora |

**Se adopta la v2.** Mejora las bandas frente a la tabla (el IC queda entero bajo cero) y su placebo empeora.
En los títulos de la base, el nivel viene de Qwen v2. En la consulta, para un título que no está en la base,
viene de la regresión logística sobre el embedding (`62`: acierta el nivel de Qwen en 92 % de los grupos no
vistos, 81 % sin palabra de rango). Esa regresión viaja dentro de la base y no necesita GPU.

### D-050, criterio a: cumple (2026-10-06)

El autor juzgó a ciegas 50 pares (título en inglés, grupo en español): 100 % de «sí» (exigido ≥ 90 %).
Resolución en `base_v18`: 2.237 de 3.827 títulos en inglés (876 por traducción exacta o capa 0; 1.361 con
el juez sobre la traducción); 1.954 se unen a otro grupo (24.609 personas). El pinball (b) se mide sobre el
nivel v2.

### D-050, criterio b: no cumple; enmienda «solo en la consulta» (2026-10-06)

**Medido** (pinball frente al nivel v2, 38.450 votos):

| Votos | idioma (base y consulta) | placebo |
|---|---|---|
| Todos | +0,00097 [+0,00034, +0,00155], **empeora** | +0,00201, empeora |
| Títulos en inglés (1.572) | +0,0036 [−0,0013, +0,0088] | +0,0337 [+0,0229, +0,0481] |
| Resto | +0,00023 [−0,00021, +0,00059] | +0,00040 |

Los títulos en inglés pasan de 29 % a 51 % con datos directos, pero la banda empeora. Lectura: el título
en inglés lleva información de sueldo (casi siempre es de una multinacional), y unirlo al grupo en español
la diluye. **La unión en la base no se adopta.**

**Enmienda (antes de medir):** variante `idioma_consulta`. La base no se toca. Solo un título en inglés
**sin datos directos propios** (el caso de un título nuevo) se busca por su traducción, con los mismos
candados. Su placebo cambia el destino por el de otro título resuelto. Mismo criterio: no empeora donde
actúa y el placebo sí empeora.

### D-050, enmienda «solo en la consulta»: no cumple. La traducción no se usa para el sueldo (2026-10-06)

| Variante (frente al nivel v2) | Donde actúa |
|---|---|
| `idioma_consulta` | 665 votos: +0,019 [+0,004, +0,032], **empeora** |
| su placebo | 716 votos: +0,061 [+0,038, +0,087], empeora |
| `idioma` (base y consulta), recalculado | +0,00111 [+0,00048, +0,00186], empeora |

(«Donde actúa» pasa a ser |diferencia| > 1e-6: las diferencias de 1e-11 son redondeo. El nivel v2 no cambia
con este umbral: 13.804 votos, −0,00334.)

**Por qué:** en esos 665 votos, el sueldo real frente al centro de la banda (mediana, en log) pasa de +0,26
con la analogía a +0,35 con la traducción, y los votos por encima del p75 suben de 36 % a 50 %. Un cargo
con título en inglés gana alrededor de 40 % más que el grupo equivalente en español (casi siempre es una
multinacional). La traducción encuentra el cargo correcto (auditoría 100 %), pero asigna el sueldo del
mercado local.

**Decisión:** la capa de idioma queda **apagada para el sueldo** (en la API, `TRADUCTOR=no` por defecto). Se
puede usar para buscar y mostrar el equivalente en español. Idea para después: traducción más una prima por
título en inglés, estimada aparte y medida con pinball.

**Producto:** `demo/base_v19.npz` = la v18 con el nivel de Qwen v2 y el clasificador de la consulta (D-049).

## D-051 — Recalibrar el ancho de las bandas que salen del modelo. Registrado antes de medir

**Por qué.** En el producto con nivel v2 (`54_nivel_v2`), las bandas por analogía tienen el 65 % de los
votos de empresas apartadas dentro de p25–p75, cuando lo esperado es 50 %: son demasiado anchas (ancho
p25–p75 mediano de 129 %), y el pinball castiga el ancho de sobra. Los datos directos con cuantiles
empíricos están en 50 %. (Una lente por «tipo de empresa» se descartó antes de registrarla: dependería de
cómo rotula la empresa, se podría manipular, y el dato que la motivaba salió de explorar la validación.)

**Qué.** Cuando la banda sale del modelo normal (`mu ± z·sd_modelo`), su `sd` se multiplica por un factor:
`k_analogia` para la analogía y `k_directo` para los datos directos sin cuantiles empíricos. La banda de
personas, la confianza y el centro no cambian.

**Cómo se estima `k`, sin tocar la validación.** Dentro del 75 % de entrenamiento de `54`, se aparta otro
25 % de empresas (semilla fija). Se construye la base con el resto, se consultan los cargos de esas empresas
y `k = mediana(|voto − mu| / sd_modelo) / 0,6745`, por tipo de banda. Luego la base se construye con todo el
entrenamiento y se aplica `k`.

**Criterios:**
- a) **Pinball** frente al producto vigente (nivel v2): el IC donde actúa no queda entero sobre cero.
- b) **Cobertura** p25–p75 de la analogía en la validación entre 45 % y 55 %.
- c) **Control:** la escala inversa (`1/k`) sí empeora.

Se adopta si se cumplen a, b y c. El `k` del producto se estima igual sobre la base completa (partición
interna de todas las empresas de entrenamiento y validación) y se guarda en la base.

### D-051, resultados: cumple, se adopta (2026-10-07)

`k` estimado con la partición interna del entrenamiento: analogía 0,637, directo 0,945.

| | nivel v2 (antes) | calibra | escala inversa |
|---|---|---|---|
| a) pinball donde actúa (17.349 votos, 45 %) | — | **−0,00369 [−0,00469, −0,00271]** | +0,02112, empeora |
| b) analogía dentro de p25–p75 | 64,6 % | **46,2 %** | 83,3 % |
| analogía dentro de p10–p90 | 89,7 % | 72,9 % | 97,6 % |
| directos dentro de p25–p75 / p10–p90 | 49,5 % / 77,8 % | 49,2 % / 77,5 % | — |

Cumple a, b y c. Nota: con un solo factor, el p10–p90 de la analogía queda por debajo del 80 % (las colas son
más pesadas que una normal). Un segundo factor para las colas sería otra decisión, con su propia medición.
**Producto:** `demo/base_v20.npz` = la v19 con `k` estimado igual, sobre todas las empresas de la base.
`k` del producto (partición interna de todas las empresas): analogía 0,691, directo 1,049.

### La banda de mercado es la de empresas (2026-10-07, decisión de producto del autor)

`p10`..`p90` de la API pasan a ser la banda de **empresas**: cada empresa cuenta una vez, como en las
encuestas salariales ponderadas por organización, y es la banda validada con pinball (D-051). La de
personas queda como detalle en `p10_per`..`p90_per`. Cada persona de la nómina se ubica dentro de la banda de
empresas: `lectura_mercado` y la nueva `posicion_mercado` (percentil aproximado, interpolado entre p10, p25,
la referencia, p75 y p90, y recortado a [10, 90]). Consecuencia esperada: más personas salen fuera del 50 %
central que con la banda de personas, porque esta no lleva la dispersión dentro de cada nómina. El front
debe rotularlo «frente a lo que pagan las empresas por este cargo».

## D-052 — El nivel de Qwen en los candados: un nivel por grupo y candado de nivel en la consulta. Registrado antes de medir

**Diagnóstico** (`base_v20`): 943 de los 12.108 grupos con más de un título mezclan niveles de Qwen (6,4 %
de las personas). Casi siempre es ruido de Qwen entre grafías del mismo cargo (`CONTADOR GENERAL` 2 o 4,
`ADMINISTRADOR` 2 o 4, `MECANICO` 1 o 2), no grupos mal hechos (la auditoría del clustering dio 95 %).
**No se parten grupos.**

**Cambios:**
1. **`nivel_grupo`:** cada título toma el nivel mayoritario de su grupo, ponderado por personas. Solo cambia
   el ajuste por nivel de la analogía.
2. **`candado_nivel`:** cuando el juez asigna un título nuevo a un grupo en la consulta (D-048), el candado
   usa el nivel del clasificador para el título (si da clase) y el nivel del grupo, en lugar de la tabla de
   palabras. Si los dos se conocen y difieren, se bloquea.

**Variantes**, sobre el producto vigente (nivel v2 + D-051, con `k` reestimado igual): `nivel_grupo`;
`nivel_grupo` + `candado_nivel`; y sus placebos (los niveles de grupo permutados entre grupos; los niveles
de la consulta permutados entre títulos).

**Criterio:** se adopta cada cambio si no empeora donde actúa frente al producto vigente (IC no entero sobre
cero) y su placebo sí empeora.

### D-052, resultados: se adoptan los dos, son neutros (2026-10-07)

| | donde actúa | placebo |
|---|---|---|
| `nivel_grupo` frente al producto (nivel v2 + D-051) | 13.804 votos: +0,00029 [−0,00006, +0,00062], no se distingue | +0,02357, empeora |
| `candado_nivel` frente a `nivel_grupo` | +0,00007 [−0,00064, +0,00086], no se distingue | +0,01607, empeora |

Cumplen el criterio (no empeoran; los placebos sí) y se adoptan, pero no mejoran el pinball. Lo que aportan
es coherencia: un solo nivel por cargo, y el juez deja de asignar unos 200 títulos nuevos a grupos de otro
nivel (6.422 → 6.216 asignaciones en las empresas apartadas). En todo `nivel_grupo` la diferencia es
+0,00009 [+0,00001, +0,00018]: mínima, pero sobre cero; queda anotado. En la API se activan al cargar la base
(`NIVEL_GRUPO=no` los apaga).

## D-053 — Nivel v3 (sin reglas fijas que sesguen) y el sueldo como desempate en los casos inseguros. Registrado antes de medir

**Por qué.** El autor encontró `HEAD OF CUSTOMER SUCCESS` (nivel 5) asignado por el juez al grupo
`CUSTOMER SUCCESS MANAGER`, que Qwen v2 puso en 5 por una regla de las instrucciones («MANAGER = 5»). Al
revisar: 758 de 917 títulos con MANAGER quedaron en 5, y Qwen dio **un solo nivel posible en el 95 % de
toda la base**. Las causas son dos reglas fijas («la palabra de rango manda», «si lo dice claro, solo uno»),
y por eso el desempate por sueldo de D-049 casi nunca tendría a qué agarrarse.

**Instrucciones v3** (`60_etiquetar_nivel.py --version v3`): el inglés se clasifica por función (MANAGER
de área o equipo 4–5; de cartera, cuenta, producto o proyecto 2–3). `posibles` debe incluir todos los
niveles que el título puede tener en distintas empresas, con una lista de palabras ambiguas en español e
inglés. `nivel` sigue siendo el más probable, y con palabra de rango en español, el de la tabla. Los
cambios salieron de un caso señalado por el autor, no de mirar sueldos.

**Desempate por sueldo** (decisión del autor; amplía D-049):
- Solo en grupos de la base con ≥ 3 empresas cuyo nivel (mayoritario, D-052) tenga más de un posible.
- Se elige, entre los `posibles`, el nivel cuya mediana salarial esté más cerca de la mediana del grupo.
  La escalera de medianas se calcula con los títulos de un solo posible, con el mismo sueldo de la base.
- El nivel desempatado alimenta el ajuste por nivel de la analogía **y el candado de la consulta** (el juez
  no asigna un título nuevo a un grupo de otro nivel). Nunca alimenta la agrupación de la base.
- En el pinball, el sueldo es solo el de las empresas de entrenamiento.

**Criterios:**
- a) Control ≥ 90 % (`nivel` frente a la tabla).
- c) κ ponderado ≥ 0,6 con los 100 juicios del autor.
- d) Pinball:
  - `nivel_v3` frente al producto vigente (v2 + D-051 + D-052);
  - `nivel_v3_sueldo` frente a `nivel_v3`;
  - placebos: niveles v3 permutados entre títulos, y desempate que elige un posible al azar.

Cada uno se adopta si no empeora donde actúa y su placebo sí empeora. Se reporta además cuántos títulos
tienen más de un posible.

### D-052, corrección (2026-10-07): los placebos estaban mal especificados

En `54_pinball.py`, la condición que permuta el nivel de Qwen título por título (el placebo de D-049) también
se aplicaba a `nivel_grupo_placebo` y a `candado_nivel_placebo`. Así, el placebo del candado permutó todos
los niveles y no solo los del candado, como se había registrado. Su «empeora» no prueba lo registrado. Se
corrige el código y se vuelven a correr los dos placebos (los archivos anteriores quedan con el sufijo
`_MAL`). La adopción de D-052 queda pendiente de ese resultado.

### D-050, uso de presentación (2026-10-07, decisión del autor)

El traductor vuelve a cargarse en la API, solo para **mostrar**. `/referencia` y el informe traen
`equivalente` (el cargo en español de la base donde se resuelve el título en inglés), y `/puestos` pone ese
cargo primero (`equivalente: true`, con su `traduccion`). La banda no cambia: sigue siendo la del título en
inglés o la de la analogía (`IDIOMA_SUELDO=si` usaría la traducción para el sueldo, pero eso se midió y
empeora). Ejemplo: `PAYROLL ANALYST` → `ANALISTA DE NOMINA`; `HEAD OF SALES` → `JEFE DE VENTAS`.
**Placebos corregidos** (2026-10-07):
- `nivel_grupo_placebo` (solo los niveles de grupo permutados): +0,02694 [+0,02318, +0,03117], empeora.
- `candado_nivel_placebo` (solo los niveles del candado permutados): +0,00113 [+0,00023, +0,00219], empeora.

**D-052 se confirma adoptado.**

### D-053, resultados (2026-10-07)

- a) control 91,5 %; c) κ 0,84; títulos con más de un posible: 52 % (v2: 5 %). MANAGER en nivel 5: 154 de
  917 (v2: 758). `CUSTOMER SUCCESS MANAGER` pasa a 3 [2, 3].
- d) `nivel_v3` frente al producto (v2 + D-051 + D-052): +0,00067 [−0,00021, +0,00165], no se distingue;
  placebo +0,01546, empeora. **Cumple, se adopta.**
- d) `nivel_v3_sueldo` frente a `nivel_v3` (2.285 grupos desempatados, 956 cambian de nivel): +0,00032
  [−0,00050, +0,00121]; su placebo (posible al azar): +0,00030 [−0,00060, +0,00115], **no empeora**. **El
  desempate por sueldo no se adopta:** no se distingue de elegir al azar entre los posibles.

Límite del protocolo, anotado para la próxima vez (no cambia esta decisión): cada variante reestima el factor
de ancho de D-051, que mueve un poco todas las bandas de la analogía. Así, «donde actúa» incluye ~17 mil
votos con cambios mínimos que diluyen un efecto localizado. En adelante, las variantes que no tocan la
calibración se miden con el `k` fijo del producto vigente.

**Producto:** `demo/base_v21.npz` = la v20 con los niveles v3 (D-052 activo en la API).

## D-054 — En la analogía, cada grupo vecino cuenta una vez. Registrado antes de medir

**Por qué** (caso `HEAD OF CUSTOMER SUCCESS`, señalado por el autor): los vecinos de la analogía son
grafías, no grupos. Las grafías de un mismo grupo entran como vecinos distintos con los mismos
estadísticos: `CUSTOMER SERVICES TEAM LEADER`, `CUSTOMER SERVICE TEAM LEADER` y `CUSTOMER EXPERIENCE
LEADER` (un grupo de 3 empresas) sumaban 40 % del peso, y `CUSTOMER SUCCESS MANAGER` entraba dos veces. Ya
se corregía el conteo de empresas (`n_emp`), pero no los pesos.

**Cambio** (`vecinos_por_grupo`): de los vecinos ordenados por parecido, se toma la primera grafía de cada
grupo (la de mayor coseno) hasta `VECINOS` grupos, antes del filtro del juez.

**Medición:** pinball frente a `nivel_v3` (el producto vigente), con el `k` de D-051 **fijo** en el que
obtuvo `nivel_v3` (analogía 0,6334, directo 0,9371), para aislar el cambio. Placebo: en vez de quitar los
duplicados, se quita la misma cantidad de vecinos al azar.

**Criterio:** se adopta si no empeora donde actúa y el placebo sí empeora.

### D-054, resultado: no se adopta (2026-10-07)

`vecinos_grupo` frente a `nivel_v3` (k fijo): donde actúa, +0,00004 [−0,00150, +0,00144]. El placebo da
+0,00019 [−0,00085, +0,00116] y **no empeora**. Cobertura de la analogía en p25–p75: 45,8 % → 46,2 %. No
se adopta. En el caso que lo motivó tampoco ayuda (`HEAD OF CUSTOMER SUCCESS`: $6.359 → $6.495): el
problema de ese caso es la falta de datos, no el conteo.

## D-055 — Títulos en inglés sin datos propios: traducción + prima del título en inglés. Registrado antes de medir

**Por qué** (caso `HEAD OF CUSTOMER SUCCESS`, autor): sin datos propios, la analogía estira desde gerentes
en inglés de nivel 3 (+79 % por el salto de nivel) y la banda queda en $2.800–$14.600. En español hay
equivalentes con más datos, pero la traducción sola subestima (D-050: la prima del título en inglés;
`HEAD OF SALES` $3.171 frente a `JEFE DE VENTAS` $1.500).

**Cambio** (`idioma_prima`):
1. **La prima π en la base:** para cada título en inglés con ≥ 3 empresas cuya traducción se resuelve
   (D-050) en otro grupo con ≥ 3 empresas, se toma `d = m(inglés) − m(grupo en español)`. π es la mediana
   de `d` por nivel (el del grupo del título en inglés), con ≥ 20 pares; si no, la global. La varianza de π
   es `(1,4826·MAD(d))²`. Con la base de entrenamiento en el pinball.
2. **En la consulta:** un título en inglés sin datos directos propios, cuya traducción cae en un grupo con
   datos directos, toma la banda de ese grupo corrida por π (del nivel del clasificador para el título, o
   si no, el del grupo). Su ancho suma la varianza de π: `sd = √(sd_banda² + var_π)`. Se rotula
   `por traduccion`.

**Medición:** pinball frente a `nivel_v3`, con el `k` fijo. Placebo: la misma π, con la traducción hacia el
grupo de otro título resuelto. **Criterio:** se adopta si no empeora donde actúa y el placebo sí empeora.
Se reportan también la cobertura de p25–p75 en los votos donde actúa y π por nivel.

### D-055, resultado: cumple, se adopta con reservas (2026-10-07)

π con la base de entrenamiento: 204 pares, global +0,26. Donde actúa (344 votos, 0,9 %): **+0,0163
[−0,0039, +0,0373], no se distingue**; placebo +0,0889 [+0,0478, +0,1265], empeora. Cumple el criterio y se
adopta. Reservas, anotadas: el punto apunta a peor y las bandas se ensanchan (p25–p75 de ×1,76 a ×2,21). Lo
que se gana es calibración: dentro de p25–p75, de 35 % a 44 %.

**Producto:** `demo/base_v22.npz` = la v21 con π estimada sobre toda la base y guardada en ella (438 pares;
global +0,26; por nivel: 1 +0,16, 2 +0,31, 3 +0,33, 4 +0,10, 5 +0,42). La API la usa si carga el traductor
(`IDIOMA_PRIMA=no` la apaga).

### Rango de mercado = p25–p75 (2026-10-07, decisión de producto del autor)

La API entrega `rango_desde` / `rango_hasta` = p25 / p75 de la banda de empresas, como el rango que se
muestra; p10–p90 queda como detalle. No cambia ningún cálculo. Nota para el front: `docs/api_para_el_front.md`.

### Títulos en inglés nuevos → banda del equivalente en español, sin prima (2026-10-07, decisión de producto del autor)

En la consulta, un título en inglés **sin datos directos propios** (un cargo nuevo) se resuelve en su
equivalente en español (D-050) y toma esa banda, tal cual y sin prima. Los títulos en inglés con datos propios
en la base mantienen su banda. Los clusters no cambian. Es la variante `idioma_consulta` de D-050, que se
midió y **empeora** donde actúa (+0,019 [+0,004, +0,032]): subestima, porque los cargos en inglés suelen
pagar 30–40 % más. El autor la elige por simplicidad y por ser explicable («tu cargo equivale a X en el
mercado ecuatoriano»), con bandas más angostas. D-055 (con prima) queda desactivado (`IDIOMA_PRIMA=no`); la
prima sigue guardada en la base.

### El mismo cargo, la misma banda, en inglés y en español (2026-10-07, decisión de producto del autor)

En la consulta, todo título en inglés que se resuelve en un equivalente en español (D-050) toma **la banda
de ese equivalente, tal cual**, aunque tenga datos propios en la base. Si no se resuelve, usa sus datos o la
analogía. Los clusters de la base no se tocan, y la prima de D-055 queda apagada (`IDIOMA_PRIMA=no`). Motivo:
que un cliente no vea dos bandas distintas para el mismo cargo según cómo lo escriba. Costo medido y aceptado:
para los cargos de multinacionales la banda queda por debajo de lo que pagan (prima del inglés ~30–40 %;
`idioma` y `idioma_consulta` empeoraron en D-050). Tamaño y actividad no corrigen esa prima (medido), pero el
filtro por segmento o rubro del cliente sigue disponible y aplica igual en los dos idiomas.
Reemplaza a la entrada anterior («Títulos en inglés nuevos → banda del equivalente en español, sin
prima»), que solo aplicaba a los títulos sin datos propios. Esa entrada se registró y se publicó por un
comando que el autor había rechazado, pero que ya se había ejecutado.

## D-056 — Unir los grupos que solo difieren en el grado. Registrado antes de medir

**Por qué.** Para tener más cargos con datos directos. El candado de grado (D-041) separa `LABORATORISTA 1`,
`2` y `4`, pero entre empresas el número de grado no ordena el sueldo (script `58`, exploratorio: 41 % de pares
en el orden esperado, como el azar). En `base_v22`: 468 familias de grado con más de un grupo (1.224 grupos,
158 mil personas); en 103 el grupo mayor tiene < 3 empresas y la familia unida tendría ≥ 3.

**Cambio** (`grados`): sobre los grupos de la base (el clustering inyectado), se unen todos los grupos que
contienen un título con la misma `clave_grado` (el título sin el grado ni los conectores, sin orden) que un
título con grado. Solo cambia la agrupación final; la consulta sigue igual.

**Medición:** pinball frente a `nivel_v3`, con el `k` fijo. Placebo: el mismo número de uniones con las
claves permutadas entre los títulos con grado (une grupos no relacionados con la misma estructura).
**Criterio:** se adopta si no empeora donde actúa y el placebo sí empeora. Se reporta también cuántos votos
pasan de analogía a datos directos.

### D-056, resultado: pasa la regla, pero no se activa (2026-10-07)

`grados` frente a `nivel_v3` (k fijo): 796 familias, 1.388 grupos unidos. Donde actúa (78 % de los votos, por
los cambios globales de la base): +0,00043 [−0,00008, +0,00091], no se distingue; el placebo da +0,00069
[+0,00021, +0,00118] y empeora. Pasa la regla, pero no cumple su propósito: solo 250 votos pasan de analogía
a datos directos (63,9 % → 64,4 %), y en esos 250 la banda se ensancha (×1,45 → ×1,50) y el pinball empeora
(0,133 → 0,140). Recomendación de Claude: no activarlo, porque dentro de una familia el grado sí separa
sueldos. **Queda inactivo hasta que el autor decida.**

## D-057 — e5 ajustado (D-045) en lugar de Vertex para buscar vecinos. Registrado antes de medir

**Por qué.** En D-045, la precisión@25 juzgada por la v3 fue 86–88 % con el e5 ajustado (variante B),
contra 69 % con Vertex. En el caso `SALES DEVELOPMENT REPRESENTATIVE`, Vertex trae `SALES COORDINATOR`
(n3), `SALES MANAGER` (n4) y `SALES SPECIALIST` (n2) entre los 10 primeros; e5 trae solo representantes de
ventas de nivel 1. Si se adopta, además, el producto deja de depender de Vertex para embeber.

**Cambio** (`e5`): los embeddings de la base y de la consulta son los del e5 ajustado
(`48_bi_encoder_B3/semilla_1`, prefijo `query: `, promedio, largo 32). Los grupos de la base no cambian.
Todo lo que usa el embedding se reestima con él: `lambda`, el clasificador de nivel y el `k` de D-051 (por
la partición interna, porque las distancias cambian). El umbral del juez en la consulta (0,90 con Vertex)
pasa al equivalente en e5, **0,8258**: el que deja la misma proporción de títulos (61,5 %) con un vecino de
otro grupo por encima. Se calculó sobre `base_v22`, sin sueldos.

**Medición:** pinball frente a `nivel_v3` (que también reestimó su `k`). Placebo: los vectores de e5
permutados entre títulos. Control descriptivo: e5 sin ajustar. **Criterio:** se adopta si no empeora donde
actúa y el placebo sí empeora. Se reportan además el ancho y la cobertura de p25–p75 de la analogía.

### D-057, resultado: cumple, se adopta (2026-10-07)

| | `nivel_v3` (Vertex) | `e5` | `e5_sin_ajustar` (control) |
|---|---|---|---|
| donde actúa | — | −0,00077 [−0,00257, +0,00108], no se distingue | +0,00144 [−0,00061, +0,00327] |
| pinball de la analogía | 0,1578 | 0,1564 | 0,1569 |
| ancho p25–p75 de la analogía | ×1,68 | ×1,74 | ×1,75 |
| analogía dentro de p25–p75 | 45,8 % | 45,8 % | 47,0 % |
| asignados por el juez en la consulta | 6.422 | 6.929 | 13.037 |
| `k` (analogía / directo) | 0,633 / 0,937 | 0,709 / 0,962 | 0,686 / 0,992 |

El placebo (vectores permutados) da +0,04061 donde actúa y empeora. **Cumple y se adopta.** No angosta las
bandas: el `k` recalibrado para e5 es mayor y mantiene la cobertura. Gana en velocidad (`67`: un título
15–21 ms local contra 371 ms con Vertex; 500 títulos en 0,25 s con GPU o 3,9 s con CPU, contra 11,3 s) y
quita la dependencia de Vertex en la consulta.
**Decisión del autor: e5 no se activa; el producto sigue con Vertex** (2026-10-07). Revisando una lista de
cargos (`68`), el autor ve más cerca de la realidad a Vertex. Causa en el caso más distinto (`SALES DEVELOPMENT
REPRESENTATIVE`): la traducción («representante de desarrollo de ventas») se resuelve con Vertex en
`REPRESENTANTE DE VENTAS` (78 empresas, P del juez 0,97) y con e5 en `DESARROLLADOR DE VENTAS` (2 empresas),
porque e5 pesa más la forma de la palabra. Sin datos directos, cae a la analogía entre títulos en inglés de
multinacionales ($1.889 contra $860). Lo mismo con `HEAD OF HR`: `JEFE DE RECURSOS HUMANO` con Vertex,
`JEFE DE RRHH` con e5. Observación aparte: esos dos grupos deberían ser uno (candidato a sinónimo).

### Glosario de RR. HH. en inglés para la capa de idioma (2026-10-08, decisión del autor)

Antes de traducir, los términos aprobados se reemplazan por su forma en español (`COLLECTIONS` → `COBRANZAS`,
`HR` → `RECURSOS HUMANOS`, `CX` → `EXPERIENCIA DEL CLIENTE`, `AR` → `CUENTAS POR COBRAR`…), y el traductor
ordena el resto. Lista de `69_glosario.py`: Qwen local propone; solo los términos que el traductor decía
distinto. El autor aprobó 86. Al probarlos sobre títulos reales, 22 rompían traducciones que salían bien
(`HEALTH CARE` → «salud atención al cliente», `BACK END` → «final de apoyo», `SALES REPRESENTANTE` →
«representante legal»), así que se sacaron; además se corrigieron dos. Quedan 64, en
`src/benchmarking/producto/datos/glosario_v1/glosario.csv` (versionado).

En los 35 cargos de la lista del autor cambian 8. Entre ellos: `Collections Assistant` pasa de «asistente de
colecciones» a «asistente de cobranzas», `Collections Analyst` deja la analogía por «analista de cobranzas», y
`CX Specialist` se resuelve en «especialista experiencia del cliente». Es una corrección de traducción, no
del modelo de bandas: no lleva pinball.

## D-058 — Capa 0 v2: limpieza de títulos cortados, con códigos o con siglas sueltas. Registrado antes de medir

**Por qué** (autor, revisando los candidatos del juez): `CONSULTOR DE`, `CONSULTOR MM`, `CONTADOR GENERAL 102`.
En `base_v22` hay 7.899 títulos sucios (12 %, 10,3 % de las personas): 774 terminan en conector (6,5 % de las
personas), 479 llevan número o código y 6.646 una sigla o código raro. Además, hay truncamiento sistemático
en 40, 50, 60 y 64 caracteres. Fragmentan los datos (menos empresas por cargo, bandas más anchas) y ocupan
lugares entre los candidatos.

**Reglas** (sobre los títulos, sin sueldos; cada título sucio se une al grupo de su título limpio si ese
existe y ningún candado lo impide: nivel de la rúbrica, seniority, grado):
- **A, cortados:** (i) se quitan los conectores finales (DE, DEL, Y, LA…), y si queda un título de la base, ese
  es el destino; (ii) si el título mide 40, 50, 60 o 64 caracteres o termina en conector, y exactamente un
  grupo tiene títulos más largos que empiezan igual, ese grupo es el destino.
- **B, códigos:** se quitan los números de 2 o más cifras y los prefijos de lista (`1060 - `, `024 `, `2.`, ` 102`);
  los grados (1–9, romanos) no se tocan.
- **C, siglas** (variante aparte): se quitan los tokens de ≤ 4 letras que no aparecen en al menos 20 títulos
  de la base (MM, FA, TOC).

**Medición** (sin auditoría, por decisión del autor): pinball frente a `nivel_v3` con `k` fijo. Dos variantes,
`limpieza` (A + B) y `limpieza_siglas` (A + B + C), cada una con su placebo: el mismo número de uniones, con
destinos al azar entre los grupos de la base. Se reportan además cuántos votos pasan a datos directos y el
ancho de banda. **Criterio:** se adopta si no empeora donde actúa y el placebo sí empeora.
**Glosario, alta dirección** (2026-10-08, decisión del autor): se agregan `CHIEF … OFFICER`, sus siglas (CEO, COO, CTO,
CFO, CMO, CIO, CHRO) y `MANAGING DIRECTOR`, reemplazados por su equivalente en inglés corriente (`CEO` → `GENERAL
MANAGER`, `COO` → `OPERATIONS MANAGER`), que el traductor pasa a «gerente general», «gerente de operaciones», etc.
Antes, `CHIEF OPERATIONAL OFFICER` se traducía «jefe de operaciones» (nivel 4), y `CEO` y `MANAGING DIRECTOR` ni
se detectaban como inglés. Se completa la lista del detector (CEO, MANAGING, EMPLOYMENT, CONSULTING…).

## D-059 — Coherencia de seniority dentro de una familia: prima típica más los datos propios. Registrado antes de medir

**Por qué** (autor): `CONSULTOR SENIOR` ($1.585, 11 empresas) queda por debajo de `CONSULTOR` ($1.608, 30), y
`INGENIERO DE SOFTWARE SENIOR` ($3.260, 6) es 2,4 veces `INGENIERO DE SOFTWARE` ($1.358, 9). Con pocas empresas,
la mediana de un cargo senior o junior es ruidosa.

**Cambio** (`coherencia`):
- **Familia:** el título sin sus marcas de seniority (`_PATRON_SEN`). En cada familia, el grupo base es el
  del título sin marca (s = 0) con más personas; el senior, el de s = 1 (SR, SENIOR); el junior, el de
  s = −1 (JR, JUNIOR). Solo cuando son grupos distintos.
- **Prima típica:** π_SR = mediana de `m(senior) − m(base)` en las familias con ≥ 10 empresas en los dos
  grupos; igual para π_JR. Con la base de entrenamiento en el pinball.
- **Combinación:** si el grupo base tiene ≥ 3 empresas, el centro del senior pasa a
  `(n_S·m_S + 10·(m_B + π_SR)) / (n_S + 10)`, con n_S el número de empresas del senior (una prima de 10
  empresas de peso). La banda entera (empresas y personas) se corre lo mismo que el centro. Igual para el
  junior.

**Medición:** pinball frente a `nivel_v3` con `k` fijo. Placebo: cada grupo senior o junior se empareja con un
grupo base al azar, en lugar del de su familia, con la misma π. **Criterio:** se adopta si no empeora donde
actúa y el placebo sí empeora. Se reportan π_SR, π_JR, cuántos grupos se mueven y cuántas inversiones
(senior < base) quedan.

### D-058, resultados: se adopta la limpieza de cortados y códigos; las siglas no (2026-10-08)

| | donde actúa | placebo |
|---|---|---|
| `limpieza` (A + B) | 11.620 votos: **−0,00022 [−0,00042, −0,00003], mejora** | +0,00006 [−0,00018, +0,00032], no se distingue |
| `limpieza_siglas` (A + B + C) | +0,00018 [−0,00002, +0,00038], no se distingue | +0,00032 [+0,00005, +0,00063], empeora |

Con la regla literal se adoptaría la variante que no mejora y se rechazaría la que sí. **Aclaración de la regla
(autor, a propuesta de Claude):** el placebo existe para descartar que «cualquier cambio ayuda». Cuando la
variante mejora con significancia, basta con que su placebo no mejore. Por eso **se adopta `limpieza`** (A + B):
los conectores finales, los títulos cortados y los códigos se unen al grupo de su título limpio. **No se adopta
`limpieza_siglas`:** no aporta y el punto apunta a peor. Efecto chico: 35 votos pasan a datos directos. Los
títulos sucios con mucha gente ya estaban agrupados por el clustering.

### D-059, resultado: no se adopta (2026-10-08)

π_SR +0,315, π_JR −0,185 (entrenamiento); 405 grupos senior y 318 junior movidos. Donde actúa (826 votos):
+0,00177 [−0,00468, +0,00831], no se distingue (el punto apunta a peor); placebo +0,00547 [−0,00135, +0,01182],
tampoco. **No se adopta:** forzar la prima de seniority no acerca las bandas a lo que pagan las empresas. La
inversión senior < base se trata como un aviso de presentación, no como un ajuste de cálculo.
**Producto:** `demo/base_v23.npz` = la v21 (nivel v3, `k` reestimado: analogía 0,697, directo 1,045) con la limpieza de
D-058: 39.261 → 39.143 grupos. Sin la prima de D-055 (apagada). La API la toma por ser la más nueva.

## D-060 — El efecto de seniority en el ajuste por escalón de la analogía. Registrado antes de medir

**Por qué** (autor: «senior sí sube tu sueldo»). Dentro de la misma empresa, el título SENIOR gana +26 % sobre
el mismo título sin marca (mediana de 599 pares; más en el 87 %), y el título sin marca +28 % sobre el JUNIOR
(473 pares; 82 %). La seniority es un escalón de sueldo real. La decisión de diseño de tratarla solo como
candado y no como ajuste fue un error. D-059 no mejoró porque ajustaba los cargos con datos propios, donde la
diferencia entre empresas tapa la prima; donde debería ayudar es en la analogía, igual que el nivel.

**Cambio** (`ajuste_seniority`): en la analogía, a cada vecino se le suma `e(s_consulta) − e(s_vecino)`, con
s = −1 (JR), 0, 0,5 (SEMI SENIOR) o 1 (SR), aparte del ajuste por nivel. `e` se estima **dentro de la
empresa** con los datos de entrenamiento: `e(1)` = mediana de `y(SR) − y(sin marca)` entre títulos de la misma
familia en la misma empresa, `e(−1)` = −(mediana de `y(sin marca) − y(JR)`), `e(0)` = 0 y `e(0,5)` = e(1)/2.
Otras marcas (TRAINEE, CORPORATIVO) no se ajustan.

**Medición:** pinball frente a `nivel_v3` con el `k` fijo. Placebo: la marca de seniority de cada vecino se
sortea con las frecuencias observadas. **Criterio** (aclarado en D-058): se adopta si mejora y su placebo no
mejora, o si no empeora y su placebo sí empeora.

### D-060, resultado: cumple, se adopta (2026-10-08)

Donde actúa (651 votos): **−0,00842 [−0,01609, −0,00147], mejora**; placebo (3.958 votos): +0,00114 [−0,00020,
+0,00252], no mejora. Por seniority de la consulta: senior −0,02617 [−0,04320, −0,00753]; sin marca y junior,
neutros. **Se adopta.** `e` se estima con toda la base y se guarda en ella (`base_v24`).

## D-061 — Coherencia de seniority con la prima medida dentro de la empresa (decisión de producto del autor). Registrado antes de medir

**Por qué:** el autor quiere que `CONSULTOR SENIOR` ($1.585, 11 empresas) no quede por debajo de `CONSULTOR`
($1.697, 31). D-059 hacía eso con una prima estimada entre empresas (+37 %) y salió neutra. D-060 midió la prima
**dentro de la empresa**: SR +26 % (e = 0,229), JR −19 % (e = −0,214).

**Cambio:** el mismo de D-059 (familia por título sin marcas; centro del senior o junior =
`(n·m + 10·(m_base + e)) / (n + 10)`; la banda se corre igual), pero con `e` de D-060, estimado dentro de la
empresa con los datos de entrenamiento, en lugar de π.

**Criterio** (decisión de coherencia del producto, no de precisión): se adopta **salvo que empeore donde actúa
con significancia** (IC entero sobre cero). Se reporta el costo y se corre también su placebo.

### D-061, resultado: se adopta (2026-10-08)

Donde actúa (853 votos): +0,00249 [−0,00295, +0,00959], no se distingue (placebo +0,00570 [−0,00172, +0,01228]).
No empeora con significancia: según su criterio, **se adopta** como regla de coherencia del producto, con un costo
en precisión nulo o mínimo. `demo/base_v25.npz` = la v24 con esta corrección, usando el `e` de D-060 estimado con
toda la base.

## D-062 — Un título en inglés se busca entero por su traducción, también por analogía. Registrado antes de medir

**Por qué** (revisión de la lista de 35 cargos, 2026-10-09; decisión del autor: «head es jefe»):

- **Analogía.** Cuando la traducción de un título en inglés no encuentra un grupo con datos, la analogía se calcula
  con el embedding del título **en inglés**. Así, `HEAD OF AI` sale a $3.273 y `JEFE DE IA` (su traducción) a
  $1.907. Con «HEAD = JEFE» del autor y «mismo cargo, misma banda» (2026-10-07), el título en inglés debe buscarse
  por su traducción en todo: vecinos, nivel de la consulta, juez y seniority.
- **Candado de nivel.** El candado entre el título original y el equivalente encontrado lee `EXECUTIVE` de
  `CHIEF EXECUTIVE OFFICER` como «ejecutivo» (nivel 1). Por eso rechaza `GERENTE GENERAL` (nivel 5), y `CEO` y
  `Chief Executive Officer` dan $3.110 y $4.807.

**Cambio** (`idioma_por_traduccion`):

1. Para un título en inglés con traducción embebida, la consulta usa la traducción: vecinos, clasificador de nivel,
   juez de la consulta, filtro de vecinos del juez y marca de seniority.
2. En el candado de `resolver_idioma`, el nivel de la rúbrica del título original se lee después del glosario
   cuando el glosario cambia la cabeza del título (`CHIEF EXECUTIVE OFFICER` → `GENERAL MANAGER`, nivel 5).

**Medición:** pinball, con empresas apartadas, frente al producto vigente con la capa de idioma en
«siempre» (D-060 + D-061 + traductor), con el `k` fijo. Se mide **donde actúa** (los votos cuya banda cambia).
Placebo: a cada título en inglés se le da la traducción embebida de **otro** título en inglés.

**Criterio** (regla de producto del autor, como D-061): se adopta **salvo que empeore donde actúa con
significancia** (IC entero sobre cero). Se reportan el costo y el placebo.

## D-063 — Tamaño de empresa por nivel del cargo, estandarizado. Registrado antes de medir

**Por qué** (revisión de la lista, 2026-10-09):

- **Sin tamaño, COO y CTO cobran más que el CEO.** `GERENTE DE OPERACIONES` está en $3.628, `GERENTE DE
  TECNOLOGIA` en $4.482 y `GERENTE GENERAL` en $3.110. La causa no es el cargo: es qué empresas lo tienen. El
  gerente general está en 778 empresas, muchas pequeñas; el de tecnología, casi solo en las grandes.
- **Con tamaño, la inversión sigue en las PEQUEÑAS y MEDIANAS.** El ajuste vigente (D-018, `ajuste_seg`) solo se
  aplica cuando el cargo tiene ≥ 10 empresas de ese tamaño; si no, deja el centro global, cargado a las grandes.
  En PEQUEÑA, COO da $2.434 y CEO $1.555; CTO $4.482. Tampoco se aplica a la analogía.

**Cambio** (`tamano_estandar`): el efecto del tamaño se estima **por nivel del cargo** (1–5), no cargo por cargo.

- **Estimación.** Con los votos (mediana por cargo y empresa; empresas con segmento conocido), se alterna:
  1. `m*_g` = mediana de `voto − δ(L, s)` del grupo `g`;
  2. `δ(L, s)` = mediana de `voto − m*_g` entre las empresas de tamaño `s` y nivel `L`.

  Tres vueltas. `δ(L, ·)` se centra para que su promedio sobre las empresas del nivel `L` sea 0.
- **Sin tamaño del cliente.** El centro y la banda de cada grupo se corren `m*_g − m_g`: un mercado «de
  composición promedio», el mismo para todos los cargos. Los vecinos de la analogía entran ya corridos. Solo se
  corren los grupos con ≥ 3 empresas con segmento.
- **Con tamaño `s`.** Al resultado anterior se le suma `δ(L, s)`, con `L` el nivel del grupo, o el de la consulta en
  la analogía. Reemplaza a `ajuste_seg` (D-018).

**Medición:** pinball (p25–p75), con empresas apartadas (las de validación con segmento conocido), con el `k`
fijo. Variantes:

- (A) producto sin tamaño;
- (B) producto con el segmento de cada empresa (D-018);
- (C) `tamano_estandar` con el segmento de cada empresa;
- (C0) `tamano_estandar` sin segmento;
- placebo de (C): la tabla `δ(L, ·)` con los segmentos permutados dentro de cada nivel.

La primaria se declara antes, como pide la nota de D-018: **el sesgo del centro por segmento**, mediana de
`voto − referencia` por segmento en los niveles 4–5, y su recorrido (máximo − mínimo). Es el defecto que se
corrige: un defecto de localización, que el pinball de bandas anchas castiga poco.

**Criterio:**

- **(C) se adopta** si cumple las tres:
  1. su recorrido del sesgo en niveles 4–5 es menor que el de (B);
  2. su pinball frente a (B) no empeora con significancia;
  3. el placebo no reduce el recorrido tanto como (C).
- **(C0), el default sin tamaño**, es una regla de coherencia (que el CEO no quede bajo el COO). Se adopta salvo que
  su pinball frente a (A) empeore con significancia.

Se reporta, como descripción, cuántos `GERENTE DE X` de la lista quedan sobre `GERENTE GENERAL`, en cada variante.

**Corrección de implementación de D-063 (2026-10-09, antes de ver resultados).** En la primera corrida, `δ(L, s)`
salía 0 en los niveles 1–3. La causa: los grupos de una sola empresa tienen residuo 0 por construcción y
arrastraban la mediana. Ahora `δ` se estima solo con grupos de ≥ 5 empresas con segmento. El corrimiento por grupo
(≥ 3 empresas) no cambia. Las tres variantes con `tamano_estandar` se relanzaron antes de terminar; no se vio
ningún pinball ni sesgo.

### D-063, resultado: (C) se adopta, (C0) no (2026-10-09)

Efecto del tamaño por nivel (`δ`, estimado con el entrenamiento), en log:

| Nivel | MICRO | PEQUEÑA | MEDIANA | GRANDE |
|---|---|---|---|---|
| 1 | 0,00 | 0,00 | 0,00 | 0,00 |
| 2 | −0,05 | −0,11 | −0,02 | +0,02 |
| 3 | +0,05 | −0,06 | −0,05 | +0,02 |
| 4 | 0,00 | −0,24 | −0,16 | +0,07 |
| 5 | −0,57 | −0,46 | −0,15 | +0,16 |

**Primaria: sesgo del centro en los niveles 4–5** (2.987 votos con segmento; mediana de voto − referencia):

| Variante | MICRO | PEQUEÑA | MEDIANA | GRANDE | Recorrido |
|---|---|---|---|---|---|
| (A) sin tamaño | −0,5 % | −27,4 % | −12,5 % | +17,5 % | 44,9 pts |
| (B) D-018 | −0,5 % | −14,8 % | −6,2 % | +10,3 % | 25,1 pts |
| **(C)** | +19,8 % | **−4,2 %** | **−0,8 %** | **+8,3 %** | **24,0 pts** |
| placebo | −7,9 % | −18,5 % | −0,2 % | +32,3 % | 50,8 pts |

El recorrido de (C) es menor que el de (B) y el del placebo, con IC anchos ([5,4; 67,7]). Lo que lo infla es
MICROEMPRESA (pocas, `δ` de −57 % en el nivel 5, que se pasa). Sin ella, el recorrido baja de 25,1 a 12,5 puntos.

**Pinball:**

| Comparación | Todos | Donde actúa |
|---|---|---|
| (C) frente a (B) | −0,00149 [−0,00216, −0,00077] | **−0,00468 [−0,00676, −0,00266]**, mejora (11.598 votos) |
| placebo frente a (B) | — | +0,00490 [+0,00241, +0,00732], empeora |
| (C) frente a (B), solo votos con segmento | — | −0,00831 [−0,01117, −0,00533] |
| (C) frente a (A), solo votos con segmento | — | −0,00886 [−0,01203, −0,00530] |

**(C) cumple los tres puntos del criterio: se adopta.**

**(C0), sin tamaño**, frente a (A): +0,00248 [+0,00151, +0,00364] donde actúa, **empeora: no se adopta.** Corregir
el centro hacia un mercado «de composición promedio» saca la referencia del mercado real de ese cargo.

**En el producto:** el corrimiento por grupo y `δ` se aplican **solo cuando se conoce el tamaño del cliente**
(`segmento`, o derivado del RUC). Sin tamaño la referencia es la de siempre: un `GERENTE DE TECNOLOGIA` está en
empresas más grandes que el `GERENTE GENERAL` promedio, y la cifra global lo refleja. Para que los cargos altos
tengan sentido entre sí, **hay que pedir el tamaño**.

### D-062, resultado: no se adopta (2026-10-09)

**Buscar por la traducción** (`trad` frente a `trad_base`), donde actúa (851 votos, 2,2 %): **+0,04777 [+0,02573,
+0,06931], empeora** (placebo: +0,01152, también empeora). Donde actúa, la referencia baja un 22 % (mediana), y esas
empresas ya pagaban un 27 % sobre la referencia anterior. Es la prima del título en inglés de D-050/D-055: quien
escribe `HEAD OF`, `COUNTRY MANAGER` o `IT BUSINESS PARTNER` en inglés es, en general, una multinacional que paga
más que el `JEFE DE` local. Según su criterio, **no se adopta**: «HEAD = JEFE» sigue valiendo para el **equivalente
que se muestra**, pero en la analogía el título en inglés se sigue buscando como está.

**Solo el candado con el glosario** (`trad_candado`): cambia 1 voto (`IT QUALITY ASSURANCE ANALYST INTERMEDIAT`,
+0,339). No mide nada sobre los cargos de dirección. Ese voto lo movió que el glosario cambiara la cabeza `IT`, y el
arreglo no iba dirigido a eso: no se adopta así.

## D-064 — El candado de idioma lee los cargos de dirección después del glosario (regla de producto del autor)

**Por qué:** el autor pidió corregir que `CEO` y `Chief Executive Officer` den bandas distintas ($3.110 frente a
$4.807). El glosario, ya aprobado, los lleva a los dos a `GENERAL MANAGER`. El candado leía `EXECUTIVE` como nivel 1
y rechazaba `GERENTE GENERAL`.

**Cambio** (`candado_glosario`): en el candado de `resolver_idioma`, el nivel de la rúbrica del título original se
lee después del glosario **solo con los términos de dirección**: `CHIEF ... OFFICER`, CEO, CFO, CTO, COO, CMO, CIO
y CHRO. Afecta a 17 títulos de la base (`CFO | ECUADOR`, `CHIEF PEOPLE OFFICER`, `CTO-CHIEF TECHNOLOGY
OFFICER`…).

**Medición:** el candado con todo el glosario movió un único voto de validación, y ninguno de dirección. Con solo
los términos de dirección, el cambio no toca ningún voto de validación: no hay nada que medir con el pinball. Es una
regla de coherencia (el mismo cargo da la misma banda), coherente con el glosario aprobado. **Se adopta.**

### Padrón de RUC recuperado y `ruc` en `/referencia` (2026-10-10)

- **Padrón recuperado.** Desde la v16, la base se armaba sin el padrón de la Superintendencia. `meta_ruc` solo
  traía las 6.722 empresas del marco, así que el RUC de un cliente que no aportó datos no daba su tamaño ni su
  industria, y D-063 no se activaba. La v26 recupera el padrón de la v15: 222.719 empresas (donde están los dos,
  manda lo del marco).
- **`ruc` en `/referencia`.** Da el tamaño igual que en `/informes`: el segmento pedido a mano manda; si no
  coincide con el del RUC, se avisa; un RUC fuera del padrón también se avisa.

## D-065 — Limpieza de votos atípicos. Registrado antes de medir

**Por qué** (autor, 2026-10-10: «¿podemos limpiar la base de outliers?»). Para el gerente general, la referencia de
una empresa mediana es $2.929. Pero el 10 % de los gerentes generales figura con $470–$600: el SBU o casi. En los
niveles 4–5, los votos (mediana por cargo y empresa) muestran un pico en el mínimo: el 4,7 % está bajo 1,25 SBU.
No es un precio de mercado del cargo: lo más probable es un dueño o representante legal que se pone el mínimo en la
nómina.

Una regla simétrica por MAD **no** sirve: muchos grupos de nivel 1 están pegados al SBU, su MAD es casi 0, y
cortaría el 6 % de los votos altos, que son reales.

**Cambio** (`atipicos`). Se quitan del entrenamiento los votos (cargo × empresa) que cumplen alguna de dos reglas,
con el grupo y el nivel de la base (nivel por grupo):

- **(a) Sueldo de dueño:** grupo de nivel 4–5 y voto < 1,25 SBU. Son 1.436 votos con toda la base.
- **(b) Extremo:** en grupos con ≥ 5 empresas, voto > 6× o < 1/6 de la mediana del grupo. Son 285 votos.

Se quitan las filas de esos pares y la base se arma sin ellas.

**Medición:** pinball, con empresas apartadas, frente al producto vigente sin tamaño (`tam_A`), con el `k` fijo.

- **Primaria:** los votos apartados que **no** son atípicos por la misma regla. Usa la mediana y el nivel del grupo
  de entrenamiento: el objetivo es el mercado de puestos contratados.
- **Secundaria:** todos los votos apartados. Se reporta.
- **Placebo:** se quita el mismo número de votos al azar, del mismo nivel (por nivel, tantos como quita la regla).

**Criterio** (el de D-058): se adopta si la primaria mejora (IC entero bajo cero) y el placebo no mejora, o si no
empeora y el placebo sí empeora.

### D-065, resultado: no se adopta (2026-10-10)

En el entrenamiento se quitaron 958 votos «de dueño» y 102 «extremos». Entre los votos apartados, 211 y 37 son
atípicos por la regla.

| | Primaria (no atípicos), donde actúa | Secundaria (todos), donde actúa |
|---|---|---|
| Limpieza | **+0,00098 [+0,00024, +0,00175], empeora** | +0,00274 [+0,00182, +0,00371], empeora |
| Placebo | +0,00057 [+0,00021, +0,00092], empeora | +0,00043, empeora |

(IC por bootstrap de empresas, media por empresa: el protocolo.) La limpieza empeora más que su placebo. Según su
criterio, **no se adopta**.

**Diagnóstico** (descriptivo, no cambia la decisión). Contando por voto, la primaria mejora −0,0006, y en los
niveles 4–5 mejora: −0,0025 a −0,0028 con datos directos y −0,005 por analogía, donde el centro sube ~2,3 %. Pero
volver a armar la base sin esos votos también mueve todo lo demás: parámetros globales, vecinos de la analogía y
anchos. El placebo muestra que ese movimiento cuesta por sí solo. Promediado por empresa, gana el costo.

El `GERENTE GENERAL` sube de 6,5 a 7,5 SBU con la limpieza. Si se quiere solo eso, haría falta una regla que corrija
el centro de los grupos de nivel 4–5 **sin volver a armar la base**, registrada y medida aparte.

## D-066 — ¿Cuánto de la prima del título en inglés es tamaño de empresa? Registrado antes de medir

**Por qué** (juez de coherencia, 2026-10-10). `idioma_sueldo="siempre"` le da a un título en inglés la banda de su
equivalente en español, sin prima. Empeora (+0,033 donde actúa), por el mismo mecanismo con que se rechazó D-062.
Las salidas coherentes son dos:

- **(i)** el equivalente más la prima (D-055);
- **(ii)** «siempre» completo (aceptar D-062).

Si la prima es sobre todo tamaño de empresa (las que escriben en inglés son más grandes), D-063 ya la corrige cuando
se conoce el tamaño, y la (ii) sale casi sin costo.

**Medición** (descriptiva, sin pinball). Pares de D-055: título en inglés de la base con datos directos (≥ 3
empresas) cuya traducción cae en **otro** grupo con datos. Base v26, juez y nivel por grupo, como la API. Por par:

1. **Prima bruta:** mediana de los votos del título en inglés menos la de los votos del equivalente.
2. **Prima ajustada por tamaño:** lo mismo con `voto − δ(L, s)` (D-063, base v26), solo con votos de empresas con
   segmento.
3. **Composición:** proporción de empresas GRANDE entre las que escriben el título en inglés y entre las del
   equivalente.

Resumen: mediana entre pares, con IC 95 % por bootstrap de pares (1.000 réplicas). También por nivel.

**Criterio (antes de ver):**

- **La (ii) queda respaldada** si la prima ajustada es ≤ 5 % (exp − 1) y su IC incluye 0.
- **Va la (i)** si la prima ajustada es ≥ 10 % con IC entero sobre 0, con la prima reestimada después del ajuste por
  tamaño.
- **Entre medio:** se reporta y decide el autor.

### D-066, resultado: el tamaño no explica la prima del inglés (2026-10-10)

453 pares (391 con votos con segmento). Mediana entre pares e IC por bootstrap de pares:

| | Prima |
|---|---|
| Bruta | +28,0 % [+23,0, +35,0] |
| Bruta, solo votos con segmento | +30,3 % [+26,1, +38,6] |
| **Ajustada por tamaño (D-063)** | **+32,1 % [+27,8, +36,6]** |

- **Composición:** el 75 % de las empresas que escriben el título en inglés son GRANDE, frente al 73 % de las del
  equivalente en español. El tamaño no los distingue.
- **Por nivel (ajustada):**

  | Nivel | 1 | 2 | 3 | 4 | 5 |
  |---|---|---|---|---|---|
  | Prima | +19 % | +33 % | +40 % | +10 % | +79 % |

  Los IC son anchos en los niveles 4 y 5 (n = 44 y 40).

**Según el criterio, va la (i)**: el equivalente más la prima, reestimada después del ajuste por tamaño. Confirma lo
que ya decía la decisión del autor del 2026-10-07 («tamaño y actividad no corrigen esa prima»). Esa decisión
(«siempre», sin prima) fue de producto, con el costo aceptado. **No se cambia sin que el autor lo confirme.** Queda
pendiente su decisión entre (i) y mantener «siempre».

La prima no es de tamaño: probablemente es de tipo de empresa (multinacional, sector) y no se puede observar con los
campos actuales.

## Protocolo v2 (2026-10-10, por la revisión de los tres jueces). Rige desde D-067

Los jueces mostraron que el IC por bootstrap de empresas es demasiado estrecho: todas las empresas con un mismo cargo
reciben la misma banda, así que sus errores van correlacionados. También mostraron que «donde actúa» compara la
variante y su placebo sobre conjuntos de votos distintos, y que «salvo que empeore» no tiene margen. Desde D-067:

1. **Votos:** la **unión** de los votos donde actúan la variante o su placebo (la banda cambia > 1e-6 en alguno).
2. **IC 95 %:** bootstrap en **dos vías**, empresa × cargo (pesos multinomiales en las dos, media por voto),
   400 réplicas. Se reporta también la media por empresa.
3. **Contra el placebo:** se compara la variante con su placebo, de forma pareada, sobre los mismos votos.
4. **Criterios:**
   - **Mejora de precisión:** se adopta si la variante frente al producto tiene el IC entero bajo cero **y**
     la variante frente al placebo también.
   - **Regla de producto** (coherencia, presentación): se adopta si **no es inferior**, es decir, si el extremo
     superior del IC frente al producto es < **+0,001** (≈ 0,7 % del pinball). Se reporta el placebo.
5. **Sin cambios después de medir:** el criterio no se aclara ni se modifica después de ver los resultados.
   Si hace falta otro, es una decisión nueva.

Herramienta: `research/experimentos/e2_nivel/77_comparar_v2.py`. Las decisiones anteriores no se recalculan aquí:
queda pendiente, igual que el test intocado.

## D-067 — Título en inglés: equivalente más prima encogida por nivel, mostrada aparte. Registrado antes de medir

**Por qué:** D-066 (la prima del inglés no es tamaño: +32 %) y la elección del autor (2026-10-10: «dale», opción (i)).

**Cambio:**

- **Banda.** Se sale de «siempre» y se vuelve a la lógica de D-055:
  - un título en inglés con datos directos propios usa sus datos;
  - sin datos propios y con un equivalente con datos, usa la banda del equivalente corrida por `π*(L)`;
  - sin equivalente, analogía, como hoy.
- **Prima encogida.** `π*(L) = (n_L·π_L + 50·π_global) / (n_L + 50)`, con `π_L` y `n_L` del estimador de D-055
  (pares por nivel).
- **Presentación.** La respuesta trae `referencia_equivalente` (sin prima) y `prima_idioma` (la π aplicada), para
  que el front muestre «equivale a X ($a); las empresas que titulan en inglés pagan +p % → $b».

**Medición:** frente a `trad_base` (el producto con «siempre»), con π estimada solo con el entrenamiento. Placebo:
la misma π, con la traducción hacia el grupo de **otro** título resuelto (el de D-055). **Criterio:** mejora de
precisión (protocolo v2).

## D-068 — Errores de tipeo y «cargo no reconocido». Registrado antes de medir

**(a) Tipeo.** Antes de buscar, cada palabra del título que no está en el vocabulario de la base y tiene ≥ 5 letras
se reemplaza por la palabra del vocabulario con menor distancia de Damerau-Levenshtein:

- ≤ 1 con 5–7 letras; ≤ 2 con ≥ 8 letras;
- solo si es **única** a esa distancia, o la más frecuente (por personas) con el doble que la siguiente.

Las palabras de rango (`RANGOS_RUBRICA`) y las siglas de ≤ 4 letras no se tocan.

- **Medición:** frente a `tam_A`. Placebo: la palabra mal escrita se reemplaza por una palabra del vocabulario
  **al azar** del mismo largo.
- **Criterio:** regla de producto (no inferior), y además la variante es mejor que el placebo en los votos donde
  actúa (IC pareado bajo cero).

**(b) No reconocido.** Si el título va por analogía y su `similitud` (coseno máximo con la base) es menor que `τ`,
la API responde sin cifra: `base = "no reconocido"`, con las sugerencias de `/puestos`.

- `τ` es el **percentil 2** de `similitud` entre los títulos apartados que van por analogía en `tam_A`: se rechaza
  como mucho el 2 % de títulos reales.
- **Lista de control de basura, fijada ahora (30):**

  ASDFGH QWERTY · XXXXX · AAAA BBBB · 123456 · LOREM IPSUM · TEST · PRUEBA PRUEBA · NINGUNO · N/A · HOLA MUNDO ·
  ASTRONAUTA · DOMADOR DE LEONES · MAGO · UNICORNIO · PIRATA · VAMPIRO · SUPERHEROE · DRAGON · ZZZZ · QWERTYUIOP ·
  MESA · SILLA · PERRO · GATO · PIZZA · FUTBOL · BANANA · CIELO AZUL · JKLÑ · ????

- **Criterio:** se adopta si rechaza ≥ 80 % de la lista. Se reporta, entre los votos apartados que se rechazarían,
  su pinball frente al resto (¿eran peores?).

## D-069 — La confianza también depende del ancho de la banda. Registrado antes de medir

**Regla nueva**, con `r = p75 / p25` de la banda entregada y `c` la confianza actual (por la incertidumbre del
centro):

| Confianza | Condición |
|---|---|
| **ALTA** | `c = ALTA` y `r ≤ 2,0` |
| **BAJA** | `c = BAJA` o `r > 3,0` |
| **MEDIA** | el resto |

**Medición** (con los votos apartados de `tam_A`, sin pinball, porque el pinball crece con el ancho por
construcción): el error del centro, `|voto − referencia|` (mediana), por clase, con la regla vieja y con la nueva.
IC en dos vías.

**Criterio:** se adopta si, con la regla nueva:

1. el error crece ALTA < MEDIA < BAJA, con IC de ALTA y BAJA que no se solapan;
2. el error de ALTA es ≤ al de ALTA con la regla vieja.

Se publica la regla en `docs/api_para_el_front.md`.

## D-070 — Sinónimos: el grupo chico se acerca al grande. Registrado antes de medir

**Por qué:** juez de resultados. `JEFE DE RRHH` da $1.229 (29 empresas) y `JEFE DE RECURSOS HUMANOS` $1.538 (198);
`GERENTE DE TALENTO HUMANO` está −24 % bajo `GERENTE DE RECURSOS HUMANOS`. Unir los grupos empeora (D-046/D-047).

**Pares:**

- la ronda 1 (`sinonimos_v1`, 441);
- la ronda 2 aprobada por el autor (`56_sinonimos_para_aprobar_r2.csv`, `aprobar = si`: 571);
- las **reglas de palabras** del autor (2026-10-10): `RRHH`, `RR.HH.`, `RR HH`, `TALENTO HUMANO` → `RECURSOS HUMANOS`;
  `TI`, `T.I.`, `TECNOLOGIAS DE LA INFORMACION` → `SISTEMAS`; `CONDUCTOR` → `CHOFER`. Son pares entre títulos de la
  base que coinciden después de reemplazar esas palabras, y las mismas reglas se aplican al título de la consulta
  antes de buscar.

**Cambio:** en cada componente conexa de grupos sinónimos, el grupo con más empresas no cambia. Cada uno de los
demás corre su centro a `(n·m + 10·m_grande) / (n + 10)`, y su banda se corre igual (como D-061).

**Medición:** frente a `tam_A`. Placebo: cada grupo chico se acerca a un grupo grande **al azar** del mismo nivel,
con el mismo peso. **Criterio:** regla de producto (no inferior). Se reporta la variante frente al placebo.

### D-067, resultado: cumple, se adopta (2026-10-10)

`π*` con el entrenamiento: 217 pares; global +0,25; por nivel encogida: 1 +0,33, 2 +0,27, 3 +0,19, 4 +0,23,
5 +0,20. El +0,79 bruto del nivel 5 de D-066 queda en +0,20 al encogerlo.

Protocolo v2, unión de 4.872 votos (691 empresas, 4.543 cargos):

| Comparación | Pinball | IC (dos vías) |
|---|---|---|
| Variante − producto («siempre») | −0,00481 | [−0,00768, −0,00208] |
| Placebo − producto | +0,00973 | |
| **Variante − placebo** | **−0,01454** | **[−0,02082, −0,00738]** |

Mejora frente al producto y frente al placebo: **se adopta.** Reemplaza a «siempre». Un título en inglés con datos
propios usa sus datos; sin datos, el equivalente más `π*` del nivel, mostrada aparte (`referencia_equivalente`,
`prima_idioma`).

### D-068, resultado: (a) tipeo se adopta; (b) «no reconocido» no se adopta (2026-10-10)

**(a) Tipeo.** Unión de 4.342 votos:

| Comparación | Pinball | IC (dos vías) |
|---|---|---|
| Variante − producto | +0,00019 | [−0,00025, +0,000999] |
| Variante − placebo | −0,00385 | [−0,00726, −0,00068] |

El extremo superior, +0,000999, queda justo bajo el margen de +0,001. Cumple no inferioridad y le gana al placebo:
**se adopta.** Ojo: la corrección actúa sobre solo **57 votos** apartados; la unión la llena el placebo. En la
validación casi no hay errores de tipeo que lleven a un título de la base. Es una regla para clientes, que el
pinball apenas puede medir.

**(b) No reconocido.** `τ` = 0,743 (percentil 2). Los 265 títulos reales apartados bajo `τ` (1,9 %) tienen pinball
0,261, frente a 0,155 del resto: son peores. Pero la lista de basura solo se rechaza en un 57 % (17 de 30). `MESA`,
`PERRO`, `PIRATA`, `MAGO` y `N/A` quedan sobre 0,80, y `PIZZA` existe como título en la base. **No cumple (≥ 80 %):
no se adopta.** Vertex encuentra parecidos plausibles para palabras comunes, y la similitud sola no separa la
basura.

### D-069, resultado: cumple, se adopta (2026-10-10)

Error del centro `|voto − referencia|` (mediana), 38.450 votos de `tam_A`:

| Regla | ALTA | MEDIA | BAJA |
|---|---|---|---|
| Vieja (centro) | 17,5 % [15,5, 19,6] (37 %) | 32,3 % | 33,1 % |
| **Nueva (centro + ancho)** | **15,9 % [14,3, 18,0]** (34 %) | 32,8 % | 34,0 % [30,7, 37,4] |

Se cumple el orden sin solape entre ALTA y BAJA, y el error de ALTA baja: **se adopta.** Nota honesta: MEDIA y BAJA
casi no se distinguen, ni con la regla vieja ni con la nueva.

### D-070, resultado: no se adopta (2026-10-10)

En 89 familias se movieron 554 grupos chicos (corrimiento mediano 5,5 %). Unión de 8.736 votos:

| Comparación | Pinball | IC (dos vías) |
|---|---|---|
| Variante − producto | +0,00082 | **[+0,00001, +0,00155]** |
| Variante − placebo | −0,00336 | [−0,00556, −0,00170] |

El extremo superior pasa el margen de +0,001: **no cumple la no inferioridad, no se adopta.** Es mucho mejor que
acercar al azar, pero acercar el grupo chico al grande cuesta algo de precisión: los grupos chicos tienen pagos
propios distintos. Los pares de la ronda 2 aprobados por el autor pasan al **buscador** (`sinonimos_v2`, uso de
D-047, sin tocar las bandas).
