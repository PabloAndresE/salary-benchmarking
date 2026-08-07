# Estado del arte

Qué hizo cada trabajo, **qué les funcionó**, y qué tomar de ellos. Ordenado por cercanía a esta
tesis, no cronológicamente.

**Cómo leer las marcas de verificación:**

| | |
|---|---|
| ✅ | referencia verificada directamente contra la fuente durante la investigación |
| ▫ | citada por un revisor con datos completos; **pendiente de comprobar la fuente antes de citarla en la tesis** |

No se cita nada que no tenga al menos autor, año y venue concretos.

---

## 1. Los tres trabajos más cercanos — y por qué importan

Estos tres hacen, cada uno por su lado, una parte de lo que esta tesis propone. Hay que
posicionarse frente a ellos explícitamente: si el resultado sale bien, la primera pregunta de un
tribunal informado será *"¿qué queda que sea suyo?"*.

### ✅ Job2Vec — el *job title benchmarking* ya está planteado

Zhang, D., Liu, J., Zhu, H., Liu, Y., Wang, L., Wang, P. & Xiong, H. (2019).
*Job2Vec: Job Title Benchmarking with Collective Multi-View Representation Learning.*
CIKM '19, pp. 2763–2771. DOI [10.1145/3357384.3357825](https://doi.org/10.1145/3357384.3357825) ·
[arXiv:2009.07429](https://arxiv.org/pdf/2009.07429)

**Qué hicieron.** Definen *Job Title Benchmarking* (JTB) como emparejar títulos de puesto con
niveles de pericia similares **entre empresas distintas**, y lo motivan exactamente igual que este
proyecto: sustituir las encuestas manuales de compensación, caras y lentas. Reformulan el problema
como **predicción de enlaces sobre un grafo de puestos**.

**Qué les funcionó.** Combinar cuatro vistas del mismo grafo en vez de una sola representación:
(1) topología del grafo, (2) semántica de las descripciones, (3) *balance* de transiciones —si la
gente se mueve en ambos sentidos entre dos puestos con frecuencia parecida, son de nivel
similar—, y (4) **duración** de la transición: cuanto más corta, más parecidos los puestos.

**Qué tomar.** La idea de que **el nivel se puede inferir de la simetría de las transiciones** es
elegante y no necesita el salario. Aquí no aplica directamente —no hay grafo de transiciones de
carrera, hay nóminas— pero el principio sí: *buscar señales de nivel que no sean el pago*.

**Qué NO hicieron, y es la diferencia.** Trabajan sobre trayectorias de carrera declaradas
(tipo LinkedIn), no sobre nómina; y su noción de nivel se apoya en el mercado laboral observado,
no en una definición de contenido del puesto.

---

### ✅ Djumalieva et al. — familia × nivel inducido de datos, con el nivel construido *con el salario*

Djumalieva, J., Lima, A. & Sleeman, C. (2018).
*Classifying Occupations According to Their Skill Requirements in Job Advertisements.*
ESCoE Discussion Paper DP-2018-04.
[Página del paper](https://www.escoe.ac.uk/publications/classifying-occupations-according-to-their-skill-requirements-in-job-advertisements/) ·
[PDF](https://escoe-website.s3.amazonaws.com/wp-content/uploads/2020/07/13154228/ESCoE-DP-2018-04U.pdf)

**Qué hicieron.** Aprendizaje semi-supervisado sobre **37 millones de anuncios de empleo del Reino
Unido** (Burning Glass) para inducir una clasificación ocupacional de **cuatro capas jerárquicas**.

**Qué les funcionó.** Las tres primeras capas agrupan por **especialización de habilidades** —qué
tipo de competencias pide el puesto— y funcionan bien porque los anuncios listan habilidades
explícitamente. La estructura jerárquica permite elegir granularidad según el uso.

**Y aquí está el punto crítico para esta tesis:** *"The fourth layer of the hierarchy is based on
the offered salary and indicates skill level."* **Su capa de nivel se construye con el salario.**

**Qué tomar.** Es el antecedente más parecido al diseño de familia × nivel inducido de datos, y
**es literatura gris** (discussion paper), así que hay que citarlo pero no intimida como precedente
publicado. Su elección de usar el salario para el nivel es exactamente lo que aquí se rechaza por
circularidad — y por tanto **es el contraste que define la contribución propia**.

---

### ✅ TWICE — particiones data-driven validadas por predicción salarial fuera de muestra

Bakirov, A., Del Prato, F. & Zacchia, P. (2026).
*TWICE: Tree-based Wage Inference with Clustering and Estimation.*
[arXiv:2601.00776](https://arxiv.org/abs/2601.00776) — preprint, enero 2026.

**Qué hicieron.** Sustituyen los efectos fijos latentes del modelo AKM (trabajador + empresa) por
**particiones interpretables de variables observables**, obtenidas con árboles con boosting sobre
datos administrativos portugueses.

**Qué les funcionó.** El argumento que los mueve es el mismo que sostiene el leave-company-out de
esta tesis: *"sparse networks inflate variance estimates"* — las redes de movilidad ralas inflan
las estimaciones de varianza. Su solución cambia capacidad de capturar lo idiosincrásico por
**robustez al ruido muestral y portabilidad fuera de muestra**, y superan a los benchmarks lineales
precisamente en predicción fuera de muestra.

**Qué tomar.** Tres cosas: (1) **la validación por predicción fuera de muestra como criterio
central** está establecida en econometría laboral, no es una heurística de ML; (2) *sorting* e
interacciones no aditivas explican más dispersión de la que sugiere AKM — relevante para
interpretar el efecto empresa; (3) su advertencia sobre redes ralas se aplica directamente al
sesgo de movilidad limitada (§7 abajo).

**Qué NO hicieron.** Su partición usa el salario como objetivo del árbol. Es supervisada por
diseño: es una descomposición de la varianza salarial, no una taxonomía ocupacional.

---

### La contribución propia, dicha en una frase

Los tres precedentes usan el salario en la construcción del agrupamiento o del nivel. De ahí sale
el enunciado defendible:

> **Familia de rol × nivel inducida sin usar el salario en ninguna etapa del agrupamiento, sobre un
> mercado no estudiado, y validada fuera de muestra con leave-company-out contra una escalera de
> nulos y un criterio de éxito pre-registrado.**

Esa frase debe estar escrita en la tesis. Sin ella, el trabajo se lee como "clustering aplicado a
un dataset nuevo".

---

## 2. Ecuador: el trabajo que no se puede ignorar

### ✅ Del Pozo-Villafuerte & Villacís-Miranda (2025) — estandarización ocupacional ecuatoriana

*Enhancing Labor Market Intelligence in Ecuador: A Framework for Generating, Standardizing and
Analyzing Job Demand Data.* Computational Economics 67:2107–2149.
DOI [10.1007/s10614-025-10935-y](https://doi.org/10.1007/s10614-025-10935-y)

**Qué hicieron.** Software que extrae ofertas de los portales de empleo líderes del Ecuador
—**Computrabajo, Multitrabajos y Encuentraempleo**— y aplica minería de texto para generar
variables de demanda laboral estandarizadas.

**Qué tomar.** Dos cosas de peso:

1. Es **revisado por pares, sobre Ecuador, y sobre estandarización ocupacional**. Ante un tribunal
   local, su ausencia del marco teórico es indefendible.
2. Resuelve, por una vía legalmente limpia, el problema del **vocabulario ocupacional ecuatoriano
   real** — que es lo único que un raspado de LinkedIn aportaría, con todos sus problemas de
   enlace, cobertura sesgada y LOPDP. Los portales de empleo publican títulos, no personas.

---

### ✅ Tablas sectoriales del Ministerio del Trabajo — una arquitectura de cargos oficial que ya existe

Acuerdo MDT-2019-395 y sucesivos; catálogo de códigos sectoriales del IESS
([PDF](https://www.iess.gob.ec/documents/10162/0/comisiones_sectoriales.pdf)). Fijadas anualmente
por comisiones sectoriales tripartitas (art. 122 del Código del Trabajo).

**Qué contienen.** Verificado extrayendo el PDF del IESS: **2.242 cargos codificados, 1.724 nombres
distintos, 22 comisiones sectoriales ancladas a rama de actividad, 118 ramas**, con salario mínimo
por cargo. El Acuerdo MDT añade dos columnas que el catálogo del IESS no trae: la **estructura
ocupacional** (niveles A Dirección / B1–B3 Supervisión / C1–C3 Operación / D1–D2 Asistencia /
E1–E2 Apoyo) y una columna de comentarios que **es un diccionario de sinónimos ya escrito**
(*"AYUDANTE DE TOPÓGRAFO — E2 — INCLUYE CADENERO, PERFILERO, NIVELADOR, PRISMERO, MOCHILERO"*).

**Qué se midió aquí.** Cruzando el catálogo del IESS con las 68.506 etiquetas de 2024–2025:

| Emparejamiento | Etiquetas | Personas |
|---|---|---|
| Exacto | 1,1% | **13,5%** |
| Similitud de caracteres ≥ 0,80 | 6,4% | 23,1% |
| ≥ 0,70 | 13,9% | 38,0% |

Pero **el emparejamiento difuso por caracteres es peligroso**, y hay evidencia directa:

```
AUXILIAR DE SERVICIOS GENERALES → JEFE DE SERVICIOS GENERALES   0,79   ✗ invierte el nivel
ASISTENTE ADMINISTRATIVO        → JEFE ADMINISTRATIVO           0,79   ✗ invierte el nivel
AGENTE DE SEGURIDAD             → JEFE DE SEGURIDAD             0,72   ✗ invierte el nivel
TRABAJADOR AGRICOLA             → TRABAJADOR ACUICOLA           0,66   ✗ agrícola ≠ acuícola
```

Las palabras de jerarquía (auxiliar / asistente / jefe / supervisor) comparten casi todos los
caracteres con su opuesto. **Cualquier emparejamiento contra el catálogo debe tratarlas como
restricción dura, no como similitud blanda.**

**Qué tomar.** Cinco usos, todos sin datos personales: *gazetteer* para emparejamiento con bloqueo
por rama; fuente de **must-links entre cadenas distintas** (los sinónimos oficiales); objetivo de
validez externa más barato que construir una referencia ISCO a mano; **escala de nivel definida por
contenido del puesto**, independiente de los datos propios; y punto de censura por cargo para un
eventual Tobit, mucho mejor especificado que el SBU genérico.

---

## 3. ¿Qué tan fiable es la codificación ocupacional? (spoiler: menos de lo que se cree)

Esta sección sostiene la motivación de la tesis con números ajenos.

### ▫ Massing, Wasmer, Wolf & Züll (2019) — el código fino no es fiable, el constructo agregado sí

*How Standardized is Occupational Coding?* Journal of Official Statistics 35(1).
DOI [10.2478/jos-2019-0008](https://doi.org/10.2478/jos-2019-0008)

**Qué encontraron.** κ ≈ **0,5** entre **agencias humanas profesionales** codificando las mismas
respuestas a 4 dígitos — pero **0,82–0,90** para los puntajes de estatus derivados de esos códigos.

**Por qué importa tanto.** Es el mejor argumento a favor de los arquetipos, dicho por otros y con
número: *el código ocupacional fino es poco fiable incluso entre profesionales; el constructo
agregado que se deriva de él sí lo es.* Justifica agrupar en familias antes que perseguir el código
exacto.

### ▫ Wan et al. (2023) — el techo del emparejamiento automático a ISCO

*Automated Coding of Job Descriptions from a General Population Study.*
Annals of Work Exposures and Health 67(5). DOI [10.1093/annweh/wxad002](https://doi.org/10.1093/annweh/wxad002)

**Qué encontraron.** Entre codificadores automáticos (AUTONOC, CASCOT, LabourR): **17,7–26,0% de
acuerdo exacto a nivel detallado, 43,8–58,1% a grupo mayor**.

**Qué tomar.** Fija la expectativa realista del test de validez externa contra ISCO-08: si el
arquetipo predice el grupo mayor al ~50%, está a la altura del estado del arte, no por debajo.
Sin este dato, un 50% parecería un fracaso.

### ▫ Speer (2016) — una representación más rica no cura sola el error de codificación

*How bad is occupational coding error? A task-based approach.* Economics Letters 141:166–168.
DOI [10.1016/j.econlet.2016.02.025](https://doi.org/10.1016/j.econlet.2016.02.025)

**Qué encontró.** Pasar al espacio de tareas de O*NET reduce la sobreestimación espuria de
movilidad ocupacional solo del ~90% al ~75%.

**Qué tomar.** Es una advertencia directa: cambiar de espacio de representación mejora, pero no
resuelve. Hay que acotar la afirmación de la tesis o mostrar que los arquetipos hacen algo mejor
que esto.

---

## 4. Cómo construyen las agencias oficiales sus celdas de comparación

### ▫ BLS — Modeled Wage Estimates por ocupación × nivel de trabajo

Allamani, J., Hudak, M. & Issan, A. (2022). *Introducing Modeled Wage Estimates by grouped work
levels.* Monthly Labor Review. DOI [10.21916/mlr.2022.23](https://doi.org/10.21916/mlr.2022.23).
Fundacional: Lettau & Zamora (2013), DOI [10.21916/mlr.2013.27](https://doi.org/10.21916/mlr.2013.27).

**Qué hicieron.** El BLS publica estimaciones salariales por **ocupación × nivel de trabajo** — es
decir, la misma arquitectura de dos ejes de esta tesis, en una agencia nacional. Y en 2022 tuvieron
que **agrupar sus 15 niveles en bandas más gruesas porque las celdas finas no eran estimables**.

**Qué tomar.** Precedente de agencia para familia × nivel, y su disyuntiva de granularidad ya
tomada. Además, el *work level* del National Compensation Survey **tiene definición operacional
pública** (sistema de puntos derivado del Factor Evaluation System de la OPM): **se puede adoptar
como constructo nominal y medir convergencia contra ella**, lo que resuelve la objeción de que
"nivel" sea lo que salga del algoritmo.

### ▫ Eurostat — Structure of Earnings Survey

Recoge ISCO a 2–3 dígitos y **publica solo a 1 dígito**, porque las celdas ocupacionales finas no
son estimables con fiabilidad.
[Metadatos SES 2022](https://ec.europa.eu/eurostat/cache/metadata/en/earn_ses2022_esms.htm)

**Qué tomar.** Evidencia de agencia de que el problema de granularidad no es local ni un defecto
de estos datos.

### ✅ BLS OEWS — la regla de los donantes

*Occupational Employment and Wage Statistics — Survey Methods and Reliability.*
[Metodología](https://www.bls.gov/oes/methods_24.pdf)

**Qué tomar.** El objetivo de **≥5 donantes por celda** antes de emitir una estimación. Es el
respaldo institucional del umbral de abstención del banco de validación, que de otro modo parecería
arbitrario.

### ▫ GAO (2025) — "qué celda de comparación" es un problema abierto a nivel de agencia

*Federal Workforce: Current and Potential Alternatives for Locality Pay Methodology.* GAO-25-107788.
[Informe](https://www.gao.gov/products/gao-25-107788)

**Qué documenta.** Desde 2019, los órganos asesores federales estadounidenses **no logran acordar
una metodología creíble** para definir las celdas de comparación salarial.

**Qué tomar.** Es el respaldo para reclamar el hueco: la pregunta "¿cuál es el grupo de comparación
correcto?" sigue abierta en la estadística oficial.

---

## 5. Validación: el diseño ya tiene nombre en la literatura

Esta es la sección que **convierte el diseño de heurística en método establecido**. Citarla elimina
de raíz la objeción "esto es una métrica ad hoc".

### ▫ Tibshirani & Walther (2005) — *prediction strength*

*Cluster Validation by Prediction Strength.* JCGS 14(3):511–528.
DOI [10.1198/106186005X59243](https://doi.org/10.1198/106186005X59243)

**Qué hicieron.** Clusterizar en train, asignar el test al centroide más cercano, medir cuánta
co-pertenencia se reproduce. Umbral convencional ≥ 0,8–0,9.

**Qué tomar.** El leave-company-out de esta tesis **es** *prediction strength* con la empresa como
unidad de partición. Hay que decirlo así.

### ▫ Kline, Saggio & Sølvsten (2020) — estimación leave-out de componentes de varianza

Econometrica 88(5). DOI [10.3982/ECTA16410](https://doi.org/10.3982/ECTA16410)

**Qué tomar.** Los estimadores *plug-in* de componentes de varianza tienen sesgo de primer orden, y
el leave-out es **la corrección principiada**, no un truco. Respalda la exclusión de la propia
empresa.

### ▫ Roberts et al. (2017) — validación cruzada con estructura jerárquica

*Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic
structure.* Ecography 40(8). DOI [10.1111/ecog.02881](https://doi.org/10.1111/ecog.02881)

**Qué tomar.** La justificación general de **partir por bloque** (aquí, empresa) cuando los datos
tienen estructura jerárquica. Es la cita que sostiene splits, bootstrap y CIs por empresa.

### ▫ Neufeld et al. (2024) — *data thinning*, para la inferencia post-selección

JMLR 25(57). [Paper](https://www.jmlr.org/papers/v25/23-0446.html)

**Qué hicieron.** Parten cada observación en dos piezas independientes: se clusteriza en una y se
valida en la otra.

**Qué tomar.** Es la salida accionable al problema de elegir la partición y luego evaluarla con los
mismos datos. Complemento econométrico: Leeb & Pötscher (2005), Econometric Theory 21(1),
DOI [10.1017/S0266466605050036](https://doi.org/10.1017/S0266466605050036).

---

## 6. Representación: pesos de bloque y métricas aprendidas

Aquí es donde el diseño estaba reinventando peor lo que ya existe.

### ▫ Análisis Factorial Múltiple (MFA) — normalizar bloques sin hiperparámetros

Escofier & Pagès (1994); exposición moderna: Abdi, Williams & Valentin (2013),
WIREs Computational Statistics 5(2). DOI [10.1002/wics.1246](https://doi.org/10.1002/wics.1246)

**Qué hace.** Divide cada bloque por su **primer valor singular**, de modo que ningún bloque imponga
su estructura sobre el primer eje.

**Por qué funciona aquí.** Es **invariante a la redundancia interna del bloque** — exactamente la
propiedad que hace falta con ~100 dimensiones de embedding frente a 3–4 de composición. Normalizar
por varianza total no lo consigue: un bloque con la misma varianza repartida en 100 direcciones
sigue dominando la distancia. **Cero parámetros libres, y por tanto ningún hiperparámetro que
afinar contra el salario.**

### ▫ RCA — aprender una métrica solo con restricciones positivas

Bar-Hillel, Hertz, Shental & Weinshall (2005). *Learning a Mahalanobis Metric from Equivalence
Constraints.* JMLR 6. [Paper](https://jmlr.org/papers/v6/bar-hillel05a.html)

**Qué hicieron.** Clausura transitiva de los must-links para formar *chunklets*; la métrica óptima
es el blanqueo por la covarianza promedio intra-chunklet. **Forma cerrada**, escala sin problema.

**Qué tomar, y con qué cuidado.** Restringida a bloque-diagonal, RCA **es** el estimador de pesos de
bloque que el diseño planteaba como hiperparámetro. Pero hay una trampa específica: al blanquear
por la covarianza intra-chunklet, **encoge las direcciones que varían dentro de un mismo cargo
textual — que es donde vive la composición**. Con must-links derivados del texto, produciría "la
composición no aporta" por construcción del estimador.

### ▫ Xing, Ng, Jordan & Russell (2002) — ponderación de variables desde pares

NIPS 2002. [Paper](https://papers.nips.cc/paper/2164-distance-metric-learning-with-application-to-clustering-with-side-information)

**Qué tomar.** La variante **diagonal** es literalmente ponderación de variables aprendida desde
pares similares y disímiles. Requiere **cannot-links**, no solo must-links.

### ▫ Wagstaff, Basu & Davidson (2006) — las restricciones pueden empeorar el resultado

*When Is Constrained Clustering Beneficial, and Why?* AAAI.
[PDF](https://www.wkiri.com/research/papers/wagstaff-constutil-06.pdf) · complemento: Davidson,
Wagstaff & Basu (2006), PKDD.

**Qué encontraron.** Un conjunto de restricciones puede **degradar** el clustering, y definen dos
diagnósticos calculables antes de clusterizar: **informativeness** (información que el algoritmo no
habría obtenido solo) y **coherence** (consistencia interna).

**Qué tomar — y es lo más importante de esta sección.** Es el instrumento que detecta el problema de
los must-links derivados del texto: si un must-link une dos personas con **la misma cadena**, su
informativeness es ≈ 0 y no puede arbitrar entre bloques. **Medir informativeness y coherence antes
de usar cualquier conjunto de restricciones.**

### ▫ Selección de variables en clustering, alternativas sin restricciones

- **Witten & Tibshirani (2010)**, JASA 105(490):713–726, DOI [10.1198/jasa.2010.tm09415](https://doi.org/10.1198/jasa.2010.tm09415) — *sparse clustering* con estadístico de brecha por permutación: mide cuánta estructura tiene un bloque **por encima de su propia versión permutada**.
- **Maugis, Celeux & Martin-Magniette (2009)**, CSDA — selección basada en modelo: el peso deja de ser hiperparámetro y pasa a ser la escala de la log-verosimilitud del bloque, elegida por BIC/ICL.
- **Milligan & Cooper (1988)**, Journal of Classification 5:181–204, DOI [10.1007/BF01897163](https://doi.org/10.1007/BF01897163) — comparan métodos de estandarización para clustering: **dividir por el rango recupera mejor la estructura que el z-score**.
- **Huang, Ng, Rong & Li (2005)**, IEEE TPAMI 27(5):657–668 — W-k-means, ponderación automática de variables.

---

## 7. Descomposición de la varianza salarial

### ▫ Torres, Portugal, Addison & Guimarães (2018) — el título del puesto sí explica salario

*The sources of wage variation and the direction of assortative matching.* Labour Economics 54:47–60.
DOI [10.1016/j.labeco.2018.06.004](https://doi.org/10.1016/j.labeco.2018.06.004)

**Qué encontraron.** Descomposición a tres vías sobre datos administrativos portugueses (26 años):
trabajador ≈ 1/3, empresa ≈ 1/4, **título del puesto ≈ 1/5** de la varianza del log-salario.

**Qué obliga a corregir.** La afirmación *"la etiqueta CARGO no sirve"* es demasiado fuerte: en
datos administrativos limpios el título es un determinante de primer orden. Hay que reformularla:
*"CARGO **tal como se captura en los estudios actuariales ecuatorianos** no sirve"*.

### ▫ Sesgo de movilidad limitada — una amenaza a un número propio

Andrews, Gill, Schank & Upward (2008), JRSS-A 171(3), DOI [10.1111/j.1467-985X.2007.00533.x](https://doi.org/10.1111/j.1467-985X.2007.00533.x).
Consenso: Card, Cardoso, Heining & Kline (2018), JOLE 36(S1), DOI [10.1086/694153](https://doi.org/10.1086/694153) —
la firma explica ≈ 20% de la variación salarial.

**Por qué importa.** Con empresas presentes en pocos años, los estimadores de componentes de
varianza **sobreestiman** el efecto empresa. El η²_empresa ≈ 0,34–0,39 medido aquí es uno de los
números que sostiene todo el argumento del leave-company-out, y **probablemente está sobreestimado**.
Hay que cuantificarlo o acotarlo.

---

## 8. Datos composicionales

### ▫ Egozcue et al. (2003) — transformación ILR

*Isometric Logratio Transformations for Compositional Data Analysis.* Mathematical Geology 35:279–300.
DOI [10.1023/A:1023818214614](https://doi.org/10.1023/A:1023818214614)

**Qué tomar, con advertencias.** El centrado correcto en el símplex es la perturbación por la media
geométrica cerrada — **no** restar medias aritméticamente, que saca los datos del símplex. Residualizar
y transformar **no conmutan**: el orden cambia el resultado.

**Y un problema práctico serio.** Con 4 partes hay 16 patrones de ceros; los datos de este proyecto
pueblan ~6. La subcomposición positiva de cada patrón vive en un símplex de **dimensión distinta**, así
que las coordenadas ILR de patrones distintos **no son conmensurables** y apilarlas para calcular
distancias euclídeas es incoherente.

**Alternativa más simple con respaldo:** Greenacre, Grunsky & Bacon-Shone muestran que un conjunto
reducido de logratios simples o amalgamados es casi óptimo en varianza explicada, con
retrotransformación exacta e interpretable
([artículo](https://www.sciencedirect.com/science/article/pii/S2590197419300175)). Con 4 partes hay
3 grados de libertad: el aparato CoDa completo es maquinaria pesada para 3 números.

**Lo que NO aplica:** `zCompositions` (Palarea-Albaladejo & Martín-Fernández, 2015) está diseñado
para ceros redondeados o bajo límite de detección, **no estructurales**. "No cobra comisión" no es un
dato faltante: es la señal más limpia del bloque.

---

## 9. Emparejamiento de títulos y taxonomías disponibles

### ✅ ESCO — clasificación europea con etiquetas alternativas en español

[Portal](https://esco.ec.europa.eu/) · [Mapeo a ISCO](https://esco.ec.europa.eu/en/about-esco/escopedia/escopedia/international-standard-classification-occupations-isco) · [API](https://esco.ec.europa.eu/en/about-esco/escopedia/escopedia/esco-api)

**Qué ofrece.** Cada ocupación mapea a **exactamente un código ISCO-08**, e idéntica a ISCO de 4
dígitos hacia arriba. Multilingüe con español, y —lo decisivo— **etiquetas alternativas**: una lista
curada de las distintas formas de nombrar cada ocupación. Datos abiertos y API pública.

**Qué tomar.** Es una fuente de sinónimos y de referencia ISCO sin datos personales ni problemas
legales. Complementa a la tabla sectorial ecuatoriana: ESCO aporta el estándar internacional, la
tabla sectorial el vocabulario y los niveles locales.

### ▫ Modelos de emparejamiento de títulos, listos para usar

- **JobBERT** — Decorte, Van Hautte, Demeester & Develder, [arXiv:2109.09605](https://arxiv.org/pdf/2109.09605): representaciones de títulos de puesto validadas contra ESCO.
- **Multilingual JobBERT-V3** — Decorte, De Lange & Van Hautte (2025), [arXiv:2507.21609](https://arxiv.org/abs/2507.21609): **21 M+ títulos, incluye español**. Es el rival correcto para el nulo solo-texto.
- **LLM4Jobs** — Li, Kang & De Bie (2025), Knowledge-Based Systems, DOI [10.1016/j.knosys.2025.113302](https://doi.org/10.1016/j.knosys.2025.113302): se evalúa contra CASCOT **y** contra GPT-4 zero-shot. Es el diseño experimental que el etiquetado con LLM debería imitar.
- **TalentCLEF 2025** — Gasco et al., [arXiv:2507.13275](https://arxiv.org/abs/2507.13275): benchmark con pista en español.
- **Carotene** — Javed et al. (2015), DOI [10.1109/BigDataService.2015.61](https://doi.org/10.1109/BigDataService.2015.61): cascada grueso→fino que combina clustering con clasificación supervisada. Precedente industrial de esta arquitectura.

---

## 10. Evaluación de puestos en la industria

### ▫ Los sistemas comerciales no tienen validación académica publicada

Panorámica: van de Glind et al. (2025), *Mapping the Literature on Job Evaluation*,
DOI [10.1177/08863687241279592](https://doi.org/10.1177/08863687241279592).

**El hallazgo.** No existe evaluación académica de validez o fiabilidad para **Mercer IPE, Korn Ferry
Hay (en su forma actual), WTW Global Grading ni Radford**. Solo material de proveedor. La única
crítica académica sustantiva de un sistema nombrado es Steinberg (1992), *Gendered Instructions:
Cultural Lag and Gender Bias in the Hay System*, Work and Occupations 19(4),
DOI [10.1177/0730888492019004004](https://doi.org/10.1177/0730888492019004004).

**Qué tomar.** Refuerza la motivación de la tesis: **la industria vende "familia × nivel" sin
evidencia de validez publicada.**

### ▫ Grams & Schwab (1985) — la evaluación de puestos lava la estructura salarial existente

Academy of Management Journal 28(2):279–290. DOI [10.2307/256201](https://doi.org/10.2307/256201)

**Qué encontraron.** Los sistemas de evaluación de puestos se anclan en el pago actual y **convierten
la estructura salarial existente en un agrupamiento aparentemente objetivo**.

**Qué tomar.** Riesgo directo para arquetipos inducidos de nómina, y conectado con el análisis de
brecha de género: si el arquetipo hereda la estructura salarial existente, la brecha ajustada por
arquetipo la subestima por construcción.

---

## 11. Los huecos que este trabajo puede reclamar

Buscados y **no encontrados**:

1. **No hay evaluación académica independiente de validez para los sistemas comerciales de
   evaluación de puestos** (§10). La industria vende esta arquitectura sin evidencia publicada.
2. **No hay evaluación académica independiente de cómo las agencias estadísticas construyen sus
   celdas de comparación salarial** — solo autodocumentación y el informe GAO que constata que no
   hay acuerdo metodológico (§4).
3. **No hay un método publicado con nombre propio para "pesos de bloque heterogéneos aprendidos
   desde must-links"**. La composición correcta es RCA o ITML con matriz bloque-diagonal — es una
   línea de código, no una contribución. **Conviene decirlo así y no presentarlo como novedad.**
4. No existe revisión sistemática 2025–26 de codificación ocupacional automática, ni paper
   metodológico revisado por pares de CASCOT, ni ningún paper de normalización de títulos firmado
   por LinkedIn (solo blogs de ingeniería y dos patentes: US 10339612 y US 10255586).

---

## 12. Qué hacer con esto

**Citas obligatorias antes de la defensa**, por orden de urgencia:

1. **Job2Vec (2019)** — la premisa, ya publicada.
2. **Del Pozo-Villafuerte & Villacís-Miranda (2025)** — Ecuador, revisado por pares.
3. **Torres et al. (2018)** — obliga a acotar la afirmación central.
4. **Tibshirani & Walther (2005) + Kline, Saggio & Sølvsten (2020) + Roberts et al. (2017)** — el
   trío que convierte el diseño de validación en método establecido.
5. **Djumalieva et al. (2018)** y **TWICE (2026)** — para el enmarque de novedad.

**Verificar antes de citar:** todo lo marcado con ▫. Las marcas ✅ se comprobaron durante esta
investigación; el resto viene de revisión y tiene datos completos, pero no se ha abierto la fuente.

**Correcciones de citación señaladas por los revisores, pendientes de comprobar:** Gao, Bien & Witten
es 2024 (JASA 119(545):332–342), no 2022; von Luxburg es 2010 (FnT ML 2(3)); Ben-Hur et al. es 2002;
OccCANINE (Dahl et al.) sigue en revisión — citar como working paper.
