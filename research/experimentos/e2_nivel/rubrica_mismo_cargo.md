# Rúbrica: ¿son el mismo cargo?

La siguen igual quien juzga a mano (los 400 de `13e`) y el LLM (el piloto y los 10.000). Si
las dos partes aplican reglas distintas, el acuerdo entre ellas no mide nada.

**Versión 1 — 2026-09-23.** Sale de los 48 juicios de `13a`, de D-013, D-025, D-026 y
D-033, y de los léxicos `RANGOS` y `SENIORIDAD` de `src/benchmarking/producto/nivel.py`.
Las cuatro reglas donde esos 48 se contradecían las decidió el autor (ver el final).

---

## La pregunta

Se te dan dos títulos de cargo, A y B, sacados de nóminas de empresas ecuatorianas. La
pregunta es:

> **¿Pondrías a una persona con el título A y a otra con el título B en la misma celda de
> comparación salarial?**

O dicho de otra forma: ¿el mercado les pagaría en la misma banda porque hacen el mismo
trabajo, al mismo nivel y con la misma antigüedad? No se pregunta si los títulos se
*parecen*, sino si describen **el mismo puesto**.

Respuesta: siempre `si` o `no`. Si dudas, elige igualmente y escribe `duda` en la nota.

## Cómo decidir: cinco pasos, en orden

Recorre los pasos en orden. El primero que diga `no` decide. Si ninguno lo dice, es `si`.

### Paso 1. Quita el ruido: nada de esto hace distintos dos títulos

- **Ortografía, erratas y abreviaturas**: `SUPERV.` = `SUPERVISOR`, `DESAROLO` =
  `DESARROLLO`, `ADM.` = `ADMINISTRACION`, `NEGOC` = `NEGOCIOS`.
- **Género y número**: `PROFESORA` = `PROFESOR`, `ENFERMERAS` = `ENFERMERO`.
- **Conectores y orden de las palabras**: `DE`, `DEL`, `Y`, `/`, `-`.
- **Códigos internos de la empresa**: letras, números, romanos y siglas sueltas que no son
  palabras de rango. `TECNICO MECANICO A` = `TECNICO MECANICO I`,
  `INGENIERO INSPECTOR DE PROYECTOS 132` = `... 108`, `SENIOR` = `SENIOR C`, `PORTERO BR`,
  `AYUDANTE DE BODEGA DEV`, `PLANIFICADOR (R)`, `SERVICIOS VARIOS 1` = `SERVICIOS VARIOS/U`.
- **La unidad o el lugar donde se trabaja**, si la tarea es la misma:
  `PROFESOR TIEMPO COMPLETO FAC. HUMANIDADES` = `... FAC. HUMANIDADES - ESC. ARTES`.
- **Traducciones que repiten el título**: `GERENTE DE PROYECTOS 项目经理` = `GERENTE DE
  PROYECTOS`.
- **`GENERAL`** no es un nivel: `SUPERVISOR DE ETIQUETADO` = `SUPERVISOR GENERAL DE
  ETIQUETADO`, `JEFE SERVICIOS` = `JEFE DE SERVICIOS GENERAL`.

### Paso 2. El escalón: si las palabras de rango están en niveles distintos, `no`

Cada título tiene, casi siempre, una palabra de rango. Estos son los niveles, de menor a
mayor:

| Nivel | Palabras de rango |
|---|---|
| 1 | PASANTE, PRACTICANTE, AYUDANTE, AUXILIAR, OPERARIO, OPERADOR, OBRERO, ASISTENTE |
| 2 | TECNICO, ANALISTA |
| 3 | SUPERVISOR, COORDINADOR, ESPECIALISTA |
| 4 | JEFE, SUBGERENTE |
| 5 | GERENTE, DIRECTOR, VICEPRESIDENTE, PRESIDENTE |

- **Distinto nivel → `no`.** `ASISTENTE` < `ANALISTA` < `COORDINADOR` son puestos
  distintos aunque el área sea la misma. `ASISTENTE DE COMITE DE ETICA` ≠ `ANALISTA DE
  COMITE DE ETICA`, `JEFE DE CONTABILIDAD Y TESORERIA` ≠ `GERENTE DE CONTABILIDAD Y
  TESORERIA`.
- **Mismo nivel, distinta palabra → sigue al paso 3.** `ASISTENTE` = `AUXILIAR` =
  `AYUDANTE`: `ASISTENTE DE BODEGA Y FARMACIA` = `AUXILIAR DE BODEGA Y FARMACIA`,
  `AUXILIAR CENTRO DISTRIBUCION` = `ASISTENTE CENTRO DISTRIBUCION`.
- **Excepción de `ESPECIALISTA`.** Si va junto a otra palabra de rango, no cuenta como
  nivel 3, sino como marca de senior del paso 3: `TECNICO ESPECIALISTA` es un técnico
  senior (nivel 2, senior). Solo cuenta como nivel 3 cuando va sin otra palabra de rango.
- **Palabras que no están en la tabla** (`ASESOR`, `PLANIFICADOR`, `PROGRAMADOR`,
  `INGENIERO`, `PROFESOR`, `CHOFER`, `PORTERO`, …) no marcan nivel.
- **Este paso solo decide si LOS DOS títulos tienen palabra de rango.** Si solo uno la
  tiene, o ninguno, sigue a los pasos siguientes: `ASISTENTE ATENCION AL CLIENTE` =
  `ASESOR ATENCION AL CLIENTE`, `PROGRAMADOR DE SOFTWARE SENIOR` = `ESPECIALISTA DE
  SOFTWARE SENIOR`. Es la misma regla que sigue el candado de escalón del producto
  (D-015).

