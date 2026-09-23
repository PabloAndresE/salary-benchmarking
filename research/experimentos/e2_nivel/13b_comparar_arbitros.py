"""Tres arbitros contra 48 juicios humanos: .hace falta entrenar algo?

LA PREGUNTA. En la banda 0,93-0,97 los umbrales no separan —`SUPERVISOR PRODUCCION`
/ `SUPERV. PRODUCCION` puntua 0,941 y `INGENIERO BACK-END` / `INGENIERO FRONT-END`
puntua 0,940— y hace falta juicio. Antes de entrenar nada conviene saber si un
modelo de estanteria ya concuerda con el criterio humano.

LOS TRES ARBITROS

  coseno       el bi-encoder que ya esta en produccion, con un corte en 0,95.
               Es la linea base: si los otros no le ganan, no aportan.

  cross        UN CROSS-ENCODER CONGELADO, sin afinar y sin etiquetas nuestras.
               Es la opcion buena y conviene entender POR QUE. El bi-encoder
               codifica cada titulo POR SEPARADO y luego compara vectores: nunca
               ve los dos textos a la vez, asi que `BACK-END` y `FRONT-END` le
               salen parecidos porque cada uno, por su cuenta, es "ingeniero
               senior de algo". Un cross-encoder mete los dos textos en la MISMA
               secuencia y su atencion cruza de uno a otro token a token, asi que
               puede aprender que toda la diferencia esta en esa palabra.

               Se usa en modo inferencia natural, que es lo que lo hace
               NO SUPERVISADO para nosotros: el modelo ya viene entrenado para
               decidir si una frase implica a otra, y esa capacidad se reaprovecha
               sin darle un solo ejemplo de cargos.

  generativo   Gemini en Vertex, como TECHO de comparacion y nada mas. No serviria
               en produccion —no es determinista y mete una dependencia de red en
               la construccion de la base, que tiene que ser reproducible— pero
               dice cuanto puede acertar un modelo que "entiende" de verdad. Si el
               cross congelado se le acerca, no hace falta nada mas.

NINGUNO VE SUELDOS. Los tres reciben dos cadenas de texto. Es la regla
anticircularidad: si el arbitro decidiera mirando lo que paga cada lado, la
agrupacion quedaria optimizada contra el sueldo por la puerta de atras.

QUE SE MIDE. Acuerdo con los 48 juicios, y por separado en los 36 `si` y los 12
`no`. Separado a proposito: un arbitro que diga "el mismo puesto" siempre acierta
el 75% y no sirve para nada, porque lo que hace falta es justo detectar los `no`.

LO QUE ESTO NO ES. 48 pares no deciden nada por si solos; sirven para descartar lo
que claramente no funciona y para estimar si merece la pena el paso siguiente. Un
arbitro que pase de aqui se mide con el protocolo completo, como todo lo demas.

ESTE FICHERO MIDIO MAL AL CROSS. LEER `13c` ANTES QUE ESTO.
------------------------------------------------------------------------------
El corte de 0,5 sobre la probabilidad de implicacion, exigido ademas en las dos
direcciones, no salio de ninguna parte: el coseno competia con su 0,95 calibrado
en produccion y el cross con un numero puesto a dedo. El corte optimo real esta
en 0,003. El 0,5 rechaza hasta `CONTADOR`/`CONTADORA`, que el producto fusiona a
proposito, y `SECRETARIA`/`SECETARIA` se queda en 0,740.

Sin umbral fijo, el cross saca AUC 0,755 [0,588, 0,895] contra 0,601 [0,410,
0,781] del coseno. El «20/48» de abajo medía mi umbral, no el modelo.

Ver `13c_arbitros_sin_umbral_fijo.py` y D-034 Enmienda 1.

RESULTADO DE ESTA CORRIDA, que se conserva solo como registro de lo que fallo.
Ver D-034.
------------------------------------------------------------------------------
    arbitro           acuerdo   en los `si`   en los `no`   dice `si`
    coseno              28/48         20/36          8/12       24/48
    generativo          24/48         13/36         11/12       14/48
    cross congelado     20/48          9/36         11/12       10/48

LA TENTACION: «el cross empata al generativo en los `no`, 11 de 12». NO SE LEA ASI.
El cross contesta `no` 38 de 48 veces cuando la verdad es `no` 12 de 48. Una moneda
que dijera `no` con esa misma frecuencia, SIN LEER EL TEXTO, acertaria 9,5 de los 12
por puro ritmo. La ultima columna no mide deteccion, mide sesgo.

Contra esa moneda —la misma tasa de `si`, texto ignorado, 20.000 simulaciones—:

    coseno            28/48  contra  24,0 esperados    p = 0,159
    generativo        24/48  contra  19,0 esperados    p = 0,075
    cross congelado   20/48  contra  17,0 esperados    p = 0,189

NINGUNO DE LOS TRES SE SEPARA DE UNA MONEDA SESGADA. Los tres van en la direccion
buena y ninguno llega, que con n=48 es exactamente lo que cabia esperar: si las
tasas del cross fueran las verdaderas (sens 0,25 / esp 0,92), la potencia de este
diseno es del 17%.

    N=48  17%     N=100  41%     N=200  63%     N=400  92%

EL CUELLO DE BOTELLA SON LAS ETIQUETAS, NO EL MODELO. Afinar algo contra 48 juicios
que no distinguen un modelo de una moneda seria afinar contra ruido. El paso
siguiente, si se quiere responder esta pregunta, es juzgar ~400 pares; con eso se
decide, y ademas se tiene con que entrenar.

Y OJO CON EL GENERATIVO: su 11/12 salio con un prompt que le da tres motivos para
decir NO y practicamente ninguno para decir SI. Su sesgo hacia el `no` es al menos
en parte mio. Un prompt no es una evaluacion de un modelo.
"""
import pathlib
import sys

