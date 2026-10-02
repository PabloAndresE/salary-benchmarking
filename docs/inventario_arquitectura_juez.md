# Inventario — archivos de la arquitectura del juez de «mismo cargo» (D-036)

Para la limpieza final: lo que está aquí **no se borra** sin revisar antes esta lista.
Actualízala cada vez que se cree un guion o una salida de esta línea de trabajo.

Leyenda de la columna *git*:
- **versionado**: está en el repositorio.
- **local**: está en `.gitignore` (títulos de clientes, LOPDP) y **solo existe en esta máquina**. Si se borra, no hay copia.
- **versionado (-f)**: sigue en `.gitignore`, para que una regeneración no entre sola, pero se añadió a mano con `git add -f` (`26cb1d3`, decisión del autor: títulos sueltos, conteos, cosenos y juicios, sin RUC ni sueldos). Si un guion lo regenera, el cambio aparece en `git status` y hay que decidir si se commitea.

---

## 1. Irreemplazables: trabajo humano y etiquetas pagadas

Si se pierden, hay que volver a juzgar a mano o volver a pagar la API. **Respaldarlos fuera
del repositorio.**

| archivo | qué es | git |
|---|---|---|
| `research/experimentos/e2_nivel/salidas/13e_para_juzgar.csv` | **el patrón de oro**: 400 pares juzgados a mano (`mismo`, `mismo_v1`, `revision`; `mismo_v3` guarda la etiqueta de antes de la Enmienda 5, que corrigió 6; `mismo_v4`, la de antes de rejuzgar `calibra` con la v5, D-038) | versionado (-f) |
| `research/experimentos/e2_nivel/salidas/13e_pares_400.csv` | metadatos del oro: grupos, `sim`, estrato y la partición `calibra`/`prueba` | versionado (-f) |
| `research/experimentos/e2_nivel/salidas/13_para_juzgar.csv` | los 48 juicios anteriores (`13a`); los excluye `16` | versionado (-f) |
| `research/experimentos/e2_nivel/salidas/16_respuestas_llm.csv` | **la plata**: respuestas de Gemini sobre el lote de 10.000 | versionado (-f) |
| `research/experimentos/e2_nivel/salidas/18_para_juzgar.csv` | los 139 pares en que Gemini se contradijo, **juzgados a mano** (89 `si` / 50 `no` tras la Enmienda 5, que corrigió 2; `mismo_v3` guarda la de antes; entran a la plata con etiqueta dura, Enmienda 3 de D-036). Irreemplazable | versionado (-f) |
| `research/experimentos/e2_nivel/salidas/18_meta.csv` | metadatos de los 139: par de `16` y lo que dijo Gemini en cada orden. No abrir antes de juzgar | versionado (-f) |
| `research/experimentos/e2_nivel/salidas/20_para_juzgar.csv` | **los 400 pares nuevos de `prueba`** (Enmienda 2 de D-036), **juzgados a mano** (325 `si` / 66 `no` / 9 `duda` tras la Enmienda 5, que corrigió 10, uno a mano; `mismo_v3` guarda la de antes. Las `duda` salen por la Enmienda 4 y 24 pares más por la 5). Irreemplazable | versionado (-f) |
| `research/experimentos/e2_nivel/salidas/20_pares_400.csv` | metadatos de los 400: grupos, `sim`, estrato, tramo. No abrir antes de juzgar | versionado (-f) |
| `research/experimentos/e2_nivel/salidas/15_respuestas_llm.csv` | respuestas del piloto sobre los 400 (validan el montaje, D-035) | versionado (-f) |

**Respaldo fuera del contenedor.** El repo vive en `/root/…`, dentro del contenedor Docker: si
el contenedor se reconstruye, se pierde lo que no esté en git. `/home/pencalada` es la carpeta
del servidor y persiste. Ahí hay (2026-09-30) una copia de `salidas/22_modelos/` en
`/home/pencalada/respaldo/22_modelos/` (9,5 GB, 148 archivos, verificada byte a byte; el
cross-encoder de H1 con su SHA-256 `040b4dc4a6c5…`). Repetir tras cada entrenamiento que
importe (la v2 irá a `/home/pencalada/respaldo/22_modelos_v2/`). `demo/base_v15.npz` y
`demo/emb_base.npz` (la caché de Vertex, idéntica a la `Z` de la base) llegaron el mismo día
desde la computadora del autor, que guarda el original.

