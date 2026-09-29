"""El paquete para entrenar el cross en otra maquina, SIN `prueba` y sin sueldos.

El servidor de la universidad tiene el repo clonado, pero no los CSV (van en .gitignore
por titulos de clientes). Copiarle los archivos crudos seria un error por dos motivos:

- `13e_para_juzgar.csv` trae los 400 juicios, INCLUIDOS los 200 de `prueba`. En cuanto
  `prueba` esta en la maquina donde se entrena, H1 deja de estar protegida por diseno y
  pasa a estarlo por disciplina.
- `demo/base_v15.npz` trae sueldos y bandas. Entrenar el cross solo necesita titulos.

Este guion corre AQUI y arma una carpeta con lo minimo, ya unido y listo:

    plata.csv       los 10.000 pares de `16`: titulos, particion entrena/valida, estrato,
                    `dificil` (escalon o seniority distintos: la senal del peso w), lo que
                    dijo Gemini en cada orden y su paso, y la ETIQUETA que se entrena:
                        1 / 0     Gemini coherente en los dos ordenes
                        0,5       Gemini incoherente y aun sin juicio humano (Enmienda 1)
                        1 / 0     incoherente ya juzgado a mano: manda el juicio
                    `motivo`: el paso de Gemini si fue coherente; el de la nota humana si la
                    hay; vacio si no se sabe (la cabeza de motivo lo ignora).
    calibra.csv     los 200 pares de `calibra` con el juicio humano, `sim` y estrato. Es lo
                    unico del oro que viaja: sirve para elegir y calibrar.
    manifiesto.json conteos, hashes de lo que se leyo, rubrica, plantilla y la comprobacion
                    de que no va ningun par de `prueba`.

COMPROBACION DURA. Se juntan todos los pares de `prueba` (los 200 de `13e` y los 400 de
`20`) por par de grupos y por par de titulos, y si alguno aparece en el paquete, el guion
se detiene sin escribir nada.

Se puede volver a correr cuando avances con los 139: los juzgados pasan de 0,5 a 1/0.

SALIDA: salidas/21_paquete/ (en .gitignore). Se copia al servidor con scp.
"""
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
PARES = SAL / "16_pares_10000.csv"
RESP = SAL / "16_respuestas_llm.csv"
INC_JUZ = SAL / "18_para_juzgar.csv"
INC_META = SAL / "18_meta.csv"
ORO_META = SAL / "13e_pares_400.csv"
ORO_JUZ = SAL / "13e_para_juzgar.csv"
NUEVOS_META = SAL / "20_pares_400.csv"
CORR_GRADO = SAL / "23_correcciones_plata.csv"   # Enmienda 5: el grado ya no separa
FUERA = SAL / "23_fuera_por_capa0.csv"           # Enmienda 5: los fusiona la capa 0
RUBRICA = AQUI / "rubrica_mismo_cargo.md"
DESTINO = SAL / "21_paquete"
PLANTILLA = "El puesto de trabajo es {}."        # con el titulo en .title(); Enmienda 2


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def leer(p, **kw):
    # Separador detectado: Excel guarda con `,` o `;` segun la configuracion regional, y
    # un juicio a mano vuelve con el que tenga la maquina de quien juzga.
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig", **kw)


def paso_de_nota(nota):
    m = re.search(r"\bp([1-5])\b", str(nota).lower())
    return "p" + m.group(1) if m else ""


