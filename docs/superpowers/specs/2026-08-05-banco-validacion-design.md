# Sub-proyecto 1 — Banco de validación y baseline — Diseño

> ⚠️ **Correcciones pendientes**, ver [`../../revision_jueces.md`](../../revision_jueces.md) y D-009.
>
> | Sección | Qué cambia |
> |---|---|
> | **§5** | La referencia está ponderada **por persona**: una empresa con 3.000 personas en una celda define el mercado aunque haya ≥3 empresas. Pasar a **ponderación por empresa**. Bloqueante: cambia todos los números |
> | **§5** | La media en espacio log se sustituye por **mediana** (medido: 0,0533 de diferencia, y no neutral entre métodos). La curva baja de 30 a 8 umbrales |
> | **§4** | El nulo solo-texto usa **embeddings de Vertex**, no TF-IDF: el emparejamiento por caracteres invierte la jerarquía (medido) |
> | **§6.1** | Se reportan **MAE y RMSE**, con MAE como principal |
> | **§9** | El pre-registro debe cerrar los **tres** elementos de D-005 Enmienda 1 — granularidad, familia **y pesos** |
> | nuevo | Medir la **ruta de servicio**: acierto de (título, centro, antigüedad) → arquetipo sobre empresas held-out |


> Primer sub-proyecto del núcleo de tesis. Construye **el instrumento de medida antes que el
> modelo** (D-002): un banco que recibe cualquier forma de agrupar personas y dice cómo de bien
> mide, comparada con el `CARGO` y con una escalera de referencias.
>
> Decisiones que lo gobiernan: **D-002** (evaluación primero), **D-003** (universo de ajuste),
> **D-004** (criterio de éxito), **D-005** (métrica primaria). Ver `docs/registro_decisiones.md`.
> Depende de **D-001** (sub-proyecto 0) sólo para el baseline con composición.

## 1. Propósito

La tesis afirma que un grupo de comparación *data-driven* mide mejor que la etiqueta `CARGO`.
Eso es una afirmación **de medición**, así que el aporte es el instrumento que la sostiene. Este
sub-proyecto entrega ese instrumento y lo estrena contra el baseline más simple posible.

Entregable operativo:

```
benchmarking evaluar --particion <asignacion.parquet>
```

recibe una tabla `(id_hash, numero_proceso, celda)` y devuelve la comparación contra `CARGO` y
contra la escalera de nulos, con intervalos de confianza y la curva error-cobertura.

Todo lo que se construya después (representación, nivel, las cuatro familias, etiquetado) se
justifica con un número producido por este banco.

## 2. Alcance

**Dentro:** splits por empresa, cálculo de la referencia salarial por celda, error fuera de muestra,
cobertura, curva error-cobertura, ω² intra-empresa con la escalera de nulos, bootstrap por empresa,
test-retest, validación del propio banco con data sintética, documento de pre-registro, y dos
baselines de estreno.

**Fuera** (sub-proyectos 2–5): representación elaborada (residualización, ILR, gate de masa fija,
pesos de bloque), modelo de nivel, GMM/HDBSCAN/jerárquico, etiquetado LLM e ISCO-08, IPW.

La única excepción: el banco debe **admitir** una columna de confianza por persona desde el día uno,
aunque los baselines de esta fase no la produzcan, para que el GMM del sub-proyecto 4 encaje sin
rediseño.

## 3. Los tres universos

Se separan explícitamente porque confundirlos fue el error que motivó D-003.

| Universo | Qué es | Contenido |
|---|---|---|
| **Ajuste** | de dónde aprende el modelo | depende del baseline (§8) |
| **Asignación** | qué filas reciben celda | las 4,66 M, todos los años |
| **Evaluación** | dónde se compara contra `CARGO` | filas con `cargo` utilizable y `sueldo > 0` |

La evaluación se restringe a filas con cargo porque **el baseline no puede competir donde no
existe**. Las filas sin cargo se reportan aparte, como cobertura exclusiva del arquetipo: ahí no hay
comparación posible y ése es precisamente el argumento (§6.3).