## 2. Diseño y decisiones

| archivo | qué es | git |
|---|---|---|
| `docs/registro_decisiones.md` | D-034 (árbitros), D-035 (plata con LLM), **D-036 (esta arquitectura y su prerregistro)** | versionado |
| `docs/inventario_arquitectura_juez.md` | este archivo | versionado |
| `research/experimentos/e2_nivel/rubrica_mismo_cargo.md` | la rúbrica v3 congelada; su hash va en cada respuesta del LLM | versionado |
| `research/experimentos/e2_nivel/rubrica_mismo_cargo_v4.md` | **la rúbrica vigente para juzgar a mano**: la v3 con el paso 1 cambiado (el grado no separa, Enmienda 5) | versionado |
| `research/experimentos/e2_nivel/rubrica_mismo_cargo_v5.md` | **la rúbrica vigente para juzgar a mano** (D-038): la v4 con el ámbito (paso 3) y la función (paso 4) afinados | versionado |
| `research/experimentos/e2_nivel/README.md` | índice de los guiones de E2 | versionado |
| diagrama de la arquitectura | <https://claude.ai/artifact/2xH4KY8WVVo9AkKoaeSfZW> (privado) | fuera del repo |

## 3. Guiones de la línea de trabajo

| archivo | papel en la arquitectura | git |
|---|---|---|
| `research/experimentos/e2_nivel/13a_sacar_pares_ambiguos.py` | primeros 48 pares de la banda 0,93–0,97 | versionado |
| `research/experimentos/e2_nivel/13b_comparar_arbitros.py` | coseno vs cross congelado vs generativo (D-034) | versionado |
| `research/experimentos/e2_nivel/13c_arbitros_sin_umbral_fijo.py` | **NLI congelado, comparador de H1** (AUC 0,755) | versionado |
| `research/experimentos/e2_nivel/13d_rerankers.py` | rerankers descartados; examen de cordura | versionado |
| `research/experimentos/e2_nivel/13e_lote_de_400.py` | construye el oro y fija la partición | versionado |
| `research/experimentos/e2_nivel/15_piloto_llm.py` | el montaje de Gemini: `ejecutar` (piloto) y **`etiquetar` (los 10.000)** | versionado |
| `research/experimentos/e2_nivel/16_lote_de_10000.py` | el lote de plata: excluye los cargos del oro, partición por cargo, negativos difíciles | versionado |
| `research/experimentos/e2_nivel/17_lineas_base_agrupamiento.py` | **fila 1 de la tabla factorial**: coseno × {componentes conexas, pivote, Leiden, HDBSCAN sobre PCA y UMAP}, Recall@K, estabilidad. Necesita el grupo opcional `agrupamiento` de `pyproject.toml` | versionado |

| `research/experimentos/e2_nivel/18_incoherentes_a_juzgar.py` | saca a un CSV ciego los 139 pares de la plata en que Gemini se contradijo entre órdenes | versionado |