def main():
    # --- plata: una fila por par, con lo que dijo Gemini en cada orden ------------------
    pares = leer(PARES)
    r = pd.read_csv(RESP, dtype=str, keep_default_na=False)
    r = r[(r["error"] == "") & r["mismo"].isin(["si", "no"])]
    ancho = r.pivot_table(index="n", columns="orden", values=["mismo", "paso"],
                          aggfunc="first")
    ancho.columns = ["{}_{}".format(a, b) for a, b in ancho.columns]
    ancho = ancho.reset_index()
    ancho["n"] = ancho["n"].astype(int)
    p = pares.merge(ancho, on="n", how="inner", validate="one_to_one")
    faltan = len(pares) - len(p)

    coherente = p["mismo_ab"] == p["mismo_ba"]
    p["etiqueta"] = (p["mismo_ab"] == "si").astype(float)
    p.loc[~coherente, "etiqueta"] = 0.5
    p["origen"] = "gemini"
    p.loc[~coherente, "origen"] = "gemini_incoherente"
    p["motivo"] = ""
    p.loc[coherente, "motivo"] = p.loc[coherente, "paso_ab"].where(
        p.loc[coherente, "mismo_ab"] == "no", "ninguno")

    # --- Enmienda 5: `no` de Gemini que solo difieren en el grado pasan a `si` (`23`) ---
    n_grado = 0
    if CORR_GRADO.exists():
        cg = pd.read_csv(CORR_GRADO)
        k = p["n"].isin(cg["n"]) & coherente
        if int(k.sum()) != len(cg):
            raise SystemExit("ALTO: {} correcciones de grado y {} pares coherentes que las "
                             "reciben. Vuelve a correr `23`.".format(len(cg), int(k.sum())))
        p.loc[k, "etiqueta"] = 1.0
        p.loc[k, "motivo"] = "ninguno"
        p.loc[k, "origen"] = "gemini_grado"
        n_grado = int(k.sum())

    # --- los 139: lo ya juzgado a mano manda -------------------------------------------
    juz = leer(INC_JUZ, dtype=str, keep_default_na=False)
    meta = leer(INC_META)
    juz["n"] = juz["n"].astype(int)
    j = meta[["id", "n_16"]].merge(juz, left_on="id", right_on="n")
    j["mismo"] = j["mismo"].str.strip().str.lower()
    hechos = j[j["mismo"].isin(["si", "no"])]
    for _, f in hechos.iterrows():
        k = p.index[p["n"] == int(f["n_16"])]
        p.loc[k, "etiqueta"] = 1.0 if f["mismo"] == "si" else 0.0
        p.loc[k, "origen"] = "humano_139"
        p.loc[k, "motivo"] = "ninguno" if f["mismo"] == "si" else paso_de_nota(f["nota"])
    n_inc = int((~coherente).sum())

    plata = p[["n", "comun", "raro", "particion", "estrato", "dificil", "sim",
               "mismo_ab", "mismo_ba", "paso_ab", "paso_ba", "etiqueta", "origen",
               "motivo"]]

    # --- calibra: lo unico del oro que viaja -----------------------------------------
    om = leer(ORO_META)
    oj = leer(ORO_JUZ, dtype=str, keep_default_na=False)[["n", "mismo"]]
    oj["n"] = oj["n"].astype(int)
    oro = om.merge(oj, on="n")
    cal = oro[oro["particion"] == "calibra"].copy()
    cal["mismo"] = cal["mismo"].str.strip().str.lower()
    cal = cal[cal["mismo"].isin(["si", "no"])]
    n_fuera_cal = 0
    if FUERA.exists():
        fu = pd.read_csv(FUERA, dtype=str)
        fu = set(fu.loc[(fu["conjunto"] == "13e") & (fu["particion"] == "calibra"), "n"])
        n_fuera_cal = int(cal["n"].astype(str).isin(fu).sum())
        cal = cal[~cal["n"].astype(str).isin(fu)]
    calibra = cal[["n", "comun", "raro", "sim", "estrato", "mismo"]]

    # --- comprobacion dura: nada de `prueba` -----------------------------------------
    pr = [oro.loc[oro["particion"] == "prueba", ["g_comun", "g_raro", "comun", "raro"]],
          leer(NUEVOS_META)[["g_comun", "g_raro", "comun", "raro"]]]
    pr = pd.concat(pr, ignore_index=True)
    pr_g = {frozenset(x) for x in zip(pr["g_comun"], pr["g_raro"])}
    pr_t = {frozenset(x) for x in zip(pr["comun"], pr["raro"])}
    fugas = []
    for nom, t, tiene_g in (("plata", p, True), ("calibra", cal, True)):
        for gc, gr, c, rr in zip(t["g_comun"], t["g_raro"], t["comun"], t["raro"]):
            if frozenset((gc, gr)) in pr_g or frozenset((c, rr)) in pr_t:
                fugas.append(nom)
    if fugas:
        raise SystemExit("ALTO: {} pares del paquete estan en `prueba` ({}). No se escribe "
                         "nada.".format(len(fugas), sorted(set(fugas))))

    # --- escribir ----------------------------------------------------------------------
    DESTINO.mkdir(parents=True, exist_ok=True)
    plata.to_csv(DESTINO / "plata.csv", index=False, encoding="utf-8")
    calibra.to_csv(DESTINO / "calibra.csv", index=False, encoding="utf-8")
    rub = RUBRICA.read_text(encoding="utf-8").split("\n## Historial")[0]
    man = {
        "creado": dt.datetime.now().isoformat(timespec="seconds"),
        "decision": "D-036, enmiendas 1, 2 y 5",
        "modelo_base": "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
        "plantilla": PLANTILLA,
        "plantilla_nota": "el titulo va con str.title(); la misma de 13c y 19",
        "rubrica_v3_sha256_12": hashlib.sha256(rub.encode("utf-8")).hexdigest()[:12],
        "plata": {
            "pares": len(plata),
            "sin_respuesta_en_los_dos_ordenes": faltan,
            "por_particion": plata["particion"].value_counts().to_dict(),
            "incoherentes": n_inc,
            "incoherentes_juzgados_a_mano": int(len(hechos)),
            "incoherentes_con_etiqueta_blanda": n_inc - int(len(hechos)),
            "corregidos_por_grado": n_grado,
            "tasa_si_coherentes": round(float(p.loc[coherente, "etiqueta"].mean()), 4),
            "dificil": int(plata["dificil"].sum()),
        },
        "calibra": {"pares": len(calibra),
                    "si": int((calibra["mismo"] == "si").sum()),
                    "no": int((calibra["mismo"] == "no").sum()),
                    "fuera_por_capa0": n_fuera_cal},
        "prueba_en_el_paquete": 0,
        "prueba_comprobada_contra": {"pares_de_grupos": len(pr_g),
                                     "pares_de_titulos": len(pr_t)},
        "fuentes_sha256_12": {f.name: sha(f) for f in (PARES, RESP, INC_JUZ, INC_META,
                                                      ORO_META, ORO_JUZ, NUEVOS_META)
                              + tuple(f for f in (CORR_GRADO, FUERA) if f.exists())},
    }
    (DESTINO / "manifiesto.json").write_text(json.dumps(man, ensure_ascii=False, indent=2),
                                             encoding="utf-8")

    print("paquete -> {}".format(DESTINO))
    print(json.dumps({k: man[k] for k in ("plata", "calibra", "prueba_en_el_paquete",
                                          "prueba_comprobada_contra")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
