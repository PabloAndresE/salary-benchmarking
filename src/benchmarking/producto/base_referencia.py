"""Base de referencia salarial: construir una vez, consultar muchas.

EL PRODUCTO. Un cliente entrega su nomina y recibe, por cada persona, la referencia de
mercado de su puesto con su intervalo y una marca de confianza.

Responde SIEMPRE (decision de ActuaLab). Un cliente sin referencia no se queda quieto:
inventa un numero. Se compite contra eso, no contra el silencio. Pero como se responde
siempre, la marca de confianza deja de ser decorativa y es lo unico que separa "esto lo se"
de "esto lo estoy suponiendo".

COMO FUNCIONA

  titulo conocido   -> la referencia de su propia celda
  titulo NUEVO      -> se embebe y se coloca entre los puestos que se le parecen

Lo segundo es lo que hace que la cobertura pase del 66,6% a casi todo: el 35,9% de la
gente de una nomina nueva tiene un titulo que no esta en la base.

ANTES DE NADA, LAS GRAFIAS SE JUNTAN. El catalogo trae el mismo puesto tecleado de varias
formas —seis variantes de espaciado de `ASISTENTE / AYUDANTE / AUXILIAR ADMINISTRATIVO`, y
una con errata—, y cada una era una celda distinta y delgada que se contestaba por
analogia... contra sus propias hermanas, pagando castigo de distancia. Fusionarlas sube la
cobertura directa del 57,7% al 64,1% sin costar precision. El COMO importa mucho y esta
medido: por enlace completo, no simple. Ver `UMBRAL_FUSION`.

EL PESO DE CADA VECINO, y por que no es `similitud x precision`

La version ingenua pesa cada vecino por su similitud multiplicada por su precision. Medido
sobre un caso real, eso rompe:

    OPERADOR DE PARQUEADERO
      OPERADOR DE PARQUEADEROS   sim 0,989   peso   8%
      OPERADOR DE EXCAVADORA     sim 0,825   peso  46%   <- gana por tener mas datos

Tenia la respuesta exacta delante y le hizo caso a una excavadora. Aqui cada vecino se
trata como una observacion ruidosa del puesto objetivo, con varianza

    var_j = 1/W_j  +  lambda * (1 - sim_j)

y se pesa por 1/var_j. El primer termino es su error de medicion; el segundo, lo que se
paga por no ser exactamente el mismo puesto. Un vecino lejano se descuenta aunque este
perfectamente medido. **`lambda` se estima de los datos**, no se elige: es cuanto difieren
de verdad dos celdas por unidad de distancia semantica.

CUANDO NO HAY VECINDARIO DE VERDAD

    LOTERO -> LINIERO, BOTERO, LAMPERO, TESORERO (sim 0,748-0,784)

El embedding no encuentra nada parecido y se agarra a la terminacion "-ERO". TESORERO
paga 2,5 veces mas. Con la varianza de arriba eso sale solo: si todos los vecinos estan
lejos, `lambda*(1-sim)` domina, el intervalo se dispara y la confianza cae a BAJA.

LIMITE QUE HAY QUE DECLARARLE AL CLIENTE. El empleador explica el 81% de lo que no se
puede predecir (tau = 0,29). Esto da el MERCADO, no la politica salarial de una empresa
concreta. Dos personas identicas en empresas distintas cobran muy diferente y ningun
metodo basado en el puesto arregla eso.
"""
import re
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

from ..evaluacion.referencia import (_cuantil_por_grupo, componentes_varianza,
                                     cuantiles_de_empresa, cuantiles_de_persona,
                                     sigma2_por_celda,
                                     tabla_votos, tau2_por_celda)
from .nivel import efecto_nivel, nivel_lexico

VECINOS = 25
MIN_EMPRESAS = 3        # suelo de identificabilidad y confidencialidad (precedente QCEW)

# EL SUELO DE EMPRESAS NO DICE NADA DE PERSONAS, y hace falta que lo diga.
#
# `MIN_EMPRESAS = 3` protege contra que UNA empresa se reconozca en el numero, y esa parte
# funciona: el peso `w_f = 1/(tau_c^2 + sigma_c^2/n_f)` esta acotado por `1/tau_c^2`, asi
# que ninguna empresa puede dominar la mediana ponderada. Medido: el peso mayor llega como
# mucho al 67,7% y la regla de dominancia del QCEW (80%) se cumple sola en las 5.168
# celdas directas — no hace falta anadirla.
#
# Lo que ese suelo NO ve es otra cosa: tres empresas con UNA persona cada una son tres
# personas, y la mediana de sus tres votos ES el sueldo de una de ellas. Medido: 297 celdas
# directas (5,7%) tienen 3 o 4 personas en total. Ver `e3_varianza/10`.
#
# EL 10 SALE DE UN BARRIDO (`e3_varianza/11`), no de la costumbre:
#
#   suelo   cobertura  pierde     MAE   protegidas   coste p/afectado
#      3       62,4%     0,0%  0,2372            0   <- no-op: 3 empresas ya son 3 personas
#      5       62,2%     0,2%  0,2372        1.781        +0,0139
#     10       61,0%     1,4%  0,2372       17.669        +0,0049   <- elegido
#     20       58,3%     4,1%  0,2382       46.983        +0,0264
#
# Tres razones convergen: el MAE global no se mueve (a partir de 15 empieza a subir), es el
# umbral donde MENOS pierde la gente afectada —las celdas de 5-9 personas son justo las que
# la analogia contesta casi igual de bien—, y no bloquea ni una de las 3.391 celdas que
# publican cuantiles empiricos, que son las mas expuestas.
MIN_PERSONAS = 10

# FUSION DE CUASI-DUPLICADOS. El catalogo trae la misma etiqueta tecleada de varias formas
# —`ASISTENTE / AYUDANTE / AUXILIAR ADMINISTRATIVO` convive con seis variantes de espaciado
# y una errata—, y cada grafia era una celda separada, delgada, que se contestaba por
# analogia pagando castigo de distancia contra sus propios hermanos.
#
# Se juntan por ENLACE COMPLETO: un grupo vale solo si TODOS sus pares superan el umbral.
# El enlace simple (union-find) NO sirve, y esta medido: encadena A~B~C~D hasta juntar
# `ASISTENTE CONTABLE` con `AUXILIAR DE LIMPIEZA` en un grupo de 1.758 titulos, y empeora
# el error un +0,0154 [IC +0,0095, +0,0206]. Con enlace completo, mismo umbral, el grupo
# mayor baja a 27 titulos y el efecto se da vuelta: -0,0030 [IC -0,0075, -0,0000].
#
# La ganancia real no es precision —esa sale neutra, rozando la mejora— sino COBERTURA
# DIRECTA: 57,7% -> 64,1% de la gente contestada con datos de su propio puesto en vez de
# por analogia. Bajar a 0,93 sube la cobertura a 66,1% pero el efecto vuelve a cero.
UMBRAL_FUSION = 0.95
VECINOS_FUSION = 10     # candidatas a fusion; los cuasi-duplicados estan siempre arriba
TOPE_GRUPO = 60         # red de seguridad; medido, el enlace completo nunca la toca

# SEGUNDA PASADA: LAS ERRATAS. Los embeddings NO ven las letras —codifican significado— y
# por eso un dedazo se les escapa: `ASITENTE`/`ASISTENTE` puntua 0,92-0,94 y no llega al
# umbral. Para un caracter cambiado, una distancia de edicion es trivialmente mejor que
# cualquier modelo semantico, y es lo unico que el lexico hace mejor aqui.
#
# QUE NO ES UNA ERRATA, y por eso esto se inspecciono antes de montarse (2.887 pares
# candidatos sobre la base de 65.181 titulos, ver `research/herramientas/erratas.py`):
#
#   OPERARIO I / OPERARIO II     1.570 pares   distancia 1, y son ESCALONES
#   VENDEDOR / VENDEDORA           961 pares   distancia 1, y es GENERO
#
# Los primeros borrarian la escalera de antiguedad que §18 quiere medir. Los segundos son
# el mismo oficio y fusionarlos es defendible, pero mueve el numero de ~468.000 personas y
# el argumento es de equidad, no de ortografia: se decide aparte.
#
# EL UMBRAL DE ASIMETRIA SALE DE LOS DATOS, no de la intuicion. Medido sobre los 2.887
# candidatos: el lado menor tiene UNA empresa en el 68% de los pares y dos o menos en el
# 82%. Pero la razon mayor/menor mediana es solo 4,0x, porque hay DOS familias:
#
#   a) dedazo contra titulo comun     -> razon enorme. Es la que interesa.
#   b) dos titulos raros a distancia 1 -> razon ~1. Ninguno llega al suelo de 3 empresas
#      ni antes ni despues, asi que fusionarlos no cruza ninguna frontera y solo anade
#      riesgo de juntar dos oficios raros distintos. Se deja fuera.
#
# De ahi la regla: el lado raro con <=2 empresas y el comun con >=10. Es exactamente el
# caso con valor —la gente del dedazo pasa de contestarse por analogia a tener datos
# propios— y deja fuera la familia (b), que no gana nada.
MIN_LARGO_ERRATA = 8    # bajo esto un caracter cambia el significado: `SUB`/`SUR`
MAX_EMPRESAS_ERRATA = 2     # el lado raro: un dedazo no lo teclean tres empresas
MIN_EMPRESAS_ABSORBE = 10   # el lado comun, mismo suelo que la banda empirica

