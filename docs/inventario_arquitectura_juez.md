# Inventario — archivos de la arquitectura del juez de «mismo cargo» (D-036)

Para la limpieza final: lo que está aquí **no se borra** sin revisar antes esta lista.
Actualízala cada vez que se cree un guion o una salida de esta línea de trabajo.

Leyenda de la columna *git*:
- **versionado**: está en el repositorio.
- **local**: está en `.gitignore` (títulos de clientes, LOPDP) y **solo existe en esta máquina**. Si se borra, no hay copia.

---

## 1. Irreemplazables: trabajo humano y etiquetas pagadas

Si se pierden, hay que volver a juzgar a mano o volver a pagar la API. **Respaldarlos fuera
del repositorio.**

| archivo | qué es | git |
|---|---|---|
| `research/experimentos/e2_nivel/salidas/13e_para_juzgar.csv` | **el patrón de oro**: 400 pares juzgados a mano (`mismo`, `mismo_v1`, `revision`) | local |
| `research/experimentos/e2_nivel/salidas/13e_pares_400.csv` | metadatos del oro: grupos, `sim`, estrato y la partición `calibra`/`prueba` | local |
| `research/experimentos/e2_nivel/salidas/13_para_juzgar.csv` | los 48 juicios anteriores (`13a`); los excluye `16` | local |
| `research/experimentos/e2_nivel/salidas/16_respuestas_llm.csv` | **la plata**: respuestas de Gemini sobre el lote de 10.000 | local |
| `research/experimentos/e2_nivel/salidas/18_para_juzgar.csv` | los 139 pares en que Gemini se contradijo, **para juzgar a mano** (Enmienda 1 de D-036). Una vez juzgados son irreemplazables | local |
| `research/experimentos/e2_nivel/salidas/18_meta.csv` | metadatos de los 139: par de `16` y lo que dijo Gemini en cada orden. No abrir antes de juzgar | local |
| `research/experimentos/e2_nivel/salidas/20_para_juzgar.csv` | **los 400 pares nuevos de `prueba`** (Enmienda 2 de D-036), para juzgar a mano. Bloquean H1. Una vez juzgados son irreemplazables | local |
| `research/experimentos/e2_nivel/salidas/20_pares_400.csv` | metadatos de los 400: grupos, `sim`, estrato, tramo. No abrir antes de juzgar | local |
| `research/experimentos/e2_nivel/salidas/15_respuestas_llm.csv` | respuestas del piloto sobre los 400 (validan el montaje, D-035) | local |

## 2. Diseño y decisiones

| archivo | qué es | git |
|---|---|---|
| `docs/registro_decisiones.md` | D-034 (árbitros), D-035 (plata con LLM), **D-036 (esta arquitectura y su prerregistro)** | versionado |
| `docs/inventario_arquitectura_juez.md` | este archivo | versionado |
| `research/experimentos/e2_nivel/rubrica_mismo_cargo.md` | la rúbrica v3 congelada; su hash va en cada respuesta del LLM | versionado |
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

| `research/experimentos/e2_nivel/19_potencia_h1.py` | potencia de H1 con el NLI congelado sobre `calibra`; motivo de ampliar `prueba` a 600 | versionado |
| `research/experimentos/e2_nivel/20_ampliar_prueba.py` | los 400 pares nuevos de `prueba`, del censo de `16`, sin grupos de la plata | versionado |

Los guiones que vengan (entrenar B, destilar A, agrupar con C, utilidad aguas abajo) se
añaden aquí con el número que les toque, `21_…` en adelante.

## 4. Salidas de los guiones

| archivo | qué es | git |
|---|---|---|
| `salidas/13b_arbitros.txt`, `13c_arbitros.txt`, `13d_rerankers.txt` | resultados de D-034 | versionado |
| `salidas/13c_puntajes_cross.csv`, `13d_puntajes_rerank.csv` | puntajes por par de los árbitros congelados | local |
| `salidas/13_pares_ambiguos.csv` | metadatos de los 48 | local |
| `salidas/15_piloto_evaluacion.txt`, `15_piloto_evaluacion_v3.txt` | evaluación del piloto v2 y v3 contra `calibra` (D-035). **Contienen títulos**: no commitear sin revisar | sin versionar aún |
| `salidas/16_pares_10000.csv` | el lote completo con grupos, `sim`, estrato, partición y señal léxica | local |
| `salidas/16_para_llm.csv` | lo único que ve el LLM: `n`, `comun`, `raro` | local |
| `salidas/16_censo.parquet` | censo de pares de donde sale el lote | local |
| `salidas/17_lineas_base.txt` | líneas base de D-036; solo agregados, sin títulos | versionado |
| `salidas/19_potencia_h1.txt` | tabla de potencia de H1; solo agregados | versionado |
| `salidas/19_puntajes_nli_calibra.csv` | puntajes del NLI congelado sobre `calibra` (caché de `19`) | local |

(`salidas/` = `research/experimentos/e2_nivel/salidas/`)

## 5. Producto: lo que la arquitectura va a modificar

No se borra nada de esto; se lista porque es donde entra B cuando gane H1.

| archivo | qué cambia | git |
|---|---|---|
| `src/benchmarking/producto/base_referencia.py` | la consolidación (`UMBRAL_FUSION`, enlace completo) pasa a C; el vecindario `λ(1 − sim)` pasa a `λ(1 − P(mismo))`; `_lambda_semantica` se reestima | versionado |
| `src/benchmarking/producto/referenciar_nomina.py` | el flujo de un cargo nuevo: asignación a grupo y las tres ramas | versionado |
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
