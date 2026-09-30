# Rúbrica: ¿son el mismo cargo?

La siguen igual quien juzga a mano y el LLM. Si las dos partes aplican reglas distintas, el
acuerdo entre ellas no mide nada.

**Versión 4 — 2026-09-30.** La vigente para juzgar a mano. Cambia solo el grado (paso 1):
ya no separa. La v3, con la que Gemini etiquetó la plata, sigue congelada en
`rubrica_mismo_cargo.md`; lo ya etiquetado se corrigió con `23_correccion_grado.py`
(Enmienda 5 de D-036). Todo lo que va antes de «Historial» es la rúbrica.

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
- **Códigos internos de la empresa**: números de tres cifras o más, y números pegados a una
  abreviatura. `SOLDADOR A` = `SOLDADOR I` (ver el grado, abajo),
  `INGENIERO INSPECTOR DE PROYECTOS 132` = `... 108`, `SENIOR` = `SENIOR C`, `PORTERO BR`,
  `AYUDANTE DE BODEGA DEV`, `PLANIFICADOR (R)`, `OPERARIO LT.4` = `OPERARIO LT.7`.
- **La unidad o el lugar donde se trabaja**, si la tarea es la misma:
  `PROFESOR TIEMPO COMPLETO FAC. HUMANIDADES` = `... FAC. HUMANIDADES - ESC. ARTES`.
- **Traducciones que repiten el título**: `GERENTE DE PROYECTOS 项目经理` = `GERENTE DE
  PROYECTOS`.
- **`GENERAL`** no es un nivel: `SUPERVISOR DE EMPAQUE` = `SUPERVISOR GENERAL DE EMPAQUE`,
  `JEFE SERVICIOS` = `JEFE DE SERVICIOS GENERAL`.

- **El grado dentro del cargo.** Un número o una letra que marca el grado de la escala
  interna **no hace distinto el puesto**, esté en uno solo de los títulos o en los dos con
  valor distinto. Es grado:
  - un número del 1 al 9 suelto (también `04`, `# 3`, o `1.` al principio);
  - un romano del I al X suelto;
  - una letra suelta, sola o entre paréntesis, salvo `E`, `Y`, `O`, `U`; la `A` solo al
    final del título;
  - `NIVEL`, `GRADO`, `CATEGORIA` o `LEVEL` delante de cualquiera de los anteriores.

  `AUXILIAR 1 DE COCINA` = `AUXILIAR 2 DE COCINA`, `LABORATORISTA I` = `LABORATORISTA II`,
  `CAJERO 3` = `CAJERO 5`, `AYUDANTE B DE MANTENIMIENTO` = `AYUDANTE C DE MANTENIMIENTO`,
  `OPERARIO CATEGORIA B` = `OPERARIO CATEGORIA C`, `TECNICO NIVEL 2` = `TECNICO NIVEL 4`,
  `OPERARIO 2 DE EMPAQUE` = `OPERARIO DE EMPAQUE`.

  **No es grado**, y se juzga como cualquier otra palabra:
  - una letra pegada a `.`, `/` o `&`, o junto a un `&`: son siglas o abreviaturas
    (`ANALISTA DE PLANTA R & D` ≠ `ANALISTA DE PLANTA R&M` si las áreas son otras);
  - la letra de un tipo: `CHOFER LICENCIA C` / `CHOFER LICENCIA E` se decide por la
    licencia, no como grado;
  - un número de dos cifras (`# 10`, `24 HORAS`): puede no ser un grado.

  La escalera de sueldos que marcaba el grado no se pierde: la recoge la banda, con la
  antigüedad, no el nombre del cargo.

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

### v4 (2026-09-30): el grado ya no separa

Decisión del autor, registrada en la Enmienda 5 de D-036 antes de abrir `prueba`. El paso 1
de la v3 tenía una «excepción del grado»: un ordinal del 1 al 9 o del I al X en los dos
títulos con valor distinto separaba. La v4 la quita y extiende la regla a las letras, que en
la v3 ya eran ruido de código. Revierte también lo que D-025 había excluido de la fusión por
errata (escalón por dígito, escalón romano, letra de grado).

Nada más cambia respecto de la v3. Los ejemplos nuevos son inventados y no coinciden con
ningún título de `13e` ni de `20` (comprobado por búsqueda).

La historia anterior (v1 a v3) está en `rubrica_mismo_cargo.md`.
