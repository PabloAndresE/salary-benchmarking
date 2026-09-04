# El producto

De la nómina de un cliente a un Excel con referencias de mercado.

```bash
benchmarking referenciar --nomina cliente.xlsx --salida referencias.xlsx
```

Autodetecta las columnas de cargo y de sueldo. Si hay sueldos, además compara contra el
mercado; si no, sólo emite referencias.

## Qué devuelve

**Hoja `detalle`**, una fila por persona. Todo en dólares o en porcentaje — nada en escala
logarítmica:

| columna | qué es |
|---|---|
| `referencia` | lo que paga la empresa que está en el medio del mercado |
| `p25`, `p75` | la banda: **la mitad de las empresas paga entre esos dos números** |
| `p10`, `p90` | la banda ancha, el 80% central |
| `confianza` | ALTA / MEDIA / BAJA — qué tan bien se conoce la **referencia** |
| `incert_centro` | cuánto puede moverse la referencia, en tanto por uno |
| `ancho_rel` | media anchura de la banda, en tanto por uno |
| `base` | `datos directos` o `por analogia` |
| `empresas`, `personas` | respaldo real, sin contar dos veces las grafías del mismo puesto |
| `vs_mercado` | cuánto se aleja del mercado |
| `vs_politica_interna` | cuánto se aleja de la política de su **propia** empresa |

**Hoja `por_puesto`**: agregado por cargo, ordenado del más bajo al más alto.

## Las cuatro decisiones de diseño

**Se responde siempre.** Un cliente sin referencia no se queda quieto: inventa un número.
Se compite contra eso, no contra el silencio. Por eso `confianza` no es opcional — es lo
único que separa "esto lo sé" de "esto lo supongo".

**Las grafías del mismo puesto se juntan antes de nada.** El catálogo trae seis variantes
de espaciado de `ASISTENTE / AYUDANTE / AUXILIAR ADMINISTRATIVO`, y una con errata. Cada
una era una celda delgada que se contestaba por analogía… contra sus propias hermanas.
Fusionarlas sube la cobertura directa del **57,7% al 64,1%** sin costar precisión.

El **cómo** importa y está medido: por **enlace completo**, no simple. Union-find encadena
`A~B~C~D` hasta juntar `ASISTENTE CONTABLE` con `AUXILIAR DE LIMPIEZA` en un grupo de 1.758
títulos, y empeora el error un +0,0154. Con enlace completo el grupo mayor baja a 27 y el
efecto se da vuelta: −0,0030 (D-015).

**La banda habla de EMPRESAS, y la confianza del CENTRO.** Son dos preguntas distintas y
antes se contestaba la misma dos veces:

```
banda      ->  ¿cuánto varía el mercado?      GERENTE GENERAL: $1,516 – $5,766
confianza  ->  ¿qué tan firme es el número?   ±3,6% con 767 empresas: ALTA
```

Que una banda enorme venga con confianza ALTA no es contradicción: el mercado es amplísimo
*y* lo sabemos con seguridad. La banda no lleva `sigma` —la dispersión dentro de una
nómina no mueve el nivel *de* la empresa— y sale de **cuantiles empíricos** cuando hay 10+
empresas, porque ninguna normal describe a la vez el pico de `AUXILIAR DE LIMPIEZA`
(p25 $475, p75 $485) y la cola de `GERENTE GENERAL` ($500 a $13.712). Ver D-016 y D-017.

**Un vecino cercano gana a uno popular.** Cada vecino se trata como una medición imperfecta
con varianza `1/W + lambda*(1-sim)`. La primera parte es su error de medición y **se cancela
al promediar**; la segunda es la distancia semántica, que es un **sesgo compartido y no se
cancela**. Sin esa separación, promediar 25 vecinos lejanos producía intervalos estrechos
para puestos que el sistema no conoce.

`lambda`, `tau_c` y `sigma_c` se estiman de los datos. **No hay un solo hiperparámetro
elegido a mano en el estimador.**