# LA BANDA HABLA DE EMPRESAS: "la mitad de las EMPRESAS paga entre X e Y". Es la pregunta
# coherente con el centro —que ya es la mediana de los votos por empresa— y la que le
# importa a un cliente que decide su politica salarial.
#
# De ahi salen las dos decisiones de esta seccion, ambas medidas en `e3_varianza`:
#
#   1. `sigma` NO entra en la banda. El nivel de una empresa es `mu + u_f`, con varianza
#      `tau_c^2`; `sigma^2` separa a dos personas de la MISMA nomina y no mueve el nivel
#      de la empresa. Meterla ensanchaba la banda por una variacion que la pregunta no
#      incluye.
#
#   2. Donde hay `MIN_EMPRESAS_BANDA` o mas, no hace falta modelo: se reportan los
#      CUANTILES EMPIRICOS de los votos. Ninguna normal describe a la vez el pico de
#      `AUXILIAR DE LIMPIEZA` (p25=$475, p75=$485) y la cola de `GERENTE GENERAL` ($500 a
#      $13.712), asi que el problema no era el ancho de la banda sino su forma.
#
# Medido sobre votos de empresa apartados, deformacion entre quintiles de dispersion:
#
#   hoy (tau,sigma globales, normal)   50,5 puntos    cob 50%: de 20% a 100% segun cargo
#   tau_c sin sigma, normal            13,5 puntos
#   cuantiles empiricos F>=10           4,3 puntos    pinball medio 0,1290 -> 0,1207
#
# UMBRAL 10 y no 5: F>=5 gana el pinball por un 0,7% que casi seguro es ruido, y F>=10 gana
# las dos coberturas, cubre al 80,6% de la gente y esta mas lejos del dato crudo. Publicar
# cuantiles empiricos de pocas empresas se acerca a revelar sueldos.
MIN_EMPRESAS_BANDA = 10
CUANTILES = (0.10, 0.25, 0.75, 0.90)
Z_NORMAL = {0.10: -1.2816, 0.25: -0.6745, 0.75: 0.6745, 0.90: 1.2816}

# ---------------------------------------------------------------------------
# BANDA POR RUBRO. Es una LENTE de producto, no una mejora del modelo, y la
# distincion importa porque la medicion dice lo contrario de lo que sugiere la
# intuicion:
#
#   sector para la BANDA    pinball 0,1289 contra 0,1255 sin el   -> PIERDE (`07`)
#   sector para el CENTRO   indistinguible de un placebo          -> nulo   (D-022)
#
# La razon de que no ayude esta medida: el sector YA esta codificado en el titulo
# para los puestos donde importa. Una petrolera tiene `PERFORADOR` y una textilera
# `OPERARIO TEXTIL` — celdas distintas, nunca se comparan entre si. Lo que las dos
# comparten es `CONTADOR`, `CHOFER`, `GUARDIA`, y ahi pagan casi lo mismo: sobre
# `ASISTENTE CONTABLE` (1.688 empresas) los sectores grandes caen dentro de un 5%
# entre si, y cada desviacion grande viene de un sector con menos de 20 empresas.
#
# SE MONTA IGUAL, y la razon es legitima aunque no sea estadistica: un cliente no
# acepta que le comparen su nomina contra el mercado entero. "De que me sirve
# compararme contra una petrolera" es una objecion de PRODUCTO, y la respuesta a
# una objecion de percepcion puede ser ensenar el corte, no ganar precision.
#
# EL COSTE SE DECLARA, no se esconde: la celda del rubro tiene menos empresas, asi
# que `1/W` sube y la etiqueta de confianza BAJA sola. El cliente ve que su
# referencia sectorial sale de 93 empresas y no de 826, y lo ve en la misma fila.
#
# EL CENTRO SIGUE A LA BANDA. Si la banda es del rubro, el centro es el p50 de esos
# MISMOS votos. Publicar un centro global dentro de una banda sectorial permitiria
# que el centro caiga fuera de su propio p25-p75, que es justo la incoherencia que
# prohibe el test de `_lectura`.
#
# `tau_c` y `sigma_c` NO se reestiman dentro del rubro: con 10-90 empresas saldrian
# pesimamente estimadas, y ya vienen encogidas de la celda entera (D-016).
#
# FALLBACK POR CARGO, no por informe: cada cargo cae al global por separado. Un
# cliente de manufactura tendra rubro para `CONTADOR` (93 empresas) y global para
# `SOLDADOR DE PRECISION` (3). Es lo unico coherente con un suelo que es de
# confidencialidad y no de gusto.
COL_RUBRO = "ciiu_n1"
MIN_EMPRESAS_RUBRO = MIN_EMPRESAS_BANDA     # mismo suelo que la banda global
MIN_PERSONAS_RUBRO = MIN_PERSONAS
_RUBRO_NULO = {"", "NAN", "NONE", "NA", "NULL"}

# LA CONFIANZA MIDE LO BIEN QUE SE CONOCE EL CENTRO, no lo ancho que es el mercado. Son
# dos preguntas distintas y antes se contestaba la que no era: la etiqueta salia del ancho
# de la banda contra el suelo del cargo, y como en la rama directa el suelo ES casi todo el
# ancho, el cociente daba ~1,00 y el 100% de las celdas se etiquetaba ALTA (medido sobre 5.168
# celdas con 3+ empresas; la peor de todas queda en 1,175 veces el suelo, y el corte era 1,25).
#
# El ancho del mercado ya lo comunica la banda. Lo que la etiqueta tiene que anadir es si
# el numero del medio es fiable, y eso es la varianza de NUESTRA estimacion — todo lo que
# no es dispersion del mercado:
#
#     directo       var_centro = 1/W
#     por analogia  var_centro = suma(peso^2/W) + suma(peso*dist) + penal_nivel
#
# MEDIDO (`e3_varianza/06`), estimando la referencia sobre dos mitades disjuntas de
# empresas y viendo cuanto se separan:
#
#                       Spearman con el movimiento real    ALTA     MEDIA    BAJA
#     hoy (ancho/suelo)         +0,367                    100,0%     0,0%    0,0%
#     nueva (1/W)               +0,576                     17,6%    45,5%   37,0%
#     ...y lo que se mueve:                                  3,8%    13,3%   31,8%
#
# LOS CORTES son en dolares y no en veces-el-suelo, porque la pregunta ahora tiene unidades
# interpretables. Las decisiones salariales se mueven en escalones de ~5%: un centro
# conocido a mejor que 5% es accionable, entre 5% y 15% hay que mirarlo dos veces, y por
# encima de 15% la referencia no distingue "sube un 10%" de "baja un 10%".
#
# LIMITE MEDIDO: `1/W` se queda CORTO, entre un 15% y un 40% segun el tramo (obs/pred va de
# 0,96 en el primer decil a 1,42 en el ultimo). Ordena bien pero es optimista. La causa
# probable es que el modelo supone la celda homogenea y `CONTADOR` mezcla empresas grandes
# y pequenas. No se corrige con un factor porque ese factor no esta medido.
CORTE_ALTA = 0.05       # el centro se conoce a mejor que +/-5%
CORTE_MEDIA = 0.15


def _confianza(var_centro):
    """ALTA / MEDIA / BAJA por cuanto puede moverse el CENTRO. Devuelve (etiqueta, pct).

    No exige que la respuesta sea directa: `var_centro` ya incluye el castigo de distancia
    semantica, asi que una analogia mala se penaliza sola y anadir la condicion seria
    contarla dos veces. Que la respuesta venga por analogia se dice en la columna `base`.
    """
    pct = float(np.exp(np.sqrt(max(float(var_centro), 0.0))) - 1.0)
    if pct <= CORTE_ALTA:
        return "ALTA", pct
    if pct <= CORTE_MEDIA:
        return "MEDIA", pct
    return "BAJA", pct


def _lambda_semantica(m, W, vec, sim, m_todos=None, W_todos=None):
    """Cuanto difieren dos celdas por unidad de distancia semantica. Por momentos.

    Para cada par (celda, vecino) la diferencia observada al cuadrado tiene dos partes:
    el ruido de medicion de ambas, y la diferencia real entre los puestos. La primera se
    conoce (1/W_i + 1/W_j); lo que sobra se atribuye a la distancia y se ajusta por
    minimos cuadrados por el origen.
    """
    mt = m if m_todos is None else m_todos
    Wt = W if W_todos is None else W_todos
    i = np.repeat(np.arange(len(m)), vec.shape[1])
    j = vec.ravel()
    s = sim.ravel()
    ok = (np.isfinite(m[i]) & np.isfinite(mt[j]) & (W[i] > 0) & (Wt[j] > 0)
          & (s < 0.9999))                      # descarta la celda consigo misma
    if ok.sum() < 100:
        return 1.0
    d2 = (m[i][ok] - mt[j][ok]) ** 2 - (1.0 / W[i][ok] + 1.0 / Wt[j][ok])
    x = 1.0 - s[ok]
    den = float((x * x).sum())
    return float(max(np.finfo(float).tiny, (x * d2).sum() / den)) if den > 0 else 1.0


