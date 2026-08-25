# E1 — La premisa central, medida

Trece mediciones que reformularon el alcance de la tesis (**D-013**, `mediciones.md` §15).

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

## `11` — el barrido de granularidad, y el precio de la cobertura

Contesta la pregunta del director en su forma mas simple: si `CARGO` tiene celdas de 2 personas,
.cuanto se gana engrosandolas?

| Agrupamiento | Celdas | Cobertura | MAE | c* del cruce | En dolares |
|---|---|---|---|---|---|
| **`CARGO` crudo** | 12.057 | 53,8% | **0,2409** | — | — |
| texto k=5000 | 5.000 | 74,2% | 0,2640 | 0,325 | 38,4% |
| **texto k=1000** | 1.000 | **92,7%** | 0,2672 | **0,304** | **35,5%** |
| texto k=200 | 200 | 84,7% | 0,2991 | 0,400 | 49,3% |
| texto k=50 | 50 | 100% | 0,3763 | 0,534 | 70,6% |

**Engrosar NO mejora la precision.** El mecanismo que se esperaba —mas gente por celda, mediana
mejor estimada— existe, pero lo cancela el contrario: la celda gruesa mezcla puestos que pagan
distinto. El MAE sube en todos los puntos.

**Lo que compra engrosar es cobertura, y tiene un precio exacto.** Pasar del 53,8% al 92,7% cuesta
`c* = 0,304`, o sea aceptar una respuesta con un ~35% de desvio a cambio de no callarse. Es la
frontera A/B de D-004 medida sobre datos reales, y **es una decision de negocio, no de
estadistica**: hay que preguntarle a ActuaLab cuanto le cuesta al cliente no tener respuesta, y
fijarlo en el pre-registro antes de tocar el test.

**Que este experimento NO prueba.** Agrupa por TEXTO, y los embeddings son ciegos a la jerarquia
(D-012): mezclan `GERENTE DE AUDITORIA` con `JEFE DE AUDITORIA` a 0,944. Es el rival que se
esperaba que perdiera, no el arquetipo. El arquetipo anade nivel y sector, que es engrosar **y**
partir a la vez, y eso este barrido no lo mide.

**Dos trampas metodologicas que costaron una version del script:**

- `MAE * cobertura` es el riesgo generalizado con **coste cero por callarse**, asi que premia
  abstenerse: con esa cuenta `CARGO` "gana" por el mero hecho de no responder al 46% de la gente.
  El unico numero comparable es el riesgo a un `c > 0`, y el que decide es el `c` del cruce.
- El `AUGRC` de la tabla **no es comparable entre metodos con techos de cobertura distintos**: se
  normaliza sobre el rango que cada uno alcanza. Sirve para ordenar la confianza dentro de un
  metodo, no para compararlos entre si. Para eso esta `c*`.

**Aviso de muestra:** con 1.200 empresas `CARGO` cubre el 53,8% frente al 66,6% del train completo,
asi que el barrido **favorece** a los metodos gruesos. Aun asi pierden en precision.

## `12` — prestar fuerza al vecindario en vez de fusionar

`11` mostro que engrosar pierde precision porque FUSIONA celdas. Aqui se prueba la otra via:
cada celda se queda donde esta y toma prestada informacion de las que se le parecen, con
Fay-Herriot (1979) — `gamma_c = sigma_u^2 / (sigma_u^2 + v_c)`, donde `v_c` es la varianza de
muestreo que el banco ya calcula. **Sin parametros libres:** `sigma_u^2` sale por momentos.

El vecindario se define con el TEXTO del cargo. El salario nunca entra en decidir quien se
parece a quien; solo el prestamo usa salarios de otras celdas, que es lo que hace cualquier
estimador de area pequena y lo que el BLS hace con sus donantes.

### Dos regimenes

**Donde `CARGO` ya responde (53,8%):** k=25 −0,12%, **k=50 −1,63%**, k=100 −1,50%. Hay optimo
cerca de k=50. **Es la primera vez que algo baja el error a cobertura constante** — misma gente
atendida, solo mejor estimada. Engrosar no lo logro en ningun punto.

