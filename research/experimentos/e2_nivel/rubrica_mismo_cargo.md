# Rúbrica: ¿son el mismo cargo?

La siguen igual quien juzga a mano y el LLM. Si las dos partes aplican reglas distintas, el
acuerdo entre ellas no mide nada.

**Versión 3 — 2026-09-25.** Todo lo que va antes de «Historial» es la rúbrica, y es lo que
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

Si lo que va tras `/` no es un puesto sino una función más (`SUPERVISOR DE EMPAQUE /
DESPACHO`), no es un título doble: es una función añadida (paso 4).

## Cómo decidir: cinco pasos, en orden

Recorre los pasos en orden. El primero que diga `no` decide. Si ninguno lo dice, es `si`.

### Paso 1. Quita el ruido: nada de esto hace distintos dos títulos

- **Ortografía, erratas, abreviaturas y espacios de más o de menos**: `SUPERV.` =
  `SUPERVISOR`, `AYUD.` = `AYUDANTE`, `DESAROLO` = `DESARROLLO`, `ADM.` = `ADMINISTRACION`,
  `BODGA` = `BODEGA`, `AUXILIARCONTABLE` = `AUXILIAR CONTABLE`.
- **Género y número**: `PROFESORA` = `PROFESOR`, `ENFERMERAS` = `ENFERMERO`.
- **Conectores, relleno y orden de las palabras**: `DE`, `DEL`, `Y`, `/`, `-`, `EN EL AREA
  DE`. Las mismas palabras en otro orden son el mismo título.
  `ASISTENTE DE BODEGA` = `ASISTENTE EN EL AREA DE BODGA`.
- **Códigos internos de la empresa**: letras sueltas, números de tres cifras o más, y
  números pegados a una abreviatura. `SOLDADOR A` = `SOLDADOR I`,
  `INGENIERO INSPECTOR DE PROYECTOS 132` = `... 108`, `SENIOR` = `SENIOR C`, `PORTERO BR`,
  `AYUDANTE DE BODEGA DEV`, `PLANIFICADOR (R)`, `OPERARIO LT.4` = `OPERARIO LT.7`.
- **La unidad o el lugar donde se trabaja**, si la tarea es la misma:
  `PROFESOR TIEMPO COMPLETO FAC. HUMANIDADES` = `... FAC. HUMANIDADES - ESC. ARTES`.
- **Traducciones que repiten el título**: `GERENTE DE PROYECTOS 项目经理` = `GERENTE DE
  PROYECTOS`.
- **`GENERAL`** no es un nivel: `SUPERVISOR DE EMPAQUE` = `SUPERVISOR GENERAL DE EMPAQUE`,
  `JEFE SERVICIOS` = `JEFE DE SERVICIOS GENERAL`.

**Excepción: el grado.** Un ordinal pequeño (del 1 al 9, o del I al X) que aparece en
**los dos** títulos con valor **distinto** es un grado de la escala interna, y separa →
`no`. `AUXILIAR 1 DE COCINA` ≠ `AUXILIAR 2 DE COCINA`, `LABORATORISTA I` ≠
`LABORATORISTA II`, `CAJERO 3` ≠ `CAJERO 5`. Si el número está en un solo
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
sugiere el nombre: en estas nóminas un `EJECUTIVO DE CUENTAS` es personal de primera
línea, no un directivo.

**Cómo se lee el nivel de un título:**

- **Es el nivel de quien ocupa el cargo.** Si un título tiene varias palabras de rango,
  cuenta la **más alta**: `ANALISTA AUXILIAR DE COMPRAS` es un analista,
  `SUPERVISOR JEFE DE TURNO` es un jefe.
- **Lo que va detrás de `DE` / `DEL` no cuenta**: dice a quién apoya, y eso es el paso 5.
  `ASISTENTE DE ADMINISTRADOR DE TIENDA` es un asistente (nivel 1).
- **`TECNICO` y `ESPECIALISTA` solo son palabras de rango si abren el título.** En
  cualquier otra posición, `TECNICO` es un adjetivo y no cuenta (`AUXILIAR TECNICO DE
  BODEGA` es un auxiliar), y `ESPECIALISTA` o `ESPECIALIZADO` son la marca de
  senior del paso 3 (`TECNICO ESPECIALISTA` es un técnico senior).
