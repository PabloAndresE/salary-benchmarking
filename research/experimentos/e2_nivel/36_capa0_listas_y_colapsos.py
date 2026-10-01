"""Capa 0: las listas para aprobar (version 1 de los diccionarios) y los colapsos del oro. D-040.

1. LISTAS PARA APROBAR, regeneradas con lo que el autor decidio tras `35`:
   - erratas SIN la regla de "3 empresas" (en `base_v15` las empresas son por grupo y la regla
     protegia erratas metidas en grupos grandes y no protegia oficios raros reales); quedan:
     menos de 5 letras, diccionario es+en, y que el titulo corregido exista en la base;
   - abreviaturas con el minimo de longitud corregido (la expansion puede tener 1 letra mas:
     BODEG -> BODEGA, no BODEGUERO), dominio >= 80 % y proteccion de rango;
   - genero por palabra (-ERO/-ERA, -OR/-ORA, -IVO/-IVA, -ADO/-ADA, -ICO/-ICA).
   Cada fila lleva hasta dos titulos de ejemplo (antes -> despues), titulos afectados y personas
   (ESTIMADAS: la base guarda personas por grupo; se reparten por igual entre los titulos del
   grupo. Las exactas por titulo necesitan los datos crudos). Ordenadas por
   personas, con la cobertura acumulada. Columna `aprobar` vacia: el autor revisa hasta el 95 %
   de las personas; lo que no se revisa no se aplica.

2. COLAPSOS DEL ORO. Cuantos pares de `calibra`, `prueba` y `prueba 2` quedarian convertidos en el
   mismo titulo por la capa 0 nueva, regla por regla y acumulado, con su etiqueta. Un colapso de
   un par `no` es un error de la regla. Las reglas pendientes (grado, segun el criterio A; y los
   tres diccionarios, segun la aprobacion) se cuentan con TODAS sus propuestas: es una cota.

Usa `.venv-texto`.

SALIDAS
    36_listas_y_colapsos.txt
    36_aprobar_erratas.csv, 36_aprobar_abreviaturas.csv, 36_aprobar_genero.csv
"""
import importlib.util
import pathlib
import re
import sys
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, AQUI / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


e34 = cargar("e34", "34_capa0_palabras.py")
e35 = cargar("e35", "35_capa0_v2.py")
FREC, RAZON = e34.FREC, e34.RAZON


def leer(p, **kw):
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig", dtype=str,
                       keep_default_na=False, **kw)


