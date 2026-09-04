# E3 — La banda que se le entrega al cliente

**El defecto más grave encontrado hasta ahora en el producto**, y salió de una objeción
en voz alta: *"τ y σ representan la variación de un cargo específico, ¿y los usan para
todos los cargos?"*.

La respuesta era que sí, y estaba mal.

**Todo corre sobre el 80% de train. El 20% de test no se toca.**

| Script | Qué contesta | Resultado |
|---|---|---|
| `01_tau_y_sigma_son_globales.py` | ¿Varía `τ` entre cargos, y es real o es ruido? | **Varía 8,3×, y es real.** Test-retest entre mitades de empresas: r = 0,78 |
| `02_calibracion_por_celda.py` | ¿La banda p25–p75 contiene al 50%? | **No: entre 18% y 98% según el cargo.** `τ_c` parte la deformación por la mitad |
| `03_la_banda_en_dolares.py` | Lo mismo, en dólares y contra gente real | 4 de 20 gerentes generales caen dentro de su propia banda |
| `04_cuantiles_empiricos.py` | ¿Y si no se supone forma y se usan cuantiles empíricos? | **Gana en las cuatro métricas.** Pinball p25 −25% |

## El hallazgo

`τ` es la dispersión de pago entre empresas y `σ` la dispersión dentro de una empresa. El
estimador usa **un solo `τ` global** para los 65.081 cargos. Medido sobre las 704 celdas
con 20+ empresas (45,2% de la gente):

```
tau por celda   p05=0.080  p25=0.213  p50=0.322  p75=0.446  p95=0.663
                              global = 0.2917
```

Y no es ruido de estimación. Partiendo las empresas de cada cargo en dos mitades al azar y
estimando por separado, las dos mitades **correlacionan a 0,78** (Spearman 0,77).
Corregido por atenuación, la fiabilidad de `τ_c` sobre la muestra completa es ~0,88.

El patrón sigue el escalón jerárquico, y tiene causa mecánica: **el salario mínimo
comprime desde abajo**.

```
AUXILIAR DE LIMPIEZA   tau 0.073      GERENTE GENERAL   tau 0.951
```

Esto añade algo a D-013: el nivel no sólo mueve la media 2,37× — escala la varianza 13×.

## Lo que eso le hace al cliente

La banda p25–p75 debería contener al 50% de la gente del cargo. Contiene:

```
GERENTE GENERAL       18.3%        ->  82 de cada 100 caen FUERA
CONTADOR              34.7%
JEFE DE BODEGA        43.9%
ASISTENTE CONTABLE    54.0%
CHOFER                69.9%
AUXILIAR DE LIMPIEZA  92.4%
TRABAJADOR AGRICOLA   98.0%
```

En dólares, `GERENTE GENERAL`: el mercado real va de $500 (p05) a $13.712 (p95), y se
entrega una banda de **$2.436 – $3.775**. Un cliente que paga $5.000 lee *"muy por encima
del mercado"* cuando en realidad está **por debajo del p75**.

## Dos defectos, no uno

`02` separó lo que depende del cargo de lo que no:

| | recorrido entre quintiles | cob. global | CRPS |
|---|---|---|---|
| A hoy (τ, σ globales) | **54,7 puntos** | 68,6% | 0,1720 |
| C (τ_c, σ_c por celda) | **23,4 puntos** | 66,5% | 0,1572 |

`τ_c` arregla la deformación **entre cargos** y deja intacto un sesgo global: todo sale
demasiado ancho. La causa es que **el centro se estima de forma robusta (mediana de votos)
y la dispersión no (raíz de una varianza)**. Las colas inflan la varianza sin ensanchar el
50% central.

Y la forma cambia por cargo, así que recalibrar el multiplicador `0,6745` no sirve: un solo
número no puede describir a la vez un pico y una cola larga.

```
AUXILIAR DE LIMPIEZA   p25=$475  p50=$475  p75=$485     <- un pico
GERENTE GENERAL        p05=$500          p95=$13,712    <- una cola
```

## La solución medida: cuantiles empíricos

Donde hay 10+ empresas, no hace falta modelo. Se reportan los cuantiles empíricos de la
celda, **ponderados por empresa** (cada empresa aporta su `w_f` repartido entre su gente;
sin eso una nómina de 400 contadores define el mercado).

```
                       cob 50%   pinball.25   pinball.75
A hoy                    68.7%     0.0973       0.1025
C (τ_c, σ_c)             66.5%     0.0841       0.0958
D empírico F>=10         59.9%     0.0728       0.0951
D empírico F>=20         61.0%     0.0745       0.0954
```

**Pinball p25 baja un 25%.** Es la métrica que decide: regla de puntuación propia para
cuantiles, que es lo que se entrega. Y D repara de paso la regresión que `τ_c` había
introducido en `CHOFER` (69,9% → 30,2% con C → **51,5%** con D).

