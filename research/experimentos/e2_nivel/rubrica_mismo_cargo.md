# Rúbrica: ¿son el mismo cargo?

La siguen igual quien juzga a mano y el LLM. Si las dos partes aplican reglas distintas, el
acuerdo entre ellas no mide nada.

**Versión 2 — 2026-09-23.** Todo lo que va antes de «Historial» es la rúbrica, y es lo que
recibe el LLM. El historial explica de dónde sale cada regla.

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

## Antes de empezar: títulos dobles

Si un título junta **dos puestos** con `/` (cada lado tiene su palabra de puesto o es un
título completo), vale como cualquiera de los dos: basta con que uno de ellos sea el mismo
puesto que el otro título.
`CAJERO / AUXILIAR DE PERCHA` = `AUXILIAR DE PERCHA`.

Si lo que va tras `/` no es un puesto sino una función más (`SUPERVISOR DE PRODUCCION /
MANTENIMIENTO`), no es un título doble: es una función añadida (paso 4).

## Cómo decidir: cinco pasos, en orden

Recorre los pasos en orden. El primero que diga `no` decide. Si ninguno lo dice, es `si`.

### Paso 1. Quita el ruido: nada de esto hace distintos dos títulos

- **Ortografía, erratas, abreviaturas y espacios de más o de menos**: `SUPERV.` =
  `SUPERVISOR`, `AYUD.` = `AYUDANTE`, `DESAROLO` = `DESARROLLO`, `ADM.` = `ADMINISTRACION`,
  `SECRETRIA` = `SECRETARIA`, `AUXILIARCONTABLE` = `AUXILIAR CONTABLE`.
- **Género y número**: `PROFESORA` = `PROFESOR`, `ENFERMERAS` = `ENFERMERO`.
- **Conectores, relleno y orden de las palabras**: `DE`, `DEL`, `Y`, `/`, `-`, `EN EL AREA
  DE`. Las mismas palabras en otro orden son el mismo título.
  `ASISTENTE DE SECRETARIA GENERAL` = `ASISTENTE EN EL AREA DE SECRETRIA GENERAL`.
- **Códigos internos de la empresa**: letras sueltas, números de tres cifras o más, y
  números pegados a una abreviatura. `SOLDADOR A` = `SOLDADOR I`,
  `INGENIERO INSPECTOR DE PROYECTOS 132` = `... 108`, `SENIOR` = `SENIOR C`, `PORTERO BR`,
  `AYUDANTE DE BODEGA DEV`, `PLANIFICADOR (R)`, `OPERARIO LT.4` = `OPERARIO LT.7`.
- **La unidad o el lugar donde se trabaja**, si la tarea es la misma:
  `PROFESOR TIEMPO COMPLETO FAC. HUMANIDADES` = `... FAC. HUMANIDADES - ESC. ARTES`.
- **Traducciones que repiten el título**: `GERENTE DE PROYECTOS 项目经理` = `GERENTE DE
  PROYECTOS`.
- **`GENERAL`** no es un nivel: `SUPERVISOR DE BODEGA` = `SUPERVISOR GENERAL DE BODEGA`,
  `JEFE SERVICIOS` = `JEFE DE SERVICIOS GENERAL`.

**Excepción: el grado.** Un ordinal pequeño (del 1 al 9, o del I al X) que aparece en
**los dos** títulos con valor **distinto** es un grado de la escala interna, y separa →
`no`. `AUXILIAR 1 DE CONTABILIDAD` ≠ `AUXILIAR 2 DE CONTABILIDAD`, `QUIMICO I` ≠
`QUIMICO II`, `ASISTENTE CONTABLE 3` ≠ `ASISTENTE CONTABLE 5`. Si el número está en un solo
título, es ruido: `OPERARIO 2 DE EMPAQUE` = `OPERARIO DE EMPAQUE`. Una letra no es un
grado: `A` frente a `I` sigue siendo ruido.

### Paso 2. El escalón: si las palabras de rango están en niveles distintos, `no`

Estos son los niveles, de menor a mayor:

| Nivel | Palabras de rango |
|---|---|
| 1 | PASANTE, PRACTICANTE, AYUDANTE, AUXILIAR, OPERARIO, OPERADOR, OBRERO, ASISTENTE, ASESOR, EJECUTIVO |
| 2 | TECNICO, ANALISTA, ADMINISTRADOR, CONTROLLER, CONSULTOR |
| 3 | SUPERVISOR, COORDINADOR, ESPECIALISTA, ENCARGADO, SUBJEFE |
| 4 | JEFE, SUBGERENTE |
| 5 | GERENTE, DIRECTOR, VICEPRESIDENTE, PRESIDENTE |

