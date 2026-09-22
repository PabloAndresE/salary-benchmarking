# Tesis y presentación

| Fichero | Para quién |
|---|---|
| `tesis.tex` | El documento académico: metodología, resultados y lo que se midió y descartó |
| `presentacion.tex` | **v1** (19 láminas). Ordenada por las reglas del método y con las cifras medidas |
| `presentacion_v2.tex` | **v2** (22 láminas). Una idea por lámina, con la cifra como prueba; sección de resultados reescrita en torno a qué se aprendió |
| `figuras.py` | Genera las cuatro figuras que usan los dos |

```
pdflatex tesis.tex             # dos veces
pdflatex presentacion.tex      # dos veces  (v1)
pdflatex presentacion_v2.tex   # dos veces  (v2)
python docs/tesis/figuras.py
```

## Las dos versiones de la presentación

Se conservan las dos a propósito; ninguna sustituye a la otra todavía.

- **v1** cuenta **qué se midió**. Va regla por regla y cierra con una tabla de nueve
  cifras. Sirve para responder preguntas concretas.
- **v2** cuenta **qué se aprendió**. Cada lámina defiende una idea y la cifra es su
  prueba, con un máximo de dos números por lámina. La sección de resultados está
  reescrita: entra que cobertura y precisión son ganancias distintas, que un promedio
  de cobertura del 53 % escondía un rango del 18 % al 98 %, y que la etiqueta de
  confianza era algebraicamente incapaz de salir de ALTA. Nada de eso estaba en la v1.

---

# Documento de tesis

`tesis.tex` — redacción del problema y de cómo se resolvió, a partir de
`registro_decisiones.md` (D-001 … D-031) y `mediciones.md`.

## Compilar

```
pdflatex tesis.tex          # dos veces, para el índice y las referencias
pdflatex presentacion.tex   # dos veces, para la numeración de láminas
```

Compilan los dos. La máquina tiene MiKTeX 25.12 (`winget install --id
MiKTeX.MiKTeX --scope user`); el resto de paquetes los instala MiKTeX solo la
primera vez que los ve. Si aparece una consola pidiendo permiso para instalar
`beamer`, es eso.

Estado: los dos sin un solo desbordamiento. `tesis.pdf` 20 páginas,
`presentacion.pdf` 17.

## Qué entra en la presentación y qué no

El destinatario son los compañeros de ActuaLab, **que ya conocen el producto**.
La presentación no explica qué entrega el sistema ni para qué sirve: va sobre
**cómo se agrupan los puestos** y sobre **lo que se midió**.

Dos exclusiones deliberadas:

- **Nada de códigos de decisión** (`D-013`, `D-022`…). Son referencias internas
  de `docs/registro_decisiones.md` y fuera de ese fichero no significan nada.
  Cuando una cifra viene de un experimento, se describe el experimento.
- **Nada de hipótesis descartadas** ni del recorrido del proyecto. Eso está en
  `tesis.tex`, que es donde un catálogo de resultados negativos es una
  contribución y no una digresión.

Y dos obligaciones que tiran en direcciones opuestas:

- Las reglas se **explican**, no se nombran. «Enlace completo, umbral 0,95» es
  una etiqueta; hay que decir por qué manda el par peor y qué pasaba con el
  enlace simple. Las constantes salen de
  `src/benchmarking/producto/base_referencia.py`, no de la memoria.
- Pero **la consolidación cabe en dos láminas**. Se explica cada decisión y se
  deja fuera lo que solo la ilustra. Quien quiera el detalle tiene el código, que
  está comentado justo para eso.

Y un registro: **descriptivo y plano**. Se enuncia la regla y la cifra. Nada de
cerrar una lámina con una máxima («el daño nunca vino de X sino de Y»), nada de
antítesis con dos puntos («no es A: es B»), y nada de atribuirle intenciones al
sistema. El título de una lámina nombra su contenido; no lo resume en una frase
ingeniosa.

Si hiciera falta una versión para el tribunal, es ese material el que hay que
volver a meter: está en `docs/registro_decisiones.md` y en el historial de git.

## El estilo de la presentación

Tema `Madrid` de beamer, de serie: barra de título, pie con autor, título,
fecha y número de lámina, y bloques redondeados. Sin tema de color, sin paquetes
de terceros y sin un solo color definido a mano. Compila con una instalación
básica de LaTeX en cualquier máquina.

