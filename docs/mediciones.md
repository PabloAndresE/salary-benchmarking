# Mediciones sobre los datos reales

Todas las cifras medidas durante el desarrollo, con su fecha, su alcance y cómo se obtuvieron.
Sirve para dos cosas: que cualquier número citado en la tesis sea trazable, y que no se vuelva a
medir lo ya medido.

**Convención:** salvo que se diga otra cosa, "personas" es el registro persona-año, que es la unidad
de la fuente (una misma persona reaparece en años sucesivos).

**Fuentes:**
`act-actuafast.actuafastv2.estudios_actuariales` (origen) ·
`act-cicd-stage-prueba.benchmarking_tesis.nomina_features` (procesado) ·
API de plantillas de ActuaFast · catálogo sectorial del IESS.

---

## 1. El universo de origen

**Fecha:** 2026-08-05 · **Alcance:** `es_ultima_version`, todos los años

| Año | Filas | Empresas | Cargo utilizable | Sueldo > 0 |
|---|---|---|---|---|
| 2025 | 617.557 | 5.985 | **96,4%** | 93,7% |
| 2024 | 722.976 | 6.137 | 77,8% | 72,1% |
| 2023 | 644.679 | 5.917 | 64,6% | 78,4% |
| 2022 | 609.477 | 5.887 | 60,4% | 78,2% |
| 2021 | 565.277 | 5.846 | 60,9% | 77,5% |
| 2020 | 547.992 | 5.617 | 54,8% | 66,3% |
| 2019 | 554.767 | 5.700 | 13,9% | 59,5% |
| 2018 | 381.000 | 5.345 | 0,5% | 56,2% |
| 2017 | 20.018 | 1.470 | 0,5% | 52,6% |
| 2016 | 179 | 5 | 0,0% | 36,3% |
| **Total** | **~4,66 M** | ~10.500 | | |

**Estudios:** 47.944 con `es_ultima_version`, `numero_proceso` e `id_version` no nulos.

**Lectura.** La ausencia de cargo es en buena medida herencia de los estudios antiguos: el "40% sin
cargo" del EDA es un promedio que esconde una tendencia fuerte. En 2025 solo falta el 3,6%.

### Solapamiento entre 2024 y 2025

**Fecha:** 2026-08-05

| | |
|---|---|
| Empresas en 2025 | 5.985 |
| Empresas en 2024 | 6.138 |
| **Empresas en ambos** | **5.238 (87,5% de las de 2025)** |
| Personas en 2025 | 598.345 |
| **Personas en ambos** | **478.522 (80,0%)** |

**Lectura.** No son dos años independientes: es el mismo panel medido dos veces. Eso desaconseja
juntarlos para inflar el n, y a la vez habilita el **test-retest** como instrumento de fiabilidad
(§4).

---

## 2. Disponibilidad de plantillas (la fuente de la composición)

**Fecha:** 2026-08-05 · **Método:** sondeo directo a la API sobre 160 estudios muestreados

| Año | Plantilla disponible |
|---|---|
| 2025 | **25/25 (100%)** |
| 2024 | 26/29 (90%) — 1×404, 2×400 |
| 2023 | **0/26** |
| 2022 | 0/33 |
| 2021 | 0/18 |
| 2020 | 0/16 |
| 2019 | 0/13 |

**Lectura.** La composición existe **solo en 2024–2025**. Es el hecho que fija el universo de
ajuste (D-003) y no admite ampliación hacia atrás.

### Concurrencia óptima de descarga

**Fecha:** 2026-08-06 · **Método:** 20 estudios de 2025 por nivel, con el cliente ya arreglado

| Hilos | ok | perdidos | peticiones HTTP | estudios/s |
|---|---|---|---|---|
| 2 | 20 | 0 | 20 | 0,54 |
| **4** | **19** | **0** | **20** | **0,80** |
| 6 | 17 | 3 | 41 | 0,28 |
| 8 | 13 | 7 | 67 | 0,16 |

**Lectura.** A partir de 6 hilos el servidor corta conexiones, los reintentos se multiplican y el
rendimiento **se desploma**. El valor anterior (8) no solo perdía el ~80% de las plantillas:
**también era 5× más lento**.

### Enlace por cédula: el sesgo geográfico

**Fecha:** 2026-08-06 · **Método:** 6 estudios de 2025, 1.397 personas

| Estudio | Personas | Antes | Después | Techo |
|---|---|---|---|---|
| 143255 | 527 | 75,1% | 90,5% | 90,5% |
| 140179 | 225 | 18,7% | 91,1% | 91,1% |
| 139370 | 309 | 91,6% | 93,9% | 93,9% |
| 141103 | 66 | **7,6%** | 93,9% | 93,9% |
| 140828 | 201 | 30,3% | 87,6% | 87,6% |
| 142728 | 69 | 55,1% | 66,7% | 66,7% |
| **Total** | **1.397** | **59,1%** | **89,9%** | **89,9%** |

**Lectura.** La plantilla guarda las cédulas sin el cero inicial; la base sí lo conserva. El enlace
por texto exacto fallaba en **toda cédula de las provincias 01–09**. La dispersión del "antes"
(7,6% a 91,6%) es la firma del sesgo: depende de cuánta gente de esa empresa es de esas provincias.
Tras el arreglo se alcanza el techo exacto en los seis casos.

**Verificación sobre el universo** (2026-08-06, 576.539 filas de 2024–25):

| | Con composición |
|---|---|
| Provincias 01–09 (cédula con cero inicial) | 79,5% |
| Provincias 10–24 | 81,3% |

Diferencia de 1,8 puntos: ruido. El sesgo desapareció.

### Efecto combinado de los arreglos

| | Plantillas descargadas | Personas enlazadas | Filas con composición |
|---|---|---|---|
| Antes | 4,6% | 59,1% | **~2,7%** |
| Después | 99,8% | 89,9% | **86,7%** *(primer lote real)* |

Factor ~32× sobre la variable que el diseño define como eje de segmentación.

---

## 3. El año 2025 completo

**Fecha:** 2026-08-06 · **Alcance:** `anio_valoracion = 2025`, tabla procesada

| | |
|---|---|
| Filas | **617.557** (cuadra exacto con el origen) |
| Estudios | **5.985** (cuadra exacto) |
| Empresas | 5.985 |
| Personas (`id_hash` distintos) | 598.345 |
| Con composición | **80,8%** |
| `en_clean` | 94,4% |
| Con cargo | 96,4% |
| Sin cruce SCVS | 26,1% |

*(2024 completo: 722.976 filas, 6.167 estudios, 62,9% con composición, 80,1% `en_clean`, 25,2% sin SCVS.)*

### Distribución de la composición

**Alcance:** 486.814 filas de 2025 con composición y `en_clean`

| | |
|---|---|
| Todo fijo (≥99%) | 30,1% |
| Variable leve (90–99% fijo) | 16,4% |
| Variable medio (70–90%) | 32,3% |
| **Variable alto (<70%)** | **21,2%** |
| Con comisiones >5% | **17,2%** |
| Con horas extras >5% | 40,6% |
| Con otros >5% | 17,8% |

> ⚠️ **Corrige una medición anterior.** Sobre 4.325 filas de 41 empresas —los estudios que
> sobrevivieron al bug de descargas, que no eran muestra de nada— salía comisiones 4,6% y variable
> alto 5,7%. Con el año completo, casi cuatro veces más. **No usar las cifras de la muestra pequeña.**

### Descomposición de varianza: ¿política de empresa o señal de rol?

**Alcance:** 5.269 empresas con ≥5 personas, 485.084 personas

