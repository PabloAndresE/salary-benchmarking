"""Potencia de H1 ANTES de abrir `prueba`: ¿alcanzan 200 pares?

H1 (D-036): B supera al coseno en AUC sobre `prueba`, y se adopta si el IC 95% de la
diferencia queda entero sobre cero. Si el efecto real es menor que el ancho de ese
intervalo, H1 sale inconclusa aunque B sea mejor. `prueba` solo se puede ampliar ANTES de
abrirla, asi que esto se mide hoy.

QUE SE USA COMO REFERENCIA DEL EFECTO. B no existe todavia. El unico juez sin entrenar que
ya le gano al coseno es el NLI congelado (D-034, AUC 0,755 sobre 48). Aqui se mide sobre
los 200 de `calibra`, con la plantilla fijada en la Enmienda 1 de D-036:

    "El puesto de trabajo es {Titulo}."      (la misma de `13c`)

El B ajustado deberia ganar AL MENOS eso; si no, no vale la pena entrenar.

COMO SE CALCULA LA POTENCIA. Bootstrap pareado sobre `calibra` para el error estandar de
la diferencia de AUC (NLI - coseno), escalado por raiz(200/n) para otros tamanos de
`prueba`, y potencia = Phi(delta/se_n - 1,96) para varios efectos supuestos. Es la
aproximacion normal habitual; no un remuestreo anidado.

Solo `calibra`. `prueba` no se abre. No se imprimen titulos.

SALIDA: salidas/19_potencia_h1.txt
"""
import os
import pathlib
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.metrics import roc_auc_score

os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.stdout.reconfigure(encoding="utf-8")
SAL = pathlib.Path(__file__).resolve().parent / "salidas"
META = SAL / "13e_pares_400.csv"
JUICIOS = SAL / "13e_para_juzgar.csv"
CACHE = SAL / "19_puntajes_nli_calibra.csv"     # en .gitignore (lleva titulos)
MODELO_CROSS = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
LOTE = 16
SEM = 20260925
B = 10_000
TAMANOS = (200, 300, 400, 600, 800)
EFECTOS = (0.05, 0.075, 0.10, 0.15)


def frase(x):
    return "El puesto de trabajo es {}.".format(str(x).title())


def nli(t):
    if CACHE.exists():
        d = pd.read_csv(CACHE, encoding="utf-8")
        if len(d) == len(t) and (d["n"].to_numpy() == t["n"].to_numpy()).all():
            print("  (puntajes NLI en cache)")
            return d["ab"].to_numpy(), d["ba"].to_numpy()
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    torch.set_num_threads(4)
    tok = AutoTokenizer.from_pretrained(MODELO_CROSS)
    mod = AutoModelForSequenceClassification.from_pretrained(MODELO_CROSS,
                                                             dtype=torch.float32).eval()
    etq = [mod.config.id2label[i].lower() for i in range(mod.config.num_labels)]
    i_ent = next(k for k, e in enumerate(etq) if "entail" in e)
    prem, hipo = [], []
    for c, r in zip(t["comun"], t["raro"]):
        prem += [frase(c), frase(r)]
        hipo += [frase(r), frase(c)]
    out = []
    for i in range(0, len(prem), LOTE):
        with torch.no_grad():
            x = tok(prem[i:i + LOTE], hipo[i:i + LOTE], return_tensors="pt",
                    padding=True, truncation=True, max_length=128)
            out += torch.softmax(mod(**x).logits, -1)[:, i_ent].tolist()
    ab, ba = np.array(out[0::2]), np.array(out[1::2])
    pd.DataFrame({"n": t["n"], "ab": ab, "ba": ba}).to_csv(CACHE, index=False,
                                                           encoding="utf-8")
    return ab, ba


def main():
    meta = pd.read_csv(META, sep=";", encoding="utf-8-sig")
    jui = pd.read_csv(JUICIOS, sep=";", encoding="utf-8-sig", dtype=str,
                      keep_default_na=False)[["n", "mismo"]]
    jui["n"] = jui["n"].astype(int)
    t = meta.merge(jui, on="n")
    t = t[(t["particion"] == "calibra")
          & t["mismo"].str.strip().str.lower().isin(["si", "no"])].reset_index(drop=True)
    y = (t["mismo"].str.strip().str.lower() == "si").astype(int).to_numpy()
    cos = t["sim"].to_numpy(float)
    ab, ba = nli(t)
    jueces = {"NLI media": (ab + ba) / 2, "NLI producto": ab * ba}

    print("=" * 78)
    print("19 · POTENCIA DE H1 ANTES DE ABRIR `prueba`")
    print("=" * 78)
    print("\ncalibra: {} pares ({} si, {} no). prueba NO se abre.".format(
        len(y), y.sum(), len(y) - y.sum()))

    rng = np.random.default_rng(SEM)
    idx_si, idx_no = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    a_cos = roc_auc_score(y, cos)
    print("\nAUC en calibra (bootstrap pareado estratificado, {:,} remuestreos)".format(B))
    print("  coseno            {:.3f}".format(a_cos))
    res = {}
    for nom, s in jueces.items():
        a = roc_auc_score(y, s)
        d = np.empty(B)
        for b in range(B):
            k = np.concatenate([rng.choice(idx_si, len(idx_si)),
                                rng.choice(idx_no, len(idx_no))])
            d[b] = roc_auc_score(y[k], s[k]) - roc_auc_score(y[k], cos[k])
        lo, hi = np.percentile(d, [2.5, 97.5])
        res[nom] = (a - a_cos, d.std())
        print("  {:<17} {:.3f}   diferencia {:+.3f}  IC95 [{:+.3f}, {:+.3f}]  "
              "ee {:.3f}".format(nom, a, a - a_cos, lo, hi, d.std()))

    # el error estandar de referencia: el del mejor juez congelado
    nom_ref = max(res, key=lambda k: res[k][0])
    delta_obs, se200 = res[nom_ref]
    print("\nREFERENCIA: {}, diferencia observada {:+.3f}, ee con 200 pares {:.3f}".format(
        nom_ref, delta_obs, se200))
    print("  medio ancho del IC95 de la DIFERENCIA con 200 pares: +/-{:.3f}".format(
        1.96 * se200))

    efectos = sorted(set(EFECTOS) | {round(delta_obs, 3)})
    print("\nPOTENCIA de H1 = P(IC95 de la diferencia entero sobre 0)")
    print("  (aprox. normal; ee escalado por raiz(200/n); misma mezcla de estratos)")
    print("\n  {:>10} ".format("efecto") + " ".join("{:>7}".format("n=" + str(n))
                                                  for n in TAMANOS))
    for e in efectos:
        fila = []
        for n in TAMANOS:
            se = se200 * np.sqrt(len(y) / n)
            fila.append("{:>6.0%}".format(norm.cdf(e / se - 1.96)))
        marca = "  <- observado (NLI congelado)" if abs(e - delta_obs) < 1e-9 else ""
        print("  {:>+10.3f} ".format(e) + "  ".join(fila) + marca)

    print("\n  n necesario para 80% de potencia:")
    for e in efectos:
        n80 = len(y) * (se200 * (1.96 + 0.8416) / e) ** 2
        print("    efecto {:+.3f}  ->  ~{:,.0f} pares".format(e, n80))


if __name__ == "__main__":
    main()