# SEGMENTAR EL CENTRO POR TAMANO DE EMPRESA, en los cargos altos y solo ahi.
#
# Medido (`e3_varianza/07`-`09`): el tamano NO estrecha la banda —pinball 0,1255 -> 0,1284,
# pierde— pero el CENTRO esta sesgado, y mucho, cuanto mas alto el escalon:
#
#   sesgo de la referencia    PEQUENA   MEDIANA   GRANDE   recorrido
#   nivel 1                    +6,9%     +8,3%    +6,1%     10,1%   <- plano
#   nivel 4                   -16,4%     -8,4%    +9,6%     26,1%
#   nivel 5                   -32,8%    -16,6%   +22,2%     55,0%
#
# `GERENTE GENERAL` va de -56,0% en pequenas a +81,9% en grandes: a una empresa pequena se
# le dice que su gerente cobra un 56% por debajo del mercado cuando entre sus pares esta
# bien. Segmentando, el recorrido del nivel 5 baja de 55,0 a 14,8 puntos.
#
# POR ESCALON Y NO POR LISTA DE CARGOS. La seleccion automatica cargo a cargo esta medida
# que es ruido: en `08` el PLACEBO eligio mas cargos (118) que la senal real (93).
#
# SE DESPLAZA LA BANDA ENTERA, no se reestima. Las dos mediciones son compatibles: la
# distribucion de las empresas pequenas esta corrida hacia abajo, no es mas estrecha.
#
# NO SE ACTIVA SOLA: hace falta pasar `segmento` explicitamente. Y esa no es solo una
# decision de interfaz — es la postura honesta despues de medir esta implementacion
# (`e3_varianza/15`) con el criterio declarado ANTES de correr:
#
#   pinball  con segmento - sin segmentar = -0,00392  IC [-0,00797, +0,00005]  no pasa
#            PLACEBO      - sin segmentar = +0,00662  IC [+0,00212, +0,01093]  empeora
#
# El criterio exigia el IC ENTERO bajo cero y el extremo superior es +0,00005. Es un casi
# —un 2,0% de mejora dentro de la poblacion afectada— pero un casi no es un si.
#
# El sesgo, que es el defecto que motivo D-018, SI se arregla casi del todo:
#
#   segmento     sin segmentar   con segmento
#   PEQUENA         -34,2%          +0,7%
#   MEDIANA         -15,0%          -0,1%
#   GRANDE           +9,0%          -4,3%
#   recorrido        43,3%           5,0%
#
# Se podria argumentar que el pinball es la primaria equivocada para un defecto de
# LOCALIZACION: penaliza debilmente un desplazamiento cuando la banda es muy ancha, y la
# de `GERENTE GENERAL` es +-95%. El argumento es probablemente cierto y NO se usa, porque
# cambiar la metrica despues de ver el resultado vacia el pre-registro de sentido. Para
# volver a intentarlo hay que declarar antes cual es la primaria correcta y por que.
NIVEL_MIN_SEGMENTAR = 4
MIN_EMPRESAS_SEGMENTO = 10
SEGMENTOS = ("MICROEMPRESA", "PEQUENA", "MEDIANA", "GRANDE")


def _norm_segmento(v):
    """`PEQUEÑA` llega con enie de BigQuery y sin ella de una bandera de consola."""
    t = str(v or "").strip().upper().replace("Ñ", "N").replace("Ñ", "N")
    return t if t in SEGMENTOS else None


def _norm_rubro(v):
    """Codigo CIIU de primer nivel, una letra. Vacio y sus disfraces cuentan como
    ausencia: `astype(str)` convierte los nulos en la cadena `'nan'` y sin esta guarda
    `'NAN'` seria un rubro mas, con miles de empresas dentro."""
    t = str(v if v is not None else "").strip().upper()
    return None if t in _RUBRO_NULO else t


def _bandas_por_rubro(d, colg, clave_etiqueta, t2_por_clave, s2_por_clave):
    """Centro, banda y respaldo de cada (grupo, rubro) que aguanta los suelos.

    Devuelve arrays PARALELOS y no una matriz densa a proposito: 65.081 celdas por 19
    rubros son 1,2 millones de casillas de las que casi ninguna pasa el suelo de 10
    empresas. Denso costaria ~80 MB de NaN.

    `clave_etiqueta` da, para cada etiqueta, el valor que tiene en `colg` — el id de
    grupo cuando hay fusion y la etiqueta misma cuando no. Sin el, la version sin fusion
    buscaria grupos "0,1,2..." contra claves que son titulos.

    `d` es el marco con la columna de grupo ya puesta; `t2_por_clave` y `s2_por_clave`
    son Series indexadas por el valor de `colg` — la varianza de la CELDA ENTERA, que es
    la que se usa para pesar dentro del rubro. Reestimarlas con las 10-90 empresas del
    rubro daria ruido con nombre de parametro.
    """
    vacio = (np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0),
             np.zeros(0), np.zeros(0, np.int64), np.zeros(0, np.int64),
             np.zeros((0, len(CUANTILES))), np.zeros((0, len(CUANTILES))), [])
    if COL_RUBRO not in d.columns:
        return vacio
    x = d[[colg, COL_RUBRO, "empresa_ruc", "y"]].dropna(subset=["y"]).copy()
    x["_r"] = x[COL_RUBRO].map(_norm_rubro)
    x = x[x["_r"].notna()]
    if x.empty:
        return vacio
    x["_cr"] = x[colg].astype(str) + "\x1f" + x["_r"].astype(str)

    # Las varianzas de la celda, reindexadas a la clave compuesta.
    mapa = x[["_cr", colg]].drop_duplicates().set_index("_cr")[colg]
    t2 = pd.Series(t2_por_clave.reindex(mapa.to_numpy()).to_numpy(float), index=mapa.index)
    s2 = pd.Series(s2_por_clave.reindex(mapa.to_numpy()).to_numpy(float), index=mapa.index)

    # Respaldo y peso total. `W` es lo que hace que la confianza baje sola cuando el
    # rubro tiene menos empresas que el mercado entero: es el coste, hecho visible.
    v = (x.groupby(["_cr", "empresa_ruc"], sort=False)["y"].size()
          .rename("n").reset_index())
    den = (t2.reindex(v["_cr"]).to_numpy(float)
           + s2.reindex(v["_cr"]).to_numpy(float) / v["n"].to_numpy(float))
    v["w"] = np.where(den > 0, 1.0 / np.where(den > 0, den, 1.0), 1.0)
    agg = v.groupby("_cr").agg(W=("w", "sum"), empresas=("empresa_ruc", "nunique"))
    agg["personas"] = x.groupby("_cr").size()
    agg = agg[(agg["empresas"] >= MIN_EMPRESAS_RUBRO)
              & (agg["personas"] >= MIN_PERSONAS_RUBRO)]
    if agg.empty:
        return vacio

    x = x[x["_cr"].isin(agg.index)]
    # El 0,50 es el CENTRO: sale de los mismos votos que la banda, no del global.
    qs = cuantiles_de_empresa(x, "_cr", t2, s2, CUANTILES + (0.50,))
    qp = cuantiles_de_persona(x, "_cr", t2, s2, CUANTILES)

    claves = [k for k in agg.index if k in qs.index]
    partes = [k.split("\x1f") for k in claves]
    rubros = sorted({p[1] for p in partes})
    pos_r = {r: i for i, r in enumerate(rubros)}
    # de clave de grupo (texto) a las etiquetas que pertenecen a ese grupo
    por_grupo = {}
    for i, g in enumerate(clave_etiqueta):
        por_grupo.setdefault(str(g), []).append(i)

    cel, cod, m, W, emp, per, bq, bp = [], [], [], [], [], [], [], []
    for k, (gk, r) in zip(claves, partes):
        etiquetas = por_grupo.get(gk)
        if not etiquetas:
            continue
        fila_q = qs.loc[k]
        fila_p = qp.loc[k] if k in qp.index else None
        centro = float(fila_q[0.50])
        if not np.isfinite(centro):
            continue
        banda = np.array([fila_q[q] for q in CUANTILES], dtype=float)
        banda_p = (np.array([fila_p[q] for q in CUANTILES], dtype=float)
                   if fila_p is not None else np.full(len(CUANTILES), np.nan))
        for i in etiquetas:
            cel.append(i)
            cod.append(pos_r[r])
            m.append(centro)
            W.append(float(agg.at[k, "W"]))
            emp.append(int(agg.at[k, "empresas"]))
            per.append(int(agg.at[k, "personas"]))
            bq.append(banda)
            bp.append(banda_p)
    if not cel:
        return vacio
    return (np.array(cel, dtype=np.int64), np.array(cod, dtype=np.int64),
            np.array(m, dtype=float), np.array(W, dtype=float),
            np.array(emp, dtype=np.int64), np.array(per, dtype=np.int64),
            np.vstack(bq), np.vstack(bp), rubros)


def _ajuste_segmento(marco, col, celdas, niveles, tau2_c, sigma2_c,
                     nivel_min=NIVEL_MIN_SEGMENTAR, min_emp=MIN_EMPRESAS_SEGMENTO):
    """Desplazamiento en log de cada (celda, segmento). Devuelve array celdas x SEGMENTOS.

    Es la diferencia entre la mediana ponderada de los votos de ESE segmento y la de
    todos. Positivo = ese tamano de empresa paga por encima de la referencia global.

    Solo para los cargos con escalon >= `nivel_min`, que es donde el sesgo esta medido.
    Y solo para los segmentos con `min_emp` empresas: por debajo, el desplazamiento seria
    ruido y moveria la referencia sin razon.
    """
    idx = {c: i for i, c in enumerate(celdas)}
    fuera = np.zeros((len(celdas), len(SEGMENTOS)))
    if "segmento" not in marco.columns:
        return fuera
    alto = {c for c, n in zip(celdas, niveles)
            if np.isfinite(n) and int(n) >= nivel_min}
    if not alto:
        return fuera

    d = marco[marco[col].astype(str).isin(alto)]
    d = d[[col, "empresa_ruc", "segmento", "y"]].dropna(subset=["y"])
    if d.empty:
        return fuera
    v = (d.groupby([col, "empresa_ruc"], sort=False)
          .agg(voto=("y", "median"), n=("y", "size"),
               seg=("segmento", "first")).reset_index())
    v["seg"] = v["seg"].map(_norm_segmento)
    c = v[col].astype(str).map(idx)
    t2 = np.asarray(tau2_c)[c.to_numpy()]
    s2 = np.asarray(sigma2_c)[c.to_numpy()]
    den = t2 + s2 / v["n"].to_numpy(float)
    v["w"] = np.where(den > 0, 1.0 / np.where(den > 0, den, 1.0), 1.0)

    def mediana(g):
        g = g.sort_values("voto")
        w = g["w"].to_numpy(float)
        acum = np.cumsum(w) - 0.5 * w
        return float(np.interp(0.5, acum / w.sum(), g["voto"].to_numpy(float)))

    for cargo, g in v.groupby(col, sort=False):
        i = idx.get(str(cargo))
        if i is None or len(g) < 2:
            continue
        base = mediana(g)
        for k, seg in enumerate(SEGMENTOS):
            gs = g[g["seg"] == seg]
            if len(gs) >= min_emp:
                fuera[i, k] = mediana(gs) - base
    return fuera


