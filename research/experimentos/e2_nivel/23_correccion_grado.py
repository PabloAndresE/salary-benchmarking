"""El numero de grado ya no separa: se corrigen los pares ya etiquetados. Enmienda 5 de D-036.

EL CRITERIO NUEVO (decision del autor, 2026-09-29). Un numero que marca el grado dentro del
cargo (`AUXILIAR 1` / `AUXILIAR 2`, `QUIMICO I` / `QUIMICO II`, `NIVEL 2`) no hace distinto
el puesto: la normalizacion lo borra. Reemplaza la excepcion del grado del paso 1 de la
rubrica v3, que decia `no` cuando el ordinal estaba en los dos titulos con valor distinto.

QUE ES UN GRADO AQUI, y nada mas:
    - un numero del 1 al 9 suelto (tambien `04`, `# 3`, `1.` al principio);
    - un romano del I al X suelto;
    - un digito del 1 al 9 pegado al final de una palabra (`CONTABLE1`);
    - `NIVEL`, `LEVEL`, `GRADO`, `CATEGORIA` o `CAT` justo antes de uno de los anteriores.
Las letras (`A`, `B`) ya eran ruido en la v3, y los numeros de 3 cifras o mas, codigos. Los
de dos cifras (`# 10`, `24 HORAS`) no se tocan: pueden no ser un grado.

LA CORRECCION ES MECANICA Y SOLO EN UN SENTIDO. Un `no` pasa a `si` cuando, borrados los
grados, los dos titulos tienen las mismas palabras (sin conectores y en cualquier orden,
que ya eran ruido en la v3). Si queda cualquier otra diferencia, no se decide aqui: el par
va a `23_revisar_grado.csv` para juicio humano. Un `si` nunca se toca, ni una `duda`.

LA REVISION A MANO. En `23_revisar_grado.csv` se rellena `mismo_nuevo` con `si` o `no`
(rubrica v3 con el grado borrado). Al volver a correr, lo rellenado se conserva y se aplica:
en `20` y `18`, `mismo` toma ese valor (`mismo_v3` sigue guardando el de antes); en la plata,
un `si` entra en `23_correcciones_plata.csv` con `regla = revision`. Vacio: nada cambia.

QUE TOCA
    juicios humanos (13e, 20, 18, 13a): se corrige `mismo` EN SU SITIO y la etiqueta de
        antes queda en `mismo_v3`, como `mismo_v1` en la v2. Se respeta el separador y el
        BOM de cada archivo. Se puede volver a correr: siempre parte de `mismo_v3`.
    plata (`16`): las respuestas de Gemini NO se tocan. Se escribe
        `23_correcciones_plata.csv` (n de `16`, etiqueta y motivo nuevos) y `21` lo aplica
        al armar el paquete. Solo pares coherentes de Gemini; los 139 van por `18`.

FUERA DE LA EVALUACION (opcion B de la Enmienda 5). Un par que, borrado el grado, queda
con las mismas palabras, lo fusiona la capa 0: en el producto nunca llega al juez. Medir
al juez con el seria pedirle lo que ya hace la normalizacion, y regalarle a B una ventaja
que no es suya. Por eso esos pares, sean `si` o `no`, salen de `calibra` y de `prueba`, y
quedan en `23_fuera_por_capa0.csv`. Lo leen `19`, `21` y el guion de H1. Se decide con
los titulos, sin mirar ningun puntaje. En la plata se quedan: ensenan que el grado no
separa, por si la capa 0 no atrapa alguna forma.

SALIDAS
    13e/20/18/13_para_juzgar.csv   corregidos en su sitio, con `mismo_v3`
    23_correcciones_plata.csv      lo que `21` aplica
    23_fuera_por_capa0.csv         pares de `13e` y `20` que salen de calibra y de prueba
    23_revisar_grado.csv           `no` con grado DISTINTO y otra diferencia, para juicio humano
"""
import csv
import pathlib
import re
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
HUMANOS = ["13e_para_juzgar.csv", "20_para_juzgar.csv", "18_para_juzgar.csv",
           "13_para_juzgar.csv"]
PARES = SAL / "16_pares_10000.csv"
RESP = SAL / "16_respuestas_llm.csv"
CORR_PLATA = SAL / "23_correcciones_plata.csv"
REVISAR = SAL / "23_revisar_grado.csv"
FUERA = SAL / "23_fuera_por_capa0.csv"
ORO_META = SAL / "13e_pares_400.csv"

ROMANOS = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
ANTES_DE_GRADO = {"NIVEL", "LEVEL", "GRADO", "CATEGORIA", "CAT"}
CONECTORES = {"DE", "DEL", "Y", "E", "EN", "EL", "LA", "LOS", "LAS", "A", "AL"}
NOTA = "grado->si (Enm. 5 D-036)"
NOTA_REV = "revisado a mano (Enm. 5 D-036)"


