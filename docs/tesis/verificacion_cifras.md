# Verificación de cifras de `docs/tesis/tesis.tex`

Pase de verificación independiente, 2026-11-11. Revisor sin participación en la redacción.

**Alcance.** Toda cifra cuantitativa de `docs/tesis/tesis.tex` (1.298 líneas): porcentajes,
intervalos de confianza, conteos, métricas y tamaños de muestra, incluidas las que viven
dentro de `\pend{}` (son cifras que el documento ya se comprometió a sostener). **Quedan
fuera por consigna** las cifras atribuidas a literatura externa (Card, Massing, Wan,
TalentCLEF, ESCO como catálogo), porque no hay acceso a esas fuentes.

**Fuentes primarias consultadas,** en orden de autoridad:

1. `docs/registro_decisiones.md` (9.716 líneas; D-001..D-092 y T-001..T-028)
2. `research/**/salidas/*.txt` y `*.json` (salidas crudas)
3. `docs/mediciones.md` (congelado ~D-026)
4. `research/experimentos/e2_nivel/salidas/92_tabla_comparativa.txt`, recuperado con
   `git show a82eb72:` porque no está en el árbol de trabajo.

**Resumen por estado**

| Estado | Cifras |
|---|---|
| DISCREPA | 9 |
| SIN FUENTE | 8 |
| AMBIGUA | 4 |
| OK | 47 |
| **Total** | **68** |

---

## DISCREPA

| # | Cifra | Dónde en `tesis.tex` | Estado | Fuente o discrepancia |
|---|---|---|---|---|
| 1 | «+9,9 % y +19,4 %» (rango del cambio de centro al pasar a remuneración total) | L1164-1165, cap. Limitaciones | **DISCREPA** | `92_tabla_comparativa.txt` §3 (commit `a82eb72`, la fuente que el propio comentario L1168 declara) da **+9,5 % a +24,5 %**. Los dos extremos del rango están mal; el superior se queda corto en 5,1 puntos. |
| 2 | «Asistente Administrativo +9,9 %; Gerente de Operaciones +11,2 %; Jefe de Bodega +15,7 %; Auxiliar de Bodega +18,1 %; Auxiliar de Farmacia +19,4 %» | L1169-1170 (comentario de procedencia) | **DISCREPA** | `92_tabla_comparativa.txt` §3: Asistente Administrativo **+9,5 %**, Auxiliar de Bodega **+11,5 %**, Auxiliar de Farmacia **+24,5 %**, Gerente de Operaciones **+9,8 %**, Jefe de Bodega **+15,4 %**. **Las cinco cifras difieren** y además la asignación cargo→cifra está cruzada: el +18,1 % que el `.tex` da a Auxiliar de Bodega no corresponde a ningún cargo de la tabla. |
| 3 | «Medido sobre la base completa» (marco del experimento de objetivo) | L1163-1164 | **DISCREPA** | La fuente es explícita: los dos brazos corren sobre **las mismas 907.331 filas con composición**, el 90,7 % de la completa (`92_tabla_comparativa.txt` §1 y mensaje de `a82eb72`). No es la base completa, y decirlo así sobrestima la generalidad del sesgo declarado. |
| 4 | «0,620 del producto» en el resultado de open set | L842-843, cap. 6, con comentario `% [T-010b]` | **DISCREPA** | En `t10b_open_set.txt` el umbral fijo (`Cfijo`) da **0,6452**, y `A − Cfijo = +0,1385 [+0,0444, +0,2250]`, que es el `+0,139` citado. El **0,620 es de T-019** (`t19_open_set.txt`, `Cfijo` balanceada 0,620), otro conjunto. La línea aparea un punto de T-010b con un comparador de T-019 bajo una sola etiqueta de procedencia. El cap. 2 (L557) cita el par correcto, 0,784 frente a **0,645**: los dos capítulos se contradicen. |
| 5 | «994.348 filas de 6.710 empresas» (marco evaluable) | L687-688, cap. 3 | **DISCREPA** | Es la cifra de `mediciones.md:647-651`, congelado ~D-026. La base viva `base_v31` da **1.000.490 filas, 6.722 empresas, 65.181 títulos, 603.159 personas** (`92_tabla_comparativa.txt` §1, medido 2026-11-10; concuerda con `registro_decisiones.md:5285` y `:5527`). El `.tex` cita una versión superada de la base en la sección que define el corpus. |
| 6 | «66,6 %» — personas cubiertas por títulos con respaldo suficiente | L268, tabla `tab:espesor` | **DISCREPA** | `mediciones.md:614` define el 66,6 % como personas en celdas con **≥3 empresas**, sobre un catálogo de **65.081** etiquetas. La tesis define «respaldo suficiente» como **≥10 empresas y ≥10 personas** (L397-398; `registro_decisiones.md:9370`), y para esa definición el propio documento da **92,3 %** (comentario L401, `base_v31`). La tabla mezcla dos definiciones y dos bases, y su fila «Títulos distintos 65.181» no proviene de la misma tabla que el 66,6 %. |
| 7 | «58.051 títulos» (tamaño del índice del bi-encoder) | L497, cap. 2 | **DISCREPA** | `registro_decisiones.md:5541` y `:5688`: 58.051 son **grupos (nodos)**, no títulos, y corresponden a **`base_v16`**. Sobre `base_v31` son **39.143 grupos para 65.181 títulos** (`registro_decisiones.md:8398`). La cifra es doblemente vieja: unidad equivocada y versión retirada. |
| 8 | «una diferencia de $-0{,}321$» atribuida al juez | L161-162 (Resumen) y L203 (Abstract) | **DISCREPA** | El signo es correcto solo como `ESCO − juez` (`t16_jobbert.txt`: «ESCO - cross-encoder reentrenado: -0.321»). Redactado como está —«el juez obtiene 0,863 frente a 0,542, una diferencia de −0,321»— el sujeto de la diferencia es el juez, para quien vale **+0,321**. El cap. 2 (L443-444) repite la misma construcción. Es la primera cifra del documento y está con el signo invertido respecto de su sujeto gramatical. |
| 9 | «magnitudes del orden de $10^{-5}$» en el régimen directo | L1100 | **DISCREPA** | En la columna primaria de `t26_regimen.txt` (la que alimenta la tabla 7.4 del `.tex`) el régimen directo da **−0,00014** y **−0,00006**, es decir $10^{-4}$. Las magnitudes de $10^{-5}$ son las de la columna secundaria «todos los del estrato», que no es la que se tabula. |

