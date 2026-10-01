"""Tres reglas candidatas para la capa 0, a nivel de palabra: plural, erratas y abreviaturas.

DESCRIPTIVO (D-040): sobre `base_v15`, cuantos grupos uniria cada regla ADEMAS de lo que ya
une hoy la base (fusion semantica, erratas de titulo completo D-025, genero D-026) y las reglas
de texto ya acordadas (codigo inicial, puntuacion, grado al final). Nada se adopta aqui.

1. NUMERO (singular / plural)
   a. regla simple: una palabra de 5+ letras que acaba en -S/-ES pasa a su singular si ese
      singular existe como palabra en la base (CLIENTES -> CLIENTE, OPERADORES -> OPERADOR).
      No se tocan las que acaban en -IS / -US (ANALISIS, VIRUS).
   b. lematizacion con spaCy (`es_core_news_md`), en minusculas: en mayusculas falla.
2. ERRATAS PALABRA -> PALABRA
   candidatos: misma clave fonetica del espanol (B/V, S/C/Z, H muda, LL/Y, G/J, QU/C/K), o
   distancia de Damerau <= 2 en palabras de 7+ letras; siempre hacia una palabra al menos 10
   veces mas frecuente (y con 10+ titulos). Protecciones, en este orden:
     - menos de 5 letras;
     - las dos frecuentes (la rara tambien esta en 10+ titulos);
     - la rara existe en el diccionario (espanol o ingles, normalizado como los titulos):
       CASERO no se toca aunque haya mil CAJERO;
     - el titulo corregido tiene que existir ya en la base.
3. ABREVIATURAS (antes de quitar la puntuacion, porque el punto es la pista)
   una palabra de 2-6 letras que no esta en el diccionario y es prefijo de palabras frecuentes
   se expande a la mas frecuente si domina: >= 60 % de la frecuencia de las candidatas con
   punto (SUPERV.), >= 80 % sin punto.

FRECUENCIA de una palabra: en cuantos titulos distintos de la base aparece.

Usa `.venv-texto` (spaCy, pyspellchecker, rapidfuzz), no el `.venv` del cross.

SALIDAS
    34_capa0_palabras.txt        el informe, con ejemplos (lleva titulos)
    34_dicc_erratas.csv          el diccionario propuesto palabra -> palabra
    34_dicc_abreviaturas.csv     el diccionario propuesto de abreviaturas
"""
import importlib.util
import pathlib
import re
import sys
import unicodedata
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
spec = importlib.util.spec_from_file_location("e32", AQUI / "32_fusion_coseno_cross.py")
e32 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e32)

FREC = 10            # una palabra es "frecuente" desde 10 titulos
RAZON = 10           # la correccion va hacia una palabra 10 veces mas frecuente
SEM = 20261008
N_EJ = 20
CONECTORES = {"DE", "DEL", "Y", "E", "EN", "EL", "LA", "LOS", "LAS", "A", "AL", "O", "U",
              "POR", "PARA", "CON"}
rng = np.random.default_rng(SEM)


def sin_tildes(s):
    s = unicodedata.normalize("NFD", s.upper())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def K0(t):
    return e32.sin_grado_final(e32.limpia(t))


class Uniones:
    def __init__(self, grupos):
        self.p = {}
        self.g = grupos

    def raiz(self, x):
        while self.p.get(x, x) != x:
            self.p[x] = self.p.get(self.p[x], self.p[x])
            x = self.p[x]
        return x

    def unir_por(self, claves):
        cub = defaultdict(set)
        for i, k in enumerate(claves):
            if k:
                cub[k].add(self.raiz(int(self.g[i])))
        n = 0
        for rs in cub.values():
            rs = sorted({self.raiz(r) for r in rs})
            for r in rs[1:]:
                a, b = self.raiz(rs[0]), self.raiz(r)
                if a != b:
                    self.p[b] = a
                    n += 1
        return n

    def copia(self):
        u = Uniones(self.g)
        u.p = dict(self.p)
        return u


