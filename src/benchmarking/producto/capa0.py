"""Capa 0: el titulo de cargo convertido en su ATOMO, con transformaciones de texto. D-040.

POR QUE UNA SOLA FUNCION. La capa 0 decide que dos titulos son el mismo antes de que los mire
nadie: ni el cross-encoder ni el clustering ven lo que ella junta. Por eso solo hace
transformaciones de TEXTO, deterministas y auditables —nada semantico: eso lo decide el
cross—, y por eso es UNA funcion que se usa igual al construir la base y al consultar el
titulo de un cliente. Antes no era asi: la fusion por errata (D-025) solo existia al
construir, y un `VENDEROR` de un cliente caia por analogia.

EL ORDEN, sobre el titulo ya normalizado (`_norm`: mayusculas, sin tildes, espacios):

    1. ABREVIATURAS, antes de quitar la puntuacion (el punto es la pista: `SUPERV.`).
       Diccionario aprobado por el autor.
    2. GRADO AL FINAL. Sobre las palabras ORIGINALES, con sus guardas: una letra junto a `&`
       es una sigla (`M & R`), tras `LICENCIA`/`TIPO` es un tipo, la `A` solo al final.
       - LETRAS (`AYUDANTE A` = `AYUDANTE B` = `AYUDANTE`): se borran, por D-041, decision
         del autor que se aparta del criterio A (las celdas sin fusionar quedan muy chicas).
         `I`, `V` y `X` cuentan como romanos, no como letras.
       - NUMEROS (`AUXILIAR 2`, `QUIMICO II`): NO se borran. El criterio A de D-040 midio que
         son un escalon (+6,9 % dentro de empresa). `grado=True` los borraria; queda apagado.
       Ademas, el CANDADO DE GRADO (`compatibles`): dos titulos con numero de grado distinto
       nunca van al mismo grupo, aunque otra pasada o el cross-encoder digan que si.
    3. LIMPIEZA: fuera el codigo o la numeracion al inicio (`09.01 …`, `1. …`, `3 …`, que es
       formato de planilla) y la puntuacion.
    4. PLURAL, regla simple: -S/-ES fuera si el singular existe en la base; no -IS/-US. El
       mapa sale del vocabulario al construir y se guarda con la base.
    5. ERRATAS palabra -> palabra, diccionario aprobado. Solo si el titulo corregido ya
       existe en la base (sin esto, una correccion dudosa fabricaria titulos nuevos).
    6. GENERO por palabra (-ERO/-ERA, -OR/-ORA, -IVO/-IVA, -ADO/-ADA, -ICO/-ICA),
       diccionario aprobado.

Los diccionarios (erratas, abreviaturas, genero) los proponen reglas y los APRUEBA el autor;
viven versionados en `datos/capa0_<version>/` con solo las filas aprobadas.
`proponer_erratas` es la regla que propone, con sus protecciones (menos de 5 letras, el
diccionario de espanol e ingles: CASERO no se toca aunque haya mil CAJERO).
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..ingesta.composicion import _norm

VERSION = "v1"
DATOS = pathlib.Path(__file__).resolve().parent / "datos"

ROMANOS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
ANTES_DE_GRADO = {"NIVEL", "LEVEL", "GRADO", "CATEGORIA", "CAT"}
NO_LETRA_GRADO = {"E", "Y", "O", "U"}
NO_GRADO_DESPUES = {"LICENCIA", "TIPO"}
_PREFIJO = re.compile(r"^(?:[\d.\-*+#'\[\]()]+\s*|\d+[.\-]?\d*\s+)+")
_PUNTO_PEGADO = re.compile(r"\.(?=[A-Z])")


def _es_grado_token(tok, previo, es_ultimo):
    t = tok.strip("()#.")
    if t.isdigit() and len(t) <= 2 and 1 <= int(t) <= 9:
        return True
    if t in ROMANOS:
        return True
    if (re.fullmatch(r"\(?[A-Z]\)?", tok) and t not in NO_LETRA_GRADO
            and previo != "&" and previo not in NO_GRADO_DESPUES
            and (t != "A" or es_ultimo)):
        return True
    return False


def _es_letra_grado(tok, previo, es_ultimo):
    t = tok.strip("()")
    return (bool(re.fullmatch(r"\(?[A-Z]\)?", tok)) and t not in NO_LETRA_GRADO
            and t not in ROMANOS and previo != "&" and previo not in NO_GRADO_DESPUES
            and (t != "A" or es_ultimo))


def quitar_letra_final(titulo):
    """`AYUDANTE DE MANTENIMIENTO B` -> `AYUDANTE DE MANTENIMIENTO` (D-041). Solo letras;
    los numeros y los romanos se quedan."""
    toks = titulo.split()
    while len(toks) > 1 and _es_letra_grado(toks[-1], toks[-2], True):
        toks = toks[:-1]
        if len(toks) > 1 and toks[-1] in ANTES_DE_GRADO:
            toks = toks[:-1]
    return " ".join(toks)


_NUM_GRADO = re.compile(r"^\(?#?([1-9])\)?\.?$")
_NUM_PEGADO = re.compile(r"^[A-Z]{3,}([1-9])$")


def grado_numerico(titulo):
    """Los numeros de grado del titulo: digitos 1-9 sueltos (o pegados al final de una
    palabra: `TECNICO2`) y romanos II-X sueltos (y `I` al final), en cualquier posicion
    salvo el codigo de planilla del inicio. Conjunto vacio si no hay ninguno."""
    t = _PREFIJO.sub("", _norm(titulo).strip())
    toks = t.split()
    out = set()
    for k, tok in enumerate(toks):
        m = _NUM_GRADO.match(tok) or _NUM_PEGADO.match(tok)
        if m:
            out.add(int(m.group(1)))
            continue
        x = tok.strip("()#.")
        if x in ROMANOS and (x != "I" or k == len(toks) - 1) and k > 0:
            out.add(ROMANOS.index(x) + 1)
    return frozenset(out)


def compatibles(a, b):
    """CANDADO DE GRADO (D-041): False si los dos titulos tienen numero de grado y es
    distinto. `AUXILIAR 1` / `AUXILIAR 2` no; `AUXILIAR` / `AUXILIAR 2` si (el numero en un
    solo titulo no se sabe a que grado equivale)."""
    ga, gb = grado_numerico(a), grado_numerico(b)
    return not (ga and gb and ga != gb)


def quitar_grado_final(titulo):
    """`AUXILIAR DE COCINA 2` -> `AUXILIAR DE COCINA`. Sobre palabras separadas por espacios
    y ANTES de quitar la puntuacion: `COORDINADOR M & R` conserva su sigla."""
    toks = titulo.split()
    while len(toks) > 1:
        previo = toks[-2]
        if not _es_grado_token(toks[-1], previo, True):
            break
        toks = toks[:-1]
        if len(toks) > 1 and toks[-1] in ANTES_DE_GRADO:
            toks = toks[:-1]
    return " ".join(toks)


def limpiar(titulo):
    """Sin codigo o numeracion al inicio y sin puntuacion. Si no queda ninguna letra, se
    devuelve el titulo tal cual (no se borra un titulo entero)."""
    s = _PREFIJO.sub("", titulo.strip())
    if not re.search(r"[A-Z]", s):
        s = titulo
    return " ".join(re.sub(r"[^\w\s]|_", " ", s).split())


def expandir_abreviaturas(titulo, abreviaturas):
    if not abreviaturas:
        return titulo
    return " ".join(abreviaturas.get(t, t)
                    for t in _PUNTO_PEGADO.sub(". ", titulo).split())


def mapa_plural(vocabulario):
    """palabra en plural -> singular, si el singular existe en el vocabulario de la base."""
    V = set(vocabulario)
    m = {}
    for w in V:
        if len(w) < 5 or not w.endswith("S") or w.endswith(("IS", "US")):
            continue
        if w[:-1] in V:
            m[w] = w[:-1]
        elif w.endswith("ES") and w[:-2] in V and len(w[:-2]) >= 3:
            m[w] = w[:-2]
    return m


@dataclass
class Capa0:
    """La capa 0 de una base: sus reglas, sus diccionarios y su version."""
    plural: dict = field(default_factory=dict)
    erratas: dict = field(default_factory=dict)
    abreviaturas: dict = field(default_factory=dict)
    genero: dict = field(default_factory=dict)
    grado: bool = False            # numeros: apagado (criterio A de D-040: son escalon)
    letras: bool = True            # letras: se fusionan (D-041)
    version: str = VERSION
    existentes: set = field(default_factory=set, repr=False)

    def _sin_erratas(self, titulo):
        t = expandir_abreviaturas(_norm(titulo), self.abreviaturas)
        if self.grado:
            t = quitar_grado_final(t)
        elif self.letras:
            t = quitar_letra_final(t)
        t = limpiar(t)
        return [self.plural.get(w, w) for w in t.split()]

    def atomo(self, titulo):
        """El atomo del titulo. Igual al construir y al consultar."""
        ws = self._sin_erratas(titulo)
        if self.erratas:
            corr = [self.erratas.get(w, w) for w in ws]
            if corr != ws and " ".join(self.genero.get(w, w) for w in corr) in self.existentes:
                ws = corr
        return " ".join(self.genero.get(w, w) for w in ws)

    def preparar(self, titulos):
        """Al construir: el mapa de plural sale del vocabulario de la base, y `existentes`
        son los atomos de la base sin aplicar erratas (para exigir que la correccion lleve a
        un titulo que ya existe)."""
        vocab = {w for t in titulos for w in limpiar(_norm(t)).split()}
        if not self.plural:
            self.plural = mapa_plural(vocab)
        erratas, self.erratas = self.erratas, {}
        self.existentes = {self.atomo(t) for t in titulos}
        self.erratas = erratas
        return self

    # --- persistencia: va dentro del .npz de la base ------------------------------------
    def a_json(self):
        return json.dumps({"version": self.version, "grado": self.grado,
                           "letras": self.letras,
                           "plural": self.plural, "erratas": self.erratas,
                           "abreviaturas": self.abreviaturas, "genero": self.genero},
                          ensure_ascii=False, sort_keys=True)

    @classmethod
    def de_json(cls, s, titulos):
        d = json.loads(s)
        c = cls(plural=d["plural"], erratas=d["erratas"], abreviaturas=d["abreviaturas"],
                genero=d["genero"], grado=d["grado"], version=d["version"],
                letras=d.get("letras", False))
        erratas, c.erratas = c.erratas, {}
        c.existentes = {c.atomo(t) for t in titulos}
        c.erratas = erratas
        return c


def cargar_diccionarios(version=VERSION, base=DATOS):
    """Los diccionarios APROBADOS de una version: erratas, abreviaturas y genero."""
    carpeta = base / "capa0_{}".format(version)

    def leer(nombre, a, b):
        f = carpeta / nombre
        if not f.exists():
            return {}
        with open(f, encoding="utf-8") as fh:
            return {r[a]: r[b] for r in csv.DictReader(fh)}
    return {"erratas": leer("erratas.csv", "rara", "corregida"),
            "abreviaturas": leer("abreviaturas.csv", "abreviatura", "expansion"),
            "genero": leer("genero.csv", "femenino", "masculino")}


def nueva(version=VERSION, grado=False, letras=True, base=DATOS):
    """Una capa 0 con los diccionarios aprobados de `version`."""
    return Capa0(grado=grado, letras=letras, version=version,
                 **cargar_diccionarios(version, base))


# --- la regla que PROPONE erratas (el autor aprueba) ------------------------------------
def fonetica(w):
    """Clave fonetica del espanol: B/V, S/C/Z, H muda, LL/Y, G/J, QU/C/K."""
    s = w.replace("CH", "X").replace("LL", "Y")
    s = re.sub(r"QU(?=[EI])", "K", s).replace("QU", "K")
    s = re.sub(r"C(?=[EI])", "S", s)
    s = re.sub(r"G(?=[EI])", "J", s)
    s = s.replace("C", "K").replace("Z", "S").replace("V", "B").replace("W", "B")
    s = s.replace("H", "")
    return re.sub(r"(.)\1+", r"\1", s)


def _damerau(a, b):
    d = {(i, -1): i + 1 for i in range(-1, len(a))}
    d.update({(-1, j): j + 1 for j in range(-1, len(b))})
    for i in range(len(a)):
        for j in range(len(b)):
            c = 0 if a[i] == b[j] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + c)
            if i and j and a[i] == b[j - 1] and a[i - 1] == b[j]:
                d[i, j] = min(d[i, j], d[i - 2, j - 2] + 1)
    return d[len(a) - 1, len(b) - 1]


def proponer_erratas(frecuencias: Counter, diccionario: set, frec=10, razon=10):
    """palabra rara -> palabra al menos `razon` veces mas frecuente (y en `frec`+ titulos),
    si comparten clave fonetica o (en 7+ letras) estan a distancia de Damerau <= 2.
    Protecciones: menos de 5 letras, y la palabra existe en `diccionario` (normalizado como
    los titulos). Devuelve (propuestas, motivos de descarte)."""
    frecuentes = [w for w, n in frecuencias.items() if n >= frec]
    por_fon = defaultdict(list)
    for w in frecuentes:
        por_fon[fonetica(w)].append(w)
    propuestas, descartes = {}, Counter()
    for r, fr in frecuencias.items():
        op = [(0, -frecuencias[c], c) for c in por_fon.get(fonetica(r), [])
              if c != r and frecuencias[c] >= razon * fr]
        if len(r) >= 7:
            op += [(d, -frecuencias[c], c) for c in frecuentes
                   if c != r and abs(len(c) - len(r)) <= 2 and frecuencias[c] >= razon * fr
                   and (d := _damerau(r, c)) <= 2]
        if not op:
            continue
        if len(r) < 5:
            descartes["menos de 5 letras"] += 1
        elif r in diccionario:
            descartes["existe en el diccionario"] += 1
        else:
            propuestas[r] = min(op)[2]
    return propuestas, descartes
