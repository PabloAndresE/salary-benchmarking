"""Piloto: un LLM (Gemini) juzga los 400 pares de `13e` con la rubrica, y se mide contra el juez.

Es el paso 3 del plan. La pregunta no es «que tal juzga el LLM», sino si el MONTAJE
--modelo, rubrica, formato, parametros-- coincide con el juez lo bastante como para
etiquetar despues 10.000 pares con el. Por eso este guion es el mismo que se usara para
los 10.000; solo cambia la lista de pares.

TRES COSAS QUE SE CUIDAN:

1. EL LLM NO VE LAS ETIQUETAS NI `sim`. Se le mandan los dos titulos y nada mas. La tabla
   de peticiones se arma solo con `n`, `comun` y `raro`, y hay una comprobacion que lo
   hace fallar si se colara otra columna.

2. UN PAR POR PETICION, EN LOS DOS ORDENES. En un chat cada par veria los anteriores y
   se anclaria en ellos; aqui cada peticion es independiente. Y cada par va como A/B y
   como B/A: si el LLM cambia de opinion al invertirlos, esa respuesta vale poco.

3. SOLO SE EVALUA CALIBRA. El LLM juzga tambien los 200 de `prueba` --hacen falta para
   la comparacion final del paso 8--, pero aqui no se puntuan. Ni siquiera hay una
   opcion para hacerlo: la mitad de prueba se toca una vez, al final, con todo congelado.

COMPUERTA, PROPUESTA ANTES DE VER NINGUNA RESPUESTA. El acierto no sirve: en calibra el
74% de los pares son `si` y contestar siempre `si` ya acierta eso. Se usa kappa, que
descuenta el acierto por azar. Para pasar, en los DOS ordenes:

    kappa                   >= 0,60   (acuerdo «sustancial», Landis y Koch 1977)
    recall de `no`          >= 0,70   (los `no` son los que ensenan al modelo)
    coherencia ab = ba      >= 0,90

Si no pasa, se ajusta la rubrica mirando SOLO los desacuerdos de calibra, y se repite.

USO (la clave se lee de GEMINI_API_KEY; nunca se escribe en ningun sitio):

    python 15_piloto_llm.py modelos
    python 15_piloto_llm.py estimar  --modelo M --autorizado [--precio-entrada X --precio-salida Y]
    python 15_piloto_llm.py ejecutar --modelo M --autorizado
    python 15_piloto_llm.py ejecutar --modelo M --autorizado --solo-calibra   (iterar)
    python 15_piloto_llm.py evaluar

`--autorizado` es obligatorio para todo lo que manda titulos a la API: son datos de
empresas clientes (regla LOPDP del .gitignore) y hace falta el permiso antes. Los precios
se pasan a mano, en USD por millon de tokens, porque cambian y aqui no se inventan.

Las respuestas se guardan en `salidas/15_respuestas_llm.csv` (en .gitignore: llevan los
titulos). Si se corta, `ejecutar` retoma donde se quedo. Cada fila lleva el hash de la
rubrica, asi que cambiarla no mezcla respuestas de dos versiones.
"""
import argparse
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import pathlib
import random
import sys
import textwrap
import time

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
RUBRICA = AQUI / "rubrica_mismo_cargo.md"
PARES = SAL / "13e_para_juzgar.csv"       # de aqui salen los titulos... y las etiquetas
META = SAL / "13e_pares_400.csv"          # particion y estrato
RESPUESTAS = SAL / "15_respuestas_llm.csv"
SEM = 20260923
LINEA = "=" * 78

COMPUERTA = {"kappa": 0.60, "recall_no": 0.70, "coherencia": 0.90}

INSTRUCCION = """Eres un analista de benchmarking salarial. Vas a recibir dos titulos de
cargo, A y B. Decide si son el mismo cargo siguiendo EXACTAMENTE la rubrica de abajo:
recorre los pasos en orden y el primero que diga `no` decide; si ninguno lo dice, es `si`.

Responde solo con el JSON pedido:
- `razon`: una frase corta con lo que decidio.
- `paso`: el paso que decidio (`p1` a `p5`), o `ninguno` si ningun paso dijo `no`.
- `mismo`: `si` o `no`.

=== RUBRICA ===

"""

