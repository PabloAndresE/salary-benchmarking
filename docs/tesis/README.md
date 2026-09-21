# Documento de tesis

`tesis.tex` — redacción del problema y de cómo se resolvió, a partir de
`registro_decisiones.md` (D-001 … D-031) y `mediciones.md`.

## Compilar

```
pdflatex tesis.tex     # dos veces, para el índice y las referencias
```

No hay LaTeX instalado en la máquina donde se escribió, así que **el documento no
se ha compilado todavía**. Está validado estructuralmente —entornos balanceados,
llaves, delimitadores de matemática, columnas de tabla— pero la primera
compilación puede sacar avisos de formato.

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