| `research/experimentos/e2_nivel/19_potencia_h1.py` | potencia de H1 con el NLI congelado sobre `calibra`; motivo de ampliar `prueba` a 600. Desde la Enmienda 5 excluye lo que fusiona la capa 0: da el `AUC_BASE` de `22` | versionado |
| `research/experimentos/e2_nivel/20_ampliar_prueba.py` | los 400 pares nuevos de `prueba`, del censo de `16`, sin grupos de la plata | versionado |
| `research/experimentos/e2_nivel/21_paquete_entrenamiento.py` | arma el paquete para entrenar el cross en el servidor: plata + los 139 + `calibra`, **sin `prueba` y sin sueldos**, con comprobación dura. Aplica las correcciones de grado de `23` y saca de `calibra` lo que fusiona la capa 0 | versionado |
| `research/experimentos/e2_nivel/22_entrenar_cross.py` | **entrena el cross-encoder B** en el servidor: pasos 1–3, grilla con 3 semillas, elección y calibración en `calibra`. Solo lee `21_paquete/` | versionado |
| `research/experimentos/e2_nivel/23_correccion_grado.py` | **el grado ya no separa** (Enmienda 5): corrige en su sitio los juicios de `13e`, `20` y `18` (guarda `mismo_v3`), escribe las correcciones de la plata y la lista de pares que la capa 0 fusiona. `quitar_grado` es el borrador de la regla de la capa 0 | versionado |
| `research/experimentos/e2_nivel/24_h1_prueba.py` | **H1**: abre `prueba` una sola vez, tras cinco candados; cross-encoder elegido contra coseno (H1) y contra NLI congelado (H1b), más estratos, mitades, ablación y calibración. `--ensayo` sobre `calibra` | versionado |
| `research/experimentos/e2_nivel/25_analisis_errores.py` | dónde se equivoca el cross-encoder de H1, por rasgo del par (solo `calibra` y `valida`) | versionado |
| `research/experimentos/e2_nivel/26_rejuzgar_calibra.py` | `calibra` a ciegas para rejuzgar con la v5 (`armar`) y pasar los juicios al oro (`aplicar`) | versionado |
| `research/experimentos/e2_nivel/27_plata_v5.py` | los pares de la plata que la rúbrica v5 podría cambiar (60), a juicio humano a ciegas (`armar`), y sus correcciones (`aplicar`), que `21` aplica al final | versionado |
| `research/experimentos/e2_nivel/28_consistencia_calibra.py` | los `si` de `calibra` que los pasos 2-3 de la rúbrica dicen `no`, sin mirar el modelo (`armar`), y su corrección (`aplicar`) | versionado |
| `research/experimentos/e2_nivel/29_prueba2.py` | **`prueba 2`**: 400 pares nuevos para el examen del cross-encoder v2 (D-038). Python del sistema (necesita `pyarrow`) | versionado |
| `research/experimentos/e2_nivel/30_lote_entrenamiento.py` | el lote de entrenamiento de la zona difícil: 400 pares (mitad por duda del cross-encoder, mitad al azar) para juzgar con la v5 (D-038) | versionado |
| `research/experimentos/e2_nivel/31_h4_prueba2.py` | **H4**: abre `prueba 2` una sola vez, tras cinco candados; v2 contra v1 (H4), réplica de H1, H4b, ensamble, estratos y calibración. `--ensayo` sobre `calibra` | versionado |
| `research/experimentos/e2_nivel/32_fusion_coseno_cross.py` … `36_capa0_listas_y_colapsos.py` | las mediciones de la capa 0 (D-040): fusión por coseno con el cross (criterio B), adelanto del grado (A), reglas por palabra, listas para aprobar y colapsos del oro | versionado |
| `research/experimentos/e2_nivel/37_exportar_capa0.py` | pasa las filas aprobadas de las listas de `36` a `producto/datos/capa0_v1/` | versionado |
| `requirements-cross.txt` | versiones exactas para entrenar y evaluar el cross (Enmienda 3) | versionado |

Los guiones que vengan (entrenar B, destilar A, agrupar con C, utilidad aguas abajo) se
añaden aquí con el número que les toque, `38_…` en adelante.

## 4. Salidas de los guiones