Las bandas contra la realidad:

```
                     REAL              A hoy             D empírico
TRABAJADOR AGRICOLA  $  470 – $  472   $  377 – $  590   $  470 – $  472
CONTADOR             $  920 – $1,839   $1,040 – $1,625   $  922 – $1,696
GERENTE GENERAL      $1,932 – $6,657   $2,422 – $3,796   $1,500 – $5,460
```

## Por qué el 59,9% no es un fracaso

No llega al 50% y no puede llegar. `TRABAJADOR AGRICOLA` tiene cuartiles reales
$470 – $472: la banda de D los reproduce **exactos** y aun así cubre el 90,3%, porque más
del 90% de esa gente cobra el mismo número. **Con masa puntual, ninguna banda de ancho
positivo contiene exactamente el 50%.** En esos cargos la cobertura deja de ser una métrica
válida y manda el pinball.

## Lo que queda abierto

**`VENDEDOR` falla**: real $482 – $520, D da $482 – $800. La sospecha es una ambigüedad de
definición que el proyecto nunca resolvió:

> ¿la banda dice *"la mitad de las **empresas** paga entre X e Y"* o *"la mitad de las
> **personas** cobra entre X e Y"*?

El centro (mediana de votos por empresa) responde la primera; la evaluación cuenta personas,
o sea mide la segunda. Son cosas distintas y hay que decidir cuál es el producto antes de
montar nada.

**Confidencialidad**: publicar p25/p75 empíricos está más cerca del dato crudo que un
número de modelo. Con 10+ empresas y ponderación por empresa es el precedente del BLS, pero
es una decisión que hay que tomar explícitamente. Subir a 20 empresas cuesta poco:
pinball 0,0728 → 0,0745.

## Cómo correrlos

```bash
export PIPELINE_SALT=<cualquiera>
export PYTHONPATH=src
.venv/Scripts/python.exe research/experimentos/e3_varianza/04_cuantiles_empiricos.py
```

`04` importa el estimador de `02` en vez de copiarlo, para que la comparación sea válida.
Las salidas commiteadas están en `salidas/`.

## `05` — decidido: la banda habla de EMPRESAS, umbral 10

Decisión de producto tras `04`: la banda dice *"la mitad de las **empresas** paga entre X e
Y"*. Es lo coherente con el centro, que ya es la mediana de los votos por empresa.

**Eso corrige un número que este README daba mal.** Medida contra personas, la cobertura
global de hoy salía 68,7%; medida contra empresas sale **53,5%**. Buena parte de aquella
descalibración aparente era el desajuste de definición. El defecto de fondo no cambia: el
53,5% es la media de errores que se cancelan.

Y **`sigma` sale de la fórmula**. El nivel de una empresa es `mu + u_f`, con varianza `τ²`;
`σ²` separa a dos personas de la misma nómina y no mueve el nivel de la empresa. La banda
de empresas es `τ_c² + 1/W`.

```
                          cob50   cob80   pin.25   pin.75   pin.medio   % gente
A hoy (norm, glob, +σ)    53.5%   76.1%   0.1252   0.1329    0.1290        —
B norm, τ_c, sin σ        50.6%   76.2%   0.1168   0.1297    0.1233        —
D empírico F>=5           49.0%   77.4%   0.1119   0.1278    0.1199      92.4%
D empírico F>=10          49.4%   78.0%   0.1133   0.1281    0.1207      80.6%
D empírico F>=20          49.6%   77.8%   0.1139   0.1285    0.1212      69.3%
```

Deformación entre quintiles de dispersión: **50,5 → 13,5 → 4,3 puntos**.

**Umbral elegido: 10.** F≥5 gana el pinball por un 0,7% que casi seguro es ruido —no hay
intervalo para esa diferencia— y F≥10 gana las dos coberturas (49,4% contra 49,0%; 78,0%
contra 77,4%), cubre al 80,6% de la gente y está más lejos del dato crudo.

`VENDEDOR`, que fallaba en `04`, era efectivamente el desajuste de definición: contra
empresas su banda real es $482–$765, no $482–$520.

## `06` — la etiqueta de confianza pasa a medir el centro

La etiqueta comparaba el ancho de la banda contra el suelo del cargo, o sea contestaba
*"¿qué tan ancho es el mercado?"* — que **ya lo dice la banda**. Lo que falta saber es si el
número del medio es fiable, y eso es la varianza de **nuestra** estimación:

```
directo       var_centro = 1/W
por analogía  var_centro = Σ(peso²/W) + Σ(peso·dist) + penal_nivel
```

Validado estimando la referencia sobre **dos mitades disjuntas de empresas** y midiendo
cuánto se separan:

