# Sinónimos v1 (D-046, D-047)

Pares de títulos que son el mismo cargo aunque se escriban con palabras distintas (`CHOFER` / `CONDUCTOR`,
`TRABAJADOR AGRICOLA` / `JORNALERO`). Salen de las propuestas de Gemini (`46`) para los 91 cargos con más
personas, revisadas una por una por el autor (`56_sinonimos_para_aprobar.csv`), con las correcciones de la
revisión con Claude: el ancla restaurada al título de la base, seguridad ocupacional frente a vigilancia, y
los puentes genéricos que encadenaban oficios (campo con planta, venta con crédito, `AUXILIAR GENERAL`,
`ASISTENTE`, el grupo ambiguo «de servicio»).

**No fusionan la base**: medido, empeoran las bandas (D-046). Se usan en el buscador de cargos del front
(`/puestos`): si lo escrito es uno de estos títulos, el otro se sugiere justo después, marcado como sinónimo.

## `consulta.csv`: lo que alguien escribe → un cargo de la base

Para títulos que **no existen en la base** y no se parecen por las letras al cargo que nombran
(`DENTISTA` → `ODONTOLOGO`): ni los embeddings ni el juez los encuentran bien. Dos columnas: `escrito`
(lo que se teclea; se normaliza con la capa 0) y `cargo_base` (un título que sí existe en la base). En
`/puestos`, el grupo de `cargo_base` sale **primero**, marcado como sinónimo. Lo llena el autor; una fila
cuyo `cargo_base` no esté en la base se ignora.
