"""`13b` estaba mal montado. Esto lo rehace sin umbral inventado.

EL DEFECTO DE `13b`. Al cross-encoder congelado se le puso un corte de 0,5 sobre la
probabilidad de implicacion, exigida ADEMAS en las dos direcciones. Ese numero no salio
de ninguna parte: el coseno competia con su 0,95 ya calibrado en produccion y el cross
con un 0,5 puesto a dedo. La comprobacion de cordura que habia que hacer antes:

    CONTADOR    / CONTADOR     identico        entailment 0,966
    CONTADOR    / CONTADORA    mismo puesto    entailment 0,395   <- por DEBAJO de 0,5
    SECRETARIA  / SECETARIA    errata          entailment 0,740
    GERENTE GENERAL / CONSERJE opuesto         entailment 0,001

El corte de 0,5 rechaza `CONTADOR`/`CONTADORA`, que el producto fusiona a proposito
(D-026), y exigirlo en las dos direcciones lo empeora. De ahi salia el «contesta `no` el
79% de las veces»: era la REGLA DE DECISION, no el juicio del modelo. El modelo, por su
parte, esta sano: en NLI de libro de texto acierta 0,996 / 0,999 / 0,999.

QUE SE MIDE AHORA. La capacidad de ORDENAR, que no depende de donde se ponga el corte:

  AUC     probabilidad de que un par `si` tomado al azar puntue por encima de un `no`
          tomado al azar. 0,50 es una moneda; 1,00 es separacion perfecta. No usa
          umbral, asi que compara arbitros en igualdad de condiciones.

  mejor   la exactitud en el mejor corte posible. Es OPTIMISTA A PROPOSITO --el corte se
          elige viendo las mismas 48 respuestas-- y esta para poner un TECHO: si ni
          siquiera el mejor corte posible pasa del coseno, no hay corte que lo salve.

CUIDADO CON EL COSENO AQUI. Los 48 pares se sacaron de la banda 0,93-0,97 (ver `13a`),
o sea que el coseno esta medido sobre un rango en el que su propia variacion es minima
por construccion. Su AUC aqui NO es su AUC en general: es lo que le queda DENTRO de la
zona donde ya se sabe que no separa. Eso no lo invalida como linea base --es justo la
pregunta: .hay algo mejor DENTRO de esa banda?-- pero prohibe leerlo como «el coseno
ordena mal».

REGLAS DE DECISION DEL CROSS. Se prueban varias para saber cuanto del resultado era la
regla y cuanto el modelo: las dos direcciones promediadas, el minimo, el maximo, y cada
direccion suelta. `min` es la que uso `13b`.

NINGUNO VE SUELDOS. Regla anticircularidad, igual que en `13b`.
"""
import pathlib
import sys

import numpy as np
import pandas as pd

SAL = pathlib.Path("research/experimentos/e2_nivel/salidas")
CACHE = SAL / "13c_puntajes_cross.csv"
MODELO_CROSS = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
LOTE = 16
LINEA = "=" * 78


def cargar_juicios():
    j = pd.read_csv(SAL / "13_para_juzgar.csv", sep=None, engine="python",
                    encoding="utf-8-sig")
    j.columns = [c.strip() for c in j.columns]
    j["mismo"] = j["mismo"].astype(str).str.strip().str.lower()
    return j[j["mismo"].isin(("si", "no"))].reset_index(drop=True)


def puntajes_cross(j):
    """Probabilidad de implicacion en las DOS direcciones, por lotes.

    En lotes porque de una en una son 7,5 s/par y en lotes de 16 son 2,8 s: el coste
    esta en el arranque de cada pasada, no en el calculo.
    """
    if CACHE.exists():
        d = pd.read_csv(CACHE, encoding="utf-8")
        if len(d) == len(j):
            print("  (puntajes en cache)")
            return d["ab"].to_numpy(), d["ba"].to_numpy()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(4)        # medido: 4 hilos > 12 > 1 en esta maquina
    tok = AutoTokenizer.from_pretrained(MODELO_CROSS)
    mod = AutoModelForSequenceClassification.from_pretrained(MODELO_CROSS)
    mod.eval()
    etq = [mod.config.id2label[i].lower() for i in range(mod.config.num_labels)]
    i_ent = next(k for k, e in enumerate(etq) if "entail" in e)

    def frase(x):
        return "El puesto de trabajo es {}.".format(str(x).title())

    prem, hipo = [], []
    for _, r in j.iterrows():
        prem += [frase(r["comun"]), frase(r["raro"])]     # ab y ba, intercalados
        hipo += [frase(r["raro"]), frase(r["comun"])]

    out = []
    for i in range(0, len(prem), LOTE):
        with torch.no_grad():
            x = tok(prem[i:i + LOTE], hipo[i:i + LOTE], return_tensors="pt",
                    padding=True, truncation=True, max_length=128)
            out += torch.softmax(mod(**x).logits, -1)[:, i_ent].tolist()
        print("    {}/{}".format(min(i + LOTE, len(prem)), len(prem)), flush=True)

    ab, ba = np.array(out[0::2]), np.array(out[1::2])
    pd.DataFrame({"comun": j["comun"], "raro": j["raro"], "ab": ab, "ba": ba}).to_csv(
        CACHE, index=False, encoding="utf-8")
    return ab, ba


