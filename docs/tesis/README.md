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
3. **Faltan las figuras.** El texto se sostiene sin ellas, pero la escalera de
   niveles, la descomposición del error y la distribución de espesor del catálogo
   piden gráfico.

## Trazabilidad

Cada cifra del documento existe en `docs/registro_decisiones.md` o en
`docs/mediciones.md`, y cada medición tiene su script en
`research/experimentos/`. Comprobado: las 17 cifras principales aparecen en las
fuentes.