| archivo | qué es | git |
|---|---|---|
| `salidas/13b_arbitros.txt`, `13c_arbitros.txt`, `13d_rerankers.txt` | resultados de D-034 | versionado |
| `salidas/13c_puntajes_cross.csv`, `13d_puntajes_rerank.csv` | puntajes por par de los árbitros congelados | versionado (-f) |
| `salidas/13_pares_ambiguos.csv` | metadatos de los 48 | versionado (-f) |
| `salidas/15_piloto_evaluacion.txt`, `15_piloto_evaluacion_v3.txt` | evaluación del piloto v2 y v3 contra `calibra` (D-035). **Contienen títulos**; commiteados en `3fbd80b` | versionado |
| `salidas/16_pares_10000.csv` | el lote completo con grupos, `sim`, estrato, partición y señal léxica | versionado (-f) |
| `salidas/16_para_llm.csv` | lo único que ve el LLM: `n`, `comun`, `raro` | versionado (-f) |
| `salidas/16_censo.parquet` | censo de pares de donde sale el lote | versionado (-f) |
| `salidas/17_lineas_base.txt` | líneas base de D-036; solo agregados, sin títulos | versionado |
| `salidas/19_potencia_h1.txt` | tabla de potencia de H1; solo agregados | versionado |
| `salidas/19_puntajes_nli_calibra.csv` | puntajes del NLI congelado sobre `calibra` (caché de `19`) | versionado (-f) |
| `salidas/21_paquete/` | `plata.csv`, `calibra.csv`, `manifiesto.json`: lo que se copia al servidor. Se regenera con `21` | versionado (-f) |
| `salidas/23_correcciones_plata.csv` | los 149 `no` de Gemini que pasan a `si` (137 por la regla del grado, 12 por la revisión a mano); los aplica `21` | versionado (-f) |
| `salidas/23_fuera_por_capa0.csv` | los 45 pares de `13e` y `20` que salen de `calibra` (9) y `prueba` (36) porque la capa 0 los fusiona (números, romanos y letras de grado). **Lo lee el guion de H1** | versionado (-f) |
| `salidas/23_revisar_grado.csv` | `no` con grado distinto y otra diferencia, **juzgados a mano** en `mismo_nuevo`. `23` los conserva (también los que salen de la lista, con `vigente = no`) y los aplica. Irreemplazable | versionado (-f) |
| `salidas/24_h1.txt`, `24_puntajes_prueba.csv` | **el resultado de H1** y los puntajes de cada juez en `prueba` (sin títulos). Se escriben una sola vez | versionado (-f) al crearse |
| `salidas/25_analisis_errores.txt` | agregados del análisis de errores (sin títulos). Los pares, en `25_errores_*.csv` | versionado; los CSV, local |
| `salidas/26_calibra_ciega.csv`, `26_calibra_mapa.csv` | `calibra` para rejuzgar a ciegas, y el mapa al `n` de `13e` (**no abrir antes de juzgar**). Una vez juzgada, irreemplazable | versionado (-f) |
| `salidas/27_revisar_v5.csv`, `27_revisar_v5_mapa.csv`, `27_correcciones_v5.csv` | los 60 pares de la plata para juzgar con la v5, el mapa (**no abrir antes**) y las correcciones que salgan. Una vez juzgados, irreemplazables | versionado (-f) |
| `salidas/28_revisar_consistencia.csv` | los 7 pares de la revisión de consistencia de `calibra`, juzgados | versionado (-f) |
| `salidas/28_revisar_consistencia_prueba2.csv` | los 9 avisos de consistencia de `prueba 2`, juzgados | versionado (-f) |
| `salidas/29_prueba2_para_juzgar.csv`, `29_prueba2_pares.csv` | **`prueba 2`, juzgada y congelada** (332 `si` / 68 `no`; `mismo_original` antes de la revisión de consistencia), y sus metadatos. Irreemplazable | versionado (-f) |
| `salidas/30_lote_para_juzgar.csv`, `30_lote_pares.csv` | el lote de entrenamiento para juzgar a ciegas, y sus metadatos con la P del modelo (**no abrir antes de juzgar**). Una vez juzgado, irreemplazable. `30_candidatos.csv` queda local | versionado (-f) |
| `salidas/31_h4.txt`, `31_puntajes_prueba2.csv` | **el resultado de H4** y los puntajes de cada juez en `prueba 2` (sin títulos). Se escriben una sola vez | versionado (-f) al crearse |
| `salidas/22_modelos/` | el cross entrenado: `elegido/` (el de H1), `corridas/` y `resultados.json`. El primer entrenamiento (commit `1bdc855`, `calibra` de 194) quedó sustituido por la Enmienda 5 y se rehace. `estado/` guarda cada corrida terminada para poder retomar (`huella.json`, y los pesos solo mientras hacen falta); `corrida.log`, el registro. Pesos de ~1 GB: fuera de git; `resultados.json` se commitea | local |
| `salidas/22_modelos_v2/` | el cross-encoder **v2** (D-038, `22 --grilla v2`): `elegido/`, `corridas/`, `semillas/` (las tres de la configuración elegida, para el ensamble) y `resultados.json`. Pesos fuera de git | local; `resultados.json` se commitea |