Las versiones entre corchetes de `\title`, `\author` e `\institute` son las que
van al pie, que es estrecho: ahí no cabe el título entero.

Se probó una plantilla externa ([pmichaillat/latex-presentation](https://github.com/pmichaillat/latex-presentation))
y se descartó. Queda anotado lo que costó, porque el síntoma no señalaba la
causa: usa Source Sans 3, y `sourcesanspro.sty` resuelve hoy a esa familia
mientras que el `updmap.cfg` de MiKTeX solo registra `SourceSansPro.map`. Sin la
entrada de Source Sans 3, pdfTeX no encuentra la fuente, cae a las Computer
Modern de mapa de bits y `microtype` aborta con `auto expansion is only possible
with scalable fonts`, un error que no nombra la fuente culpable. Se arregla con
`echo 'Map SourceSansThree.map' >> <raiz-miktex>/miktex/config/updmap.cfg` y
`miktex fontmaps configure`; queda hecho en esta máquina.

Cosas que costaron y conviene no repetir:

- **`\usepackage{lmodern}` no es opcional**, en ninguno de los dos. Sin él,
  `microtype` pide expansión de fuente sobre las Computer Modern de mapa de bits
  y aborta la compilación; y el PDF saldría con texto que no se puede buscar ni
  copiar.
- **El porcentaje no va dentro de `$...$`.** `babel-spanish` decide el espacio
  antes del `%` mirando `\lastskip`, que en modo matemático mide en `mu` y no en
  `pt`; mezcla unidades y TeX aborta. Se escribe `$-$6{,}0\,\%`, con solo el
  signo en matemáticas. El PDF salía igual, así que el error se iba sin verse.
- **El cuerpo se escribió sin tildes** y hubo que reponerlas a posteriori, en
  siete pasadas. Reponer tildes con sustitución ciega es peor de lo que parece:
  `esta`/`está` y `que`/`qué` dependen de la sintaxis, no de la palabra. Lo que
  se corrigió fue solo lo inequívoco; lo ambiguo se dejó a propósito, porque una
  tilde de más es tan error como una de menos. **En el próximo documento, se
  escribe con tildes desde el primer renglón.**

## Antes de entregarlo

1. **Las cuatro referencias marcadas `[VERIFICAR]`** en la bibliografía: falta
   confirmar paginación, año o venue. No se citan de memoria en la defensa sin
   comprobarlas.
2. **Las cifras del capítulo de resultados son de validación, no de test.** El
   20% de test sigue sin tocarse, y eso está dicho en Limitaciones. Cuando se
   toque, hay que decidir si el capítulo se reescribe o se añade uno.
3. ~~Faltan las figuras.~~ Hechas: `figuras.py` genera las tres en PDF vectorial.

## Las figuras

```
python docs/tesis/figuras.py     # desde la raiz del repo
```

| Figura | Qué muestra | Datos |
|---|---|---|
| `espesor_catalogo.pdf` | 78% de los puestos tiene 1 empresa y cubre el 21% de la gente; el 1% con 30+ cubre el 46% | en vivo desde `demo/base_v15.npz` |
| `descomposicion_error.pdf` | Cuánto del error es reducible agrupando mejor (12,1% y 13,2%) | `mediciones.md` §15.3 |
| `escalera_niveles.pdf` | El recorrido de 2,11× entre el escalón 1 y el 5 | `mediciones.md` §15.4 |
| `sesgo_tamano.pdf` | El error de no comparar por tamaño: de −56%/+82% a −12%/+18% | `mediciones.md` §17.6 |

Se guardan también en PNG, solo para poder mirarlas sin abrir un visor de PDF; el
documento usa los PDF.

La paleta es la de referencia del método de visualización, validada: ΔE 24,7 en
visión con deficiencia de color entre las dos series, contra un umbral de 8. Y
**todas las barras llevan su valor impreso**, así que la identidad nunca depende
solo del color — una tesis se imprime en blanco y negro.

## Trazabilidad

Cada cifra del documento existe en `docs/registro_decisiones.md` o en
`docs/mediciones.md`, y cada medición tiene su script en
`research/experimentos/`. Comprobado: las 17 cifras principales aparecen en las
fuentes.