| Variable | η² empresa | Varía **dentro** de la empresa |
|---|---|---|
| % horas extras | **0,498** | 50,2% |
| % comisiones | 0,388 | 61,2% |
| log del total | 0,388 | 61,2% |

> ⚠️ **Corrige una medición anterior.** Con 41 empresas salía 0,281 para extras. El valor real es
> **0,498**: la mitad de la variación en horas extras es política del empleador, y **supera** al
> efecto empresa sobre el propio salario.

**Consecuencias.** La residualización contra empleador×sector pasa de conveniente a
**imprescindible** para el bloque de extras. Y las comisiones se comportan mejor que las extras
(61,2% intra-empresa), así que merecen peso propio en vez de diluirse en un bloque único.

**Salvedad pendiente** (señalada por el tribunal): el sesgo de movilidad limitada implica que estos
η² **probablemente están sobreestimados**. Hay que cuantificarlo.

---

## 4. Test-retest: ¿la composición es rasgo o circunstancia?

**Fecha:** 2026-08-07 · **Alcance:** 333.752 personas con composición en 2024 **y** 2025

| Variable | Correlación entre años |
|---|---|
| % horas extras | **0,817** |
| % comisiones | **0,884** |
| % fijo | 0,832 |

**Lectura.** Alta. La composición del pago de una persona **se mantiene entre años**: es un rasgo
estable, no ruido mensual. Cierra la duda que D-003 dejó abierta —*"¿ese 50% intra-empresa es
sistemático por rol o es circunstancia individual?"*— a favor del diseño.

Es además evidencia de fiabilidad más fuerte que cualquier ARI de bootstrap, porque la re-medición
es **real**, no simulada.

---

## 5. La etiqueta CARGO

**Fecha:** 2026-08-05/07 · **Alcance:** 2025, `sueldo > 0`, cargo no vacío ni numérico

| | |
|---|---|
| Etiquetas distintas | **55.920** |
| Personas | 576.862 |
| Cobertura de las 50 más frecuentes | **25,6%** |
| Etiquetas con **una sola** persona | 32.388 (58% de las etiquetas) |
| Etiquetas con menos de 3 personas | **71,2%** |

**Lectura.** Podar `CARGO` a sus top-50 para igualar cardinalidad dejaría a **429.000 personas
(74,4%) en una única celda "otros"**. No es `CARGO` con menos celdas: es un baseline degradado por
construcción. Es la razón de D-005.

### Las etiquetas más pobladas y su dispersión

| # | Cargo | Personas | CV |
|---|---|---|---|
| 1 | TRABAJADOR AGRICOLA | 19.974 | 0,29 |
| 2 | DOCENTE | 10.932 | **0,62** |
| 3 | TRABAJADOR EN GENERAL | 6.415 | 0,46 |
| 4 | VENDEDOR | 6.144 | **0,79** |
| 5 | ASESOR COMERCIAL | 5.622 | **0,55** |
| 6 | GUARDIA | 4.578 | 0,17 |
| 11 | OPERARIO | 3.777 | 0,17 |
| 12 | PERCHADOR (A) | 3.629 | **0,10** |

**Lectura.** Las más frecuentes **no** son homogéneamente malas: conviven las peores (VENDEDOR 0,79)
con las mejores (PERCHADOR 0,10). Son los "dos mundos" del EDA, y es la razón por la que el
escenario más probable es la **complementariedad** (D-004, escenario C).

### CARGO como método: su cobertura

**Alcance:** 2024–2025, `en_clean`, con cargo · **Método:** donantes con leave-company-out

| Regla | Cobertura |
|---|---|
| ≥5 donantes | **66,0%** |
| ≥5 donantes **y** ≥3 empresas | **60,5%** |

**Lectura.** `CARGO` no puede dar referencia para **un tercio de la gente que sí tiene etiqueta**.
Sumando el 3,6% sin etiqueta, se acerca al 37%. Es el argumento de cobertura del escenario B,
medido antes de empezar. Exigir ≥3 empresas cuesta 5,5 puntos.

### Media contra mediana por celda

**Alcance:** 498.653 personas, 10.270 celdas de `CARGO` con ≥5 personas, en log

| | |
|---|---|
| Diferencia media ponderada por personas | **0,0533** |
| Mediana de las diferencias | 0,0292 |
| Percentil 90 | 0,1428 |
| Máximo | 1,3606 |

**Lectura.** Con un error esperado del orden de 0,30, es un sexto de la magnitud medida: **no es
despreciable**. Y no es neutral entre métodos — la diferencia aparece en las celdas mezcladas, así
que la media **castiga más a las particiones que mezclan**, que es `CARGO`. Sería un sesgo a favor
de la hipótesis propia. Es la razón de que la métrica primaria use mediana.

---

## 6. Tamaño de empresa en la muestra

**Fecha:** 2026-08-07 · **Alcance:** 2025, `en_clean`, `sueldo > 0`

| Personas en la muestra | Empresas | Personas | % |
|---|---|---|---|
| menos de 5 | 587 | 1.543 | 0,3% |
| 5 a 9 | 761 | 5.299 | 0,9% |
| 10 a 29 | 1.650 | 29.965 | 5,3% |
| 30 a 99 | 1.700 | 95.226 | 16,8% |
| **100 o más** | 1.245 | 433.173 | **76,6%** |