def _lambda_por_nivel(m, W, vec, sim, niveles, lam_global, minimo=200):
    """`lambda` por escalon lexico. Devuelve dict nivel -> lambda.

    POR QUE (medido, `e3_varianza/12`): `lambda` es el tercer parametro del modelo y era
    un solo escalar para los 65.081 cargos. Varia 18x y no es ruido — test-retest entre
    mitades de empresas r = 0,563, entre el de `tau` (0,780) y el de `sigma` (0,484):

        nivel 1   0,368      nivel 3   2,212      nivel 5   6,505
        nivel 2   1,038      nivel 4   3,340      global    1,938

    Misma causa mecanica que `tau`: abajo el salario minimo comprime y dos cargos
    parecidos pagan casi igual; arriba, `GERENTE DE FINANZAS` y `GERENTE DE OPERACIONES`
    estan cerca en el texto y lejos en el sueldo.

    LA DIRECCION DEL ERROR ERA LA PELIGROSA. Con el global, en los cargos altos se
    castigaba 3x DE MENOS a los vecinos lejanos: la respuesta se arrastraba hacia puestos
    que no eran y el intervalo no lo declaraba.

    POR ESCALON Y NO POR CELDA, a diferencia de `tau_c` y `sigma_c`. El patron es
    monotono en el nivel, asi que agrupar no pierde casi nada y gana mucha estabilidad:
    `lambda_c` por celda sale de ~25 pares y el 15,8% de las estimaciones son negativas
    por ruido. Cinco grupos con miles de pares cada uno no tienen ese problema.

    MEDIDO QUE MEJORA (`e3_varianza/14`), con pinball como metrica primaria y placebo:

        global        pinball 0,1424      por escalon  0,1338     -6,0%
        pareado: -0,00856  IC 95% [-0,01083, -0,00589]  MEJORA
        PLACEBO: +0,00032  IC 95% [+0,00024, +0,00041]  no lo reproduce

    El placebo baraja las etiquetas de escalon entre cargos y vuelve a estimar: los cinco
    `lambda` colapsan al global (1,95 / 1,92 / 1,93 / 2,05 / 2,04). La senal vive en el
    escalon, no en tener cinco grupos.

    OJO CON LA METRICA. Medido con MAE la mejora era -0,0015 (0,5%) y con pinball es
    -0,0086 (6,0%): un factor de 12. `lambda` actua sobre todo en el ANCHO y el MAE no ve
    el ancho. Con MAE esto se habria descartado por marginal.

    COSTE CONOCIDO, no resuelto: la ganancia entera viene del nivel 1 (-0,0244, el 70% de
    la gente por analogia) y los niveles 4 y 5 EMPEORAN (+0,0027 y +0,0146). Sospecha
    comprobable: `lambda` sale de diferencias AL CUADRADO y el nivel 5 tiene cola larga,
    asi que unos pocos pares extremos pueden inflar `lambda_5`. Un estimador robusto
    —diferencias absolutas o ajuste recortado— daria un `lambda_5` menor.
    """
    i = np.repeat(np.arange(len(m)), vec.shape[1])
    j = vec.ravel()
    s = sim.ravel()
    ok = (np.isfinite(m[i]) & np.isfinite(m[j]) & (W[i] > 0) & (W[j] > 0)
          & (s < 0.9999))
    if ok.sum() < minimo:
        return {}
    d2 = (m[i][ok] - m[j][ok]) ** 2 - (1.0 / W[i][ok] + 1.0 / W[j][ok])
    x = 1.0 - s[ok]
    niv_i = niveles[i][ok]

    out = {}
    for k in np.unique(niv_i[np.isfinite(niv_i)]):
        sel = niv_i == k
        if sel.sum() < minimo:
            continue
        den = float((x[sel] * x[sel]).sum())
        if den <= 0:
            continue
        # el suelo evita que una estimacion negativa por ruido anule el castigo de
        # distancia, que dejaria entrar a cualquier vecino con peso completo
        out[int(k)] = float(max(0.05 * lam_global, (x[sel] * d2[sel]).sum() / den))
    return out


