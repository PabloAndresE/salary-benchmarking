# Tesis y presentación

| Fichero | Para quién |
|---|---|
| `tesis.tex` | El documento académico: metodología, resultados y lo que se midió y descartó |
| `presentacion.tex` | **Presentación interna de ActuaLab**, 17 láminas: qué resuelve, cómo funciona, qué entrega |
| `figuras.py` | Genera las cuatro figuras que usan los dos |

```
pdflatex tesis.tex          # dos veces
pdflatex presentacion.tex   # dos veces
python docs/tesis/figuras.py
```

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

El destinatario son los compañeros de ActuaLab, así que la presentación enseña
**el producto final**: qué resuelve, cómo funciona y qué entrega. Deliberadamente
**no** entran las hipótesis que se midieron y se descartaron, los ejes que se
probaron y no se quedaron, ni el recorrido del proyecto. Todo eso está en
`tesis.tex`, que es el documento donde ese material sí cuenta —y donde un
catálogo de resultados negativos es una contribución, no una digresión.

Si hiciera falta una versión para el tribunal, es ese mismo material el que hay
que volver a meter: está en `docs/registro_decisiones.md` y en el historial de
git.

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