## 4. Las particiones que se comparan

Cinco, sobre el mismo conjunto de evaluación:

| Partición | Qué contesta | Cardinalidad |
|---|---|---|
| **Aleatoria** | ¿supero al azar? | igualada a la del arquetipo |
| **`CARGO` crudo** | ¿supero lo que se usa hoy? | 55.920 en 2025, **sin podar** |
| **Solo-texto** | ¿la composición aporta algo más allá del nombre del puesto? | igualada |
| **Arquetipo** | lo que se evalúa | la que salga |
| **Techo supervisado** | ¿cuánto es lo máximo posible con estos datos? | igualada |

**No se construye ningún `CARGO` podado** (D-005): las 50 etiquetas más frecuentes de 2025 cubren
sólo el 25,6% de la gente, así que podar dejaría a 429.000 personas en una celda "otros" y el rival
resultante no representaría a nada real. La cardinalidad igualada la aporta el nulo **solo-texto**,
que agrupa por similitud semántica del título en el mismo número de grupos que el arquetipo.

El **techo supervisado** se construye agrupando directamente por `log(sueldo/SBU)` en la misma
cardinalidad. Es circular por diseño y no es un método candidato: sirve para fijar la escala del
resultado propio y como alarma (si el arquetipo se le acerca demasiado, hay que sospechar deriva
hacia bandas salariales).

## 5. La referencia salarial de una celda

**Variable objetivo:** `log(sueldo / SBU(año))`. Se usa `sueldo` y no `total` porque `total` sólo
está bien definido donde hay composición, y un objetivo que cambia de definición entre filas no es
comparable. Benchmarkear sobre efectivo anualizado queda como roadmap (spec de clustering §12).

*(Nota anti-circularidad: la composición entra como **proporciones**, no como montos. Conocer
`pct_fijo = 0,9` no revela el nivel salarial, sólo la forma del pago. El nivel nunca es feature.)*

**Donantes.** Para estimar la referencia de una persona de test se usan las personas de su misma
celda que estén en train **y pertenezcan a otra empresa** (*leave-company-out*). La exclusión de la
propia empresa no es opcional: el efecto empresa explica ~34% de la varianza del log-sueldo (EDA), y
sin excluirla se acertaría por la razón equivocada.

**Referencia** = mediana de `log(sueldo/SBU)` de los donantes. Mediana y no media por el sesgo
derecho de la distribución salarial ya documentado en el EDA.

**Regla de abstención.** Si la celda tiene menos de `m` donantes provenientes de al menos `e`
empresas distintas, el método **se abstiene**: no emite referencia, y esa persona no cuenta en el
error sino en la cobertura. Valores de partida `m = 5`, `e = 3`.

El umbral de 5 donantes coincide con la práctica del programa OEWS del BLS y con la supresión de
celda mínima del spec §12. La condición de ≥3 empresas evita que una sola empresa defina la
referencia de mercado.

## 6. Métricas

### 6.1 Primaria — error fuera de muestra

**MAE de `log(sueldo/SBU)`** sobre las personas de test para las que el método no se abstuvo. MAE y
no RMSE por robustez ante los valores extremos salariales.

Se reporta también en escala interpretable: un MAE de 0,10 equivale a ~10% de desviación típica
respecto de la referencia.

### 6.2 Co-primaria — cobertura

Fracción de personas de test para las que el método emite referencia. Los dos métodos se abstienen
por motivos distintos y **comparar sólo el error favorecería a `CARGO`**, que acierta más porque
únicamente opina donde tiene datos.

### 6.3 La curva error-cobertura

El umbral de donantes `m` **es la perilla de confianza**, y sirve igual para los dos métodos, lo que
permite una comparación uniforme sin necesitar que cada uno produzca su propio score.

