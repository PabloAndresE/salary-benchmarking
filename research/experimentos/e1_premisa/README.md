# E1 — La premisa central, medida

Cinco mediciones que reformularon el alcance de la tesis (**D-013**, `mediciones.md` §15).

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
