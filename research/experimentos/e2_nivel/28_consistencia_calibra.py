"""`calibra` contra los pasos 2 y 3 de la rubrica v5: los `si` que la regla dice `no`. D-038.

POR QUE. Al rejuzgar `calibra` (26) algunos pares pasaron a `si` aunque sus palabras de
rango estan en niveles distintos (paso 2) o llevan marcas de seniority o ambito distintas
(paso 3), pasos que la v5 no cambio. El autor lo atribuye a descuido.

SIN MIRAR EL MODELO. La lista sale de aplicar la rubrica, mecanicamente, a TODOS los pares
de `calibra` con `si`: no de los errores del cross-encoder. Asi la revision no empuja las
etiquetas hacia el modelo. El autor confirma o corrige cada par; la regla solo avisa.

LA REGLA, tal como esta escrita en la rubrica (no el lexico de `producto/nivel.py`, que va
detras: no tiene `ASESOR`, `EJECUTIVO`, `ENCARGADO`...):
    paso 2  nivel de la palabra de rango MAS ALTA; lo que va tras `DE`/`DEL` no cuenta;
            `TECNICO` y `ESPECIALISTA` solo son rango si abren el titulo
    paso 3  marcas: TRAINEE, JR, JUNIOR, SOUS / SR, SENIOR, ESPECIALISTA-ESPECIALIZADO tras
            otra palabra, CORPORATIVO (salvo nombre de area) / ambito REGIONAL, ZONAL,
            INTERNACIONAL, LATAM, GLOBAL

USO
    python 28_consistencia_calibra.py armar     `28_revisar_consistencia.csv`
    (poner en `mismo_nuevo` si / no; vacio = se queda como esta)
    python 28_consistencia_calibra.py aplicar   pasa lo marcado a `13e_para_juzgar.csv`

    con `--conjunto prueba2` hace lo mismo sobre `prueba 2` (`29_prueba2_para_juzgar.csv`,
    el prerregistro de D-038 lo pide antes de congelarla): la lista va a
    `28_revisar_consistencia_prueba2.csv` y la etiqueta de antes queda en `mismo_original`.
"""
import argparse
import csv
import pathlib
import re
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
CALIBRA = SAL / "21_paquete" / "calibra.csv"
ORO = SAL / "13e_para_juzgar.csv"
REVISAR = SAL / "28_revisar_consistencia.csv"
NOTA = "consistencia pasos 2-3 (D-038)"

NIVEL = {}
for n, ws in {1: "PASANTE PRACTICANTE AYUDANTE AUXILIAR OPERARIO OPERADOR OBRERO ASISTENTE "
                 "ASESOR EJECUTIVO",
              2: "TECNICO ANALISTA ADMINISTRADOR CONTROLLER CONSULTOR",
              3: "SUPERVISOR COORDINADOR ESPECIALISTA ENCARGADO SUBJEFE",
              4: "JEFE SUBGERENTE",
              5: "GERENTE DIRECTOR VICEPRESIDENTE PRESIDENTE"}.items():
    for w in ws.split():
        NIVEL[w] = n
MENOS = {"TRAINEE", "JR", "JUNIOR", "SOUS"}
MAS = {"SR", "SENIOR"}
AMBITO = {"REGIONAL", "ZONAL", "INTERNACIONAL", "LATAM", "GLOBAL"}
AREA_CORP = {"BANCA", "PROCESOS", "VENTAS", "CLIENTES", "COMUNICACION", "IMAGEN", "NEGOCIOS",
             "CUENTAS", "SEGUROS", "FINANZAS", "RELACIONES", "ASUNTOS"}


def toks(t):
    return re.findall(r"[A-ZÑ]+", str(t).upper().replace(".", " "))


def raiz(w):
    """`COORDINADORA`, `ASISTENTES`, `JEFA` -> la palabra de la tabla."""
    for c in (w, w[:-1], w[:-2], w.replace("JEFA", "JEFE")):
        if c in NIVEL:
            return c
    if w.endswith("A") and w[:-1] + "O" in NIVEL:
        return w[:-1] + "O"
    return None


def nivel(t):
    ws = toks(t)
    alto = None
    for i, w in enumerate(ws):
        if w in ("DE", "DEL"):
            break                                  # lo de detras de DE dice a quien apoya
        r = raiz(w)
        if r is None or (r in ("TECNICO", "ESPECIALISTA") and i > 0):
            continue
        alto = max(alto or 0, NIVEL[r])
    return alto