```
                    Spearman con el movimiento real
hoy (ancho/suelo)          +0,367
nueva (1/W)                +0,576

            HOY                      NUEVA (1/W)
etiqueta  celdas   mueve           celdas   mueve
ALTA      100,0%   18,0%            17,6%    3,8%
MEDIA       0,0%     —              45,5%   13,3%
BAJA        0,0%     —              37,0%   31,8%
```

La vieja mete el 100% en ALTA. La nueva separa 8 a 1.

**Cortes en dólares y no en veces-el-suelo**, porque la pregunta ya tiene unidades: las
decisiones salariales se mueven en escalones de ~5%. ALTA ≤5%, MEDIA ≤15%.

**Límite medido:** `1/W` se queda **corto**, de un 15% a un 40% según el tramo (obs/pred va
de 0,96 en el primer decil a 1,42 en el último). Ordena bien pero es optimista; la causa
probable es que el modelo supone la celda homogénea y `CONTADOR` mezcla empresas grandes y
pequeñas. No se corrige con un factor porque ese factor no está medido.

En la nómina de demo el reparto pasa de 90,6/9,4/0 a **81,2/9,4/9,4**, y aparece la
separación que la regla vieja no podía dar:

```
GERENTE GENERAL   banda ±95%, confianza ALTA    <- mercado ancho, centro bien conocido
ANALISTA DE RIESGO CREDITICIO   BAJA (44,5%)    <- por analogía, es una conjetura
```

## `07`–`08` — segmentar por tamaño de empresa: medido dos veces, no paga

Pregunta natural viendo la banda de ±95% de `GERENTE GENERAL`: si sabemos el **tamaño** de
la empresa (`segmento`), el **sector** (`ciiu_n1`) y la **provincia**, ¿no conviene
condicionar por ahí y estrechar la banda?

**`07` — segmentar todo.** Diseño jerárquico: celda `cargo × segmento` cuando aguanta, si
no se cae a `cargo`.

```
definición          cob50   cob80   pinball   ancho   incert   usa celda fina
cargo (hoy)         50.3%   77.8%   0.1255    28.2%   10.4%       53.9%
cargo × tamaño      49.9%   76.2%   0.1284    27.5%   12.7%       45.7%
cargo × sector      49.8%   76.0%   0.1289    27.3%   13.2%       39.3%
cargo × provincia   49.8%   76.2%   0.1288    27.4%   12.6%       44.0%
```

**Pierde en los tres.** La banda se estrecha 0,7 puntos y la incertidumbre del centro sube
2,3. El tamaño casi no explica el *ancho*.

**`08` — segmentar sólo donde compense.** Doble partición anidada de empresas: `tr_a`
ajusta, `tr_b` decide cargo a cargo por pinball, `ts` puntúa una sola vez.

```
variante                     cargos   pinball   ancho   incert
cargo (hoy)                       0   0.1255    28.2%   10.4%
cargo × tamaño SIEMPRE       45,021   0.1284    27.5%   12.7%
cargo × tamaño SELECTIVO         93   0.1253    27.9%   10.9%
PLACEBO (selección al azar)     118   0.1258    28.1%   10.9%
```

**Tampoco.** −0,0002 contra hoy, −0,0005 contra el placebo. Y el aviso más duro: **el
placebo eligió más cargos (118) que la señal real (93)**. A nivel de cargo individual la
decisión está dominada por ruido.

**Pero la regla acierta en QUÉ cargos elegir**, que es lo interesante:

```
GERENTE GENERAL       365 emp   gana +0.0177   SEGMENTA
CONTADOR              407 emp   gana +0.0076   SEGMENTA
CHOFER                606 emp   gana −0.0015   no
AUXILIAR DE LIMPIEZA  209 emp   gana −0.0006   no
```

Elige los que la teoría predice y rechaza los que no. El agregado no se mueve porque esos
cargos son pocos. Conclusión: **no automatizar**, pero una lista corta y explícita de cargos
altos sí es defendible.

## Lo que estas dos mediciones NO cubren, y parece más grave

El pinball evalúa la **banda**, que mezcla centro y anchura. El problema que asoma en `07`
es del **centro**:

```
GERENTE GENERAL en empresa PEQUEÑA
  banda de su segmento:  $1,011 – $2,330
  referencia que damos:  $3,032        <- fuera de su banda ENTERA
```

A una empresa pequeña le decimos que paga un 40% por debajo del mercado cuando entre sus
pares está en la mitad de arriba. El agregado no lo ve porque **el 56% de los datos son
empresas GRANDES** (y el 26% no tiene segmento asignado), así que la referencia acierta
donde está la masa.

Es una pregunta distinta de todo lo medido hasta aquí y está sin medir.
