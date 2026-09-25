"""400 pares nuevos para `prueba`, que pasa de 200 a 600. Enmienda 2 de D-036.

POR QUE. `19` midio que con 200 pares el IC95 de la diferencia de AUC mide +/-0,099. Si B
le gana al coseno lo que ya le gana el NLI sin entrenar (+0,061), H1 tiene un 23% de
potencia: una moneda al aire aunque B sea mejor. Con 600 pares se detecta +0,08 con ~80%.
`prueba` solo se puede ampliar ANTES de abrirla.

EL MISMO MARCO QUE `13e`. Pares entre grupos distintos de `base_v15` con coseno 0,90-1,01,
tomados del censo que ya calculo `16` (`16_censo.parquet`), con los mismos estratos y los
cuatro tramos de la banda.

LO QUE SE EXCLUYE, y por que:

1. CUALQUIER PAR QUE TOQUE UN GRUPO DE LA PLATA (`16_pares_10000.csv`; los 139
   incoherentes estan dentro). B se entrena con esos cargos; si aparecieran en `prueba`,
   acertarlos no mediria generalizacion. Por grupo y no por texto, como en `16`.
2. LOS PARES YA JUZGADOS: los 400 de `13e` y los 48 de `13a`. Por par de grupos. Los
   GRUPOS de `13e` si pueden reaparecer, en pares nuevos: es la misma regla con que `13e`
   partio `calibra` y `prueba`, por par.

EL ESTRATO ALTO ESTA AGOTADO. De 126 pares con coseno >= 0,97 en todo el censo, tras las
exclusiones quedan 6. Se toman los 6 y lo que falta pasa a la banda, repartido entre sus
cuatro tramos. Es la regla de `16` ("lo que un tramo no llena pasa al otro"), y la banda es
ademas la zona donde hace falta juicio. Consecuencia, declarada en la Enmienda 2: los 600
tienen menos alto que `13e` (36 de 600 frente a 30 de 200), y por eso se reporta el AUC por
estrato y por separado en los 200 originales y en los 400 nuevos.

TODO VA A `prueba`. Quien juzga no lo sabe: el CSV para juzgar no lleva ni `sim`, ni
estrato, ni particion. Se juzga a ciegas con la rubrica v3 congelada, en lotes de 50.
Cronometra el primer lote para confirmar el ritmo supuesto de 20-30 s por par.

SALIDAS (en .gitignore: llevan titulos de clientes)

    20_pares_400.csv     metadatos: grupos, sim, estrato, tramo. NO se abre antes de juzgar
    20_para_juzgar.csv   lo que se rellena: n, lote, comun, raro, emp_comun, emp_raro, mismo, nota

No se regenera si `20_para_juzgar.csv` ya tiene juicios.
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = pathlib.Path(__file__).resolve().parents[3]
BASE = RAIZ / "demo" / "base_v15.npz"
SAL = pathlib.Path(__file__).resolve().parent / "salidas"
CENSO = SAL / "16_censo.parquet"
PLATA = SAL / "16_pares_10000.csv"
ORO_400 = SAL / "13e_pares_400.csv"
ORO_48 = SAL / "13_para_juzgar.csv"
META = SAL / "20_pares_400.csv"
JUZGAR = SAL / "20_para_juzgar.csv"
SEM = 20260926
POR_LOTE = 50
TOTAL = 400
# los mismos cortes y cupos que `13e` usa para 400; el alto se llena con lo que haya
CUPO = {"bajo": 60, "banda": 280, "alto": 60}
TRAMOS_BANDA = np.linspace(0.93, 0.97, 5)


def pares_48(ix, g):
    v = pd.read_csv(ORO_48, sep=None, engine="python", encoding="utf-8-sig")
    v.columns = [c.strip() for c in v.columns]
    fuera = set()
    for x, y in zip(v["comun"], v["raro"]):
        if str(x) in ix and str(y) in ix:
            fuera.add(frozenset((int(g[ix[str(x)]]), int(g[ix[str(y)]]))))
    return fuera


def main():
    if JUZGAR.exists():
        p = pd.read_csv(JUZGAR, sep=";", encoding="utf-8-sig", dtype=str,
                        keep_default_na=False)
        if (p["mismo"].str.strip() != "").any():
            raise SystemExit("{} ya tiene juicios; no se sobrescribe.".format(JUZGAR))

    d = np.load(BASE, allow_pickle=True)
    cel = [str(c) for c in d["celdas"]]
    g = d["grupo"].astype(np.int64)
    ix = {c: i for i, c in enumerate(cel)}

    c = pd.read_parquet(CENSO)
    plata = pd.read_csv(PLATA, sep=";", encoding="utf-8-sig")
    oro = pd.read_csv(ORO_400, sep=";", encoding="utf-8-sig")
    print("censo de `16`: {:,} pares".format(len(c)))

    g_plata = set(plata["g_comun"]) | set(plata["g_raro"])
    c = c[~c["g_comun"].isin(g_plata) & ~c["g_raro"].isin(g_plata)]
    print("  sin grupos de la plata: {:,}".format(len(c)))

    ya = {frozenset(x) for x in zip(oro["g_comun"], oro["g_raro"])} | pares_48(ix, g)
    c = c[[frozenset(x) not in ya for x in zip(c["g_comun"], c["g_raro"])]].copy()
    print("  sin pares ya juzgados (13e + 13a): {:,}".format(len(c)))

    c["estrato"] = pd.cut(c["sim"], [0.90, 0.93, 0.97, 1.01],
                          labels=["bajo", "banda", "alto"], include_lowest=True)
    disp = c["estrato"].value_counts().to_dict()
    print("  disponibles por estrato:", {k: disp.get(k, 0) for k in CUPO})

    alto = c[c["estrato"] == "alto"]
    n_alto = min(len(alto), CUPO["alto"])
    sobra = CUPO["alto"] - n_alto
    n_banda = CUPO["banda"] + sobra
    print("\n  alto: {} de {} pedidos; los {} que faltan pasan a la banda ({})".format(
        n_alto, CUPO["alto"], sobra, n_banda))

    trozos = [alto.sample(n_alto, random_state=SEM).assign(tramo="")]
    bajo = c[c["estrato"] == "bajo"]
    trozos.append(bajo.sample(CUPO["bajo"], random_state=SEM).assign(tramo=""))

    banda = c[c["estrato"] == "banda"].copy()
    banda["tramo"] = pd.cut(banda["sim"], TRAMOS_BANDA, include_lowest=True).astype(str)
    por, resto = divmod(n_banda, len(TRAMOS_BANDA) - 1)
    grupos = list(banda.groupby("tramo", observed=True))
    for k, (_, gr) in enumerate(grupos):
        quiero = por + (1 if k < resto else 0)
        if len(gr) < quiero:
            raise SystemExit("tramo {} con {} pares, faltan para {}".format(
                gr["tramo"].iloc[0], len(gr), quiero))
        trozos.append(gr.sample(quiero, random_state=SEM))

    m = pd.concat(trozos, ignore_index=True)
    assert len(m) == TOTAL, len(m)
    assert m[["g_comun", "g_raro"]].apply(frozenset, axis=1).nunique() == TOTAL
    m["particion"] = "prueba"
    m["origen"] = "20"

    m = m.sample(frac=1.0, random_state=SEM + 1).reset_index(drop=True)
    m.insert(0, "n", range(1, len(m) + 1))
    m["lote"] = (m["n"] - 1) // POR_LOTE + 1

    m.to_csv(META, index=False, encoding="utf-8-sig", sep=";")
    j = m[["n", "lote", "comun", "raro", "emp_comun", "emp_raro"]].copy()
    j["mismo"] = ""
    j["nota"] = ""
    j.to_csv(JUZGAR, index=False, encoding="utf-8-sig", sep=";")

    print("\n  muestra: {} pares".format(len(m)))
    print("  por estrato:", dict(m["estrato"].value_counts().sort_index()))
    print("  banda por tramo:", dict(m.loc[m["estrato"] == "banda", "tramo"]
                                     .value_counts().sort_index()))
    print("  lotes de {}: {}".format(POR_LOTE, m["lote"].max()))
    print("\n  para juzgar -> {}".format(JUZGAR.name))
    print("  metadatos   -> {}   (NO abrir antes de juzgar)".format(META.name))


if __name__ == "__main__":
    main()
