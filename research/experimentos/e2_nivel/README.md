# E2 — El eje de nivel

Cuatro mediciones para contestar si la jerarquía del puesto sirve en el producto, y cómo
meterla. **La primera mejora significativa del proyecto sale de aquí.**

Origen: D-012 midió que los embeddings son ciegos a la jerarquía (`GERENTE DE AUDITORIA` y
`JEFE DE AUDITORIA` a 0,944 de similitud) y D-013 que el nivel vale 2,11× en pago. El
vecindario del producto promediaba `SUPERVISOR DE CAJA` con `AUXILIAR DE CAJA`.

**Todo corre sobre el 80% de train. El 20% de test no se toca.**

| Script | Qué contesta | Resultado |
|---|---|---|
| `01_clasificador_de_nivel.py` | ¿Se puede predecir el nivel desde el texto? | **No.** 98,9% de acierto pero sólo porque lee la palabra de vuelta; sobre títulos sin rango vuelca el 58% al nivel 1 y la escalera sale 1,48× no monótona |
| `02_enmascarar_el_rango.py` | ¿Y si se tapa el rango al entrenar, para forzar la generalización? | **Tampoco.** 1,43×, no monótona. El nivel está en la palabra o no está en ninguna parte |
| `03_area_enmascarada_y_nivel_lexico.py` | ¿Ordena el pago el nivel léxico **dentro** de la misma área? | **Sí, y limpio.** Monótona, 2,37× del escalón 1 al 5, ω² = 0,2878 con placebo −0,0000 |
| `04_mejora_el_producto.py` | De las cuatro formas de meterlo, ¿cuál mejora? | **Título completo + corrección de escalón**, −0,0130 con IC [−0,0202, −0,0002] |

## Lo que decidió `04`

Cuatro variantes, dos decisiones cruzadas: tapar o no el rango para buscar vecinos, y
filtrar o corregir a los de otro escalón. Contraste pareado, 4.319 empresas, medido **sólo
sobre los títulos por analogía y con palabra de rango** — que es donde las variantes se
diferencian.

| | efecto | IC 95% | |
|---|---|---|---|
| **completo + corregir** | **−0,0130** | [−0,0202, −0,0002] | **mejora** |
| completo + filtrar | −0,0027 | [−0,0148, +0,0145] | sin efecto |
| tapado + filtrar | −0,0081 | [−0,0303, +0,0301] | sin efecto |
| tapado + corregir | +0,0600 | [+0,0376, +0,0800] | **empeora** |

Y el contraste directo entre las dos formas de usar la jerarquía:
`corregir − filtrar = −0,0102`, IC [−0,0208, −0,0024]. **Gana corregir.**

**Tapar el rango empeora.** Parecía buena idea: dejaba el área limpia y el léxico separaba
los escalones. Pero la palabra de rango no dice sólo el rango — `OPERARIO DE PRODUCCION` y
`ANALISTA DE PRODUCCION` quedan idénticos al taparla y son trabajos distintos. `lambda` lo
delataba antes de medirlo: **1,90 en crudo contra 2,71 enmascarado**, o sea que en el
espacio tapado la misma distancia coseno corresponde a más diferencia de pago.

**Corregir gana a filtrar** porque descartar tira información. Un `JEFE DE BODEGA` sí sabe
algo sobre lo que paga una bodega; basta con restarle la diferencia de escalón.

## Dos errores de medición que costaron dos corridas

**Potencia.** Con 900 empresas las cuatro variantes salían indistinguibles entre sí. No
era un empate: era falta de potencia. Con 4.319 aparecen tres diferencias significativas.

Lo que estrecha el intervalo son **más empresas**, no más réplicas de bootstrap: las
réplicas reducen el error de simulación, no la variabilidad real del muestreo.

**Población.** La primera versión medía sobre todos los títulos por analogía, pero el
filtro sólo actúa donde el puesto tiene palabra de rango — en el resto las variantes hacen
lo mismo. Esos empates forzados empujaban cualquier diferencia hacia cero. Es el mismo
error que arruinó `e1_premisa/13`.

## Cómo correrlos

```bash
export PIPELINE_SALT=<cualquiera>
export PYTHONPATH=src
.venv/Scripts/python.exe research/experimentos/e2_nivel/04_mejora_el_producto.py
```

Las salidas commiteadas están en `salidas/`.