import numpy as np
import pandas as pd

SAL = pathlib.Path("research/experimentos/e2_nivel/salidas")
MODELO_CROSS = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
MODELO_GEN = "gemini-2.5-flash"
CORTE_COSENO = 0.95
LINEA = "=" * 78


def cargar_juicios():
    j = pd.read_csv(SAL / "13_para_juzgar.csv", sep=None, engine="python",
                    encoding="utf-8-sig")
    j.columns = [c.strip() for c in j.columns]
    j["mismo"] = j["mismo"].astype(str).str.strip().str.lower()
    return j[j["mismo"].isin(("si", "no"))].reset_index(drop=True)


def arbitro_coseno(j):
    """La linea base: el coseno que ya decide hoy, con su umbral."""
    return (j["sim"].to_numpy(float) >= CORTE_COSENO)


def arbitro_cross(j):
    """Cross-encoder congelado, en modo inferencia natural.

    La premisa afirma un puesto y la hipotesis el otro; si el modelo dice que la
    primera IMPLICA a la segunda, son el mismo puesto. Se pregunta en los dos
    sentidos y se exige implicacion en ambos: `JEFE DE MONTAJE Y SOLDADURA` implica
    a `JEFE DE MONTAJE` pero no al reves, y esa asimetria es justo la senal de que
    uno es mas amplio que el otro.
    """
    import torch
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer)

    tok = AutoTokenizer.from_pretrained(MODELO_CROSS)
    mod = AutoModelForSequenceClassification.from_pretrained(MODELO_CROSS)
    mod.eval()
    etiquetas = [mod.config.id2label[i].lower() for i in range(mod.config.num_labels)]
    i_ent = next(k for k, e in enumerate(etiquetas) if "entail" in e)

    def implica(a, b):
        p = "El puesto de trabajo es {}.".format(a.title())
        h = "El puesto de trabajo es {}.".format(b.title())
        with torch.no_grad():
            x = tok(p, h, return_tensors="pt", truncation=True, max_length=128)
            return float(torch.softmax(mod(**x).logits[0], -1)[i_ent])

    out = []
    for _, r in j.iterrows():
        ab, ba = implica(r["comun"], r["raro"]), implica(r["raro"], r["comun"])
        out.append(min(ab, ba) >= 0.5)
    return np.array(out)