def main():
    from rapidfuzz import process
    from rapidfuzz.distance import DamerauLevenshtein
    from spellchecker import SpellChecker

    b = np.load(RAIZ / "demo" / "base_v15.npz", allow_pickle=True)
    cel = [str(c) for c in b["celdas"]]
    g = b["grupo"].astype(int)
    per_g = {int(x): int(p) for x, p in zip(g, b["personas"])}
    k0 = [e34.K0(c) for c in cel]
    F = Counter(w for t in set(k0) for w in set(t.split()))
    V = set(F)
    dicc = set()
    for leng in ("es", "en"):
        dicc |= {e34.sin_tildes(w) for w in SpellChecker(language=leng).word_frequency.dictionary}

    def singular(w):
        if len(w) < 5 or not w.endswith("S") or w.endswith(("IS", "US")):
            return w
        if w[:-1] in V:
            return w[:-1]
        if w.endswith("ES") and w[:-2] in V and len(w[:-2]) >= 3:
            return w[:-2]
        return w

    def plural(t):
        return " ".join(singular(w) for w in t.split())

    k_pl = [plural(t) for t in k0]
    Vp = set(w for t in k_pl for w in t.split())
    titulos_con = defaultdict(list)
    for i, t in enumerate(k_pl):
        for w in set(t.split()):
            titulos_con[w].append(i)

    # La base guarda personas POR GRUPO: un titulo con errata metido en un grupo grande heredaba
    # todas sus personas (TRABAJAJOR, un titulo, 34.668). Estimacion: las personas del grupo
    # repartidas por igual entre sus titulos. Las exactas por titulo necesitan los datos crudos.
    tam_g = Counter(g.tolist())

    def personas_de(ix):
        return int(round(sum(per_g[int(g[i])] / tam_g[int(g[i])] for i in ix)))

    out = []

    def p(s=""):
        print(s, flush=True)
        out.append(s)

    p("=" * 78)
    p("36 · CAPA 0: LISTAS PARA APROBAR (v1 de los diccionarios) Y COLAPSOS DEL ORO")
    p("=" * 78)

    def guardar(filas, cols, nombre, col_pers):
        d = pd.DataFrame(filas, columns=cols).sort_values(col_pers, ascending=False)
        d["cobertura_acum"] = (d[col_pers].cumsum() / d[col_pers].sum()).round(3)
        d["aprobar"] = ""
        d.to_csv(SAL / nombre, index=False, encoding="utf-8")
        n95 = int((d["cobertura_acum"] < 0.95).sum()) + 1
        p("   -> {}: {:,} filas; hasta el 95 % de las personas: {:,}".format(nombre, len(d), n95))
        return d

    def ej(ix, f, n=2):
        return " | ".join("{} -> {}".format(cel[i], f(i)) for i in ix[:n])

    # --- genero por palabra ---------------------------------------------------------------
    pares = sorted({(w[:-len(fe)] + m, w) for w in Vp for m, fe in e35.GENERO
                    if w.endswith(fe) and len(w) > len(fe) + 2 and w[:-len(fe)] + m in Vp})
    a_masc = {f: m for m, f in pares}
    filas = []
    for m, f in pares:
        ix = titulos_con[f]
        filas.append((f, m, len(ix), personas_de(ix),
                      ej(ix, lambda i: " ".join(a_masc.get(w, w) for w in k_pl[i].split()))))
    p("\nGENERO POR PALABRA: {:,} pares".format(len(pares)))
    guardar(filas, ["femenino", "masculino", "titulos", "personas_estimadas", "ejemplos"],
            "36_aprobar_genero.csv", "personas_estimadas")

    # --- erratas, sin la regla de 3 empresas ----------------------------------------------
    frecuentes = [w for w in Vp if F.get(w, 0) >= FREC]
    por_fon = defaultdict(list)
    for w in frecuentes:
        por_fon[e34.fonetica(w)].append(w)
    dicc_err, motivo, desc = {}, {}, Counter()
    for r in Vp:
        Fr = F.get(r, 1)
        op = [(0, -F[c], c, "fonetica") for c in por_fon.get(e34.fonetica(r), [])
              if c != r and F[c] >= RAZON * Fr]
        if len(r) >= 7:
            for c, d, _ in process.extract(r, frecuentes, scorer=DamerauLevenshtein.distance,
                                           score_cutoff=2, limit=5):
                if c != r and F[c] >= RAZON * Fr:
                    op.append((d, -F[c], c, "distancia {}".format(d)))
        if not op:
            continue
        _, _, c, como = min(op)
        if len(r) < 5:
            desc["menos de 5 letras"] += 1
        elif r in dicc:
            desc["existe en el diccionario"] += 1
        else:
            dicc_err[r], motivo[r] = c, como
    kt = set(k_pl)

    def corregir(t):
        tn = " ".join(dicc_err.get(w, w) for w in t.split())
        return tn if tn in kt else t
    filas = []
    for r, c in dicc_err.items():
        ix = titulos_con[r]
        ok = [i for i in ix if corregir(k_pl[i]) != k_pl[i]]
        if not ok:
            continue          # el titulo corregido no existe en ningun caso: no se propone
        filas.append((r, c, motivo[r], F.get(r, 0), F.get(c, 0), len(ok), personas_de(ok),
                      ej(ok, lambda i: corregir(k_pl[i]))))
    p("\nERRATAS (sin la regla de 3 empresas): {:,} candidatas; descartadas por menos de 5 letras"
      " {:,}, por el diccionario {:,}; con algun titulo corregido que existe: {:,}".format(
          len(dicc_err) + sum(desc.values()), desc["menos de 5 letras"],
          desc["existe en el diccionario"], len(filas)))
    d_err = guardar(filas, ["rara", "corregida", "como", "titulos_con_la_rara",
                            "titulos_con_la_corregida", "titulos_que_cambian", "personas_estimadas",
                            "ejemplos"], "36_aprobar_erratas.csv", "personas_estimadas")
    dicc_err = {r: c for r, c in zip(d_err["rara"], d_err["corregida"])}

    # --- abreviaturas, minimo de longitud corregido ---------------------------------------
    pref = defaultdict(list)
    for w in frecuentes:
        for k in range(2, min(7, len(w))):
            pref[w[:k]].append(w)
    dicc_ab, dom = {}, {}

    def decide(L, punto):
        if L in dicc or L in e34.CONECTORES:
            return None
        cs = [w for w in pref.get(L, []) if len(w) >= len(L) + 1]
        if not cs:
            return None
        tot = sum(F[w] for w in cs)
        top = max(cs, key=lambda w: F[w])
        riv = [w for w in cs if F[w] / tot >= e35.MIN_CUOTA_RIVAL]
        if any(e35.es_rango(w) for w in riv) and not all(e35.es_rango(w) for w in riv):
            return None
        if F[top] / tot >= e35.DOMINIO:
            dicc_ab[L + punto], dom[L + punto] = top, F[top] / tot
            return top
        return None

    def expandir(t):
        res = []
        for tok in re.sub(r"\.(?=[A-Z])", ". ", t).split():
            m = re.fullmatch(r"([A-Z]{2,6})(\.?)", tok)
            x = decide(m.group(1), m.group(2)) if m else None
            res.append(x if x else tok)
        return " ".join(res)
    exp = [expandir(c) for c in cel]
    uso = defaultdict(list)
    for i, c in enumerate(cel):
        for tok in re.sub(r"\.(?=[A-Z])", ". ", c).split():
            if tok in dicc_ab:
                uso[tok].append(i)
    filas = [(a, w, round(dom[a], 3), len(uso[a]), personas_de(uso[a]),
              ej(uso[a], lambda i: exp[i])) for a, w in dicc_ab.items() if uso[a]]
    p("\nABREVIATURAS (minimo de 1 letra mas, dominio >= 80 %, rango): {:,}".format(len(filas)))
    p("   BODEG -> {}".format(dicc_ab.get("BODEG", "(no se expande)")))
    d_ab = guardar(filas, ["abreviatura", "expansion", "dominio", "titulos", "personas_estimadas",
                           "ejemplos"], "36_aprobar_abreviaturas.csv", "personas_estimadas")

    # --- colapsos del oro -------------------------------------------------------------------
    e32 = e34.e32
    from benchmarking.producto.nivel import _es_grado  # noqa: F401  (vive en e32)

    def pasos(t):
        """Clave del titulo tras cada regla, en el orden de la capa 0."""
        abrev = expandir(t)
        texto = e32.limpia(abrev)
        out_ = {"1. texto (codigo inicial y puntuacion)": e32.limpia(t)}
        out_["2. + abreviaturas (todas las propuestas)"] = texto
        pl = plural(texto)
        out_["3. + plural simple"] = pl
        er = " ".join(dicc_err.get(w, w) for w in pl.split())
        out_["4. + erratas (todas las propuestas)"] = er
        ge = " ".join(a_masc.get(w, w) for w in er.split())
        out_["5. + genero por palabra (todos los pares)"] = ge
        out_["6. + grado al final (si el criterio A lo activa)"] = e32.sin_grado_final(ge)
        return out_

    conjuntos = {}
    cal = leer(SAL / "21_paquete" / "calibra.csv")
    conjuntos["calibra (191)"] = cal[["comun", "raro", "mismo"]]
    q = pd.read_csv(SAL / "24_puntajes_prueba.csv", dtype=str)
    m13 = leer(SAL / "13e_pares_400.csv")
    j13 = leer(SAL / "13e_para_juzgar.csv")[["n", "mismo"]]
    m20 = leer(SAL / "20_pares_400.csv")
    j20 = leer(SAL / "20_para_juzgar.csv")[["n", "mismo"]]
    pr = pd.concat([m13.merge(j13, on="n").assign(c="13e"), m20.merge(j20, on="n").assign(c="20")])
    pr = pr.merge(q[["n", "conjunto"]], left_on=["n", "c"], right_on=["n", "conjunto"])
    conjuntos["prueba (555, H1)"] = pr[["comun", "raro", "mismo"]]
    p2 = leer(SAL / "29_prueba2_para_juzgar.csv")
    conjuntos["prueba 2 (400, H4)"] = p2[["comun", "raro", "mismo"]]
    p("\nCOLAPSOS DEL ORO: pares que la capa 0 nueva convertiria en el mismo titulo")
    p("(acumulado regla a regla; entre parentesis, cuantos eran `no`: esos serian errores)")
    lista_no = []
    for nombre, d in conjuntos.items():
        p("\n   {}".format(nombre))
        ka = [pasos(a) for a in d["comun"]]
        kb = [pasos(x) for x in d["raro"]]
        for regla in ka[0]:
            col = np.array([x[regla] == y[regla] for x, y in zip(ka, kb)])
            no = col & (d["mismo"].str.strip().str.lower() == "no").to_numpy()
            p("      {:<52} {:>3} ({} no)".format(regla, int(col.sum()), int(no.sum())))
        ult = list(ka[0])[-1]
        for (_, f), x, y in zip(d.iterrows(), ka, kb):
            if x[ult] == y[ult] and f["mismo"].strip().lower() == "no":
                lista_no.append((nombre, f["comun"], f["raro"]))
    p("\n   pares `no` que colapsarian (errores de alguna regla):")
    for nombre, a, c in lista_no:
        p("      [{}]  {}  ||  {}".format(nombre.split(" (")[0], a, c))
    (SAL / "36_listas_y_colapsos.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