`ASESOR`, `EJECUTIVO` y `ADMINISTRADOR` están donde los ponen los juicios, no donde
sugiere el nombre: en estas nóminas un `EJECUTIVO DE COBRANZAS` es personal de primera
línea, no un directivo.

**Cómo se lee el nivel de un título:**

- **Es el nivel de quien ocupa el cargo.** Si un título tiene varias palabras de rango,
  cuenta la **más alta**: `ANALISTA AUXILIAR DE ADMINISTRACION` es un analista,
  `SUPERVISOR JEFE DE BASE` es un jefe.
- **Lo que va detrás de `DE` / `DEL` no cuenta**: dice a quién apoya, y eso es el paso 5.
  `ASISTENTE DE ADMINISTRADOR DE CAMPO` es un asistente (nivel 1).
- **`TECNICO` y `ESPECIALISTA` solo son palabras de rango si abren el título.** En
  cualquier otra posición, `TECNICO` es un adjetivo y no cuenta (`AUXILIAR TECNICO DE
  MANTENIMIENTO` es un auxiliar), y `ESPECIALISTA` o `ESPECIALIZADO` son la marca de
  senior del paso 3 (`TECNICO ESPECIALISTA` es un técnico senior).
- **Este paso solo decide si LOS DOS títulos tienen palabra de rango.** Si solo uno la
  tiene, o ninguno, sigue a los pasos siguientes. Las palabras que no están en la tabla
  (`PROGRAMADOR`, `INGENIERO`, `PROFESOR`, `CHOFER`, `VENDEDOR`, `GESTOR`, `LIDER`, …) no
  marcan nivel.

**Distinto nivel → `no`.** `ASISTENTE DE CUSTOMER EXPERIENCE` = `ASESOR DE CUSTOMER
EXPERIENCE` (los dos nivel 1), pero `EJECUTIVO DE GESTION DE COBRANZAS` ≠ `JEFE DE GESTION
DE COBRANZAS`, `ADMINISTRADOR FABRICA` ≠ `JEFE ADMINISTRATIVO DE FABRICA`, `ENCARGADO DE
MATERIALES Y SUMINISTROS` ≠ `JEFE DE MATERIALES Y SUMINISTROS`, `SUBGERENTE DE TIENDA` ≠
`SUBJEFE DE TIENDA`.

### Paso 3. La antigüedad y el alcance dentro del escalón: si no coinciden, `no`

| Menos | Sin marca | Más |
|---|---|---|
| TRAINEE, JR, JUNIOR, SOUS | — | SR, SENIOR; ESPECIALISTA o ESPECIALIZADO detrás de otra palabra; CORPORATIVO / CORPORATIVA |

Y aparte, el **ámbito**: `REGIONAL`, `ZONAL`.

- **Si un título tiene marca y el otro no, o tienen marcas distintas → `no`.**
  `ANALISTA INTELIGENCIA DE NEGOC` ≠ `ANALISTA JUNIOR - INTELIGENCIA DE NEGOCIOS`,
  `CHEF DE COCINA` ≠ `SOUS CHEF DE COCINA`, `SUPERVISOR CREDITO Y COBRANZA` ≠
  `SUPERVISOR CORPORATIVO DE CREDITO Y COBRANZA`, `GERENTE DE VENTAS COSTA` ≠
  `GERENTE REGIONAL DE VENTAS COSTA`, `COORDINADOR REGIONAL DE TALENTO HUMANO` ≠
  `COORDINADOR ZONAL DE TALENTO HUMANO`.
- **La misma marca con otra grafía no separa.** `JR.` = `JUNIOR`, `SR.` = `SENIOR`,
  `TECNICO ESPECIALISTA EN MANTENIMIENTO` = `TECNICO DE MANTENIMIENTO SR.`
- **`CORPORATIVO` no cuenta cuando es parte del nombre de un área o de un negocio**
  (`BANCA CORPORATIVA`, `PROCESOS CORPORATIVOS`, `VENTAS CORPORATIVAS`, `CLIENTES
  CORPORATIVOS`): `JEFE DE COMUNICACION` = `JEFE DE COMUNICACION CORPORATIVA`. Sí cuenta cuando
  dice el alcance del cargo: `JEFE CORPORATIVO DE SEGURIDAD INDUSTRIAL`.

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

### Paso 5. A quién apoya: un mando no es un área

