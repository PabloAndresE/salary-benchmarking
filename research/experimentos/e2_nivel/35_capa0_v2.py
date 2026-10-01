"""Capa 0, segunda ronda (D-040): genero por palabra, erratas con "palabra real" y abreviaturas
con proteccion de rango. Descriptivo; las reglas PROPONEN y el autor aprueba.

Ajustes pedidos por el autor tras `34`:

GENERO POR PALABRA. Solo en terminaciones de oficio y adjetivo: -ERO/-ERA, -OR/-ORA, -IVO/-IVA,
-ADO/-ADA, -ICO/-ICA. Un par entra si las dos formas existen en la base. Se lista cada par para
revisarlo (hay pares que no son genero: QUIMICO/QUIMICA, TECNICO/TECNICA, INFORMATICO/...).

ERRATAS. Una palabra que aparece en 3 o mas empresas distintas es REAL y no se corrige (el
diccionario no conoce los oficios: CLAVADOR, PRORRECTOR). "Las dos frecuentes" deja de existir
como proteccion aparte: bloquea solo si la palabra de origen es real (COODINADORA y PRODUCCI se
corrigen aunque esten en muchos titulos). Distancia 2 se mantiene. Siguen: menos de 5 letras,
diccionario es+en, y que el titulo corregido exista en la base.
    Empresas por palabra: `base_v15` guarda empresas POR GRUPO (padron), no por titulo. Se usa
    la COTA SUPERIOR (empresas de todos los grupos donde aparece la palabra): protege de mas,
    nunca de menos. Para una errata sola en su grupo es exacta. Se informa la cota inferior
    (solo grupos donde TODOS los titulos llevan la palabra) como sensibilidad.

ABREVIATURAS. Dominio minimo 80 % siempre (con o sin punto). Si entre las candidatas (con al
menos 5 % de la frecuencia) hay una palabra de rango y otra que no lo es, no se expande
(DIREC. puede ser DIRECTOR o DIRECCION).

PROPUESTAS PARA APROBAR. Diccionarios completos ordenados por personas afectadas (cota: personas
de los grupos donde aparece la palabra), con columna `aprobar` vacia. El autor los revisa una
vez y eso queda como la version 1.

Usa `.venv-texto`.

SALIDAS
    35_capa0_v2.txt                informe con ejemplos
    35_pares_genero.csv            pares de genero por palabra, para aprobar
    35_propuestas_erratas.csv      diccionario de erratas propuesto, para aprobar
    35_propuestas_abreviaturas.csv diccionario de abreviaturas propuesto, para aprobar
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
spec = importlib.util.spec_from_file_location("e34", AQUI / "34_capa0_palabras.py")
e34 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e34)
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.nivel import RANGOS  # noqa: E402

REAL = 3                     # empresas distintas desde las que una palabra es real
FREC, RAZON = e34.FREC, e34.RAZON
DOMINIO = 0.80
MIN_CUOTA_RIVAL = 0.05
GENERO = [("ERO", "ERA"), ("OR", "ORA"), ("IVO", "IVA"), ("ADO", "ADA"), ("ICO", "ICA")]
RANGO = set(RANGOS) | {"ASESOR", "EJECUTIVO", "ENCARGADO", "CONSULTOR", "SUBJEFE",
                       "ADMINISTRADOR", "CONTROLLER", "ASSISTANT", "MANAGER", "DIRECTOR",
                       "SUPERVISOR", "COORDINADOR", "JEFE", "GERENTE", "SUBGERENTE"}
ERRORES_34 = {"CLAVADOR": "LAVADOR", "PRORECTOR": "PROTECTOR", "EMBALADORA": "EMPACADORA",
              "ENSACADO": "ENVASADO", "SUBCONTRALOR": "SUBCONTADOR", "CUADRADOR": "CUIDADOR"}
rng = np.random.default_rng(20261009)


def es_rango(w):
    return any(w == r or w == r + "A" or w == r + "ES" or w == r + "S" or w == r + "AS"
               or (r.endswith("O") and w == r[:-1] + "A") for r in RANGO)


def main():
    from rapidfuzz import process
    from rapidfuzz.distance import DamerauLevenshtein
    from spellchecker import SpellChecker

    b = np.load(RAIZ / "demo" / "base_v15.npz", allow_pickle=True)
    cel = [str(c) for c in b["celdas"]]
    g = b["grupo"].astype(int)
    per_g = {int(x): int(p) for x, p in zip(g, b["personas"])}
    # padron: empresas por grupo
    ptr, idx = b["pad_ptr"], b["pad_idx"]
    claves = [int(c) for c in b["pad_claves"]]
    emp_de = {gk: set(idx[ptr[k]:ptr[k + 1]].tolist()) for k, gk in enumerate(claves)}

    k0 = [e34.K0(c) for c in cel]
    u0 = e34.Uniones(g)
    u0.unir_por(k0)
    out = []

    def p(s=""):
        print(s, flush=True)
        out.append(s)

    p("=" * 78)
    p("35 · CAPA 0, SEGUNDA RONDA: GENERO POR PALABRA, ERRATAS Y ABREVIATURAS (descriptivo)")
    p("=" * 78)
    p("todo se cuenta encima de lo actual (base_v15) y de las reglas de texto acordadas.")

    F = Counter(w for t in set(k0) for w in set(t.split()))
    V = set(F)
    grupos_de = defaultdict(set)
    todos_en = defaultdict(lambda: defaultdict(int))
    tam = Counter(g.tolist())
    for i, t in enumerate(k0):
        for w in set(t.split()):
            grupos_de[w].add(int(g[i]))
            todos_en[w][int(g[i])] += 1

    def emp_sup(w):
        return len(set().union(*(emp_de.get(x, set()) for x in grupos_de[w])))

    def emp_inf(w):
        return len(set().union(*(emp_de.get(x, set()) for x, n in todos_en[w].items()
                                 if n == tam[x]))) if todos_en[w] else 0

    def personas(w):
        return sum(per_g[x] for x in grupos_de[w])

    dicc = set()
    for leng in ("es", "en"):
        dicc |= {e34.sin_tildes(w) for w in SpellChecker(language=leng).word_frequency.dictionary}

    # plural simple (adoptado): base de las tres reglas
    def singular(w):
        if len(w) < 5 or not w.endswith("S") or w.endswith(("IS", "US")):
            return w
        if w[:-1] in V:
            return w[:-1]
        if w.endswith("ES") and w[:-2] in V and len(w[:-2]) >= 3:
            return w[:-2]
        return w
    k_pl = [" ".join(singular(w) for w in t.split()) for t in k0]
    u_pl = u0.copia()
    n_pl = u_pl.unir_por(k_pl)
    p("\nplural, regla simple (adoptada): {:,} grupos; lo siguiente va ENCIMA del plural".format(
        n_pl))
    Vp = set(w for t in k_pl for w in t.split())

    # --- genero por palabra --------------------------------------------------------------
    pares = []
    for w in Vp:
        for masc, fem in GENERO:
            if w.endswith(fem) and len(w) > len(fem) + 2:
                m = w[:-len(fem)] + masc
                if m in Vp:
                    pares.append((m, w))
    pares = sorted(set(pares))
    a_masc = {f: m for m, f in pares}
    k_ge = [" ".join(a_masc.get(w, w) for w in t.split()) for t in k_pl]
    u = u_pl.copia()
    n_ge = u.unir_por(k_ge)
    df_ge = pd.DataFrame([(m, f, F.get(m, 0), F.get(f, 0), personas(f), "") for m, f in pares],
                         columns=["masculino", "femenino", "titulos_masc", "titulos_fem",
                                  "personas_fem", "aprobar"])
    df_ge = df_ge.sort_values("personas_fem", ascending=False)
    df_ge.to_csv(SAL / "35_pares_genero.csv", index=False, encoding="utf-8")
    p("\nGENERO POR PALABRA (-ERO/-ERA, -OR/-ORA, -IVO/-IVA, -ADO/-ADA, -ICO/-ICA): {:,} pares "
      "A/O; une {:,} grupos mas".format(len(pares), n_ge))
    p("   por terminacion: {}".format(dict(Counter(next(f for m_, f in GENERO if fe.endswith(f))
                                              for _, fe in pares))))
    p("   los 25 con mas personas (lista completa en 35_pares_genero.csv):")
    for _, r in df_ge.head(25).iterrows():
        p("        {:<22} / {:<22} ({} / {} titulos)".format(r.masculino, r.femenino,
                                                          r.titulos_masc, r.titulos_fem))
    sosp = [x for x in pares if x[0].endswith("ICO")]
    p("   -ICO/-ICA, los mas sospechosos de no ser genero (disciplina / persona): {}".format(
        ", ".join("{}/{}".format(m, f) for m, f in sosp[:30])))
    for a, c in e34.ejemplos(u_pl, k_ge, cel, 15):
        p("      {}  ||  {}".format(a, c))

    # --- erratas -------------------------------------------------------------------------
    frecuentes = [w for w in Vp if F.get(w, 0) >= FREC]
    por_fon = defaultdict(list)
    for w in frecuentes:
        por_fon[e34.fonetica(w)].append(w)
    cand, motivo = {}, {}
    for r in Vp:
        Fr = F.get(r, 1)
        opciones = [(0, -F[c], c, "fonetica") for c in por_fon.get(e34.fonetica(r), [])
                    if c != r and F[c] >= RAZON * Fr]
        if len(r) >= 7:
            for c, d, _ in process.extract(r, frecuentes, scorer=DamerauLevenshtein.distance,
                                           score_cutoff=2, limit=5):
                if c != r and F[c] >= RAZON * Fr:
                    opciones.append((d, -F[c], c, "distancia {}".format(d)))
        if opciones:
            _, _, c, como = min(opciones)
            cand[r], motivo[r] = c, como
    desc = defaultdict(list)
    dicc_err = {}
    sens = 0
    for r, c in cand.items():
        es_, ei = emp_sup(r), emp_inf(r)
        if len(r) < 5:
            desc["menos de 5 letras"].append((r, c))
        elif es_ >= REAL:
            desc["palabra real (3+ empresas)"].append((r, c))
            if ei < REAL:
                sens += 1
        elif r in dicc:
            desc["existe en el diccionario"].append((r, c))
        else:
            dicc_err[r] = c
    kt = set(k_pl)
    k_err, aplicados, bloq = [], [], []
    for t in k_pl:
        ws = t.split()
        nuevo = [dicc_err.get(w, w) for w in ws]
        if nuevo != ws:
            tn = " ".join(nuevo)
            (aplicados if tn in kt else bloq).append((t, tn))
            k_err.append(tn if tn in kt else t)
        else:
            k_err.append(t)
    u = u_pl.copia()
    n_err = u.unir_por(k_err)
    p("\nERRATAS PALABRA -> PALABRA (con 'palabra real'): une {:,} grupos mas".format(n_err))
    p("   candidatos: {:,}".format(len(cand)))
    for prot in ("menos de 5 letras", "palabra real (3+ empresas)", "existe en el diccionario"):
        xs = desc[prot]
        p("   descarta '{}': {:,}".format(prot, len(xs)))
        for r, c in [xs[i] for i in rng.choice(len(xs), min(10, len(xs)), replace=False)]:
            p("        {} ({} tit., {} emp.) -> {} ({} tit.)".format(r, F.get(r, 0), emp_sup(r), c,
                                                                  F.get(c, 0)))
    p("   sensibilidad: con la cota INFERIOR de empresas, {:,} palabras dejarian de ser reales"
      .format(sens))
    p("   diccionario: {:,} entradas; titulos corregidos que existen: {:,}; descartados porque el "
      "titulo corregido no existe: {:,}".format(len(dicc_err), len(aplicados), len(bloq)))
    p("   LOS SEIS ERRORES DE `34`:")
    for r, c in ERRORES_34.items():
        if r in dicc_err:
            estado = "SIGUE PASANDO -> {}".format(dicc_err[r])
        elif r in cand:
            prot = next((k for k, xs in desc.items() if any(x[0] == r for x in xs)), "?")
            estado = "bloqueado por '{}' ({} empresas)".format(prot, emp_sup(r))
        else:
            estado = "ya no es candidato"
        p("        {:<14} {}".format(r, estado))
    for r in ("COODINADORA", "PRODUCCI"):
        p("        {:<14} {}".format(r, "se corrige -> {}".format(dicc_err[r]) if r in dicc_err
                                     else "no se corrige ({} empresas)".format(emp_sup(r))))
    p("   20 correcciones aplicadas, al azar:")
    for t, tn in [aplicados[i] for i in rng.choice(len(aplicados), min(20, len(aplicados)),
                                                    replace=False)]:
        p("        {}  ->  {}".format(t, tn))
    usadas = Counter(w for t, tn in aplicados for w, x in zip(t.split(), tn.split()) if w != x)
    dfe = pd.DataFrame([(r, c, F.get(r, 0), F.get(c, 0), emp_sup(r), personas(r), motivo[r],
                         r in usadas, "") for r, c in dicc_err.items()],
                       columns=["rara", "corregida", "titulos_rara", "titulos_corregida",
                                "empresas_rara_cota", "personas_afectadas_cota", "como",
                                "aplica_en_base", "aprobar"])
    dfe.sort_values("personas_afectadas_cota", ascending=False).to_csv(
        SAL / "35_propuestas_erratas.csv", index=False, encoding="utf-8")

    # --- abreviaturas --------------------------------------------------------------------
    pref = defaultdict(list)
    for w in frecuentes:
        for k in range(2, min(7, len(w) - 1)):
            pref[w[:k]].append(w)
    dicc_ab, info_ab, bloq_rango = {}, {}, []

    def expandir(t):
        t2 = re.sub(r"\.(?=[A-Z])", ". ", t)
        res = []
        for tok in t2.split():
            m = re.fullmatch(r"([A-Z]{2,6})(\.?)", tok)
            if m and m.group(1) not in dicc and m.group(1) not in e34.CONECTORES:
                L, punto = m.group(1), m.group(2)
                cs = [w for w in pref.get(L, []) if len(w) >= len(L) + 2]
                if cs:
                    tot = sum(F[w] for w in cs)
                    top = max(cs, key=lambda w: F[w])
                    rivales = [w for w in cs if F[w] / tot >= MIN_CUOTA_RIVAL]
                    if any(es_rango(w) for w in rivales) and not all(es_rango(w)
                                                                     for w in rivales):
                        bloq_rango.append((L + punto, sorted(rivales, key=lambda w: -F[w])[:4]))
                    elif F[top] / tot >= DOMINIO:
                        dicc_ab[L + punto] = top
                        info_ab[L + punto] = F[top] / tot
                        res.append(top)
                        continue
            res.append(tok)
        return " ".join(res)
    k_ab = []
    for c in cel:
        t = e34.K0(expandir(c))
        k_ab.append(" ".join(singular(w) for w in t.split()))
    u = u_pl.copia()
    n_ab = u.unir_por(k_ab)
    p("\nABREVIATURAS (dominio >= 80 %, proteccion de rango): une {:,} grupos mas; {:,} "
      "entradas".format(n_ab, len(dicc_ab)))
    vistos = {}
    for ab, rv in bloq_rango:
        vistos[ab] = rv
    p("   no se expanden por ser ambiguas entre rango y no rango: {:,}".format(len(vistos)))
    for ab, rv in list(vistos.items())[:15]:
        p("        {:<8} {}".format(ab, " / ".join(rv)))
    for a, c in e34.ejemplos(u_pl, k_ab, cel, 20):
        p("      {}  ||  {}".format(a, c))
    p("   las 20 menos dominantes que si se expanden:")
    for ab in sorted(info_ab, key=info_ab.get)[:20]:
        p("        {} -> {}   ({:.0%})".format(ab, dicc_ab[ab], info_ab[ab]))
    pers_ab = defaultdict(int)
    for i, c in enumerate(cel):
        for tok in re.sub(r"\.(?=[A-Z])", ". ", c).split():
            if tok in dicc_ab:
                pers_ab[tok] += per_g[int(g[i])]
    dfa = pd.DataFrame([(a, w, info_ab[a], pers_ab[a], "") for a, w in dicc_ab.items()],
                       columns=["abreviatura", "expansion", "dominio", "personas_afectadas_cota",
                                "aprobar"])
    dfa.sort_values("personas_afectadas_cota", ascending=False).to_csv(
        SAL / "35_propuestas_abreviaturas.csv", index=False, encoding="utf-8")

    p("\nRESUMEN (grupos que une cada regla encima de lo actual y del plural simple)")
    p("   plural simple (adoptado)          {:>6,}".format(n_pl))
    p("   genero por palabra                {:>6,}   ({:,} pares por revisar)".format(n_ge,
                                                                                    len(pares)))
    p("   erratas con 'palabra real'        {:>6,}   ({:,} propuestas por revisar)".format(
        n_err, len(dicc_err)))
    p("   abreviaturas, 80 % y rango        {:>6,}   ({:,} propuestas por revisar)".format(
        n_ab, len(dicc_ab)))
    (SAL / "35_capa0_v2.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