## Los casos que fijan el comportamiento

Salen de mirar vecindarios reales y están en los tests:

| caso | qué fallaba | qué pasa ahora |
|---|---|---|
| `OPERADOR DE PARQUEADERO` | tenía `OPERADOR DE PARQUEADEROS` (sim 0,989) delante y hacía caso a `OPERADOR DE EXCAVADORA` porque tenía más datos | el casi idéntico manda; y además las cuatro grafías se fusionan |
| `LOTERO` | sin vecindario real, se agarraba a `TESORERO` por la terminación `-ERO` | intervalo ancho y confianza BAJA |
| `SUPERVISOR DE CAJA` | se promediaba con `AUXILIAR DE CAJA` — los embeddings son ciegos a la jerarquía (D-012) | **resuelto**: corrección de escalón, −0,0130 (D-013) |
| `GERENTE GENERAL` | banda de ±24,5% con sello ALTA; sólo 20 de cada 100 empresas caían dentro | banda de su mercado real, 47% dentro |
| `ASESOR CENTRO DE ATENCION AL CLIENTE` | vecindario perfecto y aun así falla | irreducible: es `tau`, el efecto empleador |

## Rendimiento

| | |
|---|---|
| Construir la base | ~2 min (más el embebido inicial de 65.081 títulos, una vez) |
| Con base guardada | ~35 s, de los cuales ~20 son arrancar Python e importar `vertexai` |
| Tamaño de la base | 179 MB — lo dominan 65.081 vectores de 768 dimensiones |

La base se reconstruye **por lotes cuando cambian los datos**, no cuando llega un cliente.

## Herramientas de inspección

```bash
research/herramientas/explicar_puesto.py "LABORATORISTA"    # de dónde sale la referencia
research/herramientas/banda_por_tamano.py "LABORATORISTA"   # ¿le afecta el tamaño?
```

La primera muestra la cadena entera —grafías fusionadas, vecinos consultados, respaldo
real— y funciona con títulos que no estén en la base. **Las dos destaparon fallos que las
métricas agregadas no veían**, así que conviene usarlas antes de creerse un promedio.

## Lo que falta

- **Segmentar el centro por tamaño de empresa en los cargos altos.** Medido que funciona
  (`GERENTE GENERAL` pasa de −56%/+82% a −12%/+18%) pero **no montado**: exige pedirle el
  segmento al cliente y fijar la lista de cargos. Ver D-018.
- **Adelgazar la base.** `float16` o PCA sobre los embeddings, que son casi todo el peso.
- **Verificar el anclaje.** El −12,8% de la comparación interna está medido sobre una sola
  partición y **no ha pasado el contraste pareado**. Las lecturas 1 y 2 son aritmética
  directa y no dependen de él; la de equidad interna sí.
- **La escalera de antigüedad.** `JUNIOR`/`SENIOR`/`I`/`II`/`III` es una notación distinta
  de la de mando y el eje de nivel no la ve: `LABORATORISTA JR.` $497 contra
  `LABORATORISTA SENIOR` $938. Sin medir.

## Los límites que hay que decirle al cliente

**El empleador explica el 81%** de lo que no se puede predecir (`tau = 0,29`). Esto da el
**mercado**, no la política salarial de una empresa concreta — salvo que esa empresa
entregue su nómina, que es justamente lo que habilita la lectura de equidad interna.

**La confianza es optimista.** `1/W` se queda corto entre un 15% y un 40% según el tramo
(obs/pred va de 0,96 en el primer decil a 1,42 en el último). Ordena bien —separa 8 a 1 lo
fiable de la conjetura— pero el número que declara es un suelo, no una cota.

**La referencia está sesgada por tamaño en los cargos altos**, mientras D-018 no se monte:
a una empresa pequeña se le dice que su gerente general cobra un 56% por debajo del
mercado cuando entre sus pares está bien. En los cargos técnicos y de base no pasa.