Barriendo `m` de 1 a 30 se obtiene, para cada partición, una curva de error contra cobertura. La
comparación honesta es **a cobertura igualada**: leer el error de cada método en el mismo punto del
eje horizontal.

Es lo que distingue el escenario **A** del **B** de D-004; sin ella son indistinguibles.

Aparte, se reporta la **cobertura exclusiva**: fracción de personas sin `cargo` utilizable a las que
el arquetipo sí asigna celda. Ahí `CARGO` no compite y el número se presenta como tal, no como
victoria en la comparación.

### 6.4 Confirmatoria — ω² intra-empresa

Se mantiene el §9 del spec de clustering: ω² sobre `log(sueldo/SBU)` con efecto empresa, fuera de
muestra, contra la escalera de nulos. **Se calcula y se reporta siempre; no decide** (D-005).

### 6.5 Estabilidad — test-retest

478.522 personas aparecen tanto en 2024 como en 2025 (80% de las de 2025). Sus dos registros son
**dos mediciones reales de la misma persona**, no una simulación.

Se asigna celda a cada registro por separado y se mide el acuerdo. Es evidencia de fiabilidad más
fuerte que un ARI de bootstrap. No está en el spec de clustering y se incorpora aquí.

### 6.6 Incertidumbre

Todos los intervalos por **bootstrap de empresas** (remuestreo de empresas con reemplazo, 1.000
réplicas), nunca de filas: una persona recurre entre años y una empresa aporta muchas personas, así
que la fila no es la unidad independiente.

## 7. Splits

- **Por empresa.** El 20% de las empresas se aparta y se bloquea hasta la validación final. Ninguna
  persona cruza train/test, porque una persona pertenece a una sola empresa por estudio.
- **Estratificado** por sector (CIIU sección) y tamaño (segmento SCVS), para que el test no quede
  sesgado hacia un tipo de empresa.
- **Semilla fija** y el split persistido en disco: los dos baselines y todo el resto de
  sub-proyectos usan exactamente el mismo test.

## 8. Los dos baselines de estreno

Enmienda de D-003: la premisa de la tesis se pone a prueba en vez de asumirse.

| | Representación | Universo de ajuste |
|---|---|---|
| **Baseline A** | 4 proporciones de composición + antigüedad | 2024–2025 (~1,3 M filas) |
| **Baseline B** | sin composición: texto del cargo + centro de costo + antigüedad | todos los años (~3,5 M) |

Ambos con **k-means** —el baseline obligatorio del spec §7— y evaluados sobre **el mismo held-out**
de empresas de 2024–2025, para que la comparación sea limpia.

Si **B iguala o supera a A**, la composición no aporta y se puede retirar media arquitectura del
spec de clustering (ILR, gate, residualización, IPW) **con evidencia**. Si **A gana**, queda
demostrado el aporte. Es el experimento **E1/E2** del spec §10, adelantado de la semana ~12 a la ~4.

Ninguno de los dos pretende ser el modelo bueno: son la vara contra la que se medirá el
sub-proyecto 2.

## 9. Pre-registro

Documento `docs/preregistro.md`, **congelado y commiteado antes de tocar el conjunto de test**.
Contiene:

1. La métrica primaria y la co-primaria (§6.1, §6.2), con la definición exacta de la variable
   objetivo, la regla de donantes y el umbral de partida.
2. El criterio de éxito **A o B** de D-004, con los cuatro desenlaces escritos y la declaración de
   que **C se reporta como complementariedad, no como victoria**.
3. La regla de selección de modelo: la perilla de granularidad y la familia se eligen **por
   estabilidad** (ARI entre submuestras de empresas), **nunca por el acierto salarial**.
4. La identidad del split de test (hash del listado de empresas apartadas).

## 10. Cómo se comprueba que el banco no está roto

Un instrumento de medida que nadie verificó no sirve para verificar nada. Antes de usarlo con datos
reales se le pasa **data sintética con la respuesta conocida**: N personas repartidas en R roles
inventados, con composiciones y niveles salariales distintos por rol, repartidas entre empresas con
un efecto empresa simulado.

