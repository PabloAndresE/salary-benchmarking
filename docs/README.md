# Documentación del proyecto

Punto de entrada. Si retomas esto en frío —otra sesión, otra persona, el tutor— **lee en este
orden**.

---

## Para entender el proyecto (1 hora)

| # | Documento | Qué contiene |
|---|---|---|
| 1 | [`../HANDOFF.md`](../HANDOFF.md) | El qué y el porqué del proyecto. Doble naturaleza: tesis (MIA-USFQ) y producto. Restricciones que gobiernan el diseño: 330 h, LOPDP, GCP |
| 2 | [`../research/notebooks/01_eda_cargo_benchmarking.ipynb`](../research/notebooks/01_eda_cargo_benchmarking.ipynb) | El EDA que motiva todo: por qué la etiqueta `CARGO` no sirve para comparar salarios |
| 3 | [`estado_del_arte.md`](estado_del_arte.md) | Qué hicieron los trabajos previos, qué les funcionó, y **cuál es la contribución propia** |
| 4 | [`registro_decisiones.md`](registro_decisiones.md) | **El documento central.** D-001 a D-008: cada decisión de método con su evidencia, alternativas descartadas y fuentes |

## Para saber dónde está todo hoy

| Documento | Qué contiene |
|---|---|
| [`mediciones.md`](mediciones.md) | **Todas las cifras medidas**, con fecha, alcance y procedencia. Si vas a citar un número en la tesis, sale de aquí |
| [`revision_jueces.md`](revision_jueces.md) | Revisión por cuatro jueces independientes (2026-08-07): las convergencias, las contradicciones, y **las 7 correcciones pendientes** |

## Especificaciones de diseño

| Documento | Estado |
|---|---|
| [`superpowers/specs/2026-08-04-clustering-arquetipos-design.md`](superpowers/specs/2026-08-04-clustering-arquetipos-design.md) | El núcleo de la tesis. **§5, §6 y §7 tienen correcciones pendientes** — ver `revision_jueces.md` §6 |
| [`superpowers/specs/2026-08-05-banco-validacion-design.md`](superpowers/specs/2026-08-05-banco-validacion-design.md) | El banco de validación. **§5 tiene una corrección pendiente** (ponderar por empresa) |
| [`superpowers/specs/2026-07-29-pipeline-nomina-features-design.md`](superpowers/specs/2026-07-29-pipeline-nomina-features-design.md) | El pipeline de ingesta. Implementado |
| [`superpowers/plans/2026-08-11-banco-validacion-plan.md`](superpowers/plans/2026-08-11-banco-validacion-plan.md) | ✅ **VIGENTE.** 17 tareas, listo para ejecutar |
| [`superpowers/plans/2026-08-07-banco-validacion-plan.md`](superpowers/plans/2026-08-07-banco-validacion-plan.md) | 🛑 Obsoleto, se conserva como registro |
| [`preregistro.md`](preregistro.md) | Se crea en la Tarea 14 del plan vigente. Congela el método antes de tocar el test |

---

## El estado en una página

### Lo que existe y funciona

**El pipeline de ingesta** (`src/benchmarking/`): lee los estudios de BigQuery, descarga las
plantillas, une por cédula, anonimiza, deriva features, marca cuarentena, cruza con la
Superintendencia y escribe a `benchmarking_tesis.nomina_features`. Reanudable por lotes. 61 tests.

**Los datos.** El universo de ajuste es **2024–2025**: son los únicos años con plantilla y por tanto
los únicos con composición (medido: 100% de disponibilidad en 2025, 90% en 2024, 0% en 2023 y
anteriores). La corrida está acotada a esos dos años; los anteriores solo aportarían cobertura para
asignación y no hacen falta hasta el sub-proyecto 4.

### Lo que NO existe todavía

- **El banco de validación.** Ni una línea. Es el sub-proyecto 1 y su plan está obsoleto.
- **`preregistro.md`.** El documento que congela el método antes de tocar el test.
- **El enmarque de novedad** frente a Job2Vec, Djumalieva y TWICE — el riesgo mayor de la tesis si
  el resultado sale bien.
- Representación, modelo de nivel, clustering, etiquetado (sub-proyectos 2 a 5).

### El orden de trabajo acordado

```
0  Ingesta y composición                        ← hecho
1  Banco de validación + baselines              ← siguiente, plan por reescribir
2  Representación (bloques, residualización)
3  Modelo de nivel
4  Las cuatro familias de clustering
5  Etiquetado LLM e ISCO-08
```

El orden es deliberado (D-002): **primero el instrumento de medida, después el modelo.** La
contribución de la tesis es la medición, no el algoritmo.

---

## Las cinco ideas que sostienen todo

Si solo retienes cinco cosas del expediente, que sean estas:

1. **Nada se agrupa mirando el salario.** Se agrupa por la *forma* del pago, no por su tamaño; y la
   granularidad se elige por estabilidad, no por acierto. Es lo que separa esta tesis de los tres
   trabajos previos que hacen algo parecido.
2. **Todo se mide fuera de muestra y sin la propia empresa.** El empleador explica ~39% del salario:
   sin excluirlo se acertaría por la razón equivocada.
3. **Todo intervalo se remuestrea por empresa.** La fila no es la unidad independiente: una persona
   recurre entre años y una empresa aporta cientos de personas.
4. **El criterio de éxito se escribe antes de mirar**, con el hash del conjunto de test dentro del
   documento, para que sea comprobable y no una promesa.
5. **Ante dos opciones defendibles, sospecha de la que te conviene.** Cuatro decisiones de diseño
   resultaron favorecer la hipótesis propia sin que esa fuera la intención (D-006, y luego D-007).
   Es el sesgo que más ha costado detectar.
6. **Toda premisa que habilite una decisión se mide antes de tomar la decisión.** D-010: se
   construyeron tres decisiones sobre la idea de que `cargo_plantilla` era una etiqueta
   independiente. Eran la misma columna, y comprobarlo costaba una consulta.

---

## Convenciones del repositorio

- **La frontera de privacidad es sagrada.** Nada aguas abajo de `anonimizacion` ve identificadores.
  Data real nunca al repositorio: los tests usan data sintética.
- **Config sobre código.** Umbrales y decisiones parametrizables van a `settings.py` o `config.yaml`.
- **Toda decisión de método se registra** en `registro_decisiones.md` con evidencia, alternativas
  descartadas y fuentes citables. Se escribe en el momento, no al final.
- **Toda cifra medida se registra** en `mediciones.md` con fecha, alcance y procedencia.
- **Semilla del proyecto:** `20260805`.