def marcas(t):
    ws = toks(t)
    m = set()
    for i, w in enumerate(ws):
        if w in MENOS:
            m.add("-" + w.replace("JUNIOR", "JR"))
        elif w in MAS:
            m.add("+SR")
        elif w in ("ESPECIALISTA", "ESPECIALIZADO") and i > 0:
            m.add("+SR")
        elif w.startswith("CORPORATIV") and not (i > 0 and ws[i - 1] in AREA_CORP):
            m.add("CORPORATIVO")
        elif w in AMBITO:
            m.add("ambito:" + w)
    return m


def conflicto(a, b):
    na, nb = nivel(a), nivel(b)
    if na and nb and na != nb:
        return "paso 2: nivel {} / {}".format(na, nb)
    ma, mb = marcas(a), marcas(b)
    if ma != mb:
        return "paso 3: {} / {}".format(sorted(ma) or "-", sorted(mb) or "-")
    return None


PRUEBA2 = SAL / "29_prueba2_para_juzgar.csv"
REVISAR_P2 = SAL / "28_revisar_consistencia_prueba2.csv"


def rutas(conjunto):
    return (ORO, REVISAR) if conjunto == "calibra" else (PRUEBA2, REVISAR_P2)


def leer_oro(ruta):
    crudo = ruta.read_bytes()
    sep = csv.Sniffer().sniff(crudo.decode("utf-8-sig").splitlines()[0], ";,").delimiter
    return pd.read_csv(ruta, sep=sep, encoding="utf-8-sig", dtype=str,
                       keep_default_na=False), sep


def armar(conjunto="calibra"):
    oro_ruta, revisar = rutas(conjunto)
    oro, _ = leer_oro(oro_ruta)
    oro["mismo"] = oro["mismo"].str.strip().str.lower()
    if conjunto == "calibra":
        cal = pd.read_csv(CALIBRA, dtype={"n": str}, keep_default_na=False)
        d = cal[["n"]].merge(oro[["n", "comun", "raro", "mismo", "mismo_v4"]], on="n")
    else:
        if not oro["mismo"].isin(["si", "no"]).all():
            raise SystemExit("ALTO: `prueba 2` no esta juzgada entera: {}".format(
                oro.loc[~oro["mismo"].isin(["si", "no"]), "n"].tolist()))
        d = oro[["n", "comun", "raro", "mismo"]].assign(mismo_v4="")
    d = d[d["mismo"] == "si"]
    filas = []
    for _, f in d.iterrows():
        c = conflicto(f["comun"], f["raro"])
        if c:
            filas.append({"n": f["n"], "comun": f["comun"], "raro": f["raro"], "regla": c,
                          "mismo_v5": f["mismo"], "mismo_v4": f["mismo_v4"],
                          "mismo_nuevo": ""})
    r = pd.DataFrame(filas)
    r.to_csv(revisar, index=False, sep=";", encoding="utf-8-sig")
    print("{} pares `si` de {} que la regla dice `no` -> {}".format(len(r), conjunto,
                                                                   revisar.name))
    if conjunto == "calibra":
        print("  de ellos, eran `si` ya antes de rejuzgar (v4):",
              int((r["mismo_v4"] == "si").sum()))


def aplicar(conjunto="calibra"):
    oro_ruta, revisar = rutas(conjunto)
    r = pd.read_csv(revisar, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                    keep_default_na=False)
    r["mismo_nuevo"] = r["mismo_nuevo"].str.strip().str.lower()
    if not r["mismo_nuevo"].isin(["", "si", "no"]).all():
        raise SystemExit("ALTO: `mismo_nuevo` solo admite si / no / vacio")
    cambia = r[r["mismo_nuevo"].isin(["si", "no"]) & (r["mismo_nuevo"] != r["mismo_v5"])]
    oro, sep = leer_oro(oro_ruta)
    if conjunto == "prueba2" and "mismo_original" not in oro:
        oro.insert(oro.columns.get_loc("mismo") + 1, "mismo_original", oro["mismo"])
    for _, f in cambia.iterrows():
        k = oro["n"] == f["n"]
        oro.loc[k, "mismo"] = f["mismo_nuevo"]
        oro.loc[k, "nota"] = [(x + "; " if x.strip() else "") + NOTA for x in oro.loc[k, "nota"]]
    oro.to_csv(oro_ruta, index=False, sep=sep, encoding="utf-8-sig", lineterminator="\n")
    print("revisados {}; cambian {} ({})".format(
        int((r["mismo_nuevo"] != "").sum()), len(cambia),
        cambia["mismo_nuevo"].value_counts().to_dict()))
    print("Siguiente: `21`, `19` y el AUC_BASE de `22`.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["armar", "aplicar"])
    ap.add_argument("--conjunto", default="calibra", choices=["calibra", "prueba2"])
    a = ap.parse_args()
    armar(a.conjunto) if a.accion == "armar" else aplicar(a.conjunto)
