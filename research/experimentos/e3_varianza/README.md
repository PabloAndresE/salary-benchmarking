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