- **Este paso solo decide si LOS DOS títulos tienen palabra de rango.** Si solo uno la
  tiene, o ninguno, sigue a los pasos siguientes. Las palabras que no están en la tabla
  (`PROGRAMADOR`, `INGENIERO`, `PROFESOR`, `CHOFER`, `VENDEDOR`, `GESTOR`, `LIDER`, …) no
  marcan nivel.

**Distinto nivel → `no`.** `ASISTENTE DE SERVICIO AL CLIENTE` = `ASESOR DE SERVICIO AL
CLIENTE` (los dos nivel 1), pero `EJECUTIVO DE CUENTAS` ≠ `JEFE DE CUENTAS`,
`ADMINISTRADOR DE PLANTA` ≠ `JEFE ADMINISTRATIVO DE PLANTA`, `ENCARGADO DE ARCHIVO` ≠
`JEFE DE ARCHIVO`, `SUBGERENTE DE AGENCIA` ≠ `SUBJEFE DE AGENCIA`.

### Paso 3. La antigüedad y el alcance dentro del escalón: si no coinciden, `no`

| Menos | Sin marca | Más |
|---|---|---|
| TRAINEE, JR, JUNIOR, SOUS | — | SR, SENIOR; ESPECIALISTA o ESPECIALIZADO detrás de otra palabra; CORPORATIVO / CORPORATIVA |

Y aparte, el **ámbito**: `REGIONAL`, `ZONAL`.

- **Si un título tiene marca y el otro no, o tienen marcas distintas → `no`.**
  `ANALISTA INTELIGENCIA DE NEGOC` ≠ `ANALISTA JUNIOR - INTELIGENCIA DE NEGOCIOS`,
  `CHEF DE COCINA` ≠ `SOUS CHEF DE COCINA`, `SUPERVISOR DE GARANTIAS` ≠
  `SUPERVISOR CORPORATIVO DE GARANTIAS`, `GERENTE DE OPERACIONES SIERRA` ≠
  `GERENTE REGIONAL DE OPERACIONES SIERRA`, `COORDINADOR REGIONAL DE CREDITO` ≠
  `COORDINADOR ZONAL DE CREDITO`.
- **La misma marca con otra grafía no separa.** `JR.` = `JUNIOR`, `SR.` = `SENIOR`,
  `TECNICO ESPECIALISTA EN MANTENIMIENTO` = `TECNICO DE MANTENIMIENTO SR.`
- **`CORPORATIVO` no cuenta cuando es parte del nombre de un área o de un negocio**
  (`BANCA CORPORATIVA`, `PROCESOS CORPORATIVOS`, `VENTAS CORPORATIVAS`, `CLIENTES
  CORPORATIVOS`): `JEFE DE COMUNICACION` = `JEFE DE COMUNICACION CORPORATIVA`. Sí cuenta cuando
  dice el alcance del cargo: `JEFE CORPORATIVO DE AUDITORIA`.

### Paso 4. La función PRINCIPAL: si es otra, `no`

Son el mismo puesto si comparten la **función principal** —la que los dos títulos nombran
en común— y el nivel. Este paso se aplica con amplitud: separa poco.

- **Una SEGUNDA función distinta no separa.** `JEFE DE VENTAS Y MARKETING` = `JEFE DE
  VENTAS Y SERVICIO AL CLIENTE`, `JEFE DE ALMACEN` = `JEFE ALMACENAMIENTO Y DESPACHO`.
- **Especificar o acotar la misma función no separa.** `ANALISTA DE COMPRAS` = `ANALISTA
  DE COMPRAS NACIONALES E IMPORTACIONES`, `ANALISTA DE BASE DE DATOS` = `ANALISTA DE BASE
  DE DATOS Y APLICACIONES`.
- **La misma tarea sobre otro objeto no separa.** `ASISTENTE DE DOCUMENTACION EXPORT JR.`
  = `ASISTENTE DE DOCUMENTACION IMPORT JR.`
- **Nombres distintos para la misma tarea → `si`.** `PROGRAMADOR DE SOFTWARE SENIOR` =
  `ESPECIALISTA DE SOFTWARE SENIOR`, `ANALISTA DE SISTEMAS TELECOMUNICACIONES` =
  `ANALISTA DE TELECOMUNICACIONES`.

Solo separa, → `no`:

- **Función principal distinta**, sin ninguna en común: `JEFE DE COMPRAS` ≠ `JEFE DE
  TESORERIA`.
