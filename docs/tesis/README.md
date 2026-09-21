# Tesis y presentación

| Fichero | Para quién |
|---|---|
| `tesis.tex` | El documento académico: metodología, resultados y lo que se midió y descartó |
| `presentacion.tex` | **Presentación de defensa** (12 láminas + cierre). El problema, el método y los resultados medidos |
| `presentation.sty` | La plantilla, vendorizada sin modificar. Ver abajo |
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
`beamer` o `beamertheme-metropolis`, es eso.

Estado: `tesis.pdf` 20 páginas sin un solo desbordamiento; `presentacion.pdf`
13 páginas con un desbordamiento vertical de 4,2 pt, que no se ve.

## La plantilla de la presentación

`presentation.sty` es [pmichaillat/latex-presentation](https://github.com/pmichaillat/latex-presentation),
copiado sin modificar, con su licencia MIT en `presentation-LICENSE.md`. La
plantilla espera las figuras en un único PDF multipágina; aquí se usan los cuatro
PDF sueltos que ya emite `figuras.py`, y eso es lo único que se aparta de ella.

Usa Source Sans 3, `MnSymbol` y `mathastext`, y en MiKTeX **no compila de fábrica**:
`sourcesanspro.sty` resuelve hoy a Source Sans 3, pero `updmap.cfg` solo registra
`SourceSansPro.map`. Sin la entrada de Source Sans 3, pdfTeX no encuentra la
fuente, cae a las Computer Modern de mapa de bits y `microtype` aborta con
`auto expansion is only possible with scalable fonts` —un error que no nombra la
fuente culpable—. En una máquina nueva:

```
mpm --install=sourcesans --install=sourcesanspro --install=sourcecodepro
mpm --install=mnsymbol --install=mathalpha --install=mathastext
echo 'Map SourceSansThree.map' >> <raiz-miktex>/miktex/config/updmap.cfg
miktex fontmaps configure
```

Cosas que costaron y conviene no repetir:

- **`\usepackage{lmodern}` no es opcional en `tesis.tex`.** Sin él, `microtype`
  pide expansión de fuente sobre las Computer Modern de mapa de bits y aborta la
  compilación. La presentación no lo necesita porque trae su propia fuente
  escalable —una vez registrado el mapa.
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
