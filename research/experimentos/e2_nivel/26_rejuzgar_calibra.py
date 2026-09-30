"""`calibra`, juzgada otra vez a ciegas con la rubrica v5. D-038.

POR QUE. El analisis de errores (`25`) mostro que en el paso 4 el oro no era consistente: en
`calibra`, para el mismo tipo de par (misma palabra de puesto y una funcion anadida), 45 `si`
y 2 `no`. La rubrica v5 fija el criterio (funcion anadida nunca separa, misma area = mismo,
`NACIONAL`/`LOCAL` no son ambito). `calibra` elige la version del cross-encoder y calibra sus
probabilidades: tiene que decir lo mismo que la regla.

POR QUE TODA Y A CIEGAS. Corregir solo los pares donde el modelo fallo empujaria las
etiquetas hacia el modelo e inflaria su AUC: un sesgo de seleccion. Aqui se vuelven a juzgar
LOS 191, en orden aleatorio, sin `sim`, sin la etiqueta anterior y sin ninguna prediccion.
Si una etiqueta cambia, cambia por la regla.

`prueba` NO se toca: ya se abrio para H1 y su resultado queda como esta.

USO
    python 26_rejuzgar_calibra.py armar     escribe el CSV ciego y el mapa
    (juzgar `26_calibra_ciega.csv` con la rubrica v5: `mismo` = si / no; `duda` en `nota`)
    python 26_rejuzgar_calibra.py aplicar   pasa los juicios a `13e_para_juzgar.csv`

SALIDAS (con titulos; se versionan con -f cuando esten juzgadas)
    26_calibra_ciega.csv   n_ciego, comun, raro, emp_comun, emp_raro, mismo, nota
    26_calibra_mapa.csv    n_ciego -> n de `13e`. NO se abre antes de juzgar
"""
import argparse
import csv
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
CALIBRA = SAL / "21_paquete" / "calibra.csv"
ORO = SAL / "13e_para_juzgar.csv"
CIEGA = SAL / "26_calibra_ciega.csv"
MAPA = SAL / "26_calibra_mapa.csv"
SEM = 20260930
NOTA = "rejuzgado v5 (D-038)"


def armar():
    if CIEGA.exists():
        raise SystemExit("{} ya existe; no se rehace (podria tener juicios).".format(CIEGA.name))
    cal = pd.read_csv(CALIBRA, dtype={"n": str}, keep_default_na=False)
    oro = pd.read_csv(ORO, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    d = cal[["n"]].merge(oro[["n", "comun", "raro", "emp_comun", "emp_raro"]], on="n",
                         validate="one_to_one")
    d = d.sample(frac=1.0, random_state=SEM).reset_index(drop=True)
    d.insert(0, "n_ciego", range(1, len(d) + 1))
    d[["n_ciego", "n"]].to_csv(MAPA, index=False, encoding="utf-8")
    j = d[["n_ciego", "comun", "raro", "emp_comun", "emp_raro"]].copy()
    j["mismo"] = ""
    j["nota"] = ""
    j.to_csv(CIEGA, index=False, sep=";", encoding="utf-8-sig")
    print("{} pares -> {}   (mapa: {}, NO abrir antes de juzgar)".format(
        len(j), CIEGA.name, MAPA.name))


def aplicar():
    j = pd.read_csv(CIEGA, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                    keep_default_na=False)
    j["mismo"] = j["mismo"].str.strip().str.lower()
    malos = j.loc[~j["mismo"].isin(["si", "no"]), "n_ciego"].tolist()
    if malos:
        raise SystemExit("ALTO: `mismo` tiene que ser si / no en todos; faltan o sobran: {}"
                         .format(malos[:20]))
    m = pd.read_csv(MAPA, dtype=str)
    j = j.merge(m, on="n_ciego", validate="one_to_one")
    crudo = ORO.read_bytes()
    sep = csv.Sniffer().sniff(crudo.decode("utf-8-sig").splitlines()[0], ";,").delimiter
    oro = pd.read_csv(ORO, sep=sep, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    if "mismo_v4" not in oro:
        oro.insert(oro.columns.get_loc("mismo") + 1, "mismo_v4", oro["mismo"])
    nuevo = dict(zip(j["n"], j["mismo"]))
    nota_j = dict(zip(j["n"], j["nota"]))
    k = oro["n"].isin(nuevo)
    oro.loc[k, "mismo"] = oro.loc[k, "n"].map(nuevo)
    oro["nota"] = oro["nota"].str.replace(r"\s*;?\s*" + NOTA + r".*$", "", regex=True)
    oro.loc[k, "nota"] = [((n + "; ") if n.strip() else "") + NOTA +
                          ((": " + nota_j[i]) if nota_j[i].strip() else "")
                          for n, i in zip(oro.loc[k, "nota"], oro.loc[k, "n"])]
    oro.to_csv(ORO, index=False, sep=sep, encoding="utf-8-sig", lineterminator="\n")
    a = oro.loc[k, "mismo_v4"].str.strip().str.lower()
    b = oro.loc[k, "mismo"]
    print("calibra rejuzgada: {} pares".format(int(k.sum())))
    print("  antes (v4):", a.value_counts().to_dict(), "  ahora (v5):", b.value_counts().to_dict())
    print("  cambian: {}  (no->si {}, si->no {})".format(int((a != b).sum()),
          int(((a == "no") & (b == "si")).sum()), int(((a == "si") & (b == "no")).sum())))
    print("Siguiente: `21` (paquete), `19` (vara de calibra) y el AUC_BASE de `22`.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["armar", "aplicar"])
    a = ap.parse_args()
    armar() if a.accion == "armar" else aplicar()