Se le entregan al banco tres particiones: la verdadera, una aleatoria, y una deliberadamente mala
(p. ej. agrupar por inicial del nombre). **El banco debe ordenarlas correctamente.** Si no lo hace,
está mal el banco, y es infinitamente más barato descubrirlo aquí que tras nueve semanas de medir
con una regla torcida.

Casos que también se cubren con data sintética: que la abstención cuente en cobertura y no en error;
que el leave-company-out excluya efectivamente a la propia empresa; que el bootstrap remuestree
empresas y no filas; y que una partición con una celda por persona salga **mal**, no perfecta.

## 11. Estructura de código

Sigue el paquete existente (`src/benchmarking/`), con data sintética en tests y sin data real en el
repo.

| Módulo | Responsabilidad |
|---|---|
| `evaluacion/splits.py` | split de empresas estratificado, semilla fija, persistencia |
| `evaluacion/particiones.py` | construye aleatoria, `CARGO` crudo, solo-texto y techo supervisado |
| `evaluacion/referencia.py` | donantes, leave-company-out, mediana por celda, abstención |
| `evaluacion/metricas.py` | MAE, cobertura, curva error-cobertura, ω², bootstrap por empresa |
| `evaluacion/estabilidad.py` | test-retest 2024↔2025 y ARI entre submuestras |
| `evaluacion/informe.py` | tabla comparativa y gráfico |
| `cli.py` | subcomando `evaluar` |
| `research/experimentos/e0_banco/` | notebook que corre A y B y produce el informe |
| `docs/preregistro.md` | el documento congelado del §9 |

`referencia.py` y `metricas.py` son el corazón y deben poder leerse y probarse por separado: uno
construye la estimación, el otro la puntúa.

## 12. Salida esperada

```
Método                        Cobertura   MAE (log-SBU)      IC 95%
─────────────────────────────────────────────────────────────────────
Aleatorio (k igualado)           100%          0.___        [ , ]   <- piso
CARGO crudo (55.920 etiq.)        __%          0.___        [ , ]   <- rival real
Solo-texto (k igualado)          100%          0.___        [ , ]
Baseline A (con composición)     100%          0.___        [ , ]
Baseline B (sin composición)     100%          0.___        [ , ]
Techo supervisado                100%          0.___        [ , ]   <- máximo

Curva error-cobertura: <gráfico>
Test-retest (2024↔2025): __% de acuerdo
Cobertura exclusiva (personas sin cargo): __ personas
```

La frase que sale de aquí, y que es el resultado de la tesis, tiene esta forma: *"el arquetipo
recorre el __% de la distancia entre el `CARGO` y el techo alcanzable, con __ puntos más de
cobertura"*.

## 13. Riesgos y decisiones abiertas

- **El baseline A depende del sub-proyecto 0.** Sin el reproceso de 2024–2025 no hay composición con
  la que ajustarlo. El baseline B y todo el banco no dependen de él y pueden avanzar en paralelo.
- **`sueldo` como objetivo** deja fuera comisiones y extras. Es la elección consistente hoy, pero
  significa que el benchmark de esta fase es de salario base, no de efectivo total. Reevaluar cuando
  se conozca la cobertura real de composición.
- **El nulo solo-texto necesita embeddings**, y la revisión exacta del modelo debe fijarse ya como
  clave de caché para reproducibilidad (spec de clustering §11).
- **La referencia ISCO-08** para el test de validez externa (§6.4 del spec de clustering) no existe
  todavía: hay que construirla con etiquetado experto sobre una muestra y/o con los cargos de texto
  específico e inequívoco. Es trabajo real y conviene empezarlo pronto aunque se consuma en el
  sub-proyecto 5.
- **El umbral de donantes** `m=5, e=3` es un punto de partida con respaldo (BLS, spec §12), pero la
  curva completa se reporta igualmente, así que ninguna conclusión debe depender de ese valor.