**Donde no responde:** el **35,9%** de la gente de eval tiene un cargo que no aparece en train
(3.438 etiquetas). Una etiqueta nueva no tiene donantes propios pero si vecindario: se embebe y
se coloca. **Cobertura 53,8% -> 89,7%**, con MAE 0,336 en esa poblacion nueva, frente a los 0,376
que costaba cubrir al 100% engrosando (`11`).

### Frente a engrosar

| Ruta | Cobertura | MAE | c* |
|---|---|---|---|
| Engrosar (`11`, k=1000) | 92,7% | 0,2672 | **0,304** |
| Prestar fuerza (`12`, k=50) | 89,7% | 0,2767 | 0,330 |

Para comprar cobertura pura engrosar sale **marginalmente mas barato**. La diferencia que el `c*`
no captura: **engrosar empeora al 53,8% que ya estaba atendido y prestar fuerza lo mejora.** Una
ruta destruye lo que funcionaba; la otra lo conserva y anade encima.

### Limites

- **Un solo split.** El −1,63% necesita el bootstrap pareado antes de afirmarse.
- **`k` no se elige por el MAE de aqui** (D-005 Enmienda 1). Este barrido mide sensibilidad.
- El 1,63% captura ~15% del presupuesto de error de estimacion medido en `04` (10,9%).

## `13` — partir y prestar, con contraste pareado: nada gana

La hipotesis era una sinergia: **partir** por sector arregla las etiquetas anchas (D-014) pero
adelgaza las celdas; **prestar fuerza** arregla las celdas delgadas (`12`). Deberian habilitarse
mutuamente — se puede partir fino PRECISAMENTE porque se presta.

Cuatro metodos, mismo estimador, mismo split, y contraste pareado de dos etapas con 150 replicas.
**Cada contraste sobre SU PROPIA interseccion de dos**: agregando sobre la interseccion de los
cuatro se comparaba solo el 23% mejor poblado, que es justo donde prestar fuerza no hace falta.

| Metodo | Cobertura | MAE |
|---|---|---|
| `CARGO` crudo | 54,7% | 0,2409 |
| `CARGO` + vecindario | 90,6% | 0,2765 |
| `CARGO` x sector | 23,7% | 0,2135 |
| `CARGO` x sector + vecindario | 72,5% | 0,2945 |

| Contraste | Diferencia | IC 95% | n |
|---|---|---|---|
| vecindario − crudo | +0,0009 | [−0,0085, +0,0088] | 45% |
| sector − crudo | +0,0062 | [−0,0062, +0,0193] | 23% |
| sector+vecindario − crudo | +0,0178 | [−0,0086, +0,0644] | 33% |
| sector+vecindario − vecindario | +0,0126 | [−0,0016, +0,0358] | 73% |

**Ninguno gana.** Los cuatro IC cruzan el cero y los cuatro puntos estimados son positivos, es
decir peores. El ultimo roza la significacion **en la direccion contraria**: anadir el sector al
vecindario empeora.

**El −1,63% de `12` era ruido de un solo split.** Sobre su interseccion correcta (45%) queda en
+0,0009. Retirado.

**El MAE de 0,2135 de `CARGO x sector` es un artefacto de seleccion**, no una mejora: solo responde
para el 23% mas facil. Con el contraste pareado sobre esa misma poblacion, +0,0062 y no
significativo.

### Dos errores de proceso que costaron cuatro corridas

- Un bucle de Python por celda dentro del bootstrap: 15.495 celdas x 4 metodos x 150 replicas =
  9,3 millones de iteraciones, dos horas largas. **El paquete ya tenia `_cuantil_por_grupo`
  vectorizado**, escrito precisamente porque el bootstrap costaba 20 horas — y el script de
  investigacion no lo reutilizo.
- Una edicion rota dejo el fichero ejecutando la ruta vieja, y la salida salio **identica** a la
  anterior. Esa identidad era la senal, y se reporto el resultado antes de verla.

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
