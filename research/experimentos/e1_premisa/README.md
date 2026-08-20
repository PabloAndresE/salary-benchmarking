# E1 — La premisa central, medida

Diez mediciones que reformularon el alcance de la tesis (**D-013**, `mediciones.md` §15).

Origen: el EDA se hizo con la composición del pago al 2,7% y adoptó como hipótesis central —por
eliminación— que esa composición explicaría la dispersión que `CARGO` no explica. Nunca se
comprobó. Estos scripts lo comprueban.

**Todo corre sobre el 80% de train. El 20% de test no se toca.**

| Script | Qué contesta | Resultado |
|---|---|---|
| `01_premisa_composicion.py` | ¿La composición explica la dispersión que `CARGO` deja? | ω² 0,0056 contra placebo 0,0000. Señal real, diminuta |
| `02_premisa_por_tamano_celda.py` | ¿Es un artefacto de celdas mal estimadas? | No: 0,0055 / 0,0058 / 0,0052 según el mínimo de personas por etiqueta |
| `03_premisa_continua_fuera_de_muestra.py` | ¿Y como variable continua, con un modelo flexible, fuera de muestra? | R² +0,0042 → reduce la sd un **0,21%**. Antigüedad +0,0114 |
| `04_descomposicion_del_error.py` | ¿Cuánto del error de `CARGO` es irreducible y cuánto mala estimación? | τ 0,2917, σ 0,1423. **Techo de mejora: 10,9%**, y el 44,6% del error en celdas de 1–2 empresas es estimación |
| `05_paga_el_nivel_y_techo_estratificado.py` | ¿Paga el rango jerárquico? ¿Y el techo fuera de la zona del SBU? | **ω² 0,2462 → 13,2%**, escalera monótona, 2,11× de nivel 1 a 5. Techo 12,1% → 14,4% |


## Segunda tanda (`06`–`10`): la ocupación latente, y el otro fallo de la etiqueta

`01`–`05` mataron la composición como eje. Estos preguntan qué la sustituye. La dirección que
pedía el director era **inferir la ocupación real desde varias señales ruidosas**, porque el
título del cargo miente. Medido, esa dirección no tiene material — y aparece otra que sí.

| Script | Qué contesta | Resultado |
|---|---|---|
| `06_anclaje_a_la_empresa.py` | ¿Y si la referencia se ancla a la nómina del propio cliente? | **−12,8% de MAE**, más que el techo de 10,9% por agrupar mejor. Pero no mejora la cobertura y **es otra tarea**: equidad interna, no nivel de mercado |
| `07_hay_dos_vistas.py` | ¿Hay dos vistas de la ocupación (texto y no-texto)? | Texto R² +0,347; sin-texto +0,091, y **84% redundante**. Añade +0,015 sobre el texto |
| `08_vistas_y_desacuerdo.py` | Con las vistas en bloques separados, ¿y detecta etiquetas mal puestas? | Cargo +0,367; **todo menos el cargo, +0,059**. El detector marca el **88,5%** y en los marcados gana la etiqueta original: **falla su propio criterio** |
| `09_centro_de_costo_con_embeddings.py` | ¿Sobrevive el centro de costo leído por significado y no por caracteres? | **No.** R² −0,059 por significado frente a −0,123 por caracteres. Sigue siendo peor que no predecir |
| `10_etiquetas_genericas.py` | El otro fallo de la etiqueta: demasiado anchas. ¿Las parte el sector? | **Sí: −13,2% de sd** (placebo 0,9%), −17,9% con tamaño. Aplica al 71,3% de esa gente |

### Dos avisos de lectura

**`07` dice que la composición vale 2,4% y D-013 dice 0,21%. No se contradicen:** `07`
residualiza sólo contra la empresa y `03` contra empresa **y** cargo. Esa diferencia *es* el
hallazgo — la composición parecía informativa porque hacía de proxy de la ocupación. Si los dos
números aparecen en la tesis sin esta frase, es una contradicción aparente.

**El estadístico de `10` §2 estaba mal elegido en la primera versión.** Un ω² de sector agrupando
las 381 etiquetas mide *"¿hay un efecto de sector igual para todas?"* y da 0,019: casi nada. La
pregunta útil es *"cuando comparo un `VENDEDOR`, ¿ayuda saber su sector?"*, que es una
**interacción**. Medida así da 13,2% de sd. Un `OBRERO` es otra cosa según el sector (ω² 0,43) y un
`TRABAJADOR AGRICOLA` es el mismo en todas partes (0,02): promediar entre etiquetas lo borra. La
lectura impresa original concluía lo contrario de lo que dicen los datos.

**Límite de `10`:** es descomposición de varianza, no R² fuera de muestra. El placebo descuenta el
artefacto de grados de libertad, pero falta una validación held-out como la de `03`.

Las salidas commiteadas están en `salidas/`.

## Cómo correrlos

```bash
export PIPELINE_SALT=<cualquiera>   # no se usa: no hay anonimización aquí
export PYTHONPATH=src
.venv/Scripts/python.exe research/experimentos/e1_premisa/03_premisa_continua_fuera_de_muestra.py
```

## Por qué existen estos ficheros y no solo el número en un documento

Un evaluador externo grepeó τ=0,2917, el techo del 12,1% y ω²=0,2462 en el repositorio y encontró
**cero coincidencias**: las mediciones vivían en scripts temporales y solo el resultado estaba
contado de palabra. Un número que no se puede reproducir no se defiende. Ver D-013 §Consecuencia
de proceso.