---

## SIN FUENTE

| # | Cifra | Dónde en `tesis.tex` | Estado | Fuente o discrepancia |
|---|---|---|---|---|
| 10 | «101.188 filas del marco (el 10,1 %)» | L1171-1172 | **SIN FUENTE** | No aparece en `registro_decisiones.md`, en `mediciones.md` ni en ninguna salida del worktree de tesis, incluida la de `exp/objetivo-remuneracion`. `92_tabla_comparativa.txt` §1 permite derivar la exclusión por composición (1.000.490 − 907.331 = **93.159** filas, 9,3 %), que es otra cantidad. Si 101.188 son las filas que *entran* al cambiar el objetivo a total, el denominador del 10,1 % tampoco es «el marco». |
| 11 | «2.864 títulos» fuera de toda banda | L1174 | **SIN FUENTE** | Misma situación. La diferencia de títulos documentada es 65.181 − 62.873 = **2.308** (`92_tabla_comparativa.txt` §1). |
| 12 | SBU USD 460 (2024) / 470 (2025) / 482 (2026), Acuerdo MDT-2025-195 | L409, cap. 2 | **SIN FUENTE** | Ninguna de las tres cifras ni el número de acuerdo aparecen en el registro ni en las salidas. Es norma pública y probablemente correcta, pero el documento no la ancla a nada y los tres valores escalan toda la banda en dólares. |
| 13 | «78 % de los puestos… cubren el 21 % de las personas; el 1 % con 30 o más empresas cubre el 46 %» | L277-279, pie de figura `fig:espesor` | **SIN FUENTE** | No hay salida que las produzca. El propio `.tex` declara en L282 que `figuras.py` apunta a **`base_v15`** y que la base viva es `base_v31`. El 78 % se repite como afirmación en `registro_decisiones.md:9378` (dentro del bloque T-026) pero sin cálculo que lo respalde, y se reusa en el cap. 2 (L434, L541). |
| 14 | «un modelo destilado 400 veces más pequeño» | L481, cap. 2 | **SIN FUENTE** | Ninguna salida reporta esa razón. Derivada de 122 B / 280 M el valor es **≈436×**; «400 veces» no está redondeado hacia el lado conservador ni declarado como aproximación. |
| 15 | «el 82 % de las celdas vive en analogía… solo el 7,7 % de las personas» | L399-400, cap. 2 | **SIN FUENTE** | Solo respaldado por el comentario LaTeX de L401 («verificado 2026-11-10»). No hay salida, bloque T ni entrada de registro con esos conteos. Además contradice la fila del 66,6 % de la tabla 1.1 (ver #6): 100 − 7,7 = 92,3 ≠ 66,6. |
| 16 | «efecto empleador del 34--39 %» | L599, cap. 2 | **SIN FUENTE** | El 39 % aparece como aserción suelta en `registro_decisiones.md:667` y el 34 % en `:381`, ambos sin medición asociada y en contextos distintos (uno sobre abstención, otro sobre residualización). No existe una medición que produzca el intervalo 34--39 % como tal. |
| 17 | «76 equipos y más de 280 envíos» (TalentCLEF) | L638, cap. 2 | **SIN FUENTE** | Literatura externa, no verificable aquí. Se anota porque es una cifra concreta sin comentario de procedencia, a diferencia de las demás del cap. 2. |

---

## AMBIGUA

| # | Cifra | Dónde en `tesis.tex` | Estado | Fuente o discrepancia |
|---|---|---|---|---|
| 18 | «$\omega^2 = +0{,}2462$ / 13,2 %» bajo la columna «$R^2$ fuera de muestra» | L898, tabla `tab:ejes` | **AMBIGUA** | Las tres primeras filas vienen de `03_premisa_continua_fuera_de_muestra.txt` (R² **fuera de muestra**, 585.194 filas, 2.924 etiquetas, residuo tras empresa+cargo, var 0,0603). La cuarta viene de `05_paga_el_nivel_y_techo_estratificado.txt`: es **$\omega^2$ dentro de muestra**, sobre **otro residuo** (tras empresa + **ÁREA**, var 0,1828) y **otra submuestra** (228.212 personas en 3.357 áreas con ≥2 rangos). Las cuatro cifras son correctas en su propia fuente, pero la columna las presenta como comparables y no lo son. El comentario L902-904 advierte sobre Rango-vs-Nivel pero no sobre esto. |
| 19 | «vale 59 veces más» | L907 | **AMBIGUA** | 0,2462 / 0,0042 = **58,6** (razón de R²) y 13,18 / 0,21 = **62,8** (razón de reducción de sd). Ambas derivaciones son legítimas; el propio `.tex` lo marca en L908-909. Además hereda el problema de #18: es una razón entre dos cifras de marcos distintos. |
| 20 | «$2{,}11\times$» de recorrido en pago por jerarquía | L769, cap. 4 | **AMBIGUA** | `05_paga_el_nivel…txt` da «recorrido de nivel 1 a 5: **+0,7471 en log**», y $e^{0{,}7471} = 2{,}111$: la cifra cuadra. `registro_decisiones.md:1430` la cita ya convertida. Pero el `.tex` la atribuye a `% [e0_banco, 668 etiquetas; D-012]`, y las 668 etiquetas son del experimento de coseno (`mediciones.md:706`), no del de niveles (847.046 filas). Procedencia mal asignada. |
| 21 | «65.181 títulos» frente al 65.081 del comentario | L253, L265, L1151 | **AMBIGUA → se resuelve a favor de 65.181** | El comentario L254-255 pide reconciliar. **65.181** es el conteo vigente y aparece así en `base_v15`, `base_v18` y `base_v31` (`registro_decisiones.md:5527`, `:8175`, `:8777`; `t01_recuperacion.txt`; `92_tabla_comparativa.txt` §1). **65.081** es el conteo de *etiquetas/celdas* de las decisiones D-005..D-018 (`:1334`, `:1998`, `:2087`), anterior a la base. El `.tex` puede fijar 65.181 y retirar el `\verificar`; lo que no puede es seguir tomando el 66,6 % de la tabla de 65.081 (ver #6). |

---

## OK

| # | Cifra | Dónde en `tesis.tex` | Estado | Fuente |
|---|---|---|---|---|
| 22 | 164.096 votos | L947, L1005 | OK | `t18_varianza.txt`: «votos 164,096» |
| 23 | varianza total 0,477 | L1005 | OK | `t18_varianza.txt`: «varianza total 0.4773» |
| 24 | 38.715 cargos | L1024 | OK | `t18_varianza.txt`: «cargos 38,715» |
| 25 | 6.719 efectos de empresa | L1007 | OK | `t18_varianza.txt`: «empresas 6,719» |
| 26 | Nivel 46,3 % | L957, L1022 | OK | `t18_varianza.txt`, R² fuera: nivel 46.3 % |
| 27 | Cargo 57,4 % | L958, L986, L1023 | OK | `t18_varianza.txt`, R² fuera: cargo 57.4 % |
| 28 | Empresa 26,5 % | L959, L987 | OK | `t18_varianza.txt`, R² fuera: empresa 26.5 % |
| 29 | Cargo + empresa 68,4 % | L960, L1026 | OK | `t18_varianza.txt`: 68.4 % |
| 30 | Nivel + empresa 64,1 % | L1025 | OK | `t18_varianza.txt`: 64.1 % |
| 31 | Sin explicar 31,6 % | L962 | OK | `t18_varianza.txt`: «sin explicar con cargo + empresa: 31.6%» |
| 32 | La empresa agrega 11,0 puntos | L969, L987, L1004, L1007 | OK | `t18_varianza.txt`: «+11.0% de la varianza»; `registro:8952` |
| 33 | «cerca del 43 %» fuera del alcance del título | L173, L970, L1068 | OK | 11,0 + 31,6 = 42,6; titular del resultado T-018 (`registro:` «~43 %») |
| 34 | «4 puntos» de 64,1 a 68,4 | L1025-1026 | OK | 68,4 − 64,1 = 4,3, ambas de `t18_varianza.txt` |
| 35 | «más de cuatro quintas partes» (nivel vs cargo) | L1023 | OK | 46,3 / 57,4 = 0,807 |
| 36 | $\tau = 0{,}2917$, $\sigma = 0{,}1423$ | L600, L977, L1042, L1053 | OK | `01_tau_y_sigma_son_globales.txt`: «GLOBAL … tau=0.2917 sigma=0.1423» |
| 37 | $\tau^2/(\tau^2+\sigma^2) = 0{,}08509/0{,}10534 = 0{,}808$, «el 81 %» | L980-985 | OK | Aritmética exacta sobre #36: 0,0850889 / 0,1053344 = 0,8078 |
| 38 | Techo del 12,1 % | L602, L1054 | OK | `05_paga_el_nivel…txt`: «TODO (referencia) n=847.046 sd actual=0.3700 sd ideal=0.3253 TECHO=12.1%»; `registro:1375` y Enmienda 2 (`:1459-1477`) que lo fija en 12,1 % y no 10,9 %; `mediciones.md:818` |
| 39 | Oráculo de nivel $-0{,}00140$ $[-0{,}00275, -0{,}00018]$ | L667, L933 | OK | `registro:` tabla de resultado T-017 |
| 40 | Oráculo de reconocimiento $+0{,}00261$ $[+0{,}00051, +0{,}00441]$ | L171, L208, L666, L934, L1067 | OK | `registro:` tabla de resultado T-017 |
| 41 | «un 0,35 % del pinball» (oráculo de nivel) | L940 | OK | Resultado T-017, lectura: «−0,0014, un 0,35 % del pinball» |
| 42 | ESCO balanceada 0,542 vs 0,863; $-0{,}321$ $[-0{,}371, -0{,}271]$ (magnitudes) | L161, L203, L443, L803 | OK | `t16_jobbert.txt` parte B, `cerca` n=991. (El signo, ver #8.) |
| 43 | 991 pares, 790 «sí» | L163, L803 | OK | `t16_jobbert.txt`; `t27_llm_decisor.txt`: «cerca … n=991, si 790» |
| 44 | ESCO: 2.938 ocupaciones, 13.959 nombres en español | L802 | OK | `t16_jobbert.txt` parte B |
| 45 | Cobertura ESCO: mediana 0,70; 22 % pasa 0,8 | L297, L804 | OK | `t16_jobbert.txt`: «mediana 0.70; >= 0,8 22%» |
| 46 | JobBERT-v3 r@1 2,7 / r@10 19,2 / MRR 0,082 | L468 | OK | `t16_jobbert.txt` parte A |
| 47 | Vertex 3,3 / 16,7 / 0,079 | L469 | OK | `t16_jobbert.txt`, `t01_recuperacion.txt`, `t20_recuperacion.txt` |
| 48 | Qwen título+descripción 4,1 / 22,2 / 0,101 | L470, L808 | OK | ídem |
| 49 | JobBERT $-3{,}1$ pts $[-4{,}6, -1{,}5]$ | L472, L809 | OK | `t16_jobbert.txt`: «JobBERT - Qwen titulo+desc: -3.1 pts [-4.6, -1.5]» |
| 50 | JobBERT $+2{,}5$ $[+0{,}9, +4{,}1]$ sobre Vertex | L810 | OK | `t16_jobbert.txt` |
| 51 | 2.090 consultas | L166, L808 | OK | `t01_recuperacion.txt`, `t16_jobbert.txt`, `registro:7836` |
| 52 | Open set propuesto 0,784 | L557, L842, L853 | OK | `t10b_open_set.txt`: A balanceada 0.7838; `registro:8457` |
| 53 | Umbral fijo 0,645 (cap. 2) | L557 | OK | `t10b_open_set.txt`: `Cfijo` 0.6452 |
| 54 | $+0{,}139$ $[+0{,}044, +0{,}225]$ | L557, L843 | OK | `t10b_open_set.txt`: «A - Cfijo: +0.1385 [+0.0444, +0.2250]» |
| 55 | T-019: 0,780 y $+0{,}160$ $[+0{,}084, +0{,}233]$ | L847 | OK | `t19_open_set.txt`, brazo n=40 |
| 56 | «De 809 títulos, solo 40 eran nuevos» | L847-848 | OK | `t19_open_set.txt`: «consultas de T-019: 809 -> nuevas 40» |
| 57 | 23 consultas nuevas en T-010b | L1157 | OK | `t10b_open_set.txt`: «PRUEBA (413 con equivalente, 23 nuevas)» |
| 58 | T-020: $+0{,}246$ $[+0{,}150, +0{,}326]$ y $+0{,}057$ $[-0{,}028, +0{,}150]$ | L815-816 | OK | `t20_open_set.txt`: «A - L: +0.2458 [+0.1498, +0.3259]»; «A - LCE: +0.0569 [-0.0284, +0.1495]» |
| 59 | T-024: 78,1 % / 18,4 % / 3,4 % | L857-858, L1188 | OK | `t24_errores.txt`: «acierto 572 (78.1%); no reconoce 135 (18.4%); reconoce mal 25 (3.4%)» |
| 60 | T-012 / T-012b: 0,562 y 0,712 frente a 0,784 | L852-853 | OK | `registro:8747-8748` |
| 61 | T-026, cuatro filas de la tabla `tab:regimen` | L1089-1092 | OK | `t26_regimen.txt`, columna primaria por estrato (los cuatro puntos e IC coinciden exactamente) |
| 62 | T-027: $+0{,}046$ $[-0{,}044, +0{,}137]$, no concluyente | L579-580 | OK | `t27_llm_decisor.txt`: «balanceada, v9 - LLM: +0.046 [-0.044, +0.137] -> no concluyente» |
| 63 | T-027: $+0{,}032$ $[+0{,}003, +0{,}060]$ en cercanos | L576 | OK | `t27_llm_decisor.txt`, conjunto `cerca` |
| 64 | T-027: 82× más rápido, 164× más barato, $n=100$ | L583-585 | OK | `t27_llm_decisor.txt`, sección COSTO Y LATENCIA; `t27_tiempos.json`. El supuesto de 3,00 USD/H200-hora está declarado en la salida y **no** en el `.tex` |
| 65 | «el LLM sin superar al destilado en ningún conjunto» | L584 | OK | `t27_llm_decisor.txt`: v9 − LLM ≥ 0 en los dos conjuntos |
| 66 | T-009: AUC $0{,}572 \to 0{,}732$, $+0{,}160$ $[+0{,}052, +0{,}262]$; cerca $0{,}929 \to 0{,}938$ | L790-792 | OK | `registro:8322-8326`, tabla de T-009 etapa 1 |
| 67 | 19.705 pares; 9.305 etiquetados por Qwen | L778 | OK | `registro:8317` (19.705 = plata v3 + 6.308 + 2.997 = 9.305 de Qwen); `registro:9432` confirma «los 9.305 pares» |
| 68 | Qwen 78,5 % frente a GLM 71,2 % | L783 | OK | `registro:8305-8306` y `:8443` |
| 69 | T-023: 952 empresas, 136.834 filas, `169177f7…` | L751-752 | OK | `registro:9175`; `t23_empresas_test.json` |
| 70 | T-023: $-0{,}00282$ $[-0{,}00519, -0{,}00059]$ | L1129 | OK | `registro:9228` |
| 71 | «coincide con validación ($-0{,}0032$)» | L1131 | OK | `registro:8795`, `:8800`, `:9162` |
| 72 | «mejora final de un 1,0 % del pinball» | L1176 | OK | Resultado T-023: «en todos los votos del test, de 0,1270 a 0,1258 (−1,0 %)» |
| 73 | T-025: Qwen explica el 58 % de la mejora acumulada | L1124 | OK | `t25_ablacion.txt` acumulativa: paso Qwen −0,00098 sobre −0,00170 del total = 57,6 % |
| 74 | e5 adoptado con $+0{,}00141$ frente a margen $+0{,}001$ | L1139 | OK | `registro:9166`: «T-015 no cumplió el margen (extremo +0,00141 > +0,001)» |
| 75 | Composición disponible en el 2,7 % de las filas, recuperada al 86,7 % | L879-880 | OK | `registro:182`, tabla «Antes ~2,7 % / Después 86,7 %» |
| 76 | Tabla de ejes: placebo $-0{,}0002$; composición $+0{,}0042$ / 0,21 %; antigüedad $+0{,}0114$ / 0,57 % | L895-897 | OK | `03_premisa_continua_fuera_de_muestra.txt` (ver #18 por la cuarta fila) |
| 77 | $\omega^2$ Nivel $= 0{,}2388$ (comentario) | L903 | OK | `05_paga_el_nivel…txt`: «NIVEL (5 escalones) +0.2388 -> reduce la sd un 12.75%» |
| 78 | Coseno 0,857 (rango) / 0,764 (área) / 0,944 (`GERENTE` vs `JEFE DE AUDITORIA`), 668 etiquetas | L766-770 | OK | `mediciones.md:706`, `:720-721`, `:737`; `registro:1296-1301` |
| 79 | 81 grafías de `ASISTENTE ADMINISTRATIVO` | L286, L378 | OK (con reserva de versión) | `registro:5543`: «grupo más grande … 81 (grafías de `ASISTENTE ADMINISTRATIVO`)», **en `base_v16`**. Sobre `base_v31` el tamaño del grupo puede diferir. El `\verificar` de L289-290 puede retirarse, pero conviene anotar la versión |
| 80 | Mediana 2 personas / 1 empresa por título | L266-267 | OK (con reserva) | `mediciones.md:608-610`. Misma tabla de 65.081 etiquetas que origina el problema #6 |
| 81 | Régimen directo = ≥10 empresas y ≥10 personas | L397-398 | OK | `registro:9370` |
| 82 | 21.738 votos directos / 16.712 por analogía (implícito en tabla 7.4) | L1089-1092 | OK | `t26_regimen.txt`; `registro:9376` |
| 83 | 122 B (Qwen3.5) y 280 M (cross-encoder) | L569, L576, L583, L822 | OK | `t27_llm_decisor.txt`: «cross-encoder v9 (280 M)», «Qwen3.5-122B» |
| 84 | Juez de equivalencia: $-3{,}1$ pts como decisor frente a descripción generada | L472 | OK | `t16_jobbert.txt` parte A (es la cifra de recuperación; ver nota abajo) |

**Nota sobre #84.** El cap. 2 (L472-473) presenta el $-3{,}1$ $[-4{,}6, -1{,}5]$ como el
resultado de JobBERT-v3 «**como juez de equivalencia**». En la fuente ese $-3{,}1$ es de
**recuperación** (parte A, r@10). Como juez, JobBERT-v3 aparece en la parte B bajo el
nombre «ESCO (JobBERT)» con balanceada 0,576 (`lejos`) y 0,542 (`cerca`). La cifra está
bien; la frase que la introduce le cambia la tarea. Es menor porque el párrafo anterior ya
dio las de recuperación, pero conviene reescribirlo.

---

## Respuesta a la pregunta abierta de L1057 (en qué subconjunto se estimaron $\tau$ y $\sigma$)

El `\pend{}` de L1057-1059 queda **resuelto**, y la respuesta es favorable al documento:

- $\tau = 0{,}2917$ y $\sigma = 0{,}1423$ son el estimador **global agrupado sobre todo el
  marco de entrenamiento**: 847.046 filas, 5.758 empresas, 57.432 cargos
  (`01_tau_y_sigma_son_globales.txt`, primera línea; `research/experimentos/e3_varianza/01_tau_y_sigma_son_globales.py`).
  **No** están restringidos a celdas con respaldo suficiente.
- La restricción a `MIN_EMPRESAS = 20` del script afecta **solo** al análisis por celda
  (704 celdas de 57.432), no al estimador global.
- El temor del `\pend` —«la cola larga es más dispersa y la cifra no se generaliza»— **se
  confirma, y en la dirección que refuerza la conclusión**: la distribución por celda da
  $\tau$ p05 = 0,080, p50 = **0,322**, p95 = 0,663, un recorrido de **8,3×**, con la
  mediana por encima del global 0,2917. Donde el catálogo es delgado, $\tau$ tiende a ser
  **mayor**, no menor, de modo que el 81 % de la ecuación (7.1) está si acaso **subestimado**
  en la cola. El test-retest entre mitades (Pearson +0,780 para $\tau$) descarta que esa
  dispersión sea ruido de estimación.
- Esto es material para la sección 7.4 y para Limitaciones, y se puede escribir con
  cifras exactas sin correr nada nuevo.

## Veredicto sobre la sección 7.4 (reconciliación del efecto empleador)

**La versión actual es correcta.** Se verificó una por una: 46,3 / 57,4 / 26,5 / 64,1 /
68,4 / 11,0 / 31,6 coinciden exactamente con `t18_varianza.txt`, y la varianza total
declarada en L1005 es **0,477**, la real de T-018, no la 0,247 despejada de la versión
anterior. El texto dice explícitamente que las dos cantidades **no son sumables ni
despejables** y separa unidad (personas vs votos), denominador (dentro de celda vs total)
y penalización (dentro vs fuera de muestra). No reaparece ningún despeje.

Dos observaciones menores sobre esa sección:

1. El 41,9 % de `t18_varianza.txt` («lo que agrega el CARGO una vez conocida la empresa»)
   **no aparece** en el `.tex`. No es un error, pero es la cifra que cierra la simetría con
   el 11,0 % y haría más difícil malinterpretar la tabla.
2. L1024 dice «38.715 cargos distintos» al comparar contra el nivel. Correcto, pero la
   tabla 7.2 se evalúa sobre submuestras de prueba distintas por modelo (27.326 votos para
   cargo, 32.733 para nivel, según `t18_varianza.txt`). Vale la pena declararlo: los R²
   fuera de muestra de filas distintas no se comparan sobre exactamente el mismo conjunto.

---

## LAS 5 MÁS GRAVES

### 1. Las cinco cifras del experimento de remuneración total están todas mal (#1, #2, #3)

`tesis.tex` L1163-1170, capítulo de Limitaciones. El `.tex` afirma un rango de
**+9,9 % a +19,4 %** y lista cinco cargos con sus porcentajes. La fuente que el propio
comentario declara —`92_tabla_comparativa.txt`, commit `a82eb72`— da **+9,5 % a +24,5 %**
y **ninguna** de las cinco cifras coincide: Auxiliar de Farmacia es +24,5 %, no +19,4 %;
Auxiliar de Bodega es +11,5 %, no +18,1 %. Además la asignación cargo→cifra está cruzada.
Y la frase «medido sobre la base completa» contradice a la fuente, que dice 907.331 filas
con composición (90,7 %).

Es lo primero que arreglaría porque es el peor caso posible en esta tesis: una cifra que
*lleva* su comentario de procedencia y aun así no coincide con él. Un tribunal que abra
una sola salida encuentra esto, y el daño no se limita a la viñeta: pone en duda la
convención de procedencia entera, que es el activo del documento. Agravante: el error
**subestima** el sesgo que la viñeta declara (el techo real es 24,5 %, no 19,4 %), así que
no se puede defender como redondeo conservador.

### 2. El 66,6 % de la tabla 1.1 contradice al 92,3 % del capítulo 2 (#6, #15)

La tabla `tab:espesor` (L268) atribuye 66,6 % de las personas a «títulos con respaldo
suficiente». Pero 66,6 % es, en `mediciones.md:614`, el de celdas con **≥3 empresas** sobre
un catálogo de **65.081** etiquetas, mientras la tesis define respaldo suficiente como
**≥10 empresas y ≥10 personas** (L397) y para esa definición da **92,3 %** (L401, `base_v31`).
Las dos cifras están en el documento, a 150 líneas de distancia, y son incompatibles.

Lo pongo segundo porque es la cifra que sostiene la motivación entera del capítulo 1 («el
catálogo es delgado») y porque el error no se ve sin ir a la fuente: ambas cifras suenan
plausibles. Arreglo: recalcular sobre `base_v31` con la definición de L397 y usar un solo
número en los dos lugares.

### 3. El capítulo 6 compara contra un baseline de otro experimento (#4)

L842-843 reporta «0,784 frente a **0,620** del producto, +0,139» bajo la etiqueta
`% [T-010b]`. En T-010b el umbral fijo vale **0,645**, y el +0,139 es precisamente
`0,784 − 0,645`. El 0,620 viene de T-019. O sea: el punto, el comparador y el delta no
cierran entre sí, porque el comparador se tomó prestado de otro bloque.

Es exactamente el fallo que el propio proyecto ya documentó como prohibido («nunca armes
una comparación con cifras de experimentos distintos»), y el capítulo 2 del mismo
documento ya lo cita bien con 0,645. Dos capítulos de la misma tesis se contradicen.
Arreglo trivial: 0,620 → 0,645 en L842.

### 4. El marco del corpus cita una versión retirada de la base (#5, #7)

L687-688 define el corpus como **994.348 filas / 6.710 empresas**, de `mediciones.md`,
congelado hacia D-026. La base viva `base_v31` da **1.000.490 filas / 6.722 empresas**
(medido 2026-11-10). En paralelo, L497 dice «58.051 títulos» cuando son 58.051 **grupos**
de **`base_v16`**, y `base_v31` tiene **39.143 grupos** para 65.181 títulos.

Lo grave no es la magnitud —6.710 contra 6.722 es irrelevante numéricamente— sino que el
capítulo que *fija el corpus* lo fija sobre una base que ya no es la que produce los
resultados de los capítulos 5 a 7. Cualquier recuento que el tribunal haga sobre los
artefactos dará otra cosa. Y el 58.051 cambia de unidad además de versión, que es un error
de tipo distinto y más difícil de detectar.

### 5. La primera cifra del Resumen tiene el signo invertido respecto de su sujeto (#8)

L161-162: «el juez obtiene una exactitud balanceada de 0,863 frente a 0,542, una diferencia
de **−0,321**». La diferencia del juez sobre ESCO es **+0,321**; el −0,321 es `ESCO − juez`,
como lo reporta `t16_jobbert.txt`. Lo mismo en el Abstract (L203) y en el capítulo 2 (L443).

Lo incluyo entre las cinco porque es la **primera cifra que lee el tribunal** y porque,
leída literalmente, dice que el juez es peor que ESCO —lo contrario del resultado. Es un
arreglo de un carácter en tres lugares, con el mayor retorno por esfuerzo de toda esta
lista.

---

## Recomendación de proceso

Tres de los cinco hallazgos graves (#1, #4 y en parte #2) tienen la misma causa: **cifras
copiadas de una fuente que después cambió de versión**, sin un paso que lo detecte. La
convención de `% [T-0XX]` dice *de dónde salió* una cifra pero no *cuándo*, y no falla
ruidosamente cuando la fuente se mueve.

Sugerencia concreta, barata y en la línea del resto del expediente: añadir la **fecha o el
hash de la corrida** al comentario de procedencia —`% [T-018, t18_varianza.txt, 2026-10-23]`—
y un script que, para cada comentario, verifique que la cifra adyacente aparece literalmente
en el archivo citado. La mitad de los DISCREPA de este informe los habría encontrado una
expresión regular.
