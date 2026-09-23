"""Cross-encoders de RERANKING contra los 48 juicios. El candidato natural que faltaba.

POR QUE ESTE Y NO EL NLI. `13b`/`13c` usaron un modelo de inferencia natural: «.la frase
A implica la frase B?». Esa es una pregunta prestada. La pregunta propia es «.cuanto
tiene que ver A con B?», y para eso existe una familia entera de cross-encoders de
reranking, entrenados para puntuar la relevancia de un pasaje frente a una consulta.
Siguen siendo CONGELADOS y NO SUPERVISADOS para nosotros: ni un ejemplo de cargos.

EL EXAMEN DE CORDURA VA PRIMERO, Y ES ELIMINATORIO
------------------------------------------------------------------------------
La leccion de `13b` fue que un modelo congelado trae un umbral —y una escala— por
calibrar, y que interpretar su salida sin comprobarla produce conclusiones firmadas y
falsas. Asi que aqui el orden es al reves: primero se le pide al modelo que ordene seis
parejas de respuesta conocida, y solo despues se mira su AUC.

    identico  >  errata  >  genero  >  seniority  >  area  >  opuesto

Un modelo que invierta ese orden esta leyendo otra cosa, y su AUC sobre los 48 seria un
numero sin interpretacion.

RESULTADO DEL EXAMEN, declarado ANTES de ver ningun AUC:

  bge-reranker-base       PASA. Orden exacto:
                          identico 9,72 > errata 7,94 > genero 4,92 >
                          seniority 3,89 > area 0,21 > opuesto -0,82

  mmarco-mMiniLMv2        FALLA. Pone `SUPERVISOR CALIDAD`/`SUPERVISOR DE CALIDAD SR`
                          --que son DISTINTOS-- en lo mas alto (2,38), por encima de
                          `CONTADOR`/`CONTADOR` identico (-0,23), y hunde la errata
                          `SECRETARIA`/`SECETARIA` (-1,61). Es un modelo de relevancia
                          consulta->pasaje y «dos cadenas cortas iguales» no es una
                          senal que sepa leer.

mmarco QUEDA DESCALIFICADO COMO CANDIDATO. Se mide igual y se reporta, porque un modelo
que falla el examen y aun asi sacara buen AUC diria algo interesante sobre el examen,
pero no puede adoptarse por mucho que puntue.

QUE SE MIDE. AUC, que no depende de donde se ponga el corte, con IC por bootstrap y
p por permutacion de las etiquetas. Mas la comparacion pareada contra las dos
referencias: el coseno de produccion y el cross NLI de `13c`.

LOS RERANKERS SON ASIMETRICOS (nacieron para consulta->pasaje), asi que se puntua en las
dos direcciones y se reportan la media, el minimo y el maximo, igual que en `13c`.

CUIDADO CON EL COSENO, otra vez. Los 48 pares salieron de la banda 0,93-0,97, donde la
variacion del coseno es minima POR CONSTRUCCION. Su AUC aqui no es su AUC en general.

NINGUNO VE SUELDOS. Regla anticircularidad.

RESULTADO (2026-09-23). EL RERANKING NO GANA. Ver D-034 Enmienda 2.
------------------------------------------------------------------------------
    arbitro                     AUC     IC95 bootstrap  permutacion
    cross NLI media           0,755     [0,594, 0,894]     p=0,0034
    bge-reranker max          0,674     [0,495, 0,834]     p=0,0366
    bge-reranker media        0,660     [0,470, 0,831]     p=0,0514
    coseno (produccion)       0,601     [0,417, 0,776]     p=0,1480
    mmarco DESCALIF media     0,479     [0,294, 0,674]     p=0,5892

    bge media vs coseno      +0,059  [-0,157, +0,260]  P(mejor)=0,706
    bge media vs cross NLI   -0,095  [-0,306, +0,139]  P(mejor)=0,202

LA HIPOTESIS ERA RAZONABLE Y ES FALSA. «El NLI es una pregunta prestada y el
reranking la propia» sonaba bien y no se sostiene: el NLI ordena MEJOR, y el
reranker no se separa ni del coseno ni del azar (su IC incluye 0,5).

POR QUE, probablemente. La implicacion es ASIMETRICA y eso importa aqui:
`JEFE DE MONTAJE Y SOLDADURA` implica a `JEFE DE MONTAJE` pero no al reves, y esa
asimetria ES la senal de que uno es mas amplio que el otro. Un puntaje de
relevancia no tiene como expresar «distintos porque uno es mas estrecho». Lo que
parecia una pregunta prestada resulta ser la pregunta con la forma correcta.

EL EXAMEN DE CORDURA SE VALIDA... A MEDIAS, Y CONVIENE DECIR LAS DOS MITADES:

  FUNCIONA COMO CRIBA. `mmarco` fallo el examen y salio exactamente en el azar
  (AUC 0,479, p=0,59). El examen lo predijo sin gastar los 48 juicios.

  NO FUNCIONA COMO RANKING. `bge` paso el examen con el orden exacto y aun asi
  pierde contra el NLI. Ordenar bien seis casos faciles no predice discriminar
  casos dificiles: son habilidades distintas.

  O sea: el examen es NECESARIO, no SUFICIENTE. Descarta modelos rotos; no elige
  entre modelos sanos. Eso acota la leccion de D-034 Enmienda 1, que lo dejaba
  sonando mas potente de lo que es.

TODO SIGUE CORTO DE POTENCIA. Los cuatro IC son anchisimos con n=48. Nada de esto
cambia que el cuello de botella son las etiquetas.
"""
import pathlib