def arbitro_generativo(j):
    """Gemini, como techo de comparacion. NO es candidato a produccion."""
    from benchmarking.config.settings import cargar_settings
    import vertexai
    from vertexai.generative_models import GenerativeModel

    s = cargar_settings()
    vertexai.init(project=s.bq_project, location=s.vertex_location)
    mod = GenerativeModel(MODELO_GEN)

    PROMPT = (
        "Eres un analista de compensaciones en Ecuador. Te doy dos titulos de cargo "
        "tal como los escribio una empresa en su nomina.\n\n"
        "Responde SI si son el MISMO puesto escrito de otra forma, o si la diferencia "
        "es solo de redaccion, abreviatura o erratas.\n"
        "Responde NO si son puestos distintos: distinto nivel jerarquico, distinta "
        "antiguedad (senior/junior), o distinta area de trabajo.\n\n"
        "No razones sobre sueldos. Responde SOLO la palabra SI o NO.\n\n"
        "A: {a}\nB: {b}")

    # EL MARGEN DE TOKENS NO ES COSMETICO con esta familia de modelos. `2.5-flash`
    # razona antes de contestar y ese razonamiento CONSUME el presupuesto de salida:
    # con 4 tokens —de sobra para "SI"— devuelve vacio con `finish_reason:
    # MAX_TOKENS`, y con 64 tambien, porque este prompt es mas largo que una prueba
    # de juguete. Se dan 512 y se lee solo la primera palabra.
    CFG = {"temperature": 0, "max_output_tokens": 512}

    # SI FALLA, SE CAE. La primera version devolvia `False` en cada excepcion, y con
    # las 48 llamadas rotas por un 404 imprimio "12/48 · 0/36 · 12/12" — un numero
    # con pinta de medicion que en realidad era "contesta que no siempre". Un
    # arbitro que no responde no es un arbitro que responde mal.
    out, fallos = [], []
    for _, r in j.iterrows():
        try:
            t = mod.generate_content(
                PROMPT.format(a=r["comun"], b=r["raro"]),
                generation_config=CFG,
            ).text.strip().upper()
        except Exception as e:                      # noqa: BLE001
            fallos.append("{} / {}: {}".format(r["comun"], r["raro"], e))
            t = ""
        out.append(t.startswith("SI") or t.startswith("SÍ"))
    if fallos:
        raise RuntimeError(
            "{} de {} llamadas fallaron; sin respuestas no hay medicion.\n"
            "   primera: {}".format(len(fallos), len(j), fallos[0][:300]))
    return np.array(out)


def reportar(nombre, pred, real):
    si, no = real == "si", real == "no"
    ac = (pred == (real == "si").to_numpy())
    print("  {:<14} {:>8} {:>12} {:>12}".format(
        nombre,
        "{}/{}".format(int(ac.sum()), len(ac)),
        "{}/{}".format(int(ac[si.to_numpy()].sum()), int(si.sum())),
        "{}/{}".format(int(ac[no.to_numpy()].sum()), int(no.sum()))))
    return ac


def main():
    j = cargar_juicios()
    real = j["mismo"]
    print(LINEA)
    print("ARBITROS CONTRA {} JUICIOS HUMANOS  ({} si / {} no)".format(
        len(j), int((real == "si").sum()), int((real == "no").sum())))
    print(LINEA)
    print("  {:<14} {:>8} {:>12} {:>12}".format(
        "arbitro", "acuerdo", "en los `si`", "en los `no`"))

    quiere = sys.argv[1:] or ["coseno", "cross", "generativo"]
    preds = {}
    if "coseno" in quiere:
        preds["coseno"] = reportar("coseno", arbitro_coseno(j), real)
    if "cross" in quiere:
        try:
            preds["cross"] = reportar("cross congelado", arbitro_cross(j), real)
        except ImportError as e:
            print("  cross congelado  no disponible: {}".format(e))
    if "generativo" in quiere:
        try:
            preds["generativo"] = reportar("generativo", arbitro_generativo(j), real)
        except Exception as e:                      # noqa: BLE001
            print("  generativo       no disponible: {}".format(e))

    print("\n" + LINEA)
    print("LECTURA: el acuerdo global engana, porque decir `si` siempre acierta el 75%.")
    print("Lo que decide es la ultima columna: detectar los `no` es para lo que se")
    print("quiere un arbitro. Si el cross congelado se acerca al generativo, no hace")
    print("falta entrenar nada; si ninguno de los dos pasa del coseno, tampoco.")
    print(LINEA)


if __name__ == "__main__":
    main()
