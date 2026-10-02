"""Inventario para revertir la Enmienda 5 de D-036 con la rubrica v6 (D-041). SOLO LEE.

No toca ninguna etiqueta: cuenta lo que el plan cambiaria, para registrarlo antes.

La regla v6 en lo que toca al grado es MECANICA: un par cuyos dos titulos llevan numero de grado
y ese numero difiere es `no` (`capa0.compatibles` es False). Lo demas no lo decide esta regla.

Por conjunto:
  1. pares con numero distinto, y su etiqueta de hoy (los `si` son los que cambiarian a `no`);
  2. de las correcciones de la Enmienda 5 (`no` -> `si`), cuantas eran numero distinto (vuelven a
     `no`) y cuantas eran letra o numero en un solo titulo (se quedan `si`);
  3. la exclusion por la capa 0, vuelta a calcular con la capa 0 v1 (letras fuera, numeros
     dentro): par fuera si los dos titulos dan el mismo atomo.

SALIDAS: salidas/39_inventario_grado_v6.txt, salidas/39_pares_numero_distinto.csv
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto import capa0  # noqa: E402


def leer(p, **kw):
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                       keep_default_na=False, **kw)


def main():
    out = []

    def p(s=""):
        print(s, flush=True)
        out.append(s)

    b = np.load(RAIZ / "demo" / "base_v15.npz", allow_pickle=True)
    c0 = capa0.nueva("v1").preparar([str(c) for c in b["celdas"]])

    # --- los conjuntos, con la etiqueta vigente y la de antes de la Enmienda 5 ----------
    e13 = leer(SAL / "13e_para_juzgar.csv")
    part = leer(SAL / "13e_pares_400.csv")[["n", "particion"]]
    e13 = e13.drop(columns="lote").merge(part, on="n", validate="one_to_one")
    e13["lote"] = e13["particion"]
    e20 = leer(SAL / "20_para_juzgar.csv")
    p2 = leer(SAL / "29_prueba2_para_juzgar.csv")
    pl = pd.read_csv(SAL / "21_paquete" / "plata.csv", dtype=str, keep_default_na=False)
    pl["mismo"] = np.where(pl["etiqueta"] == "1.0", "si",
                           np.where(pl["etiqueta"] == "0.0", "no", "?"))
    cg = set(pd.read_csv(SAL / "23_correcciones_plata.csv", dtype=str)["n"])
    rev = leer(SAL / "23_revisar_grado.csv")
    rev12 = set(rev.loc[rev["conjunto"] == "16", "n"])

    conjuntos = [
        ("calibra (13e)", e13[e13["lote"] == "calibra"], "mismo_v3"),
        ("prueba (13e)", e13[e13["lote"] == "prueba"], "mismo_v3"),
        ("prueba (20)", e20, "mismo_v3"),
        ("prueba 2 (29)", p2, None),
        ("plata entrena", pl[pl["particion"] == "entrena"], None),
        ("plata valida", pl[pl["particion"] == "valida"], None),
    ]
    filas = []
    p("=" * 78)
    p("39 · INVENTARIO PARA REVERTIR LA ENMIENDA 5 CON LA RUBRICA v6 (solo lectura)")
    p("=" * 78)
    p("\n1-2. NUMERO DE GRADO DISTINTO (en los dos titulos, valor distinto) -> `no` en la v6")
    p("{:<16} {:>6} {:>9} {:>6} {:>6}   {}".format(
        "conjunto", "pares", "num.dist", "hoy si", "hoy no", "correcciones Enmienda 5"))
    for nom, d, col_v3 in conjuntos:
        d = d.copy()
        d["mismo"] = d["mismo"].str.strip().str.lower()
        d["dist"] = [not capa0.compatibles(a, r) for a, r in zip(d["comun"], d["raro"])]
        if col_v3:
            corr = (d[col_v3].str.strip().str.lower() == "no") & (d["mismo"] == "si") & \
                   d[col_v3].ne("")
            # solo las del grado: en 13e hay tambien las de la v4/v5 por otros motivos
            corr &= d["n"].isin(set(_ns_grado(nom)))
        elif nom.startswith("plata"):
            corr = d["n"].isin(cg | rev12)
        else:
            corr = pd.Series(False, index=d.index)
        dd = d[d["dist"]]
        txt = ""
        if corr.any():
            txt = "{} -> {} vuelven a `no`, {} se quedan `si`".format(
                int(corr.sum()), int((corr & d["dist"]).sum()), int((corr & ~d["dist"]).sum()))
        p("{:<16} {:>6} {:>9} {:>6} {:>6}   {}".format(
            nom, len(d), len(dd), int((dd["mismo"] == "si").sum()),
            int((dd["mismo"] == "no").sum()), txt))
        for _, f in dd.iterrows():
            filas.append({"conjunto": nom, "n": f["n"], "comun": f["comun"], "raro": f["raro"],
                          "mismo_hoy": f["mismo"],
                          "origen": f.get("origen", ""),
                          "correccion_enmienda5": bool(corr.loc[_]),
                          "grado_comun": sorted(capa0.grado_numerico(f["comun"])),
                          "grado_raro": sorted(capa0.grado_numerico(f["raro"]))})
    pd.DataFrame(filas).to_csv(SAL / "39_pares_numero_distinto.csv", index=False,
                               encoding="utf-8")

    # --- 3. la exclusion por la capa 0 -----------------------------------------------
    p("\n3. EXCLUSION POR LA CAPA 0 (mismo atomo de la capa 0 v1: letras fuera, numeros dentro)")
    fu = pd.read_csv(SAL / "23_fuera_por_capa0.csv", dtype=str)
    pr2 = leer(SAL / "29_prueba2_pares.csv")
    evals = [("13e", "calibra", e13[e13["lote"] == "calibra"]),
             ("13e", "prueba", e13[e13["lote"] == "prueba"]),
             ("20", "prueba", e20), ("29", "prueba2", p2)]
    p("{:<16} {:>6} {:>12} {:>12} {:>10} {:>10}".format(
        "conjunto", "pares", "fuera antes", "fuera v1", "vuelven", "salen"))
    for cj, part, d in evals:
        antes = set(fu.loc[(fu["conjunto"] == cj) & (fu["particion"] == part), "n"])
        mismo = {f["n"] for _, f in d.iterrows()
                 if c0.atomo(f["comun"]) == c0.atomo(f["raro"])}
        p("{:<16} {:>6} {:>12} {:>12} {:>10} {:>10}".format(
            "{} {}".format(cj, part), len(d), len(antes), len(mismo),
            len(antes - mismo), len(mismo - antes)))
        if mismo:
            et = d.set_index("n").loc[sorted(mismo), "mismo"].str.strip().str.lower()
            p("   los que quedan fuera con la v1: {} `si`, {} `no`; ejemplos: {}".format(
                int((et == "si").sum()), int((et == "no").sum()),
                "; ".join("{} / {}".format(*d.set_index("n").loc[k, ["comun", "raro"]])
                          for k in sorted(mismo)[:3])))
    (SAL / "39_inventario_grado_v6.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


def _ns_grado(nom):
    """Los `n` que la Enmienda 5 corrigio por el grado en cada conjunto humano (D-036)."""
    return {"calibra (13e)": ["104", "188", "350", "396"],
            "prueba (13e)": ["111", "290"],
            "prueba (20)": ["46", "53", "56", "61", "88", "113", "185", "217", "314", "237"],
            }.get(nom, [])


if __name__ == "__main__":
    main()