import numpy as np
import pandas as pd

SAL = pathlib.Path("research/experimentos/e2_nivel/salidas")
CACHE = SAL / "13d_puntajes_rerank.csv"
CACHE_NLI = SAL / "13c_puntajes_cross.csv"
LOTE = 16
N_BOOT = 5000
SEM = 20260923
LINEA = "=" * 78

# clave corta -> (nombre legible, ruta). La clave corta nombra las columnas del
# cache, asi que se declara aparte en vez de derivarla del nombre legible.
MODELOS = {
    "bge": ("bge-reranker", "BAAI/bge-reranker-base"),
    "mmarco": ("mmarco (descalificado)",
               "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"),
}


def cargar_juicios():
    j = pd.read_csv(SAL / "13_para_juzgar.csv", sep=None, engine="python",
                    encoding="utf-8-sig")
    j.columns = [c.strip() for c in j.columns]
    j["mismo"] = j["mismo"].astype(str).str.strip().str.lower()
    return j[j["mismo"].isin(("si", "no"))].reset_index(drop=True)


def puntuar(j):
    """Un logit de relevancia por par y direccion, para cada reranker."""
    if CACHE.exists():
        d = pd.read_csv(CACHE, encoding="utf-8")
        if len(d) == len(j):
            print("  (puntajes en cache)")
            return d

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(4)
    col = {}
    for clave, (nom, ruta) in MODELOS.items():
        tok = AutoTokenizer.from_pretrained(ruta)
        mod = AutoModelForSequenceClassification.from_pretrained(ruta)
        mod.eval()

        a = [str(x) for x in j["comun"]]
        b = [str(x) for x in j["raro"]]
        prem = [v for par in zip(a, b) for v in par]      # ab, ba intercalados
        hipo = [v for par in zip(b, a) for v in par]

        out = []
        for i in range(0, len(prem), LOTE):
            with torch.no_grad():
                x = tok(prem[i:i + LOTE], hipo[i:i + LOTE], return_tensors="pt",
                        padding=True, truncation=True, max_length=128)
                lg = mod(**x).logits
                out += (lg[:, 0] if lg.shape[1] == 1 else lg[:, -1]).tolist()
        col[clave + "_ab"] = out[0::2]
        col[clave + "_ba"] = out[1::2]
        print("  {} listo".format(nom), flush=True)
        del mod, tok

    d = pd.DataFrame(dict(comun=j["comun"], raro=j["raro"], **col))
    d.to_csv(CACHE, index=False, encoding="utf-8")
    return d