class BaseReferencia:
    """Construida una vez sobre el universo; se consulta por titulo."""

    def __init__(self, celdas, m, W, emp, Z, tau2, sigma2, lam, sbu,
                 nivel=None, efecto=None, grupo=None,
                 tau2_c=None, sigma2_c=None, bandas=None, personas=None,
                 bandas_per=None, lam_nivel=None, ajuste_seg=None, rubro=None):
        self.celdas = list(celdas)
        self.idx = {c: i for i, c in enumerate(self.celdas)}
        # `m`, `W` y `emp` estan indexados por ETIQUETA pero contienen los valores de su
        # GRUPO de fusion: las grafias de un mismo puesto comparten estadisticos.
        self.m, self.W, self.emp = m, W, emp
        # `Z` son los embeddings del titulo COMPLETO, sin enmascarar el rango. Enmascarar
        # esta MEDIDO que empeora (+6,0%, IC [+0,038, +0,080]): la palabra de rango no
        # dice solo el rango, y al taparla `OPERARIO DE PRODUCCION` y `ANALISTA DE
        # PRODUCCION` quedan identicos siendo trabajos distintos. La jerarquia entra por
        # el AJUSTE de `nivel`, no por la representacion.
        self.Z = Z
        self.grupo = (np.arange(len(self.celdas)) if grupo is None
                      else np.asarray(grupo, dtype=np.int64))
        # Al buscar vecinos hay que pedir de mas: los hermanos de grafia se descartan
        # despues (comparten celda, no son evidencia nueva) y sin este margen podrian
        # comerse los 25 sitios.
        _, cuenta = np.unique(self.grupo, return_counts=True)
        self.k_busqueda = VECINOS + int(cuenta.max()) if len(cuenta) else VECINOS
        # Componentes de varianza POR CELDA. Si faltan —bases guardadas antes de
        # `e3_varianza`— se cae al global y el comportamiento es el de entonces.
        n = len(self.celdas)
        self.tau2_c = (np.full(n, float(tau2)) if tau2_c is None
                       else np.asarray(tau2_c, dtype=float))
        self.sigma2_c = (np.full(n, float(sigma2)) if sigma2_c is None
                         else np.asarray(sigma2_c, dtype=float))
        # `bandas` son los cuantiles EMPIRICOS de los votos por empresa, en el orden de
        # `CUANTILES`. NaN donde la celda no llega a `MIN_EMPRESAS_BANDA`.
        # DOS BANDAS, DOS PREGUNTAS. `bandas` es la de EMPRESAS —"la mitad de las
        # empresas paga entre X e Y"— y sirve para juzgar a una empresa. `bandas_per` es
        # la de PERSONAS, que ademas incluye la dispersion dentro de cada nomina y es la
        # que hay que poner al lado del sueldo de UNA PERSONA. Poner la de empresas hace
        # que la gente parezca mas rara de lo que es, y mas donde la banda es estrecha:
        # `AUXILIAR DE LIMPIEZA` es un 26% mas ancha en personas que en empresas.
        self.bandas = (np.full((n, len(CUANTILES)), np.nan) if bandas is None
                       else np.asarray(bandas, dtype=float))
        self.bandas_per = (np.full((n, len(CUANTILES)), np.nan) if bandas_per is None
                           else np.asarray(bandas_per, dtype=float))
        # `lambda` por escalon. Vacio en bases guardadas antes de D-021: ahi se cae al
        # global y el comportamiento es el de entonces.
        self.lam_nivel = dict(lam_nivel or {})
        # Desplazamiento de la referencia por tamano de empresa, solo en cargos altos.
        # Cero donde no aplica, asi que sumarlo siempre es inocuo. Ver `_ajuste_segmento`.
        self.ajuste_seg = (np.zeros((n, len(SEGMENTOS))) if ajuste_seg is None
                           else np.asarray(ajuste_seg, dtype=float))
        # BANDA POR RUBRO, dispersa. `self.rub` mapea (indice de celda, codigo de rubro)
        # a la fila de los arrays paralelos; lo que no esta en el diccionario cae al
        # global, que es el fallback POR CARGO. Las bases guardadas antes de esto no
        # traen nada y el comportamiento es el de entonces.
        (self.rub_cel, self.rub_cod, self.rub_m, self.rub_W, self.rub_emp,
         self.rub_per, self.rub_bandas, self.rub_bandas_per) = (
            np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0), np.zeros(0),
            np.zeros(0, np.int64), np.zeros(0, np.int64),
            np.zeros((0, len(CUANTILES))), np.zeros((0, len(CUANTILES))))
        self.rubros = []
        if rubro is not None:
            (self.rub_cel, self.rub_cod, self.rub_m, self.rub_W, self.rub_emp,
             self.rub_per, self.rub_bandas, self.rub_bandas_per, rr) = rubro
            self.rubros = list(rr)
        self.rub = {(int(c), self.rubros[int(k)]): i
                    for i, (c, k) in enumerate(zip(self.rub_cel, self.rub_cod))}
        # Personas detras de cada celda (del GRUPO fusionado). No entra en ningun calculo
        # —el estimador cuenta empresas, no personas— pero es lo primero que pregunta
        # quien lee un informe: ".cuanta gente hay detras de este numero?".
        self.personas = (np.zeros(n, dtype=np.int64) if personas is None
                         else np.asarray(personas, dtype=np.int64))
        # Suelo de personas, ademas del de empresas. Es atributo y no constante para poder
        # barrerlo en los experimentos sin reconstruir la base. Las bases guardadas antes
        # de `e3_varianza/11` no traen `personas` —quedan en cero— y ahi el suelo se apaga
        # solo, porque aplicarlo dejaria toda la base sin respuesta directa.
        self.min_personas = MIN_PERSONAS if self.personas.max(initial=0) > 0 else 0
        self.tau2, self.sigma2, self.lam, self.sbu = tau2, sigma2, lam, sbu
        self.nivel = (np.full(len(self.celdas), np.nan) if nivel is None
                      else np.asarray(nivel, dtype=float))
        self.efecto = dict(efecto or {})
        # dispersion del efecto entre escalones: es la incertidumbre que queda cuando
        # NO se sabe el nivel del puesto que se pregunta
        v = list(self.efecto.values())
        self.var_nivel = float(np.var(v)) if len(v) > 1 else 0.0

    # -- construccion ----------------------------------------------------------

    @classmethod
    def construir(cls, marco, X_por_etiqueta, sbu, col="cargo_norm",
                  umbral_fusion=UMBRAL_FUSION, erratas=True, mapa_erratas=None):
        """`marco` es el universo evaluable; `X_por_etiqueta` un dict etiqueta -> vector.

        `umbral_fusion=None` desactiva la fusion de cuasi-duplicados.

        `erratas=False` apaga la segunda pasada de D-025. Existe para poder medirla: la
        variante de control tiene que salir del MISMO codigo con una sola diferencia.

        `mapa_erratas` inyecta las absorciones en vez de calcularlas —un dict grupo_raro
        -> grupo_comun—. Lo usa el PLACEBO del experimento, que absorbe los mismos grupos
        raros pero hacia destinos al azar: si la mejora se reprodujera barajando, no
        vendria de la distancia de edicion sino del mero hecho de absorber.
        """
        def _stats(d, columna, por_celda=True):
            """(m, W, emp, claves, tau2, sigma2, t2_serie, s2_serie) de `columna`.

            Con `por_celda`, los pesos usan `tau_c` y `sigma_c` en vez de los globales.
            Es lo que se midio en `e3_varianza`: con un `tau` unico, el peso de cada
            empresa sale igual para un gerente que para un auxiliar, y `1/W` —de donde
            sale la confianza— deja de distinguirlos.
            """
            tau2, sigma2 = componentes_varianza(d, columna)
            s2c, _ = sigma2_por_celda(d, columna, sigma2_global=sigma2)
            t2c = None
            if por_celda:
                t2c, _ = tau2_por_celda(d, columna, s2c, tau2_global=tau2)
            votos = tabla_votos(d, columna, tau2=tau2, sigma2=sigma2, sigma2_celda=s2c,
                                tau2_celda=t2c)
            # Vectorizado. Un bucle por celda son 65.081 iteraciones de pandas y minutos
            # de espera; `_cuantil_por_grupo` lo hace de una pasada. Es el mismo error
            # que ya se corrigio dos veces en el paquete, asi que aqui se reutiliza.
            v = votos.sort_values([columna, "voto"], kind="mergesort")
            cod, claves = pd.factorize(v[columna], sort=True)
            o = np.argsort(cod, kind="stable")
            cod = cod[o]
            vv = v["voto"].to_numpy(float)[o]
            ww = v["w"].to_numpy(float)[o]
            k = len(claves)
            return (np.asarray(_cuantil_por_grupo(cod, vv, ww, k)),
                    np.bincount(cod, weights=ww, minlength=k),
                    np.bincount(cod, minlength=k).astype(int),
                    list(claves), float(tau2), float(sigma2), t2c, s2c)

        celdas = sorted(set(marco[col].astype(str)))
        Z = np.vstack([X_por_etiqueta[c] for c in celdas]).astype(float)
        Z /= np.linalg.norm(Z, axis=1, keepdims=True)
        niv = np.array([nivel_lexico(c) if nivel_lexico(c) else np.nan
                        for c in celdas], dtype=float)
        n = len(celdas)

        # `lambda` se estima SIN fusionar, a proposito. Mide cuanto difieren dos celdas
        # por unidad de distancia semantica, y dentro de un grupo fusionado esa diferencia
        # es cero por construccion: estimarla sobre celdas fusionadas la sesgaria a la
        # baja y encogeria todos los intervalos.
        #
        # Sale ademas de una MUESTRA de celdas. Todas contra todas son 65.081^2 x 768
        # dimensiones —unos 3 billones de operaciones— para estimar un solo escalar. Con
        # 3.000 celdas la estimacion ya es estable y tarda segundos.
        m0, W0, emp0, celdas0, tau2, sigma2, _, _ = _stats(marco, col, por_celda=False)
        pos0 = {c: i for i, c in enumerate(celdas0)}
        ix0 = np.array([pos0.get(c, -1) for c in celdas])
        mm = np.where(ix0 >= 0, m0[np.maximum(ix0, 0)], np.nan)
        WW = np.where(ix0 >= 0, W0[np.maximum(ix0, 0)], 0.0)
        rng = np.random.default_rng(20260805)
        muestra = (rng.choice(n, 3000, replace=False) if n > 3000 else np.arange(n))
        vec_s, sim_s = _vecinos(Z[muestra], Z, min(VECINOS, n - 1) if n > 1 else 1,
                                excluir_propio=False)
        lam = _lambda_semantica(mm[muestra], WW[muestra], vec_s, sim_s,
                                m_todos=mm, W_todos=WW)
        # ...y por escalon, que es donde de verdad cambia. Sobre TODAS las celdas: la
        # muestra de 3.000 basta para un escalar pero no para cinco.
        vec_n, sim_n = _vecinos(Z, Z, min(VECINOS, n - 1) if n > 1 else 1,
                                excluir_propio=True)
        lam_nivel = _lambda_por_nivel(mm, WW, vec_n, sim_n, niv, lam)

        # Los estadisticos SI salen del grupo fusionado: las grafias de un mismo puesto
        # votan juntas. Se reagrega desde las filas, no sumando celdas: el voto de una
        # empresa en el grupo es la mediana de TODA su gente en cualquiera de las grafias.
        grupo = _fusionar(Z, niv, umbral_fusion) if umbral_fusion else np.arange(n)
        if umbral_fusion:
            # SEGUNDA PASADA POR ERRATA. Necesita saber cuantas empresas respalda cada
            # grupo para decidir cual es el dedazo y cual el titulo comun, y eso solo se
            # sabe DESPUES de la fusion semantica. Se cuenta aqui con un groupby barato,
            # antes de los estadisticos, para no calcularlos dos veces.
            if mapa_erratas is not None:
                grupo = np.array([mapa_erratas.get(int(g), int(g)) for g in grupo],
                                 dtype=np.int64)
                print(f"fusion por errata: {len(mapa_erratas):,} absorciones INYECTADAS")
            elif erratas:
                g0 = marco[col].astype(str).map(dict(zip(celdas, grupo))).astype("int64")
                emp_g0 = (marco.assign(_g=g0).groupby("_g")["empresa_ruc"]
                          .nunique().to_dict())
                grupo, n_err = _fusionar_erratas(celdas, grupo, niv, emp_g0)
                print(f"fusion por errata: {n_err:,} grupos absorbidos")

            g_por_etiqueta = dict(zip(celdas, grupo))
            d = marco.assign(_g=marco[col].astype(str).map(g_por_etiqueta).astype("int64"))
            m_g, W_g, emp_g, claves, tau2, sigma2, t2_serie, s2_serie = _stats(d, "_g")
            pos = {int(k): i for i, k in enumerate(claves)}
            ix = np.array([pos.get(int(g), -1) for g in grupo])
            m = np.where(ix >= 0, m_g[np.maximum(ix, 0)], np.nan)
            W = np.where(ix >= 0, W_g[np.maximum(ix, 0)], 0.0)
            emp = np.where(ix >= 0, emp_g[np.maximum(ix, 0)], 0).astype(int)
        else:
            d = marco
            m2, W2, emp2, celdas2, tau2, sigma2, t2_serie, s2_serie = _stats(marco, col)
            pos2 = {c: i for i, c in enumerate(celdas2)}
            ix2 = np.array([pos2.get(c, -1) for c in celdas])
            m = np.where(ix2 >= 0, m2[np.maximum(ix2, 0)], np.nan)
            W = np.where(ix2 >= 0, W2[np.maximum(ix2, 0)], 0.0)
            emp = np.where(ix2 >= 0, emp2[np.maximum(ix2, 0)], 0).astype(int)

        # Cuantiles empiricos de los votos, sobre la columna de GRUPO cuando hay fusion:
        # las grafias de un mismo puesto son una sola celda a todos los efectos.
        colg = col if not umbral_fusion else "_g"
        qs = cuantiles_de_empresa(d, colg, t2_serie, s2_serie, CUANTILES)
        qp = cuantiles_de_persona(d, colg, t2_serie, s2_serie, CUANTILES)

        def _expandir(serie, defecto):
            v = pd.Series(serie).reindex(
                pd.Index(grupo) if umbral_fusion else pd.Index(celdas)).to_numpy(float)
            return np.where(np.isfinite(v), v, defecto)

        tau2_c = _expandir(t2_serie, tau2)
        sigma2_c = _expandir(s2_serie, sigma2)
        bandas = np.full((n, len(CUANTILES)), np.nan)
        bandas_per = np.full((n, len(CUANTILES)), np.nan)
        for k, q in enumerate(CUANTILES):
            if q in qs.columns:
                bandas[:, k] = _expandir(qs[q], np.nan)
            if q in qp.columns:
                bandas_per[:, k] = _expandir(qp[q], np.nan)

        # personas por GRUPO, no por etiqueta: las grafias de un puesto suman juntas
        pg = d.groupby(colg).size()
        personas = pd.Series(pg).reindex(
            pd.Index(grupo) if umbral_fusion else pd.Index(celdas)
        ).fillna(0).to_numpy(dtype=np.int64)

        ajuste_seg = _ajuste_segmento(marco, col, celdas, niv, tau2_c, sigma2_c)

        # Banda por rubro. Las varianzas van indexadas por la clave de `colg` y salen de
        # los arrays YA expandidos: `t2_serie` no cubre las celdas que se cayeron de
        # `tau2_por_celda`, y ahi hace falta el global, no un NaN.
        clave_et = grupo if umbral_fusion else np.array(celdas, dtype=object)
        t2_cl = pd.Series(tau2_c, index=clave_et)
        s2_cl = pd.Series(sigma2_c, index=clave_et)
        t2_cl = t2_cl[~t2_cl.index.duplicated()]
        s2_cl = s2_cl[~s2_cl.index.duplicated()]
        rubro = _bandas_por_rubro(d, colg, clave_et, t2_cl, s2_cl)
        print(f"banda por rubro: {len(rubro[0]):,} pares (celda, rubro) sobre "
              f"{len(rubro[8])} rubros")

        ef = efecto_nivel(marco, col=col)
        return cls(celdas, m, W, emp, Z, tau2, sigma2, lam, sbu, niv, ef, grupo,
                   tau2_c, sigma2_c, bandas, personas, bandas_per, lam_nivel,
                   ajuste_seg, rubro)

    # -- persistencia ----------------------------------------------------------

    def guardar(self, ruta):
        """Un solo `.npz`. Construir la base tarda minutos —descargar un millon de filas
        y embeber 65.081 titulos—; cargarla debe tardar segundos. Sin esto, cada consulta
        de un cliente rehace todo el trabajo."""
        np.savez_compressed(
            ruta, celdas=np.array(self.celdas, dtype=object), m=self.m, W=self.W,
            emp=self.emp, Z=self.Z.astype(np.float32), nivel=self.nivel,
            grupo=self.grupo, tau2_c=self.tau2_c, sigma2_c=self.sigma2_c,
            bandas=self.bandas, bandas_per=self.bandas_per,
            ajuste_seg=self.ajuste_seg,
            lam_k=np.array(sorted(self.lam_nivel), dtype=float),
            lam_v=np.array([self.lam_nivel[k] for k in sorted(self.lam_nivel)],
                           dtype=float),
            personas=self.personas,
            ef_k=np.array(sorted(self.efecto), dtype=float),
            ef_v=np.array([self.efecto[k] for k in sorted(self.efecto)], dtype=float),
            # Banda por rubro, dispersa: pares (celda, rubro) y sus estadisticos.
            rub_cel=self.rub_cel, rub_cod=self.rub_cod, rub_m=self.rub_m, rub_W=self.rub_W, rub_emp=self.rub_emp,
            rub_per=self.rub_per, rub_bandas=self.rub_bandas,
            rub_bandas_per=self.rub_bandas_per,
            rubros=np.array(self.rubros, dtype=object),
            escalares=np.array([self.tau2, self.sigma2, self.lam], dtype=float))

    @classmethod
    def cargar(cls, ruta, sbu):
        with np.load(ruta, allow_pickle=True) as z:
            tau2, sigma2, lam = z["escalares"]
            ef = {int(k): float(v) for k, v in zip(z["ef_k"], z["ef_v"])}
            # `grupo` falta en las bases guardadas antes de la fusion; sin el, cada
            # etiqueta es su propio grupo y el comportamiento es el de entonces.
            opc = {k: (z[k] if k in z.files else None)
                   for k in ("grupo", "tau2_c", "sigma2_c", "bandas", "personas",
                             "bandas_per", "ajuste_seg")}
            lam_nivel = ({int(k): float(v) for k, v in zip(z["lam_k"], z["lam_v"])}
                         if "lam_k" in z.files else {})
            # La banda por rubro falta en las bases guardadas antes de D-023; sin ella
            # `--rubro` no encuentra nada y todo cae al global, que es el comportamiento
            # de entonces y no un error.
            rubro = None
            if "rub_cel" in z.files:
                rubro = (z["rub_cel"], z["rub_cod"], z["rub_m"], z["rub_W"],
                         z["rub_emp"], z["rub_per"], z["rub_bandas"],
                         z["rub_bandas_per"], list(z["rubros"]))
            return cls(list(z["celdas"]), z["m"], z["W"], z["emp"],
                       z["Z"].astype(float), float(tau2), float(sigma2), float(lam),
                       sbu, z["nivel"], ef, opc["grupo"], opc["tau2_c"],
                       opc["sigma2_c"], opc["bandas"], opc["personas"],
                       opc["bandas_per"], lam_nivel, opc["ajuste_seg"], rubro)

    # -- consulta --------------------------------------------------------------

    def referenciar(self, titulos, X_por_etiqueta, anio=None, segmento=None,
                    rubro=None):
        """Una fila por titulo: referencia, intervalo, confianza y en que se basa.

        `segmento` es el tamano de la empresa del CLIENTE —`GRANDE`, `MEDIANA`,
        `PEQUENA`, `MICROEMPRESA`— y sirve para corregir el sesgo de los cargos altos:
        a una empresa pequena se le decia que su gerente general cobra un 56% por debajo
        del mercado cuando entre sus pares esta bien. Sin el, no se segmenta y el
        comportamiento es el de siempre. Ver `_ajuste_segmento`.

        `rubro` es el CIIU de primer nivel del CLIENTE. Donde su celda tiene rubro con
        respaldo suficiente, la referencia y las dos bandas salen SOLO de las empresas de
        ese rubro; donde no lo tiene, ese cargo cae al mercado entero. El fallback es POR
        CARGO, no por informe. Ver el bloque de `COL_RUBRO`: no mejora la precision y se
        monta por legitimidad, con el coste visible en `empresas` y en la confianza.
        """
        titulos = [str(t) for t in titulos]
        unicos = sorted(set(titulos))
        Q = np.vstack([X_por_etiqueta[t] for t in unicos]).astype(float)
        Q /= np.linalg.norm(Q, axis=1, keepdims=True)
        vec, sim = _vecinos(Q, self.Z, self.k_busqueda, excluir_propio=False)
        seg = _norm_segmento(segmento)
        k_seg = SEGMENTOS.index(seg) if seg else None
        rub = _norm_rubro(rubro)
        if rub and rub not in self.rubros:
            # Un rubro que la base no conoce no es un error del cliente: puede ser un
            # CIIU sin ninguna celda que aguante el suelo. Se avisa y se sigue en global,
            # que es mejor que devolver un informe vacio sin decir por que.
            warnings.warn(f"rubro {rub!r} sin datos suficientes en la base; "
                          f"todo el informe cae al mercado entero")

        filas = {}
        for k, t in enumerate(unicos):
            propio = self.idx.get(t)
            mi_grupo = int(self.grupo[propio]) if propio is not None else -1
            banda = banda_per = None
            directo = (propio is not None
                       and self.emp[propio] >= MIN_EMPRESAS
                       and self.personas[propio] >= self.min_personas)
            if directo:
                # .HAY RUBRO PARA ESTE CARGO? El fallback es por cargo: un cliente de
                # manufactura tendra rubro en `CONTADOR` y mercado entero en
                # `SOLDADOR DE PRECISION`, porque el suelo es de confidencialidad.
                fr = self.rub.get((propio, rub)) if rub else None
                if fr is not None:
                    # Centro y banda salen de los MISMOS votos —los del rubro— o el
                    # centro podria caer fuera de su propio p25-p75.
                    mu = float(self.rub_m[fr])
                    W_i = float(self.rub_W[fr])
                    n_emp, n_per = int(self.rub_emp[fr]), int(self.rub_per[fr])
                    q, qp = self.rub_bandas[fr], self.rub_bandas_per[fr]
                    base, usado = f"rubro {rub}", rub
                else:
                    mu = self.m[propio]
                    W_i = float(self.W[propio])
                    n_emp, n_per = int(self.emp[propio]), int(self.personas[propio])
                    q = (self.bandas[propio] if self.emp[propio] >= MIN_EMPRESAS_BANDA
                         else np.full(len(CUANTILES), np.nan))
                    qp = (self.bandas_per[propio] if self.emp[propio] >= MIN_EMPRESAS_BANDA
                          else np.full(len(CUANTILES), np.nan))
                    base, usado = "datos directos", ""
                # `tau_c` y `sigma_c` son SIEMPRE los de la celda entera, tambien con
                # rubro: con 10-90 empresas se estimarian pesimo y ya vienen encogidas.
                # La banda habla de EMPRESAS, asi que NO lleva `sigma`: la dispersion
                # dentro de una nomina no mueve el nivel de la empresa. Ver `CUANTILES`.
                var = self.tau2_c[propio] + 1.0 / W_i
                # ...y la de PERSONAS si la lleva: al sueldo de UNA persona hay que
                # ponerle al lado lo que cobra la gente, no lo que pagan las empresas.
                var_per = var + self.sigma2_c[propio]
                # Menos empresas en el rubro => `1/W` mayor => la confianza BAJA sola.
                # Ese es el coste de la lente, y se paga donde se ve.
                var_centro = 1.0 / W_i
                # Con empresas de sobra, los cuantiles empiricos ganan a cualquier normal:
                # describen la forma real, que va de un pico a una cola larga segun cargo.
                if np.isfinite(q).all():
                    banda = dict(zip(CUANTILES, q))
                if np.isfinite(qp).all():
                    banda_per = dict(zip(CUANTILES, qp))
                mejor, directo_ok = 1.0, True
            else:
                j, s = vec[k], sim[k]
                # Se descarta el GRUPO propio entero, no solo la etiqueta exacta. Si la
                # celda no llega a MIN_EMPRESAS, sus hermanos de grafia comparten sus
                # estadisticos: dejarlos entrar como "vecinos" a distancia cero colaria
                # por la puerta de atras la misma celda que el suelo acaba de rechazar
                # —y ese suelo es de confidencialidad, no de gusto—, y de paso fingiria
                # precision promediando copias del mismo dato.
                if mi_grupo >= 0:
                    quedan = self.grupo[j] != mi_grupo
                    # Si no queda NADA fuera del grupo, la base entera es ese grupo y no
                    # hay evidencia externa que ofrecer. Se responde igual —es la decision
                    # de producto— pero solo pasa en bases degeneradas de un solo puesto.
                    if quedan.any():
                        j, s = j[quedan], s[quedan]
                j, s = j[:VECINOS], s[:VECINOS]
                # `lambda` DEL ESCALON del puesto preguntado. Varia 18x del nivel 1 al 5
                # y con el global se castigaba de menos justo arriba, que es donde mas
                # duele: la respuesta se arrastraba hacia vecinos que no eran.
                #
                # Si el titulo no declara rango se usa la media de los `lambda` de sus
                # vecinos que si lo declaran. Sin pesos a proposito: los pesos dependen de
                # `lambda`, y usarlos aqui seria circular.
                mi_niv = self.nivel[propio] if propio is not None else nivel_lexico(t)
                lam_i = None
                if self.lam_nivel:
                    if mi_niv is not None and np.isfinite(mi_niv):
                        lam_i = self.lam_nivel.get(int(mi_niv))
                    if lam_i is None:
                        vecinos_lam = [self.lam_nivel[int(nj)] for nj in self.nivel[j]
                                       if np.isfinite(nj) and int(nj) in self.lam_nivel]
                        if vecinos_lam:
                            lam_i = float(np.mean(vecinos_lam))
                dist = (self.lam if lam_i is None else lam_i) * (1.0 - s)
                var_j = 1.0 / self.W[j] + dist
                peso = 1.0 / var_j
                peso /= peso.sum()

                # AJUSTE POR NIVEL. Los vecinos vienen del area ENMASCARADA, asi que un
                # `JEFE DE BODEGA` es vecino de un `AUXILIAR DE BODEGA` — misma area,
                # distinto escalon, y entre el 1 y el 5 hay 2,37x de pago. No hay que
                # descartarlo: el efecto de cada escalon esta MEDIDO, asi que se le resta
                # al vecino su escalon y se le suma el del puesto que se pregunta.
                #
                # Si no se sabe el nivel del puesto preguntado no se puede ajustar, y esa
                # ignorancia se paga en el intervalo (`var_nivel`), no fingiendo certeza.
                aj = np.zeros(len(j))
                mi = self.nivel[propio] if propio is not None else nivel_lexico(t)
                if mi is not None and np.isfinite(mi) and self.efecto:
                    ei = self.efecto.get(int(mi), 0.0)
                    aj = np.array([ei - self.efecto.get(int(nj), ei)
                                   if np.isfinite(nj) else 0.0 for nj in self.nivel[j]])
                    penal_nivel = 0.0
                else:
                    # No se sabe el escalon del puesto preguntado, asi que no se puede
                    # ajustar. La ignorancia se paga en el intervalo — pero la que hay,
                    # no la del caso peor.
                    #
                    # Antes se sumaba `var_nivel`, la dispersion del efecto entre los
                    # CINCO escalones: tratar a un `OPERADOR DE PARQUEADERO` como si
                    # pudiera ser gerente. Si sus vecinos son todos operarios y asistentes
                    # de parqueadero, el puesto casi seguro es de nivel bajo y ese castigo
                    # sobra. Aqui se usa la dispersion de los niveles QUE HAY EN SU
                    # VECINDARIO: homogeneo -> penalizacion pequena; de auxiliar a gerente
                    # -> grande, que ahi si la merece.
                    ef_vec = np.array([self.efecto.get(int(nj), np.nan)
                                       if np.isfinite(nj) else np.nan
                                       for nj in self.nivel[j]])
                    hay = np.isfinite(ef_vec)
                    if hay.sum() >= 2:
                        pv = peso[hay] / peso[hay].sum()
                        media = float((pv * ef_vec[hay]).sum())
                        penal_nivel = float((pv * (ef_vec[hay] - media) ** 2).sum())
                    else:
                        penal_nivel = self.var_nivel
                mu = float((peso * (self.m[j] + aj)).sum())
                # Las dos partes NO se promedian igual. El error de medicion de cada
                # vecino es independiente y se cancela al promediar (suma de peso^2). La
                # distancia semantica es un SESGO compartido: si los 25 vecinos estan
                # igual de lejos, promediarlos no acerca la respuesta. Tratarla como ruido
                # hacia que `LOTERO` —sin vecindario real— saliera con un intervalo
                # estrecho por el mero hecho de promediar mucha gente equivocada.
                # `tau_c` se hereda del vecindario: un puesto desconocido rodeado de
                # gerencias dispersa como una gerencia, y uno rodeado de auxiliares no.
                tau2_v = float((peso * self.tau2_c[j]).sum())
                var = (tau2_v
                       + float((peso ** 2 / self.W[j]).sum())
                       + float((peso * dist).sum())
                       + penal_nivel)
                # Todo lo que NO es dispersion del mercado es incertidumbre nuestra: el
                # ruido de medicion de los vecinos, el castigo por no ser exactamente ese
                # puesto, y lo que no se sabe de su escalon.
                var_centro = var - tau2_v
                var_per = var + float((peso * self.sigma2_c[j]).sum())
                base, usado = "por analogia", ""
                # SIN CONTAR DOS VECES. Los vecinos que comparten grupo de fusion
                # comparten estadisticos, asi que sumarlos multiplicaria el respaldo por
                # el numero de grafias. `ANALISTA DE RIESGO CREDITICIO` declaraba 194
                # empresas cuando las de verdad eran 46.
                _, uno = np.unique(self.grupo[j], return_index=True)
                n_emp = int(self.emp[j[uno]].sum())
                n_per = int(self.personas[j[uno]].sum())
                mejor, directo_ok = float(s.max()), False
            # DOS CANTIDADES, DOS PREGUNTAS. `sd_modelo` es la del modelo y sirve para
            # la CONFIANZA: contra el suelo mide que parte del ancho es ignorancia
            # nuestra y no anchura del mercado. La BANDA es lo que se entrega, y con
            # datos de sobra sale de los cuantiles empiricos, que describen la forma
            # real. Mezclarlas hacia que una celda de 48 empresas con banda de ±2%
            # saliera BAJA, porque el suelo teorico y la dispersion observada no son la
            # misma cosa: los votos observados llevan ademas su propio ruido sigma/n.
            sd_modelo = float(np.sqrt(var))
            if banda is None:
                banda = {q: mu + Z_NORMAL[q] * sd_modelo for q in CUANTILES}
            if banda_per is None:
                sdp = float(np.sqrt(var_per))
                banda_per = {q: mu + Z_NORMAL[q] * sdp for q in CUANTILES}
            # DESPLAZAMIENTO POR TAMANO. Mueve el centro y la banda entera; no reestima
            # la anchura, que esta medido que no mejora. Cero fuera de los cargos altos.
            if k_seg is not None and propio is not None:
                aj_seg = float(self.ajuste_seg[propio, k_seg])
                if aj_seg:
                    mu += aj_seg
                    banda = {q: v + aj_seg for q, v in banda.items()}
                    banda_per = {q: v + aj_seg for q, v in banda_per.items()}

            sd = float((banda[0.75] - banda[0.25]) / (2.0 * 0.6745))
            conf, incert = _confianza(var_centro)
            ancho = float(np.exp(0.6745 * sd) - 1.0)      # el de la banda entregada
            filas[t] = {"referencia_log": mu, "sd": sd,
                        "p10_log": banda[0.10], "p25_log": banda[0.25],
                        "p75_log": banda[0.75], "p90_log": banda[0.90],
                        "p10per_log": banda_per[0.10], "p25per_log": banda_per[0.25],
                        "p75per_log": banda_per[0.75], "p90per_log": banda_per[0.90],
                        "confianza": conf, "base": base, "ancho_rel": round(ancho, 3),
                        "incert_centro": round(incert, 4),
                        "segmento": seg or "", "rubro": usado,
                        "empresas": n_emp, "personas": n_per,
                        "similitud": round(mejor, 3)}

        out = pd.DataFrame([filas[t] for t in titulos])
        out.insert(0, "cargo", titulos)
        if anio is not None:
            f = float(self.sbu(int(anio)))
            for col, nueva in (("referencia_log", "referencia"),
                               ("p10_log", "p10_emp"), ("p25_log", "p25_emp"),
                               ("p75_log", "p75_emp"), ("p90_log", "p90_emp"),
                               ("p10per_log", "p10"), ("p25per_log", "p25"),
                               ("p75per_log", "p75"), ("p90per_log", "p90")):
                out[nueva] = (np.exp(out[col]) * f).round(2)
        return out


