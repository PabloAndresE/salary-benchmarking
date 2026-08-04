# Clustering de arquetipos de puesto (rol-familia × nivel) — Diseño

> Núcleo de la tesis (MIA-USFQ) y del producto (ActuaLab). Rediseñado tras un panel de 3 jueces (metodólogo, ML, compensaciones). Alcance = **núcleo de tesis**; los endurecimientos de producto quedan como roadmap documentado (§12).

## 1. Problema y objetivo

La columna `CARGO` es poco confiable para benchmarking (misma etiqueta → sueldos muy distintos intra-empresa; placeholders; sinónimos). **Objetivo:** construir un grupo de comparación *data-driven* — **familia-de-rol × nivel de seniority** — que sea demostrablemente mejor que el `CARGO` crudo para benchmarking salarial, validado con rigor de tesis y utilizable como producto.

**Unidad de comparación (benchmark) = familia-de-rol × banda-de-nivel × controles (tamaño, sector, provincia, corte temporal).** El salario es la variable a benchmarkear DENTRO de esa celda, nunca un input del agrupamiento.

## 2. Alcance

- **En alcance (tesis):** representación, modelo de nivel, clustering de las 4 familias tras interfaz común, etiquetado ISCO-08, y la **validación** (el corazón). Sobre `benchmarking_tesis.nomina_features` (`en_clean`).
- **Roadmap de producto (fuera de alcance ahora, §12):** supresión de celda mínima + safe-harbor, naming ISCO productivo, cash anualizado, Tobit del piso SBU, ponderación al universo SCVS, mapeo online.

## 3. Principios que fija el panel (gobiernan todo el diseño)

1. **Estimando intra-empresa.** El efecto empresa domina la varianza (EDA: η²_empresa≈0,34). Toda validación se hace **dentro de empresa** (modelo mixto con efecto empresa / residualización), no sobre varianza cruda global.
2. **La unidad estadística son empresas/personas, no filas.** Una persona recurre entre años; una empresa aporta muchas personas. **Todos** los splits, bootstraps y CIs son **por empresa (y por persona)**, nunca por fila.
3. **Anti-circularidad estricta.** El salario-nivel nunca entra al clustering ni a la selección de k. La composición se residualiza (§5). El nivel se deriva evitando el salario (§6). La validación primaria es **fuera de muestra** y contra una escalera de nulos (§9).
4. **La selección de modelo NO usa la métrica salarial.** k y familia se eligen por estabilidad; la dispersión salarial se reporta como confirmación en held-out, jamás como objetivo de ajuste.
5. **Frontera de privacidad** (handoff): nada aguas abajo de `anonimizacion` ve identificadores; sin data real al repo.

## 4. Datos y particiones

- Fuente: `benchmarking_tesis.nomina_features`, filas `en_clean` (cuarentena excluida del modelado, conservada en base).
- **Splits por empresa** (`empresa_ruc`) y por persona (`id_hash`): un set de empresas held-out se reserva **intacto** hasta la validación final. Ninguna persona/empresa cruza train/test.
- **Muestreo estratificado por sector×tamaño** para el ajuste (contra el sesgo de selección, §8): se ajusta en muestra estratificada, se asigna en batch al universo.
- **Diagnóstico de missingness** (§8) como paso previo obligatorio.

## 5. Representación (capa compartida por las 4 familias)

El vector que consumen TODAS las familias. Bloques con normalización a varianza unitaria por bloque + peso de bloque como hiperparámetro (§7).

- **Composición (eje de segmentación, no "estrella"):**
  - **Residualizada** contra la media empleador×sector: se modela "cuán variable es esta persona *para su empresa/sector*", no la política de pago del empleador.
  - **Datos composicionales (símplex con ceros estructurales):** manejo **two-part** — (a) *gate* binario "tiene pago variable" (sí/no); (b) **ILR** (full-rank, no CLR) entre las partes positivas. Nunca proporciones crudas en distancia euclídea.
  - **Imputación + indicador de faltante** para las filas sin composición (se elimina la arquitectura de 2 etapas; ver §7).