def leer_revision():
    """Lo ya rellenado en `mismo_nuevo`, para no perderlo al reescribir el archivo."""
    if not REVISAR.exists():
        return {}
    r = pd.read_csv(REVISAR, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                    keep_default_na=False)
    v = r["mismo_nuevo"].str.strip().str.lower()
    raros = sorted(set(v) - {"", "si", "no"})
    if raros:
        raise SystemExit("ALTO: `mismo_nuevo` solo admite si / no / vacio; hay {}".format(raros))
    return {(c, str(n)): x for c, n, x in zip(r["conjunto"], r["n"], v) if x}


def palabras(t):
    t = re.sub(r"([A-ZÁÉÍÓÚÑ])([1-9])\b", r"\1 \2", str(t).upper())
    return re.findall(r"[A-ZÁÉÍÓÚÑÜ0-9]+", t)


def es_grado(w):
    return (w.isdigit() and len(w) <= 2 and 1 <= int(w) <= 9) or w in ROMANOS


def quitar_grado(t):
    """Las palabras del titulo sin el grado. Borrador de la regla de la capa 0."""
    ws = palabras(t)
    return [w for i, w in enumerate(ws)
            if not es_grado(w)
            and not (w in ANTES_DE_GRADO and i + 1 < len(ws) and es_grado(ws[i + 1]))]


def tiene_grado(t):
    return any(es_grado(w) for w in palabras(t))


def grados(t):
    """Los valores de grado del titulo, con el romano pasado a numero (`I` = `1`)."""
    rom = {r: i + 1 for i, r in enumerate(["I", "II", "III", "IV", "V", "VI", "VII",
                                           "VIII", "IX", "X"])}
    return {rom.get(w) or int(w) for w in palabras(t) if es_grado(w)}


def grado_distinto(a, b):
    return grados(a) != grados(b)


def clave(t):
    return frozenset(w for w in quitar_grado(t) if w not in CONECTORES)


def solo_el_grado(a, b):
    """Los dos titulos son el mismo en cuanto se borra el grado, y alguno lo tenia."""
    return (tiene_grado(a) or tiene_grado(b)) and clave(a) == clave(b)


# ---------------------------------------------------------------------------------------
def formato(p):
    crudo = p.read_bytes()
    bom = crudo.startswith(b"\xef\xbb\xbf")
    cabecera = crudo.decode("utf-8-sig").splitlines()[0]
    return bom, csv.Sniffer().sniff(cabecera, delimiters=",;").delimiter