def _fusionar(Z, niveles, umbral=UMBRAL_FUSION, tope=TOPE_GRUPO):
    """Agrupa cuasi-duplicados por ENLACE COMPLETO. Devuelve etiqueta -> id de grupo.

    Aglomerativo y voraz: las aristas candidatas se recorren de mas a menos similares y
    dos grupos se unen solo si el par PEOR entre ellos aguanta el umbral. Esa comprobacion
    es toda la diferencia con union-find, y es la que impide que el grupo crezca por
    cadena hasta juntar cosas que no se parecen.

    El candado de escalon —dos niveles lexicos distintos no se juntan— aqui casi no hace
    falta: con enlace completo solo rechaza 18 uniones de 15.870. El dano nunca vino de
    pares malos sino de la cadena que los conectaba. Se deja porque es barato y porque sin
    el, un titulo SIN palabra de rango podria servir de puente entre dos que si la tienen.
    """
    n = len(niveles)
    if n < 2 or umbral is None:
        return np.arange(n)
    vec, sim = _vecinos(Z, Z, min(VECINOS_FUSION, n - 1), excluir_propio=True)

    vistos, aristas = set(), []
    for i in range(n):
        for j, s in zip(vec[i], sim[i]):
            if s < umbral:
                break                       # `sim` viene ordenada de mayor a menor
            j = int(j)
            if j == i:
                continue
            par = (i, j) if i < j else (j, i)
            if par in vistos:
                continue
            vistos.add(par)
            na, nb = niveles[par[0]], niveles[par[1]]
            if np.isfinite(na) and np.isfinite(nb) and na != nb:
                continue
            aristas.append((float(s), par[0], par[1]))
    aristas.sort(key=lambda t: -t[0])

    de = np.arange(n)
    miembros = {}
    for _, i, j in aristas:
        gi, gj = int(de[i]), int(de[j])
        if gi == gj:
            continue
        A, B = miembros.get(gi, [gi]), miembros.get(gj, [gj])
        if len(A) + len(B) > tope:
            continue
        niv = np.unique(np.concatenate([niveles[A], niveles[B]]))
        if len(niv[np.isfinite(niv)]) > 1:
            continue
        if float((Z[A] @ Z[B].T).min()) < umbral:      # el par PEOR manda
            continue
        miembros[gi] = A + B
        miembros.pop(gj, None)
        de[A + B] = gi
    return de