**Lectura.** Justifica residualizar contra la media de la empresa sin encogimiento (D-006 #3): con
el 76,6% de la gente en empresas de 100 o más, la corrección del modelo mixto apenas mueve nada.

### Estratos para el split

**Alcance:** 2025, `en_clean`, estrato = segmento SCVS × sección CIIU

| | |
|---|---|
| Estratos | 70 |
| Con menos de 5 empresas | 11 |
| **Que desaparecerían del test sin la regla de mínimo 1** | **5** |
| Tamaño del test con la regla | 20,0% |
| Sin la regla | 19,9% |

---

## 7. Cuarentena

**Fecha:** 2026-08-07 · **Alcance:** 2024–2025

| Motivo | 2025 | 2024 |
|---|---|---|
| `cargo_placeholder` | 24.121 | **80.800** |
| `cargo_jubilado` | 4.985 | 1.800 |
| `sueldo_bajo_sbu` | 4.883 | 2.977 |
| `edad_fuera_rango` | 205 | 158 |
| `sueldo_no_positivo` | 195 | 125 |
| **Tasa total** | **5,6%** | **19,9%** |

**Lectura.** La diferencia entre años es casi toda `cargo_placeholder`, coherente con el 96,4% de
cargo capturado en 2025 contra el 77,8% de 2024.

De las 104.921 filas con `cargo_placeholder`, solo **5.057 (4,8%)** tienen composición y sueldo
válidos, así que el debate sobre si excluirlas del modelado afecta a poca gente — aunque la política
sigue mal planteada: "no tiene etiqueta utilizable" es precisamente a quien sirve el arquetipo.

### Valores negativos

| | |
|---|---|
| Filas con `total ≤ 0` | 566 — **la cuarentena las atrapa todas** ✅ |
| Filas con algún rubro negativo | 60 |
| **De ellas, en `en_clean` (antes del arreglo)** | **57** |

Corregido: `composicion_negativa` es ahora motivo de cuarentena. Importa porque la transformación
ILR toma logaritmos de las partes y un negativo la invalida.

---

## 8. Compuerta de E5 (semi-supervisado)

**Fecha:** 2026-08-07 · **Alcance:** 2024–2025, `en_clean` ·
**Grupo-semilla:** etiqueta en ≥3 empresas con ≥10 personas

| Especificidad | Grupos | Cobertura |
|---|---|---|
| 1 palabra | 666 | 19,6% |
| 2 palabras | 1.161 | 17,0% |
| **3 o más palabras** | **2.511** | **29,0%** |

**Compuerta pre-registrada:** ≥10 grupos cubriendo ≥15%. **Pasa por dos órdenes de magnitud.**

> ⚠️ **Pero la revisión posterior invalidó el uso previsto.** Estos grupos-semilla unen personas con
> **la misma cadena de texto**, así que no pueden arbitrar entre el bloque de texto y el de
> composición (ver `revision_jueces.md` §1). La compuerta pasa; el criterio hay que rehacerlo con
> must-links entre **cadenas distintas**.

---

## 9. Catálogo sectorial del IESS

**Fecha:** 2026-08-07 · **Fuente:** PDF de códigos sectoriales del IESS, 50 páginas, extraído con
`pdfplumber`

| | |
|---|---|
| Filas | 2.242 |
| Nombres de cargo distintos | 1.724 (1.715 normalizados) |
| Comisiones sectoriales | 22 |
| Ramas de actividad | 118 |
| Nombres presentes en más de una comisión | 32 de 1.715 |

Columnas: `CODIGO COMISION`, `NOMBRE DE LA COMISION`, `RAMA`, `CODIGO DEL CARGO`,
`NOMBRE DEL CARGO`, `MINIMO SECTORIAL`.

**No incluye** la estructura ocupacional (A / B1–B3 / C1–C3 / D1–D2 / E1–E2) ni la columna de
comentarios con los sinónimos: **esas están en el Acuerdo MDT-2019-395** (249 páginas), pendiente de
parsear. Son las dos piezas más valiosas.

### Cruce con las etiquetas propias

**Alcance:** 68.506 etiquetas distintas de 2024–2025 `en_clean`, 1.136.631 personas

| Emparejamiento | Etiquetas | Personas |
|---|---|---|
| Exacto | 1,1% | **13,5%** |
| Similitud de caracteres ≥ 0,95 | 2,0% | 15,3% |
| ≥ 0,80 | 6,4% | 23,1% |
| ≥ 0,70 | 13,9% | 38,0% |
| ≥ 0,60 | 26,3% | 55,5% |

**Y el emparejamiento difuso por caracteres es peligroso** — invierte la jerarquía:

```
AUXILIAR DE SERVICIOS GENERALES → JEFE DE SERVICIOS GENERALES   0,79   ✗
ASISTENTE ADMINISTRATIVO        → JEFE ADMINISTRATIVO           0,79   ✗
AGENTE DE SEGURIDAD             → JEFE DE SEGURIDAD             0,72   ✗
TRABAJADOR AGRICOLA             → TRABAJADOR ACUICOLA           0,66   ✗
```

**Lectura.** Las palabras de jerarquía (auxiliar / asistente / jefe / supervisor) comparten casi
todos los caracteres con su opuesto. Cualquier emparejamiento contra el catálogo debe tratarlas
como **restricción dura**, no como similitud blanda. Es evidencia directa, sobre datos propios, de
por qué TF-IDF de caracteres no sirve para este problema.

---

## 10. `cargo` frente a `cargo_plantilla`: son la misma columna

**Fecha:** 2026-08-11 · **Alcance:** 4.323 personas de 100 estudios de 2025, `en_clean`, con ambas
columnas presentes

| | |
|---|---|
| Cadenas idénticas | **100,0%** |
| Cadenas distintas | 0,0% |
| Pares distintos | **0** |

Inspección directa: `cargo`, `cargo_norm` y `cargo_plantilla` coinciden carácter a carácter,
incluidas cadenas largas de tabla sectorial.

**Lectura.** No hay segunda etiqueta independiente: el estudio actuarial se construye a partir de la
plantilla del cliente, así que el campo `cargo` es una copia. **Invalida la premisa de D-008** y deja
al catálogo sectorial como única vía viable para must-links entre cadenas distintas. Ver **D-010**.

**Confirmado por el equipo (2026-08-11).** ActuaFast lo ratificó de forma independiente: son el
mismo campo, porque el estudio se construye a partir de la plantilla. **Cerrado** — no queda
pendiente reconfirmarlo sobre más estudios.

**Y una observación de paso:** las etiquetas más pobladas son literalmente entradas de tabla
sectorial — `TRABAJADORES DE PRODUCCION: PESADORES DE CAJAS, ANOTADORES Y ESTIBADORES DE CAJAS PARA
CONGELACION, TOLVERO, CLASIFICACION`. Confirma que el vocabulario del `CARGO` viene del catálogo del
IESS, tal como decía el handoff, y refuerza el valor de emparejar contra él.

---

## 11. El estimador de la referencia (D-011), sobre data sintética

**Fecha:** 2026-08-11. **Alcance:** `tests/sintetico.py`, 400 empresas, 72.000 filas, 4 roles,
tamaños de empresa desiguales. Split por empresa al 25%.

Validación del estimador de la Tarea 4 antes de tocar datos reales. El generador construye el
efecto empresa con `sd = 0,24` y el ruido individual con `sd = 0,18`; el estimador de momentos
no los conoce.

| Cantidad | Valor verdadero | Estimado |
|---|---|---|
| `tau` (entre empresas, dentro de celda) | 0,24 | **0,2432** |
| `sigma` (intra empresa, dentro de celda) | 0,18 | **0,1806** |

**Recupera los dos parámetros.** Es la comprobación que faltaba: los pesos inverso-varianza son
correctos sólo si `tau2` y `sigma2` lo son, y su efecto vive en el tercer decimal del resultado
final, donde no se detectaría por inspección.

### La cota de pesos funciona

| | |
|---|---|
| Tamaños de grupo (celda × empresa) | min 5, max 85 — **ratio crudo 17×** |
| Ratio de pesos efectivo | **1,103** |
| Cota teórica `1 + sigma2/tau2` | 1,551 |

**17× de diferencia en tamaño se convierte en 1,10× de diferencia en voz.** Ése es el arreglo de
D-011: se elimina la dominancia del empleador grande sin descartar el voto de las empresas
pequeñas, y sin elegir ningún hiperparámetro.

### Coste

| Operación | Tiempo | Escala |
|---|---|---|
| `componentes_varianza` | 0,07 s | 54.960 filas |
| `predecir` | 0,09 s | 17.040 filas de test |

Extrapolado a 1,3 M de filas: del orden de segundos. La clave es que la referencia se calcula
**una vez por par (celda, empresa)**, no una vez por persona.

### Dos hallazgos de la implementación

1. **Caso degenerado con varianza cero.** Si todos los donantes valen lo mismo, `tau2 = sigma2 = 0`,
   el peso inverso-varianza es `1/0` y `predecir` devolvía NaN **en silencio** — indistinguible de
   una abstención. Imposible en datos reales, trivial de provocar en tests. Corregido con pesos
   uniformes y predictiva de masa puntual.
2. **El suelo de dominancia se activa antes que la ponderación.** Con una empresa aportando 100 de
   106 personas (94%), el método se abstiene y la ponderación nunca entra en juego. No es un
   conflicto —hacen cosas distintas— pero significa que los dos mecanismos hay que probarlos por
   separado, y que en producción la dominancia se resuelve por abstención, no por peso.

---

### El sigma2 global no era una varianza condicional (hallazgo, 2026-08-11)

Al implementar la Tarea 5 se midió que **`sd_pred` apuntaba al revés**. Marco de prueba con
dispersión real variando 12× entre celdas:

| | σ² global | σ²_c encogido |
|---|---|---|
| Rango de `sd_pred` entre celdas | **1,06×** | **2,38×** |
| Correlación de `sd_pred` con el error real | **−0,384** | **+0,656** |
| Correlación de `σ_c` estimado con el real | — | **0,993** |

**Diagnóstico.** Con `tau2` y `sigma2` globales, lo único que hacía variar `sd_pred` entre celdas
era el conteo de donantes — o sea, la "anchura predictiva" era el conteo de donantes disfrazado,
que es exactamente lo que D-011 había quitado. La regla óptima de abstención umbraliza la varianza
**condicional** (Zaoui et al. 2020); una varianza idéntica para todas las celdas no está
condicionada a nada.

**Corrección.** `sigma2_c` por celda con encogimiento empirical-Bayes sobre `log s²_c`, **sin
parámetros libres**: la varianza de muestreo de `log s²_c` es `2/df_c`, así que la varianza entre
celdas sale por momentos y el peso de cada celda es `w_c = V/(V + 2/df_c)`.

`tau2` se deja global: estimar la varianza entre empresas por celda necesita muchas empresas, y en
`CARGO` la celda típica tiene 3–5. Queda como límite declarado del método.

### Coste del bootstrap: de 19,8 horas a 28 minutos

Medido y proyectado a 1,07 M de filas de train con 7 métodos y 400 réplicas:

| Versión | s/réplica | 400 réplicas |
|---|---|---|
| Remuestreo de **filas**, pandas | ~178 | **19,8 h** |
| Remuestreo de **votos**, pandas | ~91 | 10,2 h |
| Remuestreo de votos, **numpy compilado** | **4,2** | **28 min** |

Dos ideas, ninguna aproximada:

1. **El bootstrap remuestrea votos, no filas.** Remuestrear una empresa con reemplazo sólo duplica
   su voto, así que la tabla `(celda, empresa) → voto` se calcula una vez y la réplica es una
   selección de sus filas.
2. **Dentro del bucle no se toca pandas.** Celdas a códigos enteros, tabla pre-ordenada por
   `(celda, voto)`, y el remuestreo ordena **índices** en vez de filas. El cuantil ponderado se
   calcula para todas las celdas a la vez con `bincount`/`searchsorted`.

De paso, `predecir` pasó de 6,22 s a **0,36 s** sobre 27.000 filas con 1.600 celdas: los `groupby`
con `lambda` recorrían los grupos en Python. `ssw` sale ahora de `Σy² − (Σy)²/n`, vectorizado.

Hay un test de equivalencia numérica (`rtol=1e-10`) entre el camino rápido y `predecir_desde_votos`.
Una optimización sin test de equivalencia es una reescritura a ciegas.

**Componentes fijos entre réplicas.** `tau2`, `sigma2` y `sigma2_c` se estiman una vez y no se
remuestrean: vienen de millones de filas, mientras `mu_c` viene de 3–5 empresas y ésa es la
incertidumbre que importa. Es una simplificación declarada.

---

## 12. El marco evaluable, tras cerrar la corrida 2024-2025

**Fecha:** 2026-08-11. **Alcance:** `nomina_features` completa, años 2024 y 2025.
**Fuente:** `research/experimentos/e0_banco/diagnostico_objetivo.py` (Tarea 2b del plan v3).

### La tabla, al cierre de la corrida

| Año | Filas | Estudios | Empresas | Composición | `en_clean` |
|---|---|---|---|---|---|
| 2024 | 722.976 | 6.167 | 6.137 | 62,9% | 76,6% |
| 2025 | 617.557 | 5.985 | 5.985 | 80,8% | 94,4% |

La corrida cerró con código 0 a las 15:20 del 2026-08-11. Quedan además restos de años
anteriores en la tabla (2016–2018 y 2023), sin composición y fuera del marco de evaluación.

### La brecha de composición de 2024 es estructural, no un residuo de los bugs

Se sospechó que la corrida, al reanudar saltando estudios ya escritos, hubiera conservado
lotes anteriores a los arreglos de D-001. **No es el caso:**

| | 2024 | 2025 |
|---|---|---|
| Enlace donde **sí** hay plantilla | **83,8%** | **85,2%** |
| Filas en estudios **sin** plantilla | **25,0%** | 5,2% |

La tasa de enlace es prácticamente idéntica: el arreglo de la cédula funciona igual en los dos
años. Toda la brecha es disponibilidad de plantilla.

### 263 estudios de 2024 llegaron sin plantilla y sin cargo

| Grupo | Estudios | Filas | Tamaño medio |
|---|---|---|---|
| Normal | 5.767 | 540.450 | 94 |
| Sin plantilla, con cargo | 107 | 43.894 | 410 |
| Con plantilla, sin cargo | 30 | 1.645 | 55 |
| **Sin plantilla y sin cargo** | **263** | **136.987** | **521** |

No son dos problemas independientes: es la misma población, y son **los estudios más grandes**
—5,5× la mediana—. `cargo` viene NULL en origen, no es un fallo del pipeline.

**Consecuencia metodológica, y es la que pesa:** la composición no falta al azar, falta donde
están los empleadores grandes. Es el escenario de falta sistemática de D-003 y refuerza la
necesidad del IPW del sub-proyecto 2. Un modelo entrenado sobre el universo con composición está
entrenado sobre empresas pequeñas.

**Pendiente operativo:** preguntar al equipo de ActuaFast si esos 263 estudios son recuperables
en origen. Son 137.000 filas de las empresas más grandes.

### La censura en el SBU NO invalida el piso de la escalera

Era la pregunta que bloqueaba la Tarea 2b. El umbral de alarma del plan era 30%.

| | |
|---|---|
| `y == 0` exacto | **5,9%** |
| Celdas de ≥5 personas con >50% de su gente en el SBU | **2,4%** |
| ...con >90% | 1,3% |

**La escalera sobrevive.** La partición aleatoria no gana por censura y no hace falta tratamiento
especial. Se declara así en el pre-registro.

### Pero la distribución está muy comprimida

`y ≤ 0,05` cubre el **40,4%** de la gente: dos de cada cinco personas ganan a menos de un 5% del
salario mínimo. Mediana 1,16 SBU, p75 1,81 SBU.

No invalida nada, pero **acota lo que se puede demostrar**: en la mitad inferior de la
distribución apenas hay variación que un benchmark pueda diferenciar. Debe decirse en la tesis.

### `CARGO` sobre el marco real

| | |
|---|---|
| Etiquetas distintas | 65.081 |
| Tamaño de celda, mediana | **2 personas** |
| Empresas por celda, mediana | **1** |
| Celdas con ≥3 empresas | 9,24% |
| **Personas que esas celdas cubren** | **66,6%** |
| Etiquetas de una sola persona | 20.038 (30,8%) |

El techo de cobertura de `CARGO` es **66,6%**, consistente con el 60,5% medido antes sobre 2025
solo. Confirma D-005: podar `CARGO` a sus etiquetas grandes no produce un rival, produce una celda
"otros" con la mayoría de la gente.

### La trampa `sueldo` / `total`, tercera aparición

**78.460 filas (7,31%) tenían sueldo base por debajo del SBU pese a pasar la cuarentena.** El
mínimo era `y = -4,76`: un sueldo del **0,9% del SBU**, unos 4 dólares.

Causa: `ingesta/validacion.py:35` filtra por `total < min_sbu * sbu` —sueldo más comisiones más
extras— mientras el objetivo se calcula sobre `sueldo`. Alguien con sueldo base de 4 dólares y
total de 500 pasaba.

Es la misma familia que las otras dos apariciones: `sueldo_sbu` de la tabla vale `total/SBU`
(`features_base.py:28`), y D-011 corrigió el desemparejamiento entre estimador y métrica. **Tres
veces el mismo par de columnas.**

**Hipótesis descartada por medición.** Se supuso que serían personas con muchas comisiones —sueldo
base bajo, total alto—. **Falso:** su perfil de composición es indistinguible del resto
(comisiones 3,8% frente a 4,8%, si acaso menos). Lo que sí las distingue es que **sólo el 36,9%
tiene composición**, frente al 90,8% del resto.

**Decisión:** se filtran en `evaluacion.datos.marco_evaluable` (`exigir_sbu=True`, reversible), no
en el pipeline. El objetivo se define en ese módulo, así que su criterio de validez pertenece ahí;
alinear `ingesta.validacion` exige reprocesar 1,9 M de filas y va en el próximo reproceso.

### El marco evaluable definitivo

| | Antes del filtro | **Después** |
|---|---|---|
| Filas | 1.072.808 | **994.348** |
| Empresas | 6.717 | **6.710** |
| `y` mínimo | −4,76 | **0,00** |

Sólo 7 empresas quedan sin ninguna persona. **994.348 filas y 6.710 empresas** es el universo sobre
el que corre el banco.

---

## 13. El banco pasa su prueba de aceptación

**Fecha:** 2026-08-11. **Fuente:** `tests/test_evaluacion_banco.py` (Tarea 10 del plan v3).
Data sintética, 60 empresas × 20 personas, 3 roles separados por composición.

### La escalera queda en el orden esperado

| Partición | MAE |
|---|---|
| aleatoria (k igualado) | 0,2699 |
| **verdadera** | **0,2058** |
| oráculo (k-means sobre `y`, ajustado en train) | 0,1195 |

**El oráculo gana, y es correcto.** Agrupa por la propia `y` de la persona, y nada puede ganarle
a una partición construida desde el objetivo. Por eso es bandera roja y no rival: si el arquetipo
se le acerca sobre datos reales, derivó a bandas salariales.

### La cota teórica separa lo legítimo de la trampa

Con el efecto empresa inobservable bajo leave-company-out, ningún método legítimo baja de
`√η²_empresa × MAE_aleatorio`. Aquí: `√0,373 × 0,2699 = 0,165`.

- verdadera **0,206 > 0,165** → legítima ✅
- oráculo **0,120 < 0,165** → **rompe la cota, prueba formal de que ve lo que no debe** ✅

Es un chequeo barato y sirve sobre datos reales: cualquier método que baje de la cota tiene fuga.

### Magnitud mínima detectable

Se degrada la partición verdadera reasignando al azar un x% de las etiquetas, promediando sobre
tres semillas de degradación:

| Degradación | Diferencia media | Detectada (IC pareado sin cruzar 0) |
|---|---|---|
| 0% | +0,0000 | **0/3** — sin falso positivo |
| 10% | −0,0144 | 3/3 |
| 25% | −0,0294 | 3/3 |
| 50% | −0,0415 | 3/3 |

**MDE ≤ 10%.** Va al pre-registro. Monótona y sin falsos positivos en el control.

Nota de método: con **una sola** semilla de degradación el resultado salía no monótono —5% no,
10% sí, 20% no—, porque la degradación realizada es muy variable con 3 celdas. Un MDE no monótono
no se puede escribir en un pre-registro; por eso se promedia.

---

## 14. Los embeddings son ciegos a la jerarquía

**Fecha:** 2026-08-11. **Fuente:** `research/experimentos/e0_banco/diagnostico_nivel_embeddings.py`.
**Modelo:** `text-multilingual-embedding-002`, tarea `CLUSTERING`, 668 etiquetas reales del marco
2024-2025 (las 4.000 más frecuentes cubren 897.893 personas).

**La pregunta:** el arquetipo es rol-familia × **nivel**. ¿Los embeddings codifican el nivel, o hay
que dárselo aparte? Ya se había medido que el emparejamiento por caracteres invierte la jerarquía
(§9), pero eso era TF-IDF. Suponerlo de los embeddings sin medirlo sería repetir D-010.

**El diseño:** pares construidos con etiquetas reales.
*Par de nivel* = misma área, distinto rango. *Par de área* = mismo rango, distinta área.

### El resultado

| Pares que se diferencian sólo en… | Similitud coseno (media) |
|---|---|
| el **rango** — `AUXILIAR DE BODEGA` / `JEFE DE BODEGA` | **0,857** |
| el **área** — `JEFE DE BODEGA` / `JEFE DE VENTAS` | 0,764 |

**Diferencia: −0,093.** Un gerente y un auxiliar del mismo área se parecen **más** que dos jefes de
áreas distintas. El embedding está dominado por el tema.

Y el tamaño del salto jerárquico casi no cambia nada:

| Salto | Similitud | n |
|---|---|---|
| 1 escalón | 0,861 | 173 |
| 2 escalones | 0,851 | 130 |
| 3 escalones | 0,861 | 67 |
| 4 escalones | 0,843 | 30 |

De `AYUDANTE` a `DIRECTOR` la similitud baja 0,018. **Es indiferencia, no gradiente.**

Peores casos: `GERENTE DE AUDITORIA` ↔ `JEFE DE AUDITORIA` **0,944**;
`GERENTE DE CONTABILIDAD` ↔ `JEFE DE CONTABILIDAD` 0,939;
`ASISTENTE DE MANTENIMIENTO ELECTRICO` ↔ `TECNICO MANTENIMIENTO ELECTRICO` 0,936.

### Cobertura del léxico de rango

Palabra de rango explícita en el cargo (`AYUDANTE, AUXILIAR, OPERARIO, OBRERO, ASISTENTE, TECNICO,
ANALISTA, SUPERVISOR, COORDINADOR, ESPECIALISTA, JEFE, SUBGERENTE, GERENTE, DIRECTOR`):

| | |
|---|---|
| Etiquetas distintas que la llevan | 51,1% |
| **Personas cubiertas** | **38,6%** |

Reparto: `ASISTENTE` 7,8%, `AUXILIAR` 6,6%, `JEFE` 3,6%, `AYUDANTE` 3,5%, `OBRERO` 2,6%,
`TECNICO` 2,6%, `ANALISTA` 2,5%, `SUPERVISOR` 2,4%, `OPERARIO` 2,4%, `COORDINADOR` 1,9%,
`GERENTE` 1,7%, resto <1%.

### Consecuencias

1. **Los embeddings sí resuelven los sinónimos** —por eso reconocen el área con cualquier rango—
   **y no resuelven el nivel.**
2. **Un normalizador de sinónimos con LLM no arregla lo que falta.** Fusionar
   `VENDEDOR = ASESOR COMERCIAL` no dice quién manda. Resolvería un problema ya resuelto.
3. **El modelo de nivel del sub-proyecto 3 deja de ser una suposición y pasa a estar justificado.**
4. El léxico de rango da un 38,6% gratis, determinista y auditable. Para el resto quedan el
   catálogo del MDT (niveles A–E oficiales) y, si hace falta, un LLM **de nivel** — validable
   contra ese 38,6% donde la respuesta se conoce, lo que responde la objeción de caja negra.
5. **El rival `solo_texto` ya es el "CARGO normalizado".** Agrupa por significado, con los sinónimos
   fusionados, a cardinalidad igualada. La objeción *"le amarraste una mano a `CARGO` por no
   limpiarlo"* está contestada por el diseño, sin normalizador aparte.

---

## 15. La premisa central, medida — y el eje que sí paga

**Fecha:** 2026-08-12. **Alcance:** el 80% de train (847.046 filas, 5.758 empresas). El 20% de
test **no se tocó**. **Scripts:** `research/experimentos/e1_premisa/01…05`, con las salidas en
`salidas/`.

Contexto: el EDA se hizo con la composición al 2,7% y nunca pudo comprobar la hipótesis central.
Se recuperó al 80% y aquí se mide por fin. **El resultado obliga a reformular la tesis** (D-013).

### 15.1 La composición del pago casi no explica el salario

Diseño: se residualiza `y` contra la empresa (quita el efecto empleador), luego contra
`cargo_norm`. Sobre ese residuo se mide **R² fuera de muestra** (GBM, `GroupKFold` por empresa),
restringido a etiquetas con ≥30 personas (585.194 filas, 2.924 etiquetas).

| Predictor | R² fuera de muestra | Reduce la sd del error |
|---|---|---|
| **Placebo** (ruido gaussiano) | −0,0002 | — |
| **Composición** (4 proporciones) | **+0,0042** | **0,21%** |
| Antigüedad | +0,0114 | 0,57% |
| Las dos juntas | +0,0180 | 0,91% |

Con ω² sobre partición de 25 celdas, estable en todas las especificaciones: 0,0055 (todas las
etiquetas) / 0,0058 (≥30 personas) / 0,0052 (≥100). **No es un artefacto de discretización ni de
celdas mal estimadas.**

En las **50 etiquetas más dispersas** el orden se invierte: composición +0,0118 (0,59%),
antigüedad +0,0032 (0,16%). Es la variable correcta para el problema correcto; ese problema
afecta a pocas etiquetas.

**⚠️ Alcance exacto de la afirmación, y hay que respetarlo.** El diseño residualiza contra la
empresa *antes* de medir, y la composición está determinada por la empresa entre un 39% y un 50%
(η²_empresa: comisiones 0,388, extras 0,498). El diseño elimina por construcción la parte de la
composición que podría predecir. La afirmación defendible es la estrecha: **la composición no
aporta información intra-empresa e intra-etiqueta sobre el sueldo base.** No es "la composición no
importa" — sobre compensación *total* es, mecánicamente, casi todo.

### 15.2 De dónde viene el error de `CARGO`

Componentes de varianza sobre celdas de `CARGO` (`y_fi = μ_c + a_f + e_fi`), train completo:

| | |
|---|---|
| τ (sd entre empresas dentro de celda) | **0,2917** |
| σ (sd intra empresa dentro de celda) | **0,1423** |
| Ruido irreducible bajo leave-company-out | sd **0,3246** |
| sd predictiva real de `CARGO` | **0,3651** |
| **Techo de mejora por agrupar mejor** | **10,9%** (12,1% sobre train completo) |

El empleador pesa el doble que todo lo demás junto, y bajo leave-company-out es inobservable.

**Desglose por espesor de celda** (ponderado por personas):

| Empresas donantes | Celdas | % de personas | sd predictiva | % del error que es ESTIMACIÓN |
|---|---|---|---|---|
| **1–2** | 52.264 | **34,0%** | 0,4225 | **44,6%** |
| 3–5 | 2.810 | 8,3% | 0,3578 | 20,0% |
| 6–20 | 1.680 | 12,8% | 0,3361 | 8,3% |
| 21–100 | 538 | 18,8% | 0,3249 | 2,4% |
| 101+ | 140 | 26,0% | 0,3359 | 0,4% |

**Dos mundos.** 140 celdas cubren al 26% de la gente y ahí `CARGO` está a 0,4% del óptimo. 52.264
celdas cubren al 34% y ahí casi la mitad del error es ruido de estimación — una "referencia de
mercado" calculada con dos personas de una empresa.

**Diagnóstico:** `CARGO` no está semánticamente roto, está **estadísticamente delgado**.

**Consecuencia para el pre-registro:** el resultado primario debe declararse **estratificado por
espesor de celda**, con el global como secundario. El 12,1% está diluido por el 26% de gente donde
nada puede ayudar.

### 15.3 El techo fuera de la zona comprimida por el SBU

El 40,4% de la gente gana a menos de un 5% del mínimo; ahí la respuesta correcta es "el mínimo".

| Subconjunto | n | sd actual | sd ideal | Techo |
|---|---|---|---|---|
| Todo | 847.046 | 0,3700 | 0,3253 | 12,1% |
| `y > 0,05` | 507.279 | 0,4322 | 0,3750 | 13,2% |
| `y > 0,20` | 392.667 | 0,4335 | 0,3741 | 13,7% |
| `y > 0,40` | 294.618 | 0,4328 | 0,3704 | **14,4%** |

Sube, pero moderadamente: 12,1% → 14,4%. No duplica el margen.

### 15.4 El nivel jerárquico SÍ paga, y es el hallazgo más grande del proyecto

Sobre las personas cuyo cargo empieza con palabra de rango, en áreas donde coexisten ≥2 rangos
distintos (228.212 filas, 3.357 áreas). Se descuenta la empresa y **el área** — es decir, se deja
el rango dentro del residuo y se pregunta si explica.

| | var |
|---|---|
| tras quitar empresa | 0,2435 |
| tras quitar empresa + área | 0,1828 (sd 0,428) |

| Partición sobre ese residuo | ω² | Reduce la sd |
|---|---|---|
| **Rango** (14 categorías) | **+0,2462** | **13,2%** |
| Nivel (5 escalones) | +0,2388 | 12,7% |
| **Placebo** (rango permutado) | **+0,0000** | 0,00% |

**Escalera monótona, dentro de empresa y área:**

| Nivel | Efecto sobre `y` | n |
|---|---|---|
| 1 · ayudante, auxiliar, operario, obrero, asistente | −0,1202 | 131.314 |
| 2 · técnico, analista | −0,0860 | 27.715 |
| 3 · supervisor, coordinador, especialista | +0,0542 | 29.336 |
| 4 · jefe, subgerente | +0,3109 | 26.611 |
| 5 · gerente, director | +0,6270 | 13.236 |

**Recorrido de nivel 1 a 5: +0,7471 en log = factor 2,11× en salario.**

**59 veces más que la composición** (0,2462 frente a 0,0042). Y con los embeddings ciegos a este
eje (§14: 0,857 entre rangos frente a 0,764 entre áreas), **un pipeline que agrupe por similitud
de texto fusiona en la misma celda a personas que cobran el doble.**

### 15.5 Cobertura del léxico de rango — dos cifras, dos definiciones

Se han medido dos cosas distintas y hay que citarlas por separado para no contradecirse:

| Definición | Cobertura |
|---|---|
| Palabra de rango **en cualquier posición** de la etiqueta (§14) | **38,6%** de las personas |
| Palabra de rango **al inicio, seguida de un área** (`^RANGO (DE )?RESTO`) | **34,5%** de las personas |

La segunda es la usable para descomponer en (rango, área), y es la que sostiene §15.4. La primera
es el techo de detección del rango. **Al escribir, usar 34,5% cuando se hable de descomponer y
38,6% cuando se hable de detectar.**

### 15.6 Lo que se cae y lo que entra

**Se cae:** la composición como eje central, y con ella su maquinaria — transformación ILR, CoDa,
compuerta de masa fija, IPW por falta sistemática, restricciones semi-supervisadas y los pesos de
bloque que motivaron la normalización MFA. Se reporta como *arquitectura descartada por medición*.

**Entra:** el **eje de nivel** como pieza central, con ω² de 0,246 frente a 0,004. Sus fuentes por
orden: léxico de rango (34,5% gratis y auditable), catálogo MDT-2019-395 (niveles A–E oficiales
por contenido de puesto) y, para el resto, un clasificador **validado contra el 34,5% donde la
verdad se conoce**.

### 15.7 Medición pendiente que sostiene todo esto

**Acotar el sesgo de movilidad limitada sobre τ.** Todo el techo cuelga de τ = 0,2917, y η²_empresa
está probablemente sobreestimado (pendiente desde el 2026-08-07). Buena noticia: si τ está
inflado, el ruido irreducible está inflado y **el techo está subestimado**. Pero hay que medirlo y
reportar el techo como intervalo, o un economista laboral desarma el capítulo central.

---

## 16. Las grafías del mismo puesto, y por qué el enlace lo decide todo

**Fecha:** 2026-09-02/04. **Alcance:** el 80% de train, partido por empresas en 75% construir /
25% evaluar. El 20% de test **no se tocó**. **Scripts:** `research/experimentos/e2_nivel/05…07`,
con las salidas en `salidas/`.

Contexto: `ANALISTA DE RIESGO CREDITICIO` competía contra seis grafías del mismo puesto, cada una
con una o dos empresas. Ver D-015.

### 16.1 La primera medición dijo que fusionar empeora

Contraste pareado sobre los títulos afectados, 150 réplicas, remuestreando empresas con reemplazo
y construyendo las dos variantes sobre **el mismo** remuestreo.

| Umbral | Efecto | IC 95% | Veredicto |
|---|---|---|---|
| >0,99 | −0,0007 | [−0,0038, +0,0024] | sin efecto |
| >0,97 | −0,0034 | [−0,0088, +0,0001] | sin efecto |
| >0,95 | **+0,0154** | [+0,0095, +0,0206] | **empeora** |

### 16.2 La inspección de los grupos concretos invalidó esa lectura

Enlace simple (union-find) a 0,95 produce **un grupo de 1.758 títulos**:

```
ASISTENTE CONTABLE       0,324   4.670 pers.
AUXILIAR DE LIMPIEZA     0,011   2.751 pers.      dispersion del grupo: 28,83x
```

Y otro de 502 que junta `ASISTENTE DE ALMACEN` (nivel 1) con `JEFE DE COMPRAS` (nivel 4), pese al
candado de escalón. Verificado el mecanismo: el candado sólo actúa cuando **los dos** títulos
tienen palabra de rango, y `GESTOR DE TALENTO HUMANO` → `None` hacía de puente.

### 16.3 Con enlace completo el signo se invierte

Un grupo vale sólo si **todos** sus pares superan el umbral. Mismo umbral, misma gente, mismas
réplicas:

| Variante | Efecto | IC 95% | Grupo mayor | p99 dispersión | Cobertura directa |
|---|---|---|---|---|---|
| simple >0,95 | **+0,0154** | [+0,0095, +0,0206] | 1.758 | 8,28× | 67,4% |
| **completo >0,95** | **−0,0030** | [−0,0075, −0,0000] | **27** | 5,88× | **64,1%** |
| completo >0,97 | −0,0017 | [−0,0063, +0,0016] | 22 | 5,39× | 59,9% |
| completo >0,93 | −0,0005 | [−0,0056, +0,0052] | 33 | 6,75× | 66,1% |

El tope de 60 títulos por grupo **nunca se activó**: el enlace completo acota el tamaño solo. Y
sólo **18 uniones de 15.870** las rechazó el candado de escalón.

Los grupos que sobreviven son puro ruido de tecleo:

```
ASISTENTE / AYUDANTE / AUXILIAR ADMINISTRATIVO     0,179   1.920 pers.
ASISTENTE/AYUDANTE/AUXILIAR ADMINISTRATIVO         0,142      50 pers.
ASISTENTE/ AYUDANTE/ AUXILIAR ADMINISTRATIVO       0,019      38 pers.
```

**Lectura:** la ganancia es de **cobertura** (57,7% → 64,1%), no de precisión. El −0,0030 roza el
cero.

---

## 17. La banda que se entrega al cliente, y la etiqueta que la acompaña

**Fecha:** 2026-09-04. **Alcance:** el 80% de train, partido por empresas en 75%/25%. El 20% de
test **no se tocó**. **Scripts:** `research/experimentos/e3_varianza/01…09`, con las salidas en
`salidas/`.

Origen: una objeción durante la revisión — *"`tau` y `sigma` representan la variación de un cargo
específico, ¿y usan el mismo par para los 65.081?"*. Ver D-016, D-017 y D-018.

### 17.1 `tau` varía 8,3× entre cargos, y la variación es real

ANOVA de un factor dentro de cada celda, sobre las 704 celdas con 20+ empresas (45,2% de la gente):

| | p05 | p25 | p50 | p75 | p95 |
|---|---|---|---|---|---|
| `tau` por celda | 0,080 | 0,213 | **0,322** | 0,446 | 0,663 |
| `sigma` por celda | 0,039 | 0,089 | 0,133 | 0,185 | 0,288 |

Global: `tau` = 0,2917.

**Test-retest**, partiendo las empresas de cada cargo en dos mitades al azar y estimando por
separado:

| | Pearson | Spearman |
|---|---|---|
| `tau` | **+0,780** | +0,772 |
| `sigma` | +0,484 | +0,486 |

Si el parámetro fuese común y lo observado fuera ruido, `r ≈ 0`. Corregida la atenuación
(Spearman-Brown), la fiabilidad de `tau_c` sobre la muestra completa es **~0,88**.

El patrón sigue al escalón jerárquico, con causa mecánica —el mínimo legal comprime desde abajo—:

```
AUXILIAR DE LIMPIEZA   tau 0,073        JEFE DE BODEGA    tau 0,363
GUARDIA DE SEGURIDAD   tau 0,101        CONTADOR          tau 0,451
CHOFER                 tau 0,177        GERENTE GENERAL   tau 0,951
```

**Añade a §15:** el nivel no sólo mueve la media 2,37× — escala la varianza 13×.

### 17.2 La banda no contenía al 50%: contenía entre el 18% y el 98%

Medido sobre personas de empresas apartadas, con la banda que entregaba el producto:

| Cargo | `tau_c` | Contenía |
|---|---|---|
| `GERENTE GENERAL` | 0,937 | **18,3%** |
| `CONTADOR` | 0,442 | 34,7% |
| `JEFE DE BODEGA` | 0,363 | 43,9% |
| `ASISTENTE CONTABLE` | 0,229 | 54,0% |
| `CHOFER` | 0,176 | 69,9% |
| `AUXILIAR DE LIMPIEZA` | 0,060 | 92,4% |
| `TRABAJADOR AGRICOLA` | 0,093 | **98,0%** |

En dólares, `GERENTE GENERAL`: el mercado real va de $500 (p05) a $13.712 (p95) y se entregaba
**$2.436 – $3.775**. De 20 personas al azar, **4** caían dentro.

### 17.3 Son dos defectos, y el segundo es de forma, no de anchura

| | Recorrido entre quintiles | cob. global | CRPS |
|---|---|---|---|
| `tau`, `sigma` globales | **54,7 pts** | 68,6% | 0,1720 |
| `tau_c`, `sigma_c` por celda | **23,4 pts** | 66,5% | **0,1572** |

`tau_c` arregla lo que depende del cargo y deja un sesgo global. La causa: el centro se estima de
forma **robusta** (mediana de votos) y la dispersión **no** (raíz de una varianza). Y la forma
cambia por cargo, así que recalibrar el multiplicador `0,6745` no puede arreglarlo:

```
AUXILIAR DE LIMPIEZA   p25=$475  p50=$475  p75=$485      <- un pico
GERENTE GENERAL        p05=$500          p95=$13.712     <- una cola
```

### 17.4 Con la definición correcta —empresas— y cuantiles empíricos

La banda dice *"la mitad de las **empresas** paga entre X e Y"*, así que se evalúa contra votos de
empresas apartadas y `sigma` sale de la fórmula.

| Variante | cob50 | cob80 | pinball.25 | pinball.75 | medio |
|---|---|---|---|---|---|
| hoy (normal, globales, +σ) | 53,5% | 76,1% | 0,1252 | 0,1329 | 0,1290 |
| normal, `tau_c`, sin σ | 50,6% | 76,2% | 0,1168 | 0,1297 | 0,1233 |
| empírico F≥5 | 49,0% | 77,4% | **0,1119** | 0,1278 | **0,1199** |
| **empírico F≥10** | 49,4% | **78,0%** | 0,1133 | 0,1281 | 0,1207 |
| empírico F≥20 | 49,6% | 77,8% | 0,1139 | 0,1285 | 0,1212 |

Deformación entre quintiles de dispersión: **50,5 → 13,5 → 4,3 puntos**.

Se elige **F≥10**: F≥5 gana el pinball por un 0,7% que no es distinguible de ruido, y F≥10 gana las
dos coberturas y está más lejos del dato crudo.

**Corrige un número de §17.2:** medida contra personas la cobertura global salía 68,7%; contra
empresas, 53,5%. Buena parte de la descalibración aparente era el desajuste de definición.

**Aviso de lectura:** con masa puntual la cobertura deja de ser métrica válida. `TRABAJADOR
AGRICOLA` tiene cuartiles reales $470–$472, la banda los reproduce **exactos** y aun así cubre el
90,3%.

### 17.5 La etiqueta de confianza no distinguía nada, y era algebraico

En la rama directa, `var = tau² + sigma² + 1/W` con reparto 80,7% / 19,2% / **0,1%**. Desarrollando
a primer orden, `veces ≈ 1 + 0,557·r`, y salir de ALTA exige `W < 21,1`; como cada empresa aporta
al menos 9,50, harían falta **menos de 2,2 empresas**. Con `MIN_EMPRESAS = 3` era **imposible**.
Medido sobre las 5.168 celdas con 3+ empresas: **100,00%** en ALTA, incluidas las 1.561 que
tienen exactamente 3. La celda mas desfavorable de todas queda en **1,175 veces el suelo** y el
corte esta en 1,25: ninguna lo roza siquiera.

La alternativa es la varianza de la estimación propia. Validada sobre dos mitades disjuntas de
empresas:

| | Spearman con el movimiento real | ALTA | MEDIA | BAJA |
|---|---|---|---|---|
| hoy (ancho/suelo) | +0,367 | **100,0%** | 0,0% | 0,0% |
| nueva (`1/W`) | **+0,576** | 17,6% | 45,5% | 37,0% |
| *y cuánto se mueve la referencia* | | **3,8%** | **13,3%** | **31,8%** |

**Límite:** `1/W` se queda corto, obs/pred va de 0,96 en el primer decil a **1,42** en el último.
Ordena bien pero es optimista.

### 17.6 El tamaño de empresa: no para la banda, sí para el centro

| Definición | cob50 | pinball | ancho | incert |
|---|---|---|---|---|
| cargo (hoy) | 50,3% | **0,1255** | 28,2% | 10,4% |
| cargo × tamaño | 49,9% | 0,1284 | 27,5% | 12,7% |
| cargo × sector | 49,8% | 0,1289 | 27,3% | 13,2% |
| cargo × provincia | 49,8% | 0,1288 | 27,4% | 12,6% |

Y la selección cargo a cargo, con doble partición anidada y **placebo**:

| Variante | Cargos | pinball |
|---|---|---|
| cargo (hoy) | 0 | 0,1255 |
| selectivo | 93 | 0,1253 |
| **placebo (al azar)** | **118** | 0,1258 |

El placebo elige **más** cargos que la señal real. Sin él, esto se habría reportado como mejora.

**Pero el pinball evalúa la banda.** El sesgo del **centro** es otra cosa:

| Sesgo de la referencia de hoy | PEQUEÑA | MEDIANA | GRANDE | recorrido |
|---|---|---|---|---|
| nivel 1 | +6,9% | +8,3% | +6,1% | 10,1% |
| nivel 3 | −13,5% | +6,1% | +2,7% | 19,6% |
| nivel 4 | −16,4% | −8,4% | +9,6% | 26,1% |
| **nivel 5** | **−32,8%** | −16,6% | **+22,2%** | **55,0%** |

Y segmentar lo arregla: nivel 5 pasa a −0,6% / −5,8% / +9,0% (**14,8 pts**). `GERENTE GENERAL` de
−56,0%/+81,9% a −12,1%/+17,9%; `CONTADOR` de −23,8%/+20,5% a +0,2%/+2,2%; `CHOFER` no tenía nada
que arreglar y no se estropea.

**Corrige un número dado antes:** *"el 56% de los datos son empresas GRANDES"* es **por filas**. Por
**empresas** —la unidad que vota— las grandes son el **20,9%** y una de cada cinco es pequeña o
micro.

---

## 18. Mediciones pendientes

| Qué | Por qué importa | Coste |
|---|---|---|
| Estructura ocupacional y sinónimos del MDT-2019-395 | Aporta niveles A–E por contenido de puesto y el diccionario oficial de sinónimos | parsear 249 pp. |
| Recuperar en origen los 263 estudios de 2024 sin plantilla ni cargo | 137.000 filas de las empresas mas grandes | preguntar al equipo |
| Alinear la cuarentena `sueldo_bajo_sbu` con `sueldo` en vez de `total` | Hoy se parchea en `marco_evaluable`; el pipeline sigue midiendo otra cosa | proximo reproceso |
| Cobertura de plantilla en 2023 con muestra mayor | Solo se sondearon 26 estudios, todos 404 | 1 sondeo |
| Cuantificar el sesgo de movilidad limitada sobre η²_empresa | Es un número que sostiene el leave-company-out y probablemente está inflado | análisis |
| Ruta de servicio: acierto de (título, centro, antigüedad) → arquetipo | Decide si el producto del §12 se puede servir | 1 día, tras el banco |
| Ortogonalidad de `pct_fijo` frente a `log(sueldo/SBU)` | El spec la declara; hay que medirla | 1 consulta |
| **Montar D-018**: segmentar el centro por tamano en los cargos altos | Medido que arregla -56%/+82% -> -12%/+18% en `GERENTE GENERAL`. Falta decidir la lista de cargos y pedirle el segmento al cliente | 1 dia |
| El **26-34% de empresas sin `segmento`**, y por que paga distinto | Es el bloqueo real de D-018: un tercio del padron no se puede segmentar, y ese grupo no se comporta como los demas | 1 consulta + cruce SCVS |
| La **escalera de antiguedad** `JUNIOR`/`SENIOR`/`I`/`II`/`III` | Notacion distinta de la de mando, invisible al eje de nivel. `LABORATORISTA JR.` $497 contra `LABORATORISTA SENIOR` $938 (1,9x). Mismo diseno que E2 | 1 experimento |
| Por que **`1/W` se queda corto** entre un 15% y un 40% | La etiqueta de confianza (D-017) ordena bien pero es optimista. Sospecha: el modelo supone la celda homogenea y no lo es | 1 experimento |
| El **ancla de empresa (-12,8%)** con contraste pareado | Es el numero mas grande del expediente y sigue sobre una sola particion. Pendiente desde D-014 | 1 corrida |