def corregir_humanos(rev):
    revisar, resumen = [], []
    for nom in HUMANOS:
        p = SAL / nom
        bom, sep = formato(p)
        d = pd.read_csv(p, sep=sep, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        if "mismo_v3" not in d:
            d.insert(d.columns.get_loc("mismo") + 1, "mismo_v3", d["mismo"])
        antes = d["mismo_v3"].str.strip().str.lower()
        d["mismo"] = d["mismo_v3"]
        for n_ in (NOTA, NOTA_REV):
            d["nota"] = d["nota"].str.replace(r"\s*;?\s*" + re.escape(n_), "", regex=True)
            d["nota"] = d["nota"].str.replace(r"^\s*;\s*", "", regex=True)
        sg = [solo_el_grado(a, b) for a, b in zip(d["comun"], d["raro"])]
        cambia = (antes == "no") & pd.Series(sg, index=d.index)
        d.loc[cambia, "mismo"] = "si"
        d.loc[cambia, "nota"] = [(n + "; " if n.strip() else "") + NOTA
                                 for n in d.loc[cambia, "nota"]]
        con_grado = [grado_distinto(a, b) for a, b in zip(d["comun"], d["raro"])]
        otra = (antes == "no") & pd.Series(con_grado, index=d.index) & ~pd.Series(sg, index=d.index)
        conj = nom.split("_")[0]
        revisados = []
        for i, f in d[otra].iterrows():
            nuevo = rev.get((conj, str(f["n"])), "")
            revisar.append({"conjunto": conj, "n": f["n"], "comun": f["comun"],
                            "raro": f["raro"], "mismo_v3": f["mismo_v3"], "nota": f["nota"],
                            "mismo_nuevo": nuevo})
            if nuevo and nuevo != antes[i]:
                d.loc[i, "mismo"] = nuevo
                d.loc[i, "nota"] = (f["nota"] + "; " if f["nota"].strip() else "") + NOTA_REV
                revisados.append(f["n"])
        cambia = cambia | d["n"].isin(revisados)
        if cambia.any() or "mismo_v3" in pd.read_csv(p, sep=sep, nrows=0,
                                                      encoding="utf-8-sig"):
            d.to_csv(p, index=False, sep=sep, encoding="utf-8-sig" if bom else "utf-8",
                     lineterminator="\n")
        resumen.append((nom, len(d), int(cambia.sum()), d.loc[cambia, "n"].tolist()))
    return resumen, revisar


def corregir_plata(rev):
    pares = pd.read_csv(PARES, sep=None, engine="python", encoding="utf-8-sig")
    r = pd.read_csv(RESP, dtype=str, keep_default_na=False)
    r = r[(r["error"] == "") & r["mismo"].isin(["si", "no"])]
    ancho = r.pivot_table(index="n", columns="orden", values=["mismo", "paso"],
                          aggfunc="first")
    ancho.columns = ["{}_{}".format(a, b) for a, b in ancho.columns]
    p = pares.merge(ancho.reset_index().astype({"n": int}), on="n")
    coh_no = (p["mismo_ab"] == "no") & (p["mismo_ba"] == "no")
    sg = pd.Series([solo_el_grado(a, b) for a, b in zip(p["comun"], p["raro"])],
                   index=p.index)
    con_grado = pd.Series([grado_distinto(a, b) for a, b in zip(p["comun"], p["raro"])],
                          index=p.index)
    otra = p[coh_no & con_grado & ~sg & (p["paso_ab"] == "p1")]
    revisar = [{"conjunto": "16", "n": str(f["n"]), "comun": f["comun"], "raro": f["raro"],
                "mismo_v3": "no", "nota": "gemini p1",
                "mismo_nuevo": rev.get(("16", str(f["n"])), "")}
               for _, f in otra.iterrows()]
    si_rev = otra[[rev.get(("16", str(n))) == "si" for n in otra["n"]]]
    filas = [(p[coh_no & sg], "grado"), (si_rev, "revision")]
    corr = pd.concat([pd.DataFrame({"n": c["n"], "particion": c["particion"],
                                    "etiqueta_v3": 0.0, "etiqueta": 1.0,
                                    "motivo_v3": c["paso_ab"], "motivo": "ninguno",
                                    "regla": regla}) for c, regla in filas],
                     ignore_index=True)
    corr.to_csv(CORR_PLATA, index=False, encoding="utf-8")
    return corr, revisar


def fuera_por_capa0():
    """Los pares de `13e` y `20` que la capa 0 fusiona, con su particion. Sin puntajes."""
    filas = []
    oro = pd.read_csv(ORO_META, sep=None, engine="python", encoding="utf-8-sig",
                      dtype=str, keep_default_na=False)
    for conj, d in (("13e", oro), ("20", None)):
        if d is None:
            d = pd.read_csv(SAL / "20_para_juzgar.csv", sep=None, engine="python",
                            encoding="utf-8-sig", dtype=str, keep_default_na=False)
            d["particion"] = "prueba"
        for _, f in d.iterrows():
            if solo_el_grado(f["comun"], f["raro"]):
                filas.append({"conjunto": conj, "n": f["n"], "particion": f["particion"]})
    t = pd.DataFrame(filas, columns=["conjunto", "n", "particion"])
    t.to_csv(FUERA, index=False, encoding="utf-8")
    return t


def main():
    print("=" * 78)
    print("23 · EL GRADO YA NO SEPARA: CORRECCION DE LO ETIQUETADO (Enmienda 5, D-036)")
    print("=" * 78)
    rev = leer_revision()
    res, rev_h = corregir_humanos(rev)
    print("\njuicios humanos: cambios por el grado y por la revision a mano")
    for nom, n, k, ns in res:
        print("   {:<22} {:>4} pares   {:>2} corregidos   {}".format(nom, n, k, ns))
    corr, rev_p = corregir_plata(rev)
    print("\nplata (Gemini coherente `no` -> `si`): {} pares {}".format(
        len(corr), corr["regla"].value_counts().to_dict()))
    print("   por particion:", corr["particion"].value_counts().to_dict())
    print("   motivo de Gemini antes:", corr["motivo_v3"].value_counts().to_dict())
    rev = pd.DataFrame(rev_h + rev_p)
    rev.to_csv(REVISAR, index=False, sep=";", encoding="utf-8-sig")
    print("\npara revisar a mano (`no` con grado y otra diferencia): {}, {} ya revisados".format(
        len(rev), int((rev["mismo_nuevo"] != "").sum()) if len(rev) else 0))
    if len(rev):
        print("   por conjunto:", rev["conjunto"].value_counts().to_dict())
    fu = fuera_por_capa0()
    print("\nfuera de la evaluacion (la capa 0 los fusiona): {}".format(len(fu)))
    print("   ", fu.groupby(["conjunto", "particion"]).size().to_dict())
    print("\n-> {}\n-> {}\n-> {}".format(CORR_PLATA.name, REVISAR.name, FUERA.name))
    print("Siguiente: `21` (paquete), `19` (linea base de calibra) y el AUC_BASE de `22`.")


if __name__ == "__main__":
    main()