_ROMANO_ERR = re.compile(r"\b(I{1,3}|IV|V|VI{0,3}|IX|X)\b")
_DIGITO_ERR = re.compile(r"\d")


def _distancia1(a, b):
    """True si `a` y `b` estan a distancia de edicion exactamente 1.

    No es un Levenshtein general: a distancia 1 solo hay tres formas —sustituir, insertar
    o borrar un caracter— y comprobarlas directamente evita la matriz de programacion
    dinamica sobre 65.081 titulos.
    """
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        dif = [i for i in range(la) if a[i] != b[i]]
        return len(dif) == 1
    if la > lb:
        a, b, la = b, a, lb
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _es_errata(a, b):
    """.El par a distancia 1 es un DEDAZO, y no un escalon ni una variante de genero?

    Devuelve False para todo lo que no sea claramente ortografico. Es deliberadamente
    conservador: un falso positivo aqui funde dos oficios distintos en una sola celda y
    contamina la referencia de las dos.
    """
    if _DIGITO_ERR.search(a) or _DIGITO_ERR.search(b):
        return False                                    # OPERARIO 1 / OPERARIO 2
    if set(_ROMANO_ERR.findall(a)) != set(_ROMANO_ERR.findall(b)):
        return False                                    # OPERARIO I / OPERARIO II
    if any(t in a or t in b for t in ("/A", "(A)")):
        return False                                    # forma inclusiva: TRABAJADOR/A
    # donde y como difieren
    if len(a) == len(b):
        i = next(k for k in range(len(a)) if a[k] != b[k])
        # LETRA DE GRADO. `AYUDANTE B DE MANTENIMIENTO` / `AYUDANTE C DE MANTENIMIENTO`
        # y `SUPERVISOR C`: una letra SUELTA es escalafon, no ortografia. Los dos casos
        # aparecieron al inspeccionar la base real y habrian pasado como dedazos.
        if _letra_suelta(a, i) and _letra_suelta(b, i):
            return False
        # GENERO, incluido en plural. La primera version exigia que la vocal fuera la
        # ULTIMA del titulo, y por eso `ENFERMERAS`/`ENFERMEROS` se colaba como errata:
        # la O/A va seguida de la S del plural.
        if {a[i], b[i]} == {"O", "A"} and _fin_de_palabra(a, i):
            return False                                # OPERARIO/OPERARIA, ENFERMER-AS/OS
        return True
    corta, larga = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(corta) and corta[i] == larga[i]:
        i += 1
    c = larga[i]
    if c == "A" and _fin_de_palabra(larga, i) and i > 0 and corta[i - 1] in "RNL":
        return False                                    # VENDEDOR / VENDEDORA
    return True