### Paso 3. La antigüedad dentro del escalón: si no coincide, `no`

Estas marcas indican antigüedad **dentro** del nivel:

| Menos antiguo | Sin marca | Más antiguo |
|---|---|---|
| TRAINEE, JR, JUNIOR, SOUS | — | SR, SENIOR, CORPORATIVO / CORPORATIVA |

- **Si un título tiene marca y el otro no, o tienen marcas distintas → `no`.**
  `ANALISTA INTELIGENCIA DE NEGOC` ≠ `ANALISTA JUNIOR - INTELIGENCIA DE NEGOCIOS`,
  `CHEF DE COCINA` ≠ `SOUS CHEF DE COCINA`, `GERENTE DE INGENIERIA INDUSTRIAL` ≠
  `GERENTE CORPORATIVO DE INGENIERIA`.
- **Misma marca con otra grafía → no separa.** `JR.` = `JUNIOR`, `SR.` = `SENIOR`:
  `ASISTENTE DE TESORERIA JR.` = `ASISTENTE DE TESORERIA JUNIOR`.
- **`ESPECIALISTA` junto a otra palabra de rango cuenta como `SR`** (ver el paso 2):
  `TECNICO ESPECIALISTA EN MANTENIMIENTO` = `TECNICO DE MANTENIMIENTO SR.`
- Las letras y números **no** son antigüedad (paso 1), aunque a veces lo parezcan.

### Paso 4. La función: si es otro trabajo, `no`

- **Otra función u otra área → `no`.** `JEFE DE INGENIERIA Y MANTENIMIENTO` ≠ `JEFE DE
  INFRAESTRUCTURA Y MANTENIMIENTO`.
- **Función añadida (`X` frente a `X Y Z`).** Si lo añadido es contiguo a la función
  principal, es el mismo puesto → `si`: `JEFE DE ALMACEN` = `JEFE ALMACENAMIENTO Y
  DESPACHO`, `ANALISTA DE BASE DE DATOS` = `ANALISTA DE BASE DE DATOS Y APLICACIONES`.
  Si lo añadido es **otro oficio, con su propio mercado salarial**, → `no`:
  `JEFE DE MONTAJE` ≠ `JEFE DE MONTAJE Y SOLDADURA` (la soldadura es un oficio certificado
  aparte).
- **Especialidades hermanas.** Si el mercado las contrata y las paga por separado, → `no`:
  `INGENIERO BACK-END SENIOR` ≠ `INGENIERO FRONT-END SENIOR`. Si es la misma tarea sobre
  otro objeto, → `si`: `ASISTENTE DE DOCUMENTACION EXPORT JR.` = `ASISTENTE DE
  DOCUMENTACION IMPORT JR.`
- **Nombres distintos para la misma tarea → `si`.** `PROGRAMADOR DE SOFTWARE SENIOR` =
  `ESPECIALISTA DE SOFTWARE SENIOR`, `ANALISTA DE SISTEMAS TELECOMUNICACIONES` =
  `ANALISTA DE TELECOMUNICACIONES`.

### Paso 5. A quién apoya: una persona no es un área

`ASISTENTE DE [área]` apoya a un área; `ASISTENTE DE [un cargo]` apoya a una persona
concreta. Son puestos distintos → `no`.
`ASISTENTE DE PRODUCCION` ≠ `ASISTENTE DEL SUPERVISOR DE PRODUCCION`,
`ASISTENTE COMERCIAL CORPORATIVO` ≠ `ASISTENTE DE ASESOR COMERCIAL`.

---

## Formato de la respuesta

| Campo | Valor |
|---|---|
| `mismo` | `si` o `no` |
| `nota` | Opcional. El paso que decidió (`p2`, `p3`, …) y, si dudas, `duda`. |

La nota con el paso es lo que permite ver después **en qué regla** discrepan la persona y
el LLM, en vez de saber solo que discrepan.

---

## Decisiones del autor que fija esta versión

Cuatro puntos en los que los 48 juicios de `13a` se contradecían, resueltos el 2026-09-23:

1. **Escalón**: `ASISTENTE` < `ANALISTA` < `COORDINADOR`, y distinto nivel es distinto
   puesto.
2. **Función añadida**: el mismo puesto, salvo que lo añadido sea otro oficio.
3. **Especialidades hermanas**: distinto puesto si el mercado las paga distinto.
4. **`ESPECIALISTA` junto a otra palabra de rango** equivale a `SR`.

**Efecto sobre los 48.** Aplicada a mano a los 48, esta versión reproduce 47 juicios. El
que cambia es el #38 (`ASISTENTE` /
`ANALISTA DE COMITE DE ETICA`) pasa de `si` a `no`. El fichero de los 48 no se corrige:
queda como registro de lo que se juzgó entonces. El patrón de oro son los 400.

**Supuesto a vigilar.** `ASESOR` se trata como palabra de función y no de rango, porque
los dos pares `ASISTENTE` / `ASESOR` de los 48 se juzgaron `si`. Si en los 400 aparecen
`ASESOR` claramente por encima de `ASISTENTE`, se revisa.

**Pendiente en el código, no en la rúbrica.** La decisión 4 contradice el candado de
seniority de D-033, que hoy separa `TECNICO ESPECIALISTA EN MANTENIMIENTO` de
`TECNICO DE MANTENIMIENTO SR.` (es su único falso positivo medido).
