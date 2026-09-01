# El producto

De la nómina de un cliente a un Excel con referencias de mercado.

```bash
benchmarking referenciar --nomina cliente.xlsx --salida referencias.xlsx
```

Autodetecta las columnas de cargo y de sueldo. Si hay sueldos, además compara contra el
mercado; si no, sólo emite referencias.

## Qué devuelve

**Hoja `detalle`**, una fila por persona:

| columna | qué es |
|---|---|
| `referencia`, `p25`, `p75` | la referencia de mercado y su rango |
| `confianza` | ALTA / MEDIA / BAJA |
| `base` | datos directos, o por analogía |
| `vs_mercado` | cuánto se aleja del mercado |
| `vs_politica_interna` | cuánto se aleja de la política de su **propia** empresa |

**Hoja `por_puesto`**: agregado por cargo, ordenado del más bajo al más alto.

## Las tres decisiones de diseño

**Se responde siempre.** Un cliente sin referencia no se queda quieto: inventa un número.
Se compite contra eso, no contra el silencio. Por eso `confianza` no es opcional — es lo
único que separa "esto lo sé" de "esto lo supongo".

**La confianza sale del intervalo, no del conteo de empresas.** Contar engaña: un puesto
con 14 empresas salía igual de "ALTA" que uno con 823. Y el corte no es un porcentaje
fijo sino **cuántas veces más ancho que el suelo irreducible** — con `tau` y `sigma` se
sabe cuál es el intervalo más estrecho posible, y un umbral absoluto no se traslada a
otro mercado.

**Un vecino cercano gana a uno popular.** Cada vecino se trata como una medición
imperfecta con varianza `1/W + lambda*(1-sim)`. La primera parte es su error de medición
y **se cancela al promediar**; la segunda es la distancia semántica, que es un **sesgo
compartido y no se cancela**. Sin esa separación, promediar 25 vecinos lejanos producía
intervalos estrechos para puestos que el sistema no conoce.

`lambda` se estima de los datos, no se elige.

## Los cuatro casos que fijan el comportamiento

Salen de mirar vecindarios reales y están en los tests:

| caso | qué fallaba | qué debe pasar |
|---|---|---|
| `OPERADOR DE PARQUEADERO` | tenía `OPERADOR DE PARQUEADEROS` (sim 0,989) delante y hacía caso a `OPERADOR DE EXCAVADORA` porque tenía más datos | el casi idéntico manda |
| `LOTERO` | sin vecindario real, se agarraba a `TESORERO` por la terminación `-ERO` | intervalo ancho y confianza BAJA |
| `SUPERVISOR DE CAJA` | se promediaba con `AUXILIAR DE CAJA` — los embeddings son ciegos a la jerarquía (D-012) | **pendiente**: clasificador de nivel |
| `ASESOR CENTRO DE ATENCION AL CLIENTE` | vecindario perfecto y aun así falla | irreducible: es `tau`, el efecto empleador |

## Rendimiento

| | |
|---|---|
| Construir la base | ~90 s (más el embebido inicial de 65.081 títulos, una vez) |
| Con base guardada | ~35 s, de los cuales ~20 son arrancar Python e importar `vertexai` |
| Tamaño de la base | 187 MB — 65.081 vectores de 768 dimensiones |

La base se reconstruye **por lotes cuando cambian los datos**, no cuando llega un cliente.

## Lo que falta

- **Adelgazar la base.** 187 MB es mucho para cargar por consulta. Los embeddings se
  pueden guardar en `float16` o reducir con PCA sin perder precisión apreciable.
- **El clasificador de nivel.** Es el tercer caso de la tabla y el que más error queda por
  quitar: un nivel jerárquico vale 2,11x en pago.
- **Verificar el anclaje.** El -12,8% de la comparación interna está medido sobre una sola
  partición y **no ha pasado el contraste pareado**. Las lecturas 1 y 2 son aritmética
  directa y no dependen de él; la de equidad interna sí.

## El límite que hay que decirle al cliente

El empleador explica el **81%** de lo que no se puede predecir (`tau = 0,29`). Esto da el
**mercado**, no la política salarial de una empresa concreta — salvo que esa empresa
entregue su nómina, que es justamente lo que habilita la lectura de equidad interna.