- **Pre-segmentación de la masa fija/piso (gate):** la población "sin variable / al piso SBU" no la separa la composición (es fija por construcción). Se **enruta a un carril propio** y el clustering fino corre sobre la **población con estructura**; la masa fija se asigna por cargo-texto + centro + nivel. (Decisión arquitectónica clave: sin este gate cualquier partición dura malgasta clusters en el blob amorfo.)
- **Texto del cargo (demotado):** peso bajo o **fuera del espacio geométrico**; se usa para (a) nombrar/etiquetar (§8 LLM) y (b) fuente de *must-links* suaves (E5). Test obligatorio de que **no re-inyecta la etiqueta sucia** (no daña en labels colapsados conocidos).
- **`centro_de_costo`:** bloque de bajo peso; normalizar tokens específicos de empresa (riesgo de codificar identidad de empresa); preferir tratarlo como texto embebido o vía k-prototypes, nunca target-encoding.
- **Excluidos del clustering** (controles/auditoría aguas abajo): salario-nivel (circularidad), `sexo` (fairness → auditoría Oaxaca §9), `edad`/`antiguedad` (alimentan el modelo de nivel §6), empresa/tamaño/sector/provincia (controles del benchmark).

## 6. Modelo de nivel / seniority (completo)

La unidad final es rol-familia × **banda de nivel**. Modelo de nivel **explícito y completo**, separado del clustering de rol:

- **Señales (priorizando NO-salario para evitar circularidad):** `antiguedad_total`, `edad`, **tokens de seniority del título** (jefe/gerente/asistente/senior/junior/auxiliar/coordinador…), y — con cautela — **rank de pago intra-empresa** (ordinal, dentro de la misma empresa).
- **Salida:** banda discreta (p.ej. auxiliar / pleno / senior / jefatura) por rol-familia; calibrada por familia (un "senior" de un rol ≠ de otro).
- **Anti-circularidad del nivel (punto crítico):** el `rank de pago intra-empresa` usa salario → si el nivel se define con él y luego se benchmarkea salario dentro de rol×nivel, hay fuga. Mitigación: (a) construir la banda **primariamente con señales no-salariales**; (b) si se incluye el rank, es **ordinal intra-empresa** (no el monto), y (c) en la validación del benchmark se hace **leave-company-out** y una variante **sin rank** para acotar la fuga. Se reporta la sensibilidad.

## 7. Clustering — 4 familias tras interfaz común

Todas consumen la representación de §5 (población con estructura, post-gate) y se comparan en E3.

- **GMM — primario.** Soft assignment → **score de confianza por persona** (alimenta el "% ambiguo" de selección y el *fallback* a mediana sector×tamaño×nivel para baja confianza); modela clusters elípticos/solapados; puede usar **EM con faltantes**. Gaussiana sobre coords ILR (no sobre proporciones crudas).
- **HDBSCAN — contendiente fuerte.** Densidad variable + **etiqueta ruido** (el ruido → fallback explícito, atado a la supresión de celda mínima). Se corre sobre muestra + `approximate_predict`. Ojo: k variable complica el "k-igualado" de §9 (se maneja aparte); no-determinismo (§11).
- **Jerárquico aglomerativo — para la jerarquía/granularidad.** O(n²) → se corre **sobre prototipos** (dendrograma de arquetipos, no de personas) para decidir cuántas familias y su anidamiento (arquitectura de cargos). Métrica compositional/Gower.
- **K-means — baseline obligatorio** (referencia a vencer). MiniBatch para escala; requiere imputación+indicador y coords ILR.
- *(Candidato)* **k-prototypes** para el mixto numérico+categórico (`centro`) sin one-hot dominante.

**Selección de modelo:** k y familia por **estabilidad (ARI bootstrap por empresa)** + silhouette/Davies-Bouldin + % de asignaciones ambiguas. **NUNCA** por la dispersión salarial. Normalización por bloque + **peso de bloque afinado contra dispersión salarial en held-out** (único punto donde la métrica salarial toca el ajuste, y solo en held-out).

## 8. Etiquetado (LLM → ISCO-08) y missingness

- **Etiquetado (E4):** Gemini/Vertex AI, temperatura 0, 3 corridas/cluster, salida JSON → **ISCO-08** + nombre en español + descripción + 3–5 títulos de ejemplo. Es la **capa de accionabilidad**: "tu VENDEDOR → *Comercial con variable alto (ISCO 5223)*". Consistencia entre corridas + acuerdo con experto.
- **Diagnóstico de missingness (obligatorio, previo):** modelar el mecanismo (`missing ~ año + segmento + ciiu + n_empleados + provincia`), reportar balance observado-vs-faltante, e **IPW/análisis de sensibilidad** para que los arquetipos no queden sesgados a firmas formales/recientes.