Si uno de los títulos es `ASISTENTE`, `AUXILIAR`, `AYUDANTE` o `SECRETARIA` **de un
mando** —una palabra de nivel 3 o más: `SUPERVISOR`, `COORDINADOR`, `JEFE`, `GERENTE`,
`DIRECTOR`…— y el otro apoya a un área, son puestos distintos → `no`.
`ASISTENTE DE PRODUCCION` ≠ `ASISTENTE DEL SUPERVISOR DE PRODUCCION`.

No separa:
- **Si lo apoyado no es un mando** (`TECNICO`, `OPERADOR`, `ADMINISTRADOR`, `CONTROLLER`):
  `AYUDANTE DE TECNICO` = `AYUDANTE SERVICIO TECNICO`, `ASISTENTE DE ADMINISTRADOR DE
  CAMPO` = `ASISTENTE ADMINISTRATIVO CAMPO`.
- **Si el área nombrada es la oficina de ese mando**: `GERENCIA` = `GERENTE`, `JEFATURA` =
  `JEFE`, `DIRECCION` = `DIRECTOR`, `SUPERVISION` = `SUPERVISOR`, `COORDINACION` =
  `COORDINADOR`. Apoyar a la gerencia general es apoyar al gerente general.

---

## Formato de la respuesta

| Campo | Valor |
|---|---|
| `mismo` | `si` o `no` |
| `nota` | Opcional. El paso que decidió (`p1`, `p2`, …) y, si dudas, `duda`. |

---

## Historial

### v1 (2026-09-23): cuatro contradicciones de los 48 de `13a`

1. **Escalón**: `ASISTENTE` < `ANALISTA` < `COORDINADOR`, y distinto nivel es distinto
   puesto.
2. **Función añadida**: el mismo puesto, salvo que lo añadido sea otro oficio.
3. **Especialidades hermanas**: distinto puesto si el mercado las paga distinto.
4. **`ESPECIALISTA` junto a otra palabra de rango** equivale a `SR`.

### v2 (2026-09-23): revisión con los 400 de `13e` a la vista

La v1 dejaba sin cubrir casos que el juez resolvió de forma coherente, y en otros el juez
se contradecía. Lo decidió el autor:

- **`TECNICO` como adjetivo**, **`REGIONAL`/`ZONAL` como ámbito** y **el paso 5 solo para
  mandos**: salen de juicios coherentes del juez (11, 4 y 3 casos).
- **Palabras fuera de la tabla**: se les asigna nivel. La tabla es la única que no
  contradice ninguna de las 400 etiquetas; por eso `EJECUTIVO` queda en 1. `GESTOR` se
  queda fuera: `ANALISTA` = `GESTOR` y `GERENTE` = `GESTOR` no caben en un mismo nivel.
- **`CORPORATIVO` separa**, como en D-033; salvo como nombre de área o negocio.
- **`GENERAL` no separa.**
- **Un grado distinto separa.**

**Etiquetas corregidas en los 400** (su valor original queda en `mismo_v1`): 13. Cuatro
en la revisión con la v1 (#65, #182, #329 a `no`; #114 a `si`) y nueve al cerrar la v2
(#164, #205, #308, #320, #188, #350, #290 a `no`; #35, #192 a `si`).

**Comprobación.** Un verificador mecánico de los pasos 1, 2, 3 y 5 reproduce las 400
etiquetas salvo dos, que lee mal y la rúbrica aplicada a mano resuelve: un código
pegado a una abreviatura (#286) y una errata por un espacio que falta (#338). En
los 48 de `13a` reproduce 47; el #38 (`ASISTENTE` / `ANALISTA`) es la regla del escalón.

**Aviso de método.** La v2 se escribió viendo también la mitad de `prueba`. El acuerdo del
LLM en `prueba` sale por eso algo optimista, y hay que decirlo al reportarlo. En el texto
que recibe el LLM no aparece ningún título de `prueba`: se comprobó por búsqueda, y tres
que se habían colado (uno ya en la v1) se cambiaron por ejemplos inventados.

### Pendiente en el código del producto, no en la rúbrica

La rúbrica y `src/benchmarking/producto/nivel.py` ya no dicen lo mismo:

- `RANGOS` no tiene las palabras nuevas (`ASESOR`, `EJECUTIVO`, `ADMINISTRADOR`,
  `CONTROLLER`, `CONSULTOR`, `ENCARGADO`, `SUBJEFE`), ni las reglas de `TECNICO` como
  adjetivo o de «lo que va tras `DE`».
- `SENIORIDAD` separa `TECNICO ESPECIALISTA` de `TECNICO ... SR` (el único falso positivo
  de D-033), cuenta `CORPORATIVO` también como nombre de área, y no tiene `REGIONAL` /
  `ZONAL`.

Cambiarlo obliga a reconstruir la base y a volver a medir, así que es una decisión aparte.
