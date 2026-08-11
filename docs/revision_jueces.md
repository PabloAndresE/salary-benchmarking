# Revisión por panel de jueces — 2026-08-07

Cuatro revisiones independientes del diseño del núcleo, cada una con un lente distinto y con el
encargo explícito de **atacar la idea, no validarla**. Ninguno vio el informe de los otros.

Lo más informativo no son los veredictos por separado, sino **dónde convergen sin haberse hablado**
y dónde se contradicen.

| Lente | Encargo |
|---|---|
| **Metodólogo estadístico** | ¿está justificado el esquema de bloques y pesos, o es un invento indefendible? |
| **Aprendizaje de representación** | ¿qué metodología establecida está el diseño reinventando peor? |
| **Compensaciones (práctica)** | ¿qué hace la industria con nóminas sucias, y qué ignora este diseño? |
| **Tribunal de tesis** | ¿por dónde se ataca esto en una defensa? |

Documentos que revisaron: los dos specs, `registro_decisiones.md` (D-001 a D-008) y el plan del
banco.

> ⚠️ **Aviso: una premisa del encargo era falsa.** Los revisores recibieron D-008, que afirmaba que
> `cargo_plantilla` era *"una segunda etiqueta del mismo puesto, independiente de la del estudio
> actuarial"*. **Medido después (D-010): son la misma cadena en el 100% de los casos.** El estudio
> se construye a partir de la plantilla, así que el campo es una copia.
>
> Afecta a las conclusiones que apoyaban en esa fuente — dos jueces la calificaron como "el activo
> infravalorado del proyecto" y "la única fuente no circular de restricciones informativas y de
> cannot-links". **El error es del encargo, no de los revisores**, y su diagnóstico sobre por qué
> los must-links actuales son degenerados (§1) sigue siendo válido: lo que cambia es que la salida
> propuesta ya no existe por esa vía. Queda el catálogo sectorial.

---

## 1. La convergencia grave — D-007 está roto

**Dos jueces, por caminos independientes, demuestran que los must-links tal como se definieron no
pueden funcionar.**

La decisión D-007 estableció los *must-links* como criterio no circular para elegir pesos de
bloque. El metodólogo lo desmonta con una demostración:

> Un grupo-semilla se definió como *"la misma etiqueta de cargo"*. Dos personas unidas por un
> must-link tienen por construcción **la misma cadena de texto** → el mismo embedding →
> **distancia de texto exactamente 0**. El argmax sobre pesos que maximiza la satisfacción de
> must-links es trivial y único:
>
> `w_texto → 1`, `w_composición, w_centro, w_antigüedad → 0`

Es decir: **el procedimiento converge al nulo solo-texto, que es justo el rival al que hay que
vencer.**

El juez de representación llega a la misma conclusión por otra vía: el conjunto de restricciones
tiene ***informativeness* ≈ 0** en el sentido de Davidson, Wagstaff & Basu (PKDD 2006) — no aporta
información que el bloque de texto no tuviera ya. Y añade un agravante específico: con RCA, al
blanquear por la covarianza intra-*chunklet*, **se encogen las direcciones que varían dentro de un
mismo cargo textual — que es exactamente donde vive la composición**. Saldría *"la composición no
aporta"* por construcción del estimador.

**Tres agravantes que ambos señalan:**

1. **Faltan cannot-links.** Solo con restricciones positivas, la solución "todo en un cluster" las
   satisface al 100%. Toda la literatura de metric learning con restricciones usa must-link **y**
   cannot-link precisamente por eso.
2. **Sesgo de selección en el 29%.** Los 2.511 grupos exigen etiqueta repetida en ≥3 empresas con
   ≥10 personas, lo que selecciona las ocupaciones **estandarizadas** — perchador (CV 0,10),
   guardia (0,17) — justo donde `CARGO` ya funciona. Se afinaría en la mitad fácil y se
   extrapolaría a la sucia.
3. **D-008 no lo arregla por sí solo.** El filtro de dos etiquetas concordantes sigue estando
   llaveado por identidad de cadena de la primera etiqueta.