- **Lo añadido es OTRO OFICIO certificado**, con su propio mercado: `JEFE DE MONTAJE` ≠
  `JEFE DE MONTAJE Y SOLDADURA`.
- **Especialidades con mercados claramente distintos**: `INGENIERO BACK-END SENIOR` ≠
  `INGENIERO FRONT-END SENIOR`.

**En la duda** entre dos títulos que comparten la función principal: `si`.

### Paso 5. A quién apoya: un mando no es un área

Si uno de los títulos es `ASISTENTE`, `AUXILIAR`, `AYUDANTE` o `SECRETARIA` **de un
mando** —una palabra de nivel 3 o más: `SUPERVISOR`, `COORDINADOR`, `JEFE`, `GERENTE`,
`DIRECTOR`…— y el otro apoya a un área, son puestos distintos → `no`.
`ASISTENTE DE PRODUCCION` ≠ `ASISTENTE DEL SUPERVISOR DE PRODUCCION`.

No separa:
- **Si lo apoyado no es un mando** (`TECNICO`, `OPERADOR`, `ADMINISTRADOR`, `CONTROLLER`):
  `AYUDANTE DE SOLDADOR` = `AYUDANTE DE SOLDADURA`, `ASISTENTE DE ADMINISTRADOR DE
  TIENDA` = `ASISTENTE ADMINISTRATIVO DE TIENDA`.
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

> **La v3 está CONGELADA (D-035, 2026-09-25).** No se toca nada de lo que va antes de este
> historial, ni una tilde: su hash (`118be8eb1105`) es lo que identifica las respuestas del
> LLM, y cambiarlo las deja huérfanas. Cualquier cambio es una v4, y obliga a repetir el
> piloto. Las notas nuevas van aquí, debajo.

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

### v3 (2026-09-25): el paso 4, tras el piloto con `gemini-3.8-flash`

**El piloto con la v2 pasó la compuerta por poco** (kappa 0,640 / 0,662, recall de `no`
0,93 / 0,95, coherencia 0,970, AUC 0,880 sobre `calibra`). Y lo hizo con la medición
inflada: la v2 usaba 34 títulos de `calibra` como ejemplos, con su respuesta, y el LLM los
veía. Se habían elegido de `calibra` para proteger `prueba`, sin ver que así se contaminaba
la mitad con la que se decide.

**El desacuerdo tenía una sola dirección.** De 33, 29 eran «juez `si`, LLM `no`», casi
todos en el paso 4: el juez junta dos títulos que comparten la función principal aunque la
segunda sea otra, y el texto de la v2 («otro oficio», «especialidades que el mercado paga
distinto») era más estricto que ese criterio. Etiquetar 10.000 así habría enseñado al
modelo a separar de más, justo donde el producto ya se queda corto (estrato `bajo`).

**Qué cambia:**

- **El paso 4 se reescribe** alrededor de la función principal compartida, y en la duda
  dice `si`. Lo aprobó el autor.
- **Todos los ejemplos que ve el LLM son inventados**, sin ningún título de los 400. Así
  el acuerdo en `calibra` de la v3 mide la rúbrica, y no la memoria de sus ejemplos.
- **Choca con dos de los 48** de `13a`, que no son el patrón de oro: #32 (`JEFE DE
  INGENIERIA Y MANTENIMIENTO` / `… INFRAESTRUCTURA Y MANTENIMIENTO`) y #22 (`JEFE DE
  PROCESOS Y SISTEMA` / `JEFE ORGANIZACION Y PROCESOS`), juzgados `no` aunque comparten
  una función. En los 400 el juez resolvió igual casos así con `si` (#296, #300).

### Pendiente en el código del producto, no en la rúbrica

La rúbrica y `src/benchmarking/producto/nivel.py` ya no dicen lo mismo:

- `RANGOS` no tiene las palabras nuevas (`ASESOR`, `EJECUTIVO`, `ADMINISTRADOR`,
  `CONTROLLER`, `CONSULTOR`, `ENCARGADO`, `SUBJEFE`), ni las reglas de `TECNICO` como
  adjetivo o de «lo que va tras `DE`».
- `SENIORIDAD` separa `TECNICO ESPECIALISTA` de `TECNICO ... SR` (el único falso positivo
  de D-033), cuenta `CORPORATIVO` también como nombre de área, y no tiene `REGIONAL` /
  `ZONAL`.

Cambiarlo obliga a reconstruir la base y a volver a medir, así que es una decisión aparte.