ESQUEMA = {
    "type": "object",
    "properties": {
        "razon": {"type": "string"},
        "paso": {"type": "string", "enum": ["p1", "p2", "p3", "p4", "p5", "ninguno"]},
        "mismo": {"type": "string", "enum": ["si", "no"]},
    },
    "required": ["razon", "paso", "mismo"],
}

CAMPOS = ["n", "orden", "a", "b", "modelo", "version_modelo", "rubrica_sha", "mismo",
          "paso", "razon", "tok_entrada", "tok_salida", "tok_pensamiento", "fin", "error"]


# --------------------------------------------------------------------------- peticiones

def rubrica():
    """Solo las reglas. El historial cita pares por numero y cuenta como se decidio cada
    regla: al LLM no le sirve y solo le da material para anclarse. El hash es de lo que
    se manda, asi que tocar el historial no invalida las respuestas ya guardadas."""
    texto = RUBRICA.read_text(encoding="utf-8").split("\n## Historial")[0].rstrip()
    return INSTRUCCION + texto, hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


def peticiones(solo_calibra=False):
    """Una fila por par y orden. Solo titulos: el LLM no ve nada mas.

    `solo_calibra` es para iterar la rubrica: `prueba` se juzga una vez, con la rubrica
    ya congelada, y no se paga en cada vuelta. La particion filtra QUE pares se piden; el
    LLM sigue sin verla."""
    p = pd.read_csv(PARES, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    p = p[["n", "comun", "raro"]]
    assert list(p.columns) == ["n", "comun", "raro"], "se colo una columna en las peticiones"
    if solo_calibra:
        m = pd.read_csv(META, sep=";", encoding="utf-8-sig", dtype=str)
        p = p[p.n.isin(m.loc[m.particion == "calibra", "n"])]
    ab = p.assign(orden="ab", a=p["comun"], b=p["raro"])
    ba = p.assign(orden="ba", a=p["raro"], b=p["comun"])
    r = pd.concat([ab, ba])[["n", "orden", "a", "b"]]
    # Orden al azar: si la cuota corta a mitad, lo que falta no cae entero en un estrato.
    return r.sample(frac=1.0, random_state=SEM).reset_index(drop=True)


def contenido(a, b):
    return "A: {}\nB: {}".format(a, b)


def cliente():
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Falta GEMINI_API_KEY en el entorno.")
    from google import genai
    return genai.Client()


def configuracion(sistema):
    from google.genai import types
    return types.GenerateContentConfig(
        system_instruction=sistema,
        temperature=0.0,
        seed=SEM,
        response_mime_type="application/json",
        response_json_schema=ESQUEMA,
    )


def juzgar(cli, modelo, cfg, fila, sha, intentos=6):
    """Una peticion, con reintentos ante cuota (429) y fallos del servidor (5xx)."""
    from google.genai import errors
    base = dict(n=fila.n, orden=fila.orden, a=fila.a, b=fila.b, modelo=modelo,
                rubrica_sha=sha)
    for k in range(intentos):
        try:
            r = cli.models.generate_content(model=modelo, contents=contenido(fila.a, fila.b),
                                            config=cfg)
            u = r.usage_metadata
            base.update(version_modelo=r.model_version or "",
                        tok_entrada=getattr(u, "prompt_token_count", None),
                        tok_salida=getattr(u, "candidates_token_count", None),
                        tok_pensamiento=getattr(u, "thoughts_token_count", None),
                        fin=str(r.candidates[0].finish_reason) if r.candidates else "")
            try:
                j = json.loads(r.text or "")
                base.update(mismo=j["mismo"], paso=j["paso"], razon=j["razon"], error="")
            except (ValueError, KeyError, TypeError):
                base.update(error="respuesta no es el JSON pedido: {!r}".format(r.text)[:300])
            return base
        except errors.APIError as e:
            if e.code in (429, 500, 502, 503, 504) and k < intentos - 1:
                time.sleep(min(60, 2 ** k) + random.random())
                continue
            base.update(error="APIError {}: {}".format(e.code, str(e)[:250]))
            return base
    return base


def ya_hechas(modelo, sha):
    if not RESPUESTAS.exists():
        return set()
    d = pd.read_csv(RESPUESTAS, encoding="utf-8", dtype=str, keep_default_na=False)
    d = d[(d.modelo == modelo) & (d.rubrica_sha == sha) & (d.error == "")]
    return set(zip(d.n, d.orden))


def correr(filas, modelo, sistema, sha, hilos):
    """Lanza las peticiones y va escribiendo cada respuesta en cuanto llega."""
    cli, cfg = cliente(), configuracion(sistema)
    nuevo = not RESPUESTAS.exists()
    fallos = 0
    with open(RESPUESTAS, "a", newline="", encoding="utf-8") as fh, \
            cf.ThreadPoolExecutor(hilos) as ex:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        if nuevo:
            w.writeheader()
        futs = [ex.submit(juzgar, cli, modelo, cfg, f, sha) for f in filas.itertuples()]
        for i, fu in enumerate(cf.as_completed(futs), 1):
            r = fu.result()
            fallos += bool(r.get("error"))
            w.writerow({k: r.get(k, "") for k in CAMPOS})
            fh.flush()
            if i % 50 == 0 or i == len(futs):
                print("    {}/{}  (fallos: {})".format(i, len(futs), fallos), flush=True)
    return fallos


# ----------------------------------------------------------------------------- ordenes

def cmd_modelos(_):
    cli = cliente()
    for m in cli.models.list():
        acc = getattr(m, "supported_actions", None) or []
        if "generateContent" in acc:
            print("  {:<45} {}".format(m.name.replace("models/", ""), m.display_name or ""))


def cmd_estimar(a):
    sistema, sha = rubrica()
    todas = peticiones()

    print(LINEA)
    print("ESTIMACION DE COSTE  modelo={}  rubrica={}".format(a.modelo, sha))
    print(LINEA)
    # Todo se mide en unas pocas peticiones reales, con lo que reporta el propio Gemini.
    # `count_tokens` no sirve: en la API de desarrolladores no acepta `system_instruction`,
    # y sin ella contaria dos titulos y no la rubrica, que es casi toda la entrada. Las
    # respuestas no se tiran: quedan en el cache y cuentan para `ejecutar`.
    muestra = todas.head(a.muestra)
    hechas = ya_hechas(a.modelo, sha)
    falta = muestra[[(n, o) not in hechas for n, o in zip(muestra.n, muestra.orden)]]
    if len(falta):
        print("  {} peticiones reales para medir la salida...".format(len(falta)))
        correr(falta, a.modelo, sistema, sha, a.hilos)
    d = pd.read_csv(RESPUESTAS, encoding="utf-8", dtype=str, keep_default_na=False)
    d = d[(d.modelo == a.modelo) & (d.rubrica_sha == sha)]
    if (d.error == "").sum() == 0:
        errores = d.error.value_counts().head(3)
        sys.exit("Ninguna peticion de muestra salio bien. Errores:\n  " +
                 "\n  ".join("{} x  {}".format(c, e) for e, c in errores.items()))
    d = d[d.error == ""]
    ent = pd.to_numeric(d.tok_entrada, errors="coerce").fillna(0)
    sal = pd.to_numeric(d.tok_salida, errors="coerce").fillna(0)
    pen = pd.to_numeric(d.tok_pensamiento, errors="coerce").fillna(0)

    n = len(todas)
    e_med, s_med = float(ent.mean()), float((sal + pen).mean())
    print("  medido en {} respuestas".format(len(d)))
    print("\n  peticiones             : {}  (400 pares x 2 ordenes)".format(n))
    print("  entrada media          : {:,.0f} tokens".format(e_med))
    print("  salida media           : {:,.0f} tokens  (de ellos pensamiento: {:,.0f})".format(
        s_med, float(pen.mean())))
    print("  TOTAL piloto           : {:.2f} M de entrada, {:.2f} M de salida".format(
        n * e_med / 1e6, n * s_med / 1e6))
    print("  TOTAL 10.000 pares     : {:.1f} M de entrada, {:.1f} M de salida".format(
        n * e_med / 1e6 * 25, n * s_med / 1e6 * 25))
    if a.precio_entrada is None or a.precio_salida is None:
        print("\n  Sin precios: multiplica esos millones por el precio por millon del modelo.")
        return
    coste = n * (e_med * a.precio_entrada + s_med * a.precio_salida) / 1e6
    print("  COSTE ESTIMADO         : {:.2f} USD".format(coste))
    print("  para 10.000 pares      : {:.2f} USD".format(coste * 25))
    print("  (la salida incluye el pensamiento, que se cobra como salida; si la cache")
    print("   implicita abarata la rubrica, el coste real sale algo menor)")


def cmd_ejecutar(a):
    sistema, sha = rubrica()
    todas = peticiones(a.solo_calibra)
    hechas = ya_hechas(a.modelo, sha)
    falta = todas[[(n, o) not in hechas for n, o in zip(todas.n, todas.orden)]]
    print(LINEA)
    print("PILOTO  modelo={}  rubrica={}{}".format(
        a.modelo, sha, "  (solo calibra)" if a.solo_calibra else ""))
    print("  hechas: {}   faltan: {}".format(len(todas) - len(falta), len(falta)))
    print(LINEA)
    if len(falta):
        fallos = correr(falta, a.modelo, sistema, sha, a.hilos)
        if fallos:
            print("\n  {} fallaron. Vuelve a lanzar `ejecutar` para reintentarlas.".format(fallos))


# ---------------------------------------------------------------------------- evaluar

def kappa(x, y):
    x, y = np.asarray(x), np.asarray(y)
    po = (x == y).mean()
    pe = sum((x == c).mean() * (y == c).mean() for c in ("si", "no"))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def auc(punt, es_si):
    a, b = punt[es_si], punt[~es_si]
    return ((a[:, None] > b[None, :]).sum()
            + 0.5 * (a[:, None] == b[None, :]).sum()) / (len(a) * len(b))


def medir(juez, llm):
    ok = llm.notna()
    j, l = juez[ok], llm[ok]
    return dict(n=int(ok.sum()), acierto=(j == l).mean(), kappa=kappa(j, l),
                recall_no=((l == "no") & (j == "no")).sum() / max(1, (j == "no").sum()),
                recall_si=((l == "si") & (j == "si")).sum() / max(1, (j == "si").sum()))


def cmd_evaluar(a):
    if not RESPUESTAS.exists():
        sys.exit("No hay respuestas todavia: corre `ejecutar` primero.")
    r = pd.read_csv(RESPUESTAS, encoding="utf-8", dtype=str, keep_default_na=False)
    r = r[r.error == ""].drop_duplicates(["n", "orden", "modelo", "rubrica_sha"], keep="last")
    j = pd.read_csv(PARES, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    m = pd.read_csv(META, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    base = j[["n", "comun", "raro", "mismo"]].merge(m[["n", "particion", "estrato"]], on="n")
    base = base.rename(columns={"mismo": "juez"})

    for (modelo, sha), g in r.groupby(["modelo", "rubrica_sha"]):
        w = g.pivot(index="n", columns="orden", values="mismo")
        razon = g[g.orden == "ab"].set_index("n")[["paso", "razon"]]
        d = base.merge(w, left_on="n", right_index=True, how="left") \
                .merge(razon, left_on="n", right_index=True, how="left")
        for o in ("ab", "ba"):
            if o not in d:
                d[o] = np.nan
        cal = d[d.particion == "calibra"]
        pru = d[d.particion == "prueba"]
        # Las respuestas de `estimar` son una muestra de 10: no hay nada que medir con ellas.
        if min(cal.ab.notna().sum(), cal.ba.notna().sum()) < 100:
            print("  ({} con rubrica {}: {} respuestas en calibra, pocas para evaluar; se omite)"
                  .format(modelo, sha, int(cal.ab.notna().sum() + cal.ba.notna().sum())))
            continue

        print(LINEA)
        print("PILOTO CONTRA EL JUEZ, SOLO CALIBRA  modelo={}  rubrica={}".format(modelo, sha))
        print(LINEA)
        print("  respuestas en calibra : ab {}/200   ba {}/200".format(
            int(cal.ab.notna().sum()), int(cal.ba.notna().sum())))
        print("  prueba                : {} respuestas guardadas, NO se evaluan (paso 8)".format(
            int(pru.ab.notna().sum() + pru.ba.notna().sum())))
        print("  contestar siempre si  : acierta {:.3f}  (el liston que el acierto no ve)".format(
            (cal.juez == "si").mean()))

        res = {o: medir(cal.juez, cal[o]) for o in ("ab", "ba")}
        print("\n  {:<6} {:>5} {:>8} {:>7} {:>10} {:>10}".format(
            "orden", "n", "acierto", "kappa", "recall no", "recall si"))
        for o, x in res.items():
            print("  {:<6} {:>5} {:>8.3f} {:>7.3f} {:>10.3f} {:>10.3f}".format(
                o, x["n"], x["acierto"], x["kappa"], x["recall_no"], x["recall_si"]))

        ambos = cal.ab.notna() & cal.ba.notna()
        coh = (cal.ab[ambos] == cal.ba[ambos]).mean() if ambos.any() else float("nan")
        print("\n  coherencia ab = ba    : {:.3f}  ({} pares con los dos ordenes)".format(
            coh, int(ambos.sum())))
        if ambos.any():
            p = ((cal.ab == "si").astype(float) + (cal.ba == "si").astype(float))[ambos] / 2
            es_si = (cal.juez[ambos] == "si").to_numpy()
            if 0 < es_si.sum() < len(es_si):
                print("  AUC (0 / 0,5 / 1)     : {:.3f}  (comparable con 13c y 13d)".format(
                    auc(p.to_numpy(), es_si)))

        print("\n  matriz, orden ab (filas juez, columnas LLM):")
        print(pd.crosstab(cal.juez, cal.ab.fillna("sin respuesta")).to_string()
              .replace("\n", "\n    ").join(["    ", ""]))
        print("\n  kappa ab por estrato:")
        for e, ge in cal.groupby("estrato"):
            x = medir(ge.juez, ge.ab)
            print("    {:<6} n={:>3}  acierto {:.3f}  kappa {:.3f}".format(
                e, x["n"], x["acierto"], x["kappa"]))

        pasa = all(res[o]["kappa"] >= COMPUERTA["kappa"] and
                   res[o]["recall_no"] >= COMPUERTA["recall_no"] for o in res) \
            and coh >= COMPUERTA["coherencia"]
        print("\n  COMPUERTA (kappa >= {kappa}, recall no >= {recall_no}, coherencia >= "
              "{coherencia}): {veredicto}".format(veredicto="PASA" if pasa else "NO PASA",
                                                  **COMPUERTA))

        dis = cal[(cal.ab.notna()) & (cal.ab != cal.juez)]
        print("\n  DESACUERDOS EN CALIBRA, orden ab ({}), para revisar la rubrica:".format(
            len(dis)))
        for f in dis.itertuples():
            print("    #{:<4} juez {:<2}  LLM {:<2} [{}]  {}  /  {}".format(
                f.n, f.juez, f.ab, f.paso, f.comun, f.raro))
            print("           {}".format(f.razon))
        print()


def main():
    # Los titulos traen de todo (tildes rotas, chino); la consola de Windows no.
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("modelos", help="lista los modelos de Gemini disponibles")
    for nombre in ("estimar", "ejecutar"):
        p = sub.add_parser(nombre)
        p.add_argument("--modelo", required=True)
        p.add_argument("--hilos", type=int, default=4)
        p.add_argument("--autorizado", action="store_true",
                       help="hay permiso para mandar estos titulos a una API externa")
        if nombre == "estimar":
            p.add_argument("--precio-entrada", type=float, help="USD / 1M (opcional)")
            p.add_argument("--precio-salida", type=float, help="USD / 1M (opcional)")
            p.add_argument("--muestra", type=int, default=10)
        else:
            p.add_argument("--solo-calibra", action="store_true",
                           help="para iterar la rubrica: no juzga los 200 de prueba")
    sub.add_parser("evaluar")
    a = ap.parse_args()
    if a.cmd in ("estimar", "ejecutar") and not a.autorizado:
        sys.exit("Esto manda titulos de empresas clientes a Gemini. Con el permiso ya "
                 "confirmado, repite con --autorizado.")
    {"modelos": cmd_modelos, "estimar": cmd_estimar, "ejecutar": cmd_ejecutar,
     "evaluar": cmd_evaluar}[a.cmd](a)


if __name__ == "__main__":
    main()