**Qué hacer.** Los must-links tienen que unir **cadenas distintas** (CHOFER↔CONDUCTOR), no
idénticas. Fuentes válidas: el cruce `cargo` × `cargo_plantilla` (D-008) y los sinónimos oficiales
del catálogo sectorial. Y hay que **medir informatividad y coherencia antes de usar cualquier
conjunto de restricciones** — es un diagnóstico calculable, no una intuición.

---

## 2. La otra convergencia — MFA sustituye al peso de bloque

**Los mismos dos jueces proponen, sin consultarse, la misma solución.**

La frase del spec §5 —*"normalización a varianza unitaria por bloque"*— resulta estar **ambigua en
un factor de 25 a 200×** según se lea por variable o por bloque, y el spec no dice cuál:

- Con z-score **por variable**, la contribución de un bloque a la distancia euclídea es
  proporcional a su **dimensión**: ~100 componentes de texto contra ~4 de composición son 25:1
  antes de tocar ningún peso.
- Con varianza **total** por bloque, es 1:1 — pero entonces el bloque concentrado domina los
  primeros ejes, que es la geometría que k-means y GMM realmente usan.

Y la elección implícita supone que **varianza = importancia**, lo cual es falso por construcción: un
bloque de puro ruido se escala hasta ocupar la misma huella que uno de señal.

**La solución: normalización de Multiple Factor Analysis** — dividir cada bloque por su **primer
valor singular**, de modo que ningún bloque imponga su estructura sobre el primer eje. Es
invariante a la redundancia interna del bloque, que es justo la propiedad que hace falta.
**Cero parámetros libres, y por tanto ningún hiperparámetro que afinar contra el salario.**

