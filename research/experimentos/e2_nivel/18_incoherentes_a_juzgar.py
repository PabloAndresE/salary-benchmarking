"""Los pares de la plata en que Gemini se contradijo entre ordenes, para juzgarlos a mano.

Enmienda 1 de D-036, punto 2. De los 10.000 pares de `16`, Gemini contesto `si` en un
orden y `no` en el otro en 139 (1,39%). Probablemente son la frontera, y por eso no se
tiran: entran al entrenamiento con etiqueta blanda 0,5 hasta que se juzguen, y juzgados
pasan a etiqueta dura.

SIRVEN PARA ENTRENAR, NO PARA EVALUAR. Estan elegidos por ser dificiles para Gemini, asi
que son una muestra sesgada: un modelo que acierte aqui no dice nada de H1. El oro de
evaluacion sigue siendo `13e`.

LO QUE VE QUIEN JUZGA, igual que en `13e`: los dos titulos y el respaldo (empresas de
cada lado, para reconocer una errata). NO se muestran `sim`, la respuesta de Gemini, su
razon, el estrato ni la particion: cualquiera de esos anclaria el juicio.

El orden se baraja con semilla fija, para que el cansancio no caiga sobre un tramo.

SALIDAS (en .gitignore: llevan titulos de clientes)

    18_para_juzgar.csv   lo que se rellena: n, comun, raro, emp_comun, emp_raro, mismo, nota
    18_meta.csv          n -> par de `16`, con lo que dijo Gemini en cada orden. NO se
                         abre antes de juzgar

No se regenera si `18_para_juzgar.csv` ya tiene juicios.
"""
import pathlib
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
SAL = pathlib.Path(__file__).resolve().parent / "salidas"
PARES = SAL / "16_pares_10000.csv"
RESPUESTAS = SAL / "16_respuestas_llm.csv"
JUZGAR = SAL / "18_para_juzgar.csv"
META = SAL / "18_meta.csv"
SEM = 20260925


def main():
    if JUZGAR.exists():
        p = pd.read_csv(JUZGAR, sep=";", encoding="utf-8-sig", dtype=str,
                        keep_default_na=False)
        if (p["mismo"].str.strip() != "").any():
            raise SystemExit("{} ya tiene juicios; no se sobrescribe.".format(JUZGAR))

    r = pd.read_csv(RESPUESTAS, dtype=str, keep_default_na=False)
    r = r[(r["error"] == "") & r["mismo"].isin(["si", "no"])]
    ancho = r.pivot_table(index="n", columns="orden", values="mismo", aggfunc="first")
    ancho = ancho.dropna()
    inc = ancho[ancho["ab"] != ancho["ba"]].reset_index()
    inc["n"] = inc["n"].astype(int)
    print("pares con los dos ordenes: {:,}".format(len(ancho)))
    print("incoherentes:              {:,} ({:.2%})".format(len(inc), len(inc) / len(ancho)))

    pares = pd.read_csv(PARES, sep=";", encoding="utf-8-sig")
    m = inc.merge(pares, on="n", how="left", validate="one_to_one")
    if m["comun"].isna().any():
        raise SystemExit("hay incoherentes sin par en {}".format(PARES.name))

    m = m.sample(frac=1.0, random_state=SEM).reset_index(drop=True)
    m.insert(0, "id", range(1, len(m) + 1))

    meta = m[["id", "n", "g_comun", "g_raro", "sim", "estrato", "particion", "dificil",
              "ab", "ba"]].rename(columns={"n": "n_16", "ab": "gemini_ab", "ba": "gemini_ba"})
    j = m[["id", "comun", "raro", "emp_comun", "emp_raro"]].rename(columns={"id": "n"})
    j["mismo"] = ""
    j["nota"] = ""

    meta.to_csv(META, index=False, encoding="utf-8-sig", sep=";")
    j.to_csv(JUZGAR, index=False, encoding="utf-8-sig", sep=";")

    print("\n  por estrato  :", dict(m["estrato"].value_counts().sort_index()))
    print("  por particion:", dict(m["particion"].value_counts()))
    print("\n  para juzgar -> {}".format(JUZGAR))
    print("  metadatos   -> {}   (NO abrir antes de juzgar)".format(META))
    print("\n  rellena `mismo` con si o no (rubrica v3); si dudas, elige y pon `duda` en `nota`. Sin sim ni la")
    print("  respuesta de Gemini, a proposito.")


if __name__ == "__main__":
    main()