def ejemplos(u0, claves, cel, n=N_EJ):
    """Pares de titulos que la regla junta y que antes estaban en grupos distintos."""
    cub = defaultdict(list)
    for i, k in enumerate(claves):
        if k:
            cub[k].append(i)
    pares = []
    for ix in cub.values():
        rs = defaultdict(list)
        for i in ix:
            rs[u0.raiz(int(u0.g[i]))].append(i)
        if len(rs) > 1:
            grupos = list(rs.values())
            pares.append((cel[grupos[0][0]], cel[grupos[1][0]]))
    if len(pares) > n:
        pares = [pares[i] for i in rng.choice(len(pares), n, replace=False)]
    return pares


# --- fonetica del espanol -----------------------------------------------------------------
def fonetica(w):
    s = w.replace("CH", "X").replace("LL", "Y")
    s = re.sub(r"QU(?=[EI])", "K", s).replace("QU", "K")
    s = re.sub(r"C(?=[EI])", "S", s)
    s = re.sub(r"G(?=[EI])", "J", s)
    s = s.replace("C", "K").replace("Z", "S").replace("V", "B").replace("W", "B")
    s = s.replace("H", "")
    return re.sub(r"(.)\1+", r"\1", s)


def main():
    from rapidfuzz.distance import DamerauLevenshtein
    from rapidfuzz import process
    from spellchecker import SpellChecker

    b = np.load(RAIZ / "demo" / "base_v15.npz", allow_pickle=True)
    cel = [str(c) for c in b["celdas"]]
    g = b["grupo"].astype(int)
    k0 = [K0(c) for c in cel]
    u0 = Uniones(g)
    n_texto = u0.unir_por(k0)
    grupos_base = len(set(g))
    out = []

    def p(s=""):
        print(s, flush=True)
        out.append(s)

    p("=" * 78)
    p("34 · CAPA 0 A NIVEL DE PALABRA: PLURAL, ERRATAS Y ABREVIATURAS (descriptivo)")
    p("=" * 78)
    p("grupos en base_v15: {:,}; tras las reglas de texto ya acordadas (codigo inicial, "
      "puntuacion, grado): {:,} (une {:,})".format(grupos_base, grupos_base - n_texto, n_texto))
    p("todo lo que sigue se cuenta ENCIMA de eso (y de la fusion semantica y D-025, que estan "
      "en base_v15)")

    F = Counter(w for t in set(k0) for w in set(t.split()))
    V = set(F)
    dicc = set()
    for leng in ("es", "en"):
        dicc |= {sin_tildes(w) for w in SpellChecker(language=leng).word_frequency.dictionary}
    p("vocabulario de la base: {:,} palabras; frecuentes (>= {} titulos): {:,}; diccionario "
      "es+en: {:,}".format(len(V), FREC, sum(1 for w in V if F[w] >= FREC), len(dicc)))
    resumen = {}

    # --- 1a. plural, regla simple --------------------------------------------------------
    def singular(w):
        if len(w) < 5 or not w.endswith("S") or w.endswith(("IS", "US")):
            return w
        if w[:-1] in V:
            return w[:-1]
        if w.endswith("ES") and w[:-2] in V and len(w[:-2]) >= 3:
            return w[:-2]
        return w
    k_pl = [" ".join(singular(w) for w in t.split()) for t in k0]
    u = u0.copia()
    n = u.unir_por(k_pl)
    resumen["1a. plural, regla simple"] = n
    p("\n1a. PLURAL, REGLA SIMPLE: une {:,} grupos mas".format(n))
    for a, c in ejemplos(u0, k_pl, cel):
        p("      {}  ||  {}".format(a, c))

    # --- 1b. plural, spaCy ---------------------------------------------------------------
    import spacy
    nlp = spacy.load("es_core_news_md", disable=["parser", "ner"])
    unicos = sorted(set(k0))
    lema = {}
    for t, doc in zip(unicos, nlp.pipe([x.lower() for x in unicos], batch_size=2000)):
        lema[t] = " ".join(sin_tildes(tok.lemma_) for tok in doc)
    k_sp = [lema[t] for t in k0]
    u = u0.copia()
    n = u.unir_por(k_sp)
    u_simple = u0.copia()
    u_simple.unir_por(k_pl)
    n_extra = u_simple.copia().unir_por(k_sp)
    resumen["1b. lematizacion spaCy"] = n
    p("\n1b. LEMATIZACION spaCy (en minusculas): une {:,} grupos mas; {:,} ademas de la regla "
      "simple".format(n, n_extra))
    p("    (spaCy tambien cambia genero y verbos: parte de lo que une no es numero)")
    for a, c in ejemplos(u0, k_sp, cel):
        p("      {}  ||  {}".format(a, c))
    p("    ejemplos de lo que spaCy junta y la regla simple NO:")
    for a, c in ejemplos(u_simple, k_sp, cel):
        p("      {}  ||  {}".format(a, c))

    # --- 2. erratas palabra -> palabra ---------------------------------------------------
    frecuentes = [w for w in V if F[w] >= FREC]
    por_fon = defaultdict(list)
    for w in frecuentes:
        por_fon[fonetica(w)].append(w)
    cand, motivo = {}, {}
    for r in V:
        if F[r] >= FREC * RAZON:
            continue
        opciones = [(0, -F[c], c, "fonetica") for c in por_fon.get(fonetica(r), [])
                    if c != r and F[c] >= RAZON * F[r]]
        if len(r) >= 7:
            for c, d, _ in process.extract(r, frecuentes, scorer=DamerauLevenshtein.distance,
                                           score_cutoff=2, limit=5):
                if c != r and F[c] >= RAZON * F[r]:
                    opciones.append((d, -F[c], c, "distancia {}".format(d)))
        if opciones:
            _, _, c, como = min(opciones)
            cand[r] = c
            motivo[r] = como
    descartes = defaultdict(list)
    dicc_err = {}
    for r, c in cand.items():
        if len(r) < 5:
            descartes["menos de 5 letras"].append((r, c))
        elif F[r] >= FREC:
            descartes["las dos frecuentes"].append((r, c))
        elif r in dicc:
            descartes["existe en el diccionario"].append((r, c))
        else:
            dicc_err[r] = c
    ktitulos = set(k0)
    k_err, bloq_titulo, aplicados = [], [], []
    for t in k0:
        ws = t.split()
        nuevo = [dicc_err.get(w, w) for w in ws]
        if nuevo != ws:
            tn = " ".join(nuevo)
            if tn in ktitulos:
                k_err.append(tn)
                aplicados.append((t, tn))
            else:
                k_err.append(t)
                bloq_titulo.append((t, tn))
        else:
            k_err.append(t)
    u = u0.copia()
    n = u.unir_por(k_err)
    resumen["2. erratas palabra -> palabra"] = n
    p("\n2. ERRATAS PALABRA -> PALABRA: une {:,} grupos mas".format(n))
    p("   candidatos (palabra rara -> palabra 10x mas frecuente): {:,}  (fonetica {:,}, "
      "distancia {:,})".format(len(cand), sum(1 for m in motivo.values() if m == "fonetica"),
                               sum(1 for m in motivo.values() if m != "fonetica")))
    for prot in ("menos de 5 letras", "las dos frecuentes", "existe en el diccionario"):
        xs = descartes[prot]
        p("   descarta '{}': {:,}".format(prot, len(xs)))
        for r, c in [xs[i] for i in rng.choice(len(xs), min(10, len(xs)), replace=False)]:
            p("        {} ({}) -> {} ({})".format(r, F[r], c, F[c]))
    p("   diccionario resultante: {:,} entradas".format(len(dicc_err)))
    p("   titulos corregidos que ya existen en la base: {:,}; descartados porque el titulo "
      "corregido no existe: {:,}".format(len(aplicados), len(bloq_titulo)))
    for t, tn in [bloq_titulo[i] for i in rng.choice(len(bloq_titulo), min(10, len(bloq_titulo)),
                                                      replace=False)]:
        p("        {}  ->  {}   (no existe)".format(t, tn))
    p("   20 correcciones aplicadas, al azar:")
    for t, tn in [aplicados[i] for i in rng.choice(len(aplicados), min(N_EJ, len(aplicados)),
                                                    replace=False)]:
        p("        {}  ->  {}".format(t, tn))
    usadas = {w for t, tn in aplicados for w, x in zip(t.split(), tn.split()) if w != x}
    dud = sorted(usadas, key=lambda r: F[dicc_err[r]] / F[r])[:30]
    p("   las 30 mas dudosas (frecuencias mas parecidas entre las aplicadas):")
    for r in dud:
        p("        {} ({}) -> {} ({})   x{:.0f}  [{}]".format(r, F[r], dicc_err[r],
                                                             F[dicc_err[r]],
                                                             F[dicc_err[r]] / F[r], motivo[r]))
    p("   errata en dos palabras del mismo titulo, corregida: {:,} titulos".format(
        sum(1 for t, tn in aplicados
            if sum(1 for w, x in zip(t.split(), tn.split()) if w != x) >= 2)))
    pd.DataFrame([(r, c, F[r], F[c], motivo[r], r in usadas) for r, c in dicc_err.items()],
                 columns=["rara", "corregida", "frec_rara", "frec_corregida", "como",
                          "usada"]).to_csv(SAL / "34_dicc_erratas.csv", index=False,
                                           encoding="utf-8")

    # --- 3. abreviaturas (antes de quitar la puntuacion) ---------------------------------
    pref_idx = defaultdict(list)
    for w in frecuentes:
        for k in range(2, min(7, len(w) - 1)):
            pref_idx[w[:k]].append(w)
    dicc_ab, cuota = {}, {}

    def expandir(t):
        t2 = re.sub(r"\.(?=[A-Z])", ". ", t)
        res = []
        for tok in t2.split():
            m = re.fullmatch(r"([A-Z]{2,6})(\.?)", tok)
            if m:
                L, punto = m.group(1), m.group(2)
                if L not in dicc and L not in CONECTORES:
                    cs = [w for w in pref_idx.get(L, []) if len(w) >= len(L) + 2]
                    if cs:
                        top = max(cs, key=lambda w: F[w])
                        sh = F[top] / sum(F[w] for w in cs)
                        if sh >= (0.6 if punto else 0.8):
                            dicc_ab[L + punto] = top
                            cuota[L + punto] = sh
                            res.append(top)
                            continue
            res.append(tok)
        return " ".join(res)
    k_ab = [K0(expandir(c)) for c in cel]
    u = u0.copia()
    n = u.unir_por(k_ab)
    resumen["3. abreviaturas"] = n
    p("\n3. ABREVIATURAS: une {:,} grupos mas; diccionario de {:,} entradas".format(
        n, len(dicc_ab)))
    for a, c in ejemplos(u0, k_ab, cel):
        p("      {}  ||  {}".format(a, c))
    p("   las 20 expansiones mas dudosas (menor dominio de la palabra elegida):")
    for ab in sorted(cuota, key=cuota.get)[:20]:
        p("        {} -> {}   ({:.0%} de las candidatas)".format(ab, dicc_ab[ab], cuota[ab]))
    pd.DataFrame([(a, w, cuota[a]) for a, w in dicc_ab.items()],
                 columns=["abreviatura", "expansion", "dominio"]).to_csv(
        SAL / "34_dicc_abreviaturas.csv", index=False, encoding="utf-8")

    # --- todas juntas ----------------------------------------------------------------------
    k_todo = []
    for c in cel:
        t = K0(expandir(c))
        ws = [singular(w) for w in t.split()]
        tn = " ".join(dicc_err.get(w, w) for w in ws)
        k_todo.append(tn if tn in ktitulos or tn == " ".join(ws) else " ".join(ws))
    u = u0.copia()
    n = u.unir_por(k_todo)
    p("\nRESUMEN (grupos que une cada regla, sola, encima de lo actual)")
    for k_, v in resumen.items():
        p("   {:<34} {:>6,}".format(k_, v))
    p("   {:<34} {:>6,}   (abreviaturas + plural simple + erratas)".format("las tres juntas", n))
    (SAL / "34_capa0_palabras.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
