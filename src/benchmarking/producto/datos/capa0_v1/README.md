# Capa 0 v1 — diccionarios aprobados (D-040)

Solo las filas **aprobadas por el autor**. Las reglas proponen (`research/experimentos/e2_nivel/36_capa0_listas_y_colapsos.py`
y sus listas `36_aprobar_*.csv`) y el autor aprueba; lo que no se revisa no se aplica.

| archivo | columnas | qué hace |
|---|---|---|
| `erratas.csv` | `rara,corregida` | palabra con errata → palabra correcta; solo si el título corregido ya existe en la base |
| `abreviaturas.csv` | `abreviatura,expansion` | `ASIST.` → `ASISTENTE`; se aplica antes de quitar la puntuación |
| `genero.csv` | `femenino,masculino` | `VENDEDORA` → `VENDEDOR`, solo terminaciones de oficio y adjetivo |

**Estado (2026-10-02): vacíos, a la espera de la revisión.** Una base construida con `capa0` guarda
dentro de su `.npz` los diccionarios con que se construyó, y la consulta usa esos, no estos.
