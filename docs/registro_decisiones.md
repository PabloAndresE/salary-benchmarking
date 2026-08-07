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

**Cambios aplicados** (`e03ff8d`):

1. `descargar_plantilla` reintenta ante `RequestException` (SSL / conexión / timeout) y agota en
   `DescargaFallida`, distinta de `404 → None`. Espera inyectable para tests rápidos.
2. `_una_plantilla` devuelve `(montos, motivo)` y `_composicion_estudios` acumula un `Counter`:
   `ok / sin_plantilla / fallo_descarga / fallo_parseo`, con aviso destacado si hubo pérdidas.
3. `descargas_concurrentes` 8 → 4, con la tabla de medición documentada en `settings.py`.

**Dos bugs adicionales, descubiertos al desplegar:**

- **`c8efc3f`** — el job de Cloud Run pasaba `--concurrencia=8` por `--args`, lo que habría pisado
  el valor medido y reintroducido la pérdida. Se retira el flag: la concurrencia tiene una sola
  fuente de verdad (`settings.py`).
- **`ad9409a`** — la primera ejecución del job murió al importar, con `FileNotFoundError` sobre
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

**Arreglo** (`50b20b8`): `_ced_key()` normaliza para el join (quita el `.0` espurio de las columnas
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