## 9. Validación (el corazón)

- **Primaria — reducción de dispersión salarial, bien hecha:** ¿rol×nivel explica la dispersión salarial mejor que `CARGO`, **intra-empresa, fuera de muestra, a k igualado**? Modelo mixto con efecto empresa; ω²/CV con **bootstrap por empresa**. Contra una **escalera de nulos**: (i) partición aleatoria a k igualado, (ii) solo-texto (aísla lo que aporta la composición), (iii) **techo supervisado** = clusterizar directo sobre el salario (cota superior alcanzable). Se reporta dónde caen los arquetipos entre nulo y techo.
- **Validez externa:** predecir algo NO salarial (ISCO-08/educación/etiqueta experta) desde el arquetipo → rebate "solo binneaste el salario".
- **Estabilidad:** ARI bootstrap por empresa; % de asignaciones ambiguas.
- **Fairness:** brecha de género **ajustada (Oaxaca-Blinder)**, descomposición entre-arquetipo (segregación) vs intra-arquetipo (pago), con supresión de celda; nunca la brecha cruda (el EDA ya mostró Simpson).
- **Anti-fuga de inferencia:** al construir la distribución de referencia para benchmarkear a una persona, **leave-company-out** (y correlación composición↔nivel acotada, §6).
- **Pre-registro:** métrica primaria, regla de selección de k y test-set bloqueado se fijan **antes** de mirar el salario en test (garden-of-forking-paths).

## 10. Matriz experimental (alineada al handoff §7 + adiciones v2)

- **E1** — ¿aporta el embedding de cargo? con/sin bloque texto **+ test de no-daño en labels colapsados** (v2).
- **E2** — anti-circularidad: actividad vs nivel. con/sin salario **+ residualización de composición vs empleador + techo supervisado** (v2).
- **E3** — **4 familias × 2 mejores representaciones** (intacto): GMM/HDBSCAN/jerárquico/k-means bajo la interfaz común, decididas por estabilidad y confirmadas por dispersión held-out.
- **E4** — etiquetado LLM: consistencia entre corridas + acuerdo experto + mapeo ISCO-08.
- **E5** — semi-supervisado: **must-links** (no semillas de clase) desde etiquetas confiables / texto de cargo demotado; gate pre-registrado (≥10 grupos-semilla, ≥15% cobertura).
- **Adiciones v2 transversales:** modelo de nivel (rol×nivel), validación intra-empresa/fuera-de-muestra con escalera de nulos y validez externa, diagnóstico de missingness, brecha ajustada.

## 11. Reproducibilidad

Revisión exacta del modelo de embeddings fijada y como key de caché `(model_revision, normalización)`; todas las semillas fijas; convención de signo determinista en PCA; corrida canónica single-thread; **versionado de los modelos de arquetipo** para diffear la deriva entre releases.

## 12. Roadmap de producto (documentado, fuera de alcance)

Supresión de celda mínima (≥5 empresas, ninguna >~50%) + agregación safe-harbor (launch blocker legal/LOPDP); naming ISCO productivo; **cash anualizado** (base + décimos, utilidades/beneficios fuera con caveat); **Tobit** para el piso SBU; **ponderación al universo SCVS** + caveat de "referencia sesgada a formales/grandes"; **mapeo online** por título+depto (nivel por antigüedad/rank), sin requerir composición del cliente.

## 13. Estructura de código y entregables

- `src/benchmarking/representacion/` (vector base, residualización, ILR/two-part, gate, imputación, bloques).
- `src/benchmarking/modelado/nivel.py` (modelo de nivel).
- `src/benchmarking/clustering/` (4 familias tras interfaz común + selección).
- `src/benchmarking/etiquetado/` (Vertex/ISCO-08).
- `src/benchmarking/benchmarking/` (estadística intra-empresa + validación; supresión de celda = roadmap).
- `research/experimentos/` + notebooks por experimento + `registro_experimentos.md`. Data sintética en tests.

## 14. Decisiones abiertas / riesgos

- **Nivel completo añade alcance** sobre el handoff (330h): confirmado incluirlo; vigilar el costo vs. cronograma (nov-2026).
- **Corr(composición, nivel)** a cuantificar y acotar antes de reclamar "sin circularidad".
- **HDBSCAN a escala** y su fracción de ruido: definir el umbral de fallback junto con la celda mínima.
- **Peso de bloque** y **manejo de ceros** en ILR son load-bearing: sensibilidad reportada.