def _fin_de_palabra(s, i):
    """El caracter `i` cierra su palabra, admitiendo una `S` de plural detras."""
    resto = s[i + 1:]
    j = 0
    while j < len(resto) and resto[j] == "S":
        j += 1
    return j >= len(resto) or not resto[j].isalpha()


def _letra_suelta(s, i):
    """El caracter `i` es una palabra de una sola letra: `AYUDANTE B DE ...` -> grado."""
    if not s[i].isalpha():
        return False
    antes = i == 0 or not s[i - 1].isalnum()
    despues = i == len(s) - 1 or not s[i + 1].isalnum()
    return antes and despues


def _fusionar_erratas(celdas, grupo, niveles, emp_por_grupo,
                      min_largo=MIN_LARGO_ERRATA, max_raro=MAX_EMPRESAS_ERRATA,
                      min_comun=MIN_EMPRESAS_ABSORBE):
    """Absorbe los grupos-dedazo dentro del grupo comun del que son errata.

    Segunda pasada, DESPUES de la fusion semantica y por separado: asi no altera nada de
    lo que `e2_nivel/07` midio. Y es de una sola direccion —lo raro entra en lo comun—,
    asi que no encadena: el destino nunca es a su vez absorbido, porque para serlo tendria
    que tener <=2 empresas y acaba de exigirsele >=10.

    Los pares se buscan por VARIANTES DE BORRADO (SymSpell) y no todos contra todos:
    65.081 titulos son 2.100 millones de pares, y dos cadenas a distancia <=1 comparten
    siempre una variante con un caracter menos. Son ~1,8 millones de claves y segundos.
    """
    n = len(celdas)
    idx = defaultdict(list)
    for i, c in enumerate(celdas):
        if len(c) < min_largo:
            continue
        idx[c].append(i)
        for k in range(len(c)):
            idx[c[:k] + c[k + 1:]].append(i)

    destino, vistos, fusiones = {}, set(), 0
    for lista in idx.values():
        if len(lista) < 2:
            continue
        for x in range(len(lista)):
            for y in range(x + 1, len(lista)):
                i, j = lista[x], lista[y]
                par = (i, j) if i < j else (j, i)
                if par in vistos:
                    continue
                vistos.add(par)
                gi, gj = int(grupo[par[0]]), int(grupo[par[1]])
                if gi == gj:
                    continue
                ni, nj = niveles[par[0]], niveles[par[1]]
                if np.isfinite(ni) and np.isfinite(nj) and ni != nj:
                    continue
                a, b = celdas[par[0]], celdas[par[1]]
                if not _distancia1(a, b) or not _es_errata(a, b):
                    continue
                ei, ej = emp_por_grupo.get(gi, 0), emp_por_grupo.get(gj, 0)
                raro, comun = (gi, gj) if ei <= ej else (gj, gi)
                if emp_por_grupo.get(raro, 0) > max_raro:
                    continue
                if emp_por_grupo.get(comun, 0) < min_comun:
                    continue
                if raro in destino:            # ya absorbido por otro comun
                    continue
                destino[raro] = comun
                fusiones += 1

    if not destino:
        return np.asarray(grupo), 0
    nuevo = np.array([destino.get(int(g), int(g)) for g in grupo], dtype=np.int64)
    return nuevo, fusiones


def _vecinos(Q, B, k, excluir_propio):
    """(indices, similitudes) de los k vecinos de cada fila de Q dentro de B."""
    # `argpartition` exige kth < n. Antes se recortaba a n-1 SIEMPRE, y con bases cortas
    # eso escondia la ultima celda: pedir 27 vecinos de una base de 3 devolvia 2. Cuando
    # esos dos eran hermanos de grafia, el filtro de grupo se quedaba sin nada fuera del
    # grupo y la celda acababa contestandose a si misma. Aqui, si caben todas, se ordena
    # la fila entera y no se pierde ninguna.
    n_b = B.shape[0]
    k = max(1, min(k, n_b - 1 if excluir_propio else n_b))
    vec = np.zeros((Q.shape[0], k), dtype=np.int32)
    sim = np.zeros((Q.shape[0], k), dtype=float)
    paso = 512
    for i0 in range(0, Q.shape[0], paso):
        S = Q[i0:i0 + paso] @ B.T
        for r in range(S.shape[0]):
            fila = S[r]
            if excluir_propio:
                fila[i0 + r] = -np.inf
            if k >= n_b:
                cand = np.argsort(-fila)[:k]
            else:
                cand = np.argpartition(-fila, k)[:k]
                cand = cand[np.argsort(-fila[cand])]
            vec[i0 + r] = cand
            sim[i0 + r] = np.clip(fila[cand], 0.0, None)
    return vec, sim
