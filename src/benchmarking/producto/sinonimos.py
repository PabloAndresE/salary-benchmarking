"""Sinonimos aprobados por el autor (D-046, D-047): solo para el buscador de cargos, no para la base.

Medido: unir los grupos de la base por sinonimos empeora las bandas (juntan grupos grandes y
heterogeneos que ya tenian datos propios). Lo que si resuelven es ENCONTRAR el cargo: escribir
`CONDUCTOR` en el formulario tiene que sugerir `CHOFER`, y el parecido por embedding no lo hace
(`CHOFER` / `CONDUCTOR` esta en el puesto 1.312 de los vecinos de Vertex).
"""
import csv
import pathlib

DATOS = pathlib.Path(__file__).resolve().parent / "datos"
VERSION = "v2"   # 2026-10-10: rondas 1 y 2 aprobadas por el autor (D-070: solo buscador)


def cargar_pares(version=VERSION, base=DATOS):
    """Los pares aprobados de `version`; lista vacia si no estan."""
    f = base / "sinonimos_{}".format(version) / "sinonimos.csv"
    if not f.exists():
        return []
    with open(f, encoding="utf-8") as fh:
        return [(r["titulo_a"], r["titulo_b"]) for r in csv.DictReader(fh)]


def grupo_de(base, titulo):
    """El grupo de la base de un titulo: tal cual, o por la capa 0 si la base la tiene."""
    i = base.idx.get(str(titulo))
    if i is None and getattr(base, "capa0", None) is not None:
        i = base._por_capa0(str(titulo))
    return None if i is None else int(base.grupo[i])


def por_grupo(base, pares):
    """grupo -> conjunto de grupos sinonimos (simetrico), sobre la base cargada."""
    out = {}
    for a, b in pares:
        ga, gb = grupo_de(base, a), grupo_de(base, b)
        if ga is None or gb is None or ga == gb:
            continue
        out.setdefault(ga, set()).add(gb)
        out.setdefault(gb, set()).add(ga)
    return out


def cargar_consulta(version=VERSION, base=DATOS):
    """(escrito, cargo_base) de `consulta.csv`: lo que alguien teclea -> un cargo de la base."""
    f = base / "sinonimos_{}".format(version) / "consulta.csv"
    if not f.exists():
        return []
    with open(f, encoding="utf-8") as fh:
        return [(r["escrito"].strip().upper(), r["cargo_base"].strip().upper())
                for r in csv.DictReader(fh) if r.get("escrito") and r.get("cargo_base")]


def de_consulta(base, pares):
    """clave del texto escrito (atomo de la capa 0, o el texto) -> grupo de la base."""
    out = {}
    for escrito, cargo in pares:
        g = grupo_de(base, cargo)
        if g is not None:
            out[clave(base, escrito)] = g
    return out


def clave(base, texto):
    c0 = getattr(base, "capa0", None)
    return c0.atomo(str(texto)) if c0 is not None else str(texto).strip().upper()


# D-070: reglas de palabras del autor (2026-10-10). Se aplican al titulo antes de buscar y generan pares entre
# titulos de la base que coinciden despues de aplicarlas.
REGLAS_PALABRAS = (
    (r"(?<![A-Z])RR\.?\s?HH\.?(?![A-Z])", "RECURSOS HUMANOS"),
    (r"(?<![A-Z])TALENTO HUMANO(?![A-Z])", "RECURSOS HUMANOS"),
    (r"(?<![A-Z])TECNOLOGIAS? DE (LA )?INFORMACION(?![A-Z])", "SISTEMAS"),
    (r"(?<![A-Z])T\.?I\.?(?![A-Z])", "SISTEMAS"),
    (r"(?<![A-Z])CONDUCTOR(A|ES)?(?![A-Z])", "CHOFER"),
)


def canonico(titulo):
    """El titulo con las reglas de palabras de D-070 aplicadas (o el mismo)."""
    import re
    t = str(titulo).upper()
    for pat, rep in REGLAS_PALABRAS:
        t = re.sub(pat, rep, t)
    return re.sub(r"\s+", " ", t).strip()


def pares_por_reglas(titulos):
    """Pares (a, b) de titulos de la base que coinciden despues de `canonico`."""
    por = {}
    for t in titulos:
        c = canonico(t)
        if c != t:
            por.setdefault(c, []).append(t)
    tset = set(titulos)
    out = []
    for c, ts in por.items():
        if c in tset:
            out += [(t, c) for t in ts]
        else:
            out += [(ts[0], t) for t in ts[1:]]
    return out