(`salidas/` = `research/experimentos/e2_nivel/salidas/`)

## 5. Producto: lo que la arquitectura va a modificar

No se borra nada de esto; se lista porque es donde entra B cuando gane H1.

| archivo | qué cambia | git |
|---|---|---|
| `src/benchmarking/producto/base_referencia.py` | la consolidación (`UMBRAL_FUSION`, enlace completo) pasa a C; el vecindario `λ(1 − sim)` pasa a `λ(1 − P(mismo))`; `_lambda_semantica` se reestima | versionado |
| `src/benchmarking/producto/referenciar_nomina.py` | el flujo de un cargo nuevo: asignación a grupo y las tres ramas | versionado |
| `src/benchmarking/producto/capa0.py` | **la capa 0** (D-040): `Capa0.atomo`, una sola función de texto al construir y al consultar; `proponer_erratas` | versionado |
| `src/benchmarking/producto/datos/capa0_v1/` | los diccionarios **aprobados** de la capa 0 v1 (erratas, abreviaturas, género); vacíos hasta la revisión | versionado |
| `src/benchmarking/producto/nivel.py` | `nivel_lexico` y `seniority_lexica`: capa 0, y la señal del peso por nivel en la pérdida de B | versionado |
| `src/benchmarking/evaluacion/referencia.py` | votos, pesos y cuantiles de la banda; no cambia, pero la utilidad aguas abajo se mide con él | versionado |
| `src/benchmarking/evaluacion/embeddings.py` | los embeddings de Vertex con caché: el espacio del coseno, línea base y punto de partida de A | versionado |
| `src/benchmarking/cli.py` | `referenciar` y `grafias` leen `demo/base_v15.npz` | versionado |

## 6. Datos de base

| archivo | qué es | git |
|---|---|---|
| `demo/base_v15.npz` | **la base vigente**: `celdas`, `Z` (embeddings), `grupo`, `emp`, `nivel`, bandas… Todos los guiones de `13e` en adelante la leen | local |

Las versiones anteriores de `demo/base_v*.npz` (v1 a v14) **no las usa esta línea de
trabajo**. Si las usa otra cosa, no se comprobó aquí.

## 7. Guiones previos que siguen siendo la línea base

La consolidación de hoy es la fila «coseno» de la tabla factorial. No se borran porque la
tesis compara contra ellos:

| archivo | por qué importa |
|---|---|
| `research/experimentos/e2_nivel/06_inspeccionar_fusiones.py` | la percolación del enlace simple (grupo de 1.758 títulos), el argumento de H2 |
| `research/experimentos/e2_nivel/07_fusion_enlace_completo.py` | el enlace completo a 0,95 que usa el producto |
| `research/experimentos/e2_nivel/08_…` a `12_…`, `14_…` | erratas, género, clave dura y candado de seniority: la capa 0 |
| `research/experimentos/e2_nivel/01_…` a `04_…` | la ceguera jerárquica y el nivel léxico: la motivación del peso por nivel |

## 8. Tesis

| archivo | qué hay que hacer |
|---|---|
| `docs/tesis/tesis.tex` | reescribir el resumen, «La reformulación» y la defensa del modelo simple para el nuevo eje |
| `docs/estado_del_arte.md` | reorientar hacia normalización y similitud de títulos de cargo (JobBERT, ESCO) |
