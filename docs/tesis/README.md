# Tesis y presentación

| Fichero | Para quién |
|---|---|
| `tesis.tex` | El documento académico: metodología, resultados y lo que se midió y descartó |
| `presentacion.tex` | **Presentación comercial** (Beamer, 11 láminas). Ordenada por las preguntas que hace un cliente, no por la derivación del método |
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

Estado: `tesis.pdf` 20 páginas sin un solo desbordamiento; `presentacion.pdf` 11
láminas con dos desbordamientos verticales de 15,6 pt y 8,8 pt, que no se ven.

Dos cosas que costaron y conviene no repetir:

- **`\usepackage{lmodern}` no es opcional.** Sin él, `microtype` pide expansión
  de fuente sobre las Computer Modern de mapa de bits y aborta la compilación.
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