def auc(punt, es_si):
    """AUC por conteo de pares, con medio punto a los empates."""
    a, b = punt[es_si], punt[~es_si]
    comp = (a[:, None] > b[None, :]).sum() + 0.5 * (a[:, None] == b[None, :]).sum()
    return comp / (len(a) * len(b))


def mejor_corte(punt, es_si):
    """La exactitud en el mejor corte. OPTIMISTA: el corte se elige sobre estos datos."""
    mejor = (0, None)
    for c in np.unique(punt):
        for signo in (1, -1):
            pred = (punt * signo) >= (c * signo)
            ac = int((pred == es_si).sum())
            if ac > mejor[0]:
                mejor = (ac, (c, signo))
    return mejor


def contra_moneda(aciertos, dice_si, n_si, n_no, rng, n=20000):
    """.Le gana a una moneda que dijera `si` al mismo ritmo, sin leer el texto?"""
    p = dice_si / (n_si + n_no)
    sim = np.array([(rng.random(n_si) < p).sum() + (rng.random(n_no) >= p).sum()
                    for _ in range(n)])
    return sim.mean(), float((sim >= aciertos).mean())


def main():
    j = cargar_juicios()
    es_si = (j["mismo"] == "si").to_numpy()
    n_si, n_no = int(es_si.sum()), int((~es_si).sum())
    rng = np.random.default_rng(20260923)

    print(LINEA)
    print("ARBITROS SIN UMBRAL FIJO  ({} si / {} no)".format(n_si, n_no))
    print(LINEA)
    print("  calculando el cross...", flush=True)
    ab, ba = puntajes_cross(j)

    arbitros = {
        "coseno": j["sim"].to_numpy(float),
        "cross media": (ab + ba) / 2,
        "cross min (el de 13b)": np.minimum(ab, ba),
        "cross max": np.maximum(ab, ba),
        "cross comun->raro": ab,
        "cross raro->comun": ba,
    }

    print("\n  {:<24} {:>7} {:>26} {:>24}".format(
        "arbitro", "AUC", "mejor corte posible", "contra moneda igual"))
    for nom, p in arbitros.items():
        a = auc(p, es_si)
        ac, corte = mejor_corte(p, es_si)
        pred = (p * corte[1]) >= (corte[0] * corte[1])
        esp, pv = contra_moneda(ac, int(pred.sum()), n_si, n_no, rng)
        print("  {:<24} {:>7.3f} {:>14} en {:>7.3f}  {:>9.1f} esp  p={:.3f}".format(
            nom, a, "{}/{}".format(ac, len(j)), corte[0], esp, pv))

    print("\n  " + "-" * 74)
    print("  Y lo que hizo 13b, para que se vea de donde salia:")
    p13b = np.minimum(ab, ba) >= 0.5
    print("    corte fijo en 0,50 -> acierta {}/{}, dice `si` {} veces de {}".format(
        int((p13b == es_si).sum()), len(j), int(p13b.sum()), len(j)))

    print("\n" + LINEA)
    print("LECTURA: el AUC no depende del corte, asi que es la comparacion justa. Si el")
    print("cross no le gana ahi al coseno, no hay umbral que lo arregle y la inferencia")
    print("natural no es la forma de plantear esta pregunta. Si le gana, `13b` medio mi")
    print("umbral y no el modelo, y hay que rehacer la conclusion.")
    print(LINEA)


if __name__ == "__main__":
    main()
