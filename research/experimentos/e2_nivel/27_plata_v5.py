"""La plata con la rubrica v5: los pares que la v5 podria cambiar, a juicio humano. D-038.

LA PLATA LA ETIQUETO GEMINI CON LA v3. La v5 cambia dos cosas que pueden tocarla:
    - paso 4: una funcion anadida NUNCA separa (la v3 separaba si era "otro oficio");
    - paso 3: `NACIONAL` y `LOCAL` no son ambito; `INTERNACIONAL`, `LATAM`, `GLOBAL` si.

NO SE CORRIGE POR REGLA. Se probo: "un titulo contiene al otro" no distingue una funcion
anadida de un modificador que cambia el sentido (`COORDINADOR DE VENTA` / `… POST VENTA`,
`… RIESGOS FINANCIEROS` / `… NO FINANCIEROS`, `SUPERVISOR` / `ASST SUPERVISOR`), y
`TRANSPORTE INTERNACIONAL` es una funcion, no un ambito. Asi que la regla solo PROPONE: los
pares de esos tipos cuya etiqueta actual no es la que la v5 daria mecanicamente van a juicio
humano, a ciegas (sin la etiqueta actual).

QUE PARES: misma palabra de puesto; sin escalon ni seniority distintos; y la diferencia es
    - solo palabras anadidas (un titulo contiene al otro), sin palabras de rango, seniority
      ni ambito entre ellas -> la v5 diria `si`;
    - solo `NACIONAL` / `LOCAL` -> `si`;
    - solo un ambito que separa, anadido -> `no`.
De los 1.862 pares de la plata de estos tipos, 60 tienen otra etiqueta (el resto ya cumple).

INCLUYE los 139 juzgados a mano (18): sus juicios se hicieron con la v3.

USO
    python 27_plata_v5.py armar     `27_revisar_v5.csv`, a ciegas
    (juzgar con la rubrica v5: `mismo` = si / no; `duda` en `nota`)
    python 27_plata_v5.py aplicar   `27_correcciones_v5.csv`, que `21` aplica al final

`21` las aplica DESPUES de las del grado y de los 139: la v5 es el criterio mas reciente.
"""
import argparse
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.nivel import (CONECTORES, RANGOS, SENIORIDAD,  # noqa: E402
                                         nivel_lexico, quitar_grado, seniority_lexica)

PLATA = SAL / "21_paquete" / "plata.csv"
REVISAR = SAL / "27_revisar_v5.csv"
MAPA = SAL / "27_revisar_v5_mapa.csv"
CORR = SAL / "27_correcciones_v5.csv"
SEM = 20260930

AMBITO_SEPARA = {"REGIONAL", "ZONAL", "INTERNACIONAL", "LATAM", "GLOBAL"}
AMBITO_NO = {"NACIONAL", "LOCAL"}
RANGO = set(RANGOS) | {"JEFE", "GERENTE", "DIRECTOR", "SUPERVISOR", "COORDINADOR",
                       "SUBGERENTE", "SUBJEFE", "ENCARGADO", "ASESOR", "EJECUTIVO",
                       "ADMINISTRADOR", "CONTROLLER", "CONSULTOR", "ESPECIALISTA", "TECNICO",
                       "ANALISTA", "ASISTENTE", "AUXILIAR", "AYUDANTE", "OPERARIO",
                       "OPERADOR", "PASANTE", "PRACTICANTE", "OBRERO", "PRESIDENTE",
                       "VICEPRESIDENTE", "SECRETARIA", "SECRETARIO"}
SENIOR = set(SENIORIDAD) | {"SR", "JR", "SENIOR", "JUNIOR", "TRAINEE", "SOUS",
                            "CORPORATIVO", "CORPORATIVA", "ESPECIALIZADO"}


def palabras(t):
    return [w for w in quitar_grado(t) if w not in CONECTORES]


def v5_diria(a, b):
    """(tipo, etiqueta que la v5 daria) si el par es de un tipo que la v5 toca; si no, None."""
    pa, pb = palabras(a), palabras(b)
    if not pa or not pb or pa[0] != pb[0]:
        return None
    sa, sb = set(pa), set(pb)
    na, nb = nivel_lexico(a), nivel_lexico(b)
    if na is not None and nb is not None and na == na and nb == nb and na != nb:
        return None
    if seniority_lexica(a) != seniority_lexica(b):
        return None
    extra = sa ^ sb
    if not extra:
        return None
    if extra & AMBITO_SEPARA:
        return ("ambito que separa", 0.0) if (sa < sb or sb < sa) and extra <= AMBITO_SEPARA \
            else None
    if extra <= AMBITO_NO:
        return ("NACIONAL / LOCAL", 1.0)
    if extra & (RANGO | SENIOR | AMBITO_NO):
        return None
    if sa < sb or sb < sa:
        return ("funcion anadida o acotada", 1.0)
    return None


def armar():
    if REVISAR.exists():
        raise SystemExit("{} ya existe; no se rehace (podria tener juicios).".format(REVISAR.name))
    p = pd.read_csv(PLATA, dtype=str, keep_default_na=False)
    filas = []
    for _, f in p.iterrows():
        r = v5_diria(f["comun"], f["raro"])
        if r and float(f["etiqueta"]) != r[1]:
            filas.append({"n": f["n"], "tipo": r[0], "comun": f["comun"], "raro": f["raro"],
                          "particion": f["particion"], "origen": f["origen"],
                          "etiqueta_actual": f["etiqueta"]})
    d = pd.DataFrame(filas).sample(frac=1.0, random_state=SEM).reset_index(drop=True)
    d.insert(0, "n_ciego", range(1, len(d) + 1))
    d[["n_ciego", "n", "tipo", "particion", "origen", "etiqueta_actual"]].to_csv(
        MAPA, index=False, encoding="utf-8")
    j = d[["n_ciego", "comun", "raro"]].copy()
    j["mismo"] = ""
    j["nota"] = ""
    j.to_csv(REVISAR, index=False, sep=";", encoding="utf-8-sig")
    print("{} pares -> {}  por tipo {}  (mapa: {}, NO abrir antes de juzgar)".format(
        len(j), REVISAR.name, d["tipo"].value_counts().to_dict(), MAPA.name))


def aplicar():
    j = pd.read_csv(REVISAR, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                    keep_default_na=False)
    j["mismo"] = j["mismo"].str.strip().str.lower()
    malos = j.loc[~j["mismo"].isin(["si", "no"]), "n_ciego"].tolist()
    if malos:
        raise SystemExit("ALTO: `mismo` tiene que ser si / no en todos; faltan: {}".format(
            malos[:20]))
    d = j.merge(pd.read_csv(MAPA, dtype=str), on="n_ciego", validate="one_to_one")
    d["etiqueta"] = np.where(d["mismo"] == "si", 1.0, 0.0)
    d["motivo"] = np.where(d["mismo"] == "si", "ninguno",
                           np.where(d["tipo"].str.startswith("ambito"), "p3", "p4"))
    d = d[d["etiqueta"] != d["etiqueta_actual"].astype(float)]
    d[["n", "particion", "tipo", "etiqueta_actual", "etiqueta", "motivo", "nota"]].to_csv(
        CORR, index=False, encoding="utf-8")
    print("juzgados {}; cambian {} -> {}".format(len(j), len(d), CORR.name))
    print("  por tipo:", d["tipo"].value_counts().to_dict())
    print("Siguiente: `21` (paquete).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["armar", "aplicar"])
    a = ap.parse_args()
    armar() if a.accion == "armar" else aplicar()