Escofier & Pagès (1994); exposición moderna en Abdi, Williams & Valentin (2013), *WIREs
Computational Statistics* 5(2), DOI [10.1002/wics.1246](https://doi.org/10.1002/wics.1246).

**Nota adicional del metodólogo:** el z-score está además *contraindicado* por evidencia clásica —
Milligan & Cooper (1988), *Journal of Classification* 5:181–204, encontraron que **dividir por el
rango recupera consistentemente mejor la estructura** que el z-score.

---

## 3. El agujero del pre-registro

El metodólogo encontró una inconsistencia interna en el propio expediente:

> D-005 Enmienda 1 dice literalmente: *"si la métrica se usa para decidir la granularidad, la
> familia o **los pesos**"*. Enumera **tres** cosas. El pre-registro cubre **dos**. Los pesos quedan
> fuera — y el spec de clustering §7 los envía precisamente a la métrica salarial.

**La contaminación, en números.** Una rejilla de 4 pesos de bloque a 3 niveles son G=81
configuraciones. El sesgo del ganador es ≈ E[max_G Z]·SE ≈ 2,3·SE, y como el IC bootstrap reporta
semiancho ≈1,96·SE, **el optimismo es ≈1,2 veces el semiancho del intervalo que se iba a publicar**.
El IC no cubriría el valor verdadero.

**Y la dirección no es neutral.** El sesgo empuja peso hacia el bloque que más correlaciona con el
nivel de pago —composición ↔ roles comerciales ↔ nivel salarial—, o sea **hacia el techo
supervisado, que el propio diseño define como la alarma de deriva a bandas salariales.**
*La alarma no puede sonar si se sintonizó hacia ella.*

**Y "held-out" no es held-out si se selecciona en él.** El hash del split certifica la identidad
del conjunto de test, no su virginidad.

---

## 4. Donde se contradicen

**El juez de compensaciones ataca la premisa central**, y los otros no llegan tan lejos:

> En un estudio de mercado, el *pay mix* es un **resultado** que se reporta por cargo y grado —
> nunca el espacio métrico donde se descubren los cargos. Con 30,1% de gente en 100% fijo y
> η²_empresa = 49,8% en extras, ese eje da para **tres carriles** (comisionado / operativo con
> extras / fijo administrativo), no para cincuenta arquetipos.

Tres carriles es la frontera *exempt / non-exempt* que la industria usa como separación de
*career stream* — valiosa, pero no distingue soldador de electricista ni contador de analista de
compras. Justo donde `VENDEDOR` falla.

Los otros dos quieren la composición **más pequeña y mejor tratada**, no fuera.

**Quién tiene razón lo decide el baseline A vs B en la semana 4** — la comparación ya está en el
diseño. Contrapeso medido después de la revisión: la correlación entre años es **0,817 en extras y
0,884 en comisiones** sobre 333.752 personas, así que la composición es un rasgo estable de la
persona y no circunstancia del mes. El bloque es real; la discusión es cuánto pesa y qué separa.

**Segunda contradicción:** el tribunal señala que el diseño de validación **ya tiene nombre en la
literatura** (*prediction strength*), mientras los otros tres lo elogian como la pieza más fuerte.
No es contradicción real: es bueno, pero no es novedad, y hay que citarlo para que no parezca una
heurística inventada.

**Tercera:** el juez de compensaciones quiere que el entregable sea una **distribución** (P25/P50/P75
+ calibración), no un estimador puntual con MAE. Tiene razón sobre el producto; los otros tienen
razón sobre la tesis. Ambas pueden convivir.

---

## 5. La amenaza a la novedad

El tribunal encontró tres trabajos que hacen, cada uno por su lado, parte de lo que esta tesis
propone. Los tres verificados:

| Trabajo | Qué hizo | El detalle |
|---|---|---|
| **Job2Vec** (Zhang et al., CIKM 2019) | *job title benchmarking* entre empresas, para sustituir encuestas de compensación | **es la premisa, publicada** |
| **Djumalieva et al.** (ESCoE DP-2018-04) | jerarquía ocupacional de 4 capas desde 37 M de anuncios | **la 4.ª capa se construye con el salario** |
| **TWICE** (Bakirov et al., arXiv 2601.00776, ene-2026) | particiones data-driven de observables validadas por predicción salarial fuera de muestra | su partición usa el salario como objetivo |

**La pregunta de defensa:** *"¿qué queda que sea suyo?"*

**La respuesta, y hay que escribirla:**

> Familia de rol × nivel inducida **sin usar el salario en ninguna etapa del agrupamiento**, sobre
> un mercado no estudiado, y validada fuera de muestra con leave-company-out contra una escalera de
> nulos y un criterio de éxito pre-registrado.

Los tres precedentes usan el salario para construir el agrupamiento o el nivel. Ese es el
diferenciador, y hoy no está escrito en ningún archivo del repositorio.

**Riesgo relacionado:** Grams & Schwab (1985), *AMJ* 28(2):279–290 — los sistemas de evaluación de
puestos se anclan en el pago actual y **lavan la estructura salarial existente convirtiéndola en un
agrupamiento aparentemente objetivo**. Conecta directo con el análisis de brecha de género: si el
arquetipo absorbe la diferencia de pago, la brecha ajustada la subestima por construcción.

---

## 6. Las siete correcciones, por prioridad

| # | Corrección | Por qué | Dónde |
|---|---|---|---|
| **1** | **Ponderar la referencia por empresa**, no por persona | Una empresa con 3.000 personas en una celda define el mercado aunque haya ≥3 empresas. Con el empleador explicando el 39% del salario, es medir a un empleador y llamarlo mercado. **Cambia todos los números del banco** | spec del banco §5 |
| **2** | **MFA en vez de peso de bloque afinado** | Elimina el hiperparámetro y el agujero del pre-registro de un golpe | spec de clustering §5, §7 |
| **3** | **Escribir `docs/preregistro.md`** cerrando los **tres** elementos, pesos incluido | No existe todavía | nuevo |
| **4** | **Rehacer los must-links**: entre cadenas distintas, con cannot-links, desde `cargo_plantilla` y el catálogo sectorial | Los actuales son degenerados (§1) | D-007 |
| **5** | **Escribir el enmarque de novedad** frente a Job2Vec, Djumalieva y TWICE | Es el riesgo mayor si el resultado sale bien | marco teórico |
| **6** | **Medir la ruta de servicio** (título → arquetipo) sobre empresas held-out | El §12 promete mapeo online **sin** composición: entonces lo que se vende es un clasificador de texto, no el clusterer. Si acierta al 85%, el clustering fue una forma cara de hacer una taxonomía de texto; si al 40%, el producto no se puede servir. **Cuesta un día** | nuevo |
| **7** | **Sacar `edad` del modelo de nivel** y anclarlo a definición externa | Antigüedad + edad + rank de pago es una **banda de senioridad personal**, no un nivel de puesto: un operario con 30 años de casa sigue siendo C3. Y `edad` en un producto de compensación es un pasivo legal. El *work level* del NCS del BLS tiene definición operacional pública: adoptarla como constructo nominal | spec de clustering §6 |

**Ninguna toca el pipeline de ingesta.** Todas caen en el banco de validación y en la
representación.

---

## 7. Correcciones de enmarque que el tribunal exige

**"El CARGO no sirve" es demasiado fuerte.** Torres, Portugal, Addison & Guimarães (2018),
*Labour Economics* 54:47–60, miden sobre datos administrativos portugueses limpios: trabajador ≈1/3,
empresa ≈1/4, **título del puesto ≈1/5** de la varianza del log-salario. La afirmación tiene que
pasar a *"CARGO **tal como se captura en los estudios actuariales ecuatorianos** no sirve"*.

**Contrapeso a favor, y es la mejor frase del marco teórico:** Massing, Wasmer, Wolf & Züll (2019),
*JOS* 35(1) — κ≈0,5 entre **agencias humanas profesionales** codificando a 4 dígitos, pero
**0,82–0,90** para los puntajes de estatus derivados. *El código fino no es fiable ni entre
expertos; el constructo agregado sí.* Es el argumento a favor de los arquetipos, dicho por otros.

**Amenaza a un número propio:** el **sesgo de movilidad limitada** (Andrews et al. 2008) implica que
con empresas presentes en pocos años los estimadores de componentes de varianza **sobreestiman** el
efecto empresa. El η²_empresa ≈ 0,34–0,39 medido aquí es uno de los números que sostiene todo el
argumento del leave-company-out, y **probablemente está sobreestimado**. Hay que cuantificarlo o
acotarlo. (Consenso: firma ≈20%, Card et al. 2018.)

---

## 8. Lo que los cuatro salvan

Coinciden en no tocar:

- **D-005** — error fuera de muestra + cobertura como co-primaria, y **no podar `CARGO`**. El juez de
  compensaciones, el más duro con el resto, dice que el rigor de medición del banco **supera al de
  cualquier informe comercial que él haya firmado**.
- **Leave-company-out** con bootstrap y splits por empresa. Correctamente motivado.
- **Construir el banco antes que el modelo** (D-002) y **pre-registrar el criterio** (D-004/D-005).
- **Los baselines A/B con la conclusión escrita de antemano** — un interruptor de apagado real sobre
  la hipótesis propia.
- **El test-retest sobre 478.522 personas** — evidencia de fiabilidad más fuerte que cualquier ARI,
  y señalada como infrautilizada: debería usarse también sobre las *features*, no solo sobre las
  particiones.
- **Excluir salario y sexo** del agrupamiento, y tratar empresa/sector/tamaño/provincia como
  controles.
- **El banco se valida a sí mismo** con data sintética de respuesta conocida, con roles separados por
  composición y no por sueldo.
- **D-008** — cachear el XLSX crudo. Señalado como *"el activo infravalorado del proyecto"*: no es
  solo un filtro de calidad, es **la única fuente no circular de restricciones informativas y de
  cannot-links** que tiene el diseño.

Y los cuatro mencionan, por separado, **la nota final de D-006** —el patrón de decisiones que
favorecen la hipótesis propia— como lo mejor del expediente. Dos añaden lo mismo: **aplíquese
también a D-007**.

---

## 9. Contradicción interna del spec, pendiente de resolver

Señalada por el juez de representación:

> El §3 principio 4 dice *"la selección de modelo NO usa la métrica salarial"*.
> El §7 afina el peso de bloque **contra dispersión salarial en held-out**.

El spec se contradice a sí mismo. La corrección 2 (MFA) lo resuelve.