def auc(punt, es_si):
    a, b = punt[es_si], punt[~es_si]
    return ((a[:, None] > b[None, :]).sum()
            + 0.5 * (a[:, None] == b[None, :]).sum()) / (len(a) * len(b))


def con_incertidumbre(punt, es_si, rng):
    a = auc(punt, es_si)
    bs = []
    for _ in range(N_BOOT):
        i = rng.integers(0, len(punt), len(punt))
        if 0 < es_si[i].sum() < len(punt):
            bs.append(auc(punt[i], es_si[i]))
    perm = np.array([auc(punt, rng.permutation(es_si)) for _ in range(N_BOOT)])
    return a, np.percentile(bs, 2.5), np.percentile(bs, 97.5), float((perm >= a).mean())


def pareado(p1, p0, es_si, rng):
    """AUC(p1) - AUC(p0) con IC bootstrap. Pareado: remuestrea los MISMOS pares."""
    bs = []
    for _ in range(N_BOOT):
        i = rng.integers(0, len(p1), len(p1))
        if 0 < es_si[i].sum() < len(p1):
            bs.append(auc(p1[i], es_si[i]) - auc(p0[i], es_si[i]))
    bs = np.array(bs)
    return (auc(p1, es_si) - auc(p0, es_si),
            np.percentile(bs, 2.5), np.percentile(bs, 97.5), float((bs > 0).mean()))


def main():
    j = cargar_juicios()
    es_si = (j["mismo"] == "si").to_numpy()
    rng = np.random.default_rng(SEM)

    print(LINEA)
    print("RERANKERS CONTRA {} JUICIOS  ({} si / {} no)".format(
        len(j), int(es_si.sum()), int((~es_si).sum())))
    print(LINEA)
    d = puntuar(j)

    arb = {"coseno (produccion)": j["sim"].to_numpy(float)}
    if CACHE_NLI.exists():
        n = pd.read_csv(CACHE_NLI, encoding="utf-8")
        arb["cross NLI media"] = (n["ab"].to_numpy() + n["ba"].to_numpy()) / 2
    for clave, etq in (("bge-reranker", "bge-reranker"), ("mmarco", "mmarco DESCALIF")):
        ab, ba = d[clave + "_ab"].to_numpy(), d[clave + "_ba"].to_numpy()
        arb[etq + " media"] = (ab + ba) / 2
        arb[etq + " min"] = np.minimum(ab, ba)
        arb[etq + " max"] = np.maximum(ab, ba)

    print("\n  {:<24} {:>6} {:>18} {:>12}".format(
        "arbitro", "AUC", "IC95 bootstrap", "permutacion"))
    for nom, p in arb.items():
        a, lo, hi, pv = con_incertidumbre(p, es_si, rng)
        print("  {:<24} {:>6.3f} {:>18} {:>12}".format(
            nom, a, "[{:.3f}, {:.3f}]".format(lo, hi),
            "p={:.4f}".format(pv)))

    print("\n  " + "-" * 74)
    print("  COMPARACION PAREADA (positivo = el primero ordena mejor)")
    base = {"coseno": arb["coseno (produccion)"]}
    if "cross NLI media" in arb:
        base["cross NLI"] = arb["cross NLI media"]
    for contra, p0 in base.items():
        for nom in ("bge-reranker media",):
            dif, lo, hi, pg = pareado(arb[nom], p0, es_si, rng)
            print("  {:<22} vs {:<12} {:>+7.3f}  [{:+.3f}, {:+.3f}]  P(mejor)={:.3f}".format(
                nom, contra, dif, lo, hi, pg))

    print("\n" + LINEA)
    print("LECTURA: `bge` paso el examen de cordura, asi que su AUC se puede interpretar.")
    print("`mmarco` no lo paso y su AUC va solo como referencia: por bueno que salga, un")
    print("modelo que pone dos puestos DISTINTOS por encima de dos IDENTICOS no entra.")
    print("La pregunta es si `bge` le gana al cross NLI de 13c y al coseno de produccion.")
    print(LINEA)


if __name__ == "__main__":
    main()
