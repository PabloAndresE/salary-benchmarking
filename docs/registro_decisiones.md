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
ruido irreducible sd 0,3246 frente a 0,3651 real → **techo de mejora por agrupar mejor: 10,9%**
(12,1% sobre train completo, 14,4% fuera de la zona pegada al SBU). Concentrado en el 34% de gente
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
—más que el 10,9% que da agrupar mejor— y sube a −14,6% en empresas con más de 100 compañeros con
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

`13,2%` del nivel, `13,2%` del sector y `10,9%` del techo **no se suman ni se comparan
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
