"""Pares de titulos a distancia de edicion 1 que la fusion semantica NO junta.

    python research/herramientas/erratas.py demo/base_v8.npz

EL HUECO. La fusion usa coseno sobre embeddings con umbral 0,95, y los embeddings NO ven
las letras: `ASITENTE` y `ASISTENTE` puntuan 0,92-0,94 y se quedan como dos celdas
separadas, cada una mas delgada de lo que deberia. Para un dedazo, una distancia de
edicion es trivialmente mejor que cualquier modelo semantico.

COMO SE BUSCAN LOS PARES SIN COMPARAR TODOS CONTRA TODOS. 65.181 titulos son 2.100
millones de pares. Se usa el truco de las variantes por BORRADO (SymSpell): dos cadenas a
distancia <=1 comparten al menos una variante con un caracter borrado. Se indexan las
variantes —unos 1,6 millones de claves— y solo se comparan las que colisionan.

LO QUE NO ES UNA ERRATA, y es la razon de que esto se inspeccione antes de montarse:

  `OPERARIO I` / `OPERARIO II`     distancia 1, y son ESCALONES distintos
  `ANALISTA 1` / `ANALISTA 2`      idem
  `VENDEDOR`   / `VENDEDORA`       distancia 1, mismo trabajo (genero)
  `JEFE`       / `JEFA`            idem

Los dos primeros NO pueden fusionarse: la diferencia es antiguedad, no ortografia, y
juntarlos borraria justo la senal que `18` (la escalera JUNIOR/SENIOR/I/II/III) quiere
medir. Por eso el script separa los candidatos en tres cubos y no propone una regla hasta
haberlos mirado.

NO decide nada. Solo enumera y clasifica para que la regla se escriba mirando datos.
"""
import argparse
import re
import sys
import unicodedata
from collections import defaultdict

import numpy as np

# La consola de Windows es cp1252 y algunas etiquetas traen bytes que no mapea.
# Sin esto el script muere a mitad del listado por un solo caracter raro.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Un caracter que cambia y es DIGITO o numeral romano suelto: es escalon, no dedazo.
_ROMANO = re.compile(r"\b(I{1,3}|IV|V|VI{0,3}|IX|X)\b")
_DIGITO = re.compile(r"\d")


def variantes_por_borrado(s):
    """Todas las cadenas que resultan de borrar UN caracter. Dos cadenas a distancia de
    edicion <=1 comparten al menos una de estas (o una es variante de la otra)."""
    return {s[:i] + s[i + 1:] for i in range(len(s))}


def distancia1(a, b):
    """True si `a` y `b` estan a distancia de edicion exactamente 1 (sustitucion,
    insercion o borrado). Mas barato que un Levenshtein general: solo hay tres formas."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:                                    # sustitucion
        dif = [i for i in range(la) if a[i] != b[i]]
        return len(dif) == 1
    if la > lb:                                     # borrado en a
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _diferencia(a, b):
    """Donde y como difieren dos cadenas a distancia 1.

    Devuelve `("sust", pos, char_a, char_b)` o `("ins", pos, char)` con el caracter que
    sobra en la MAS LARGA. Hace falta para clasificar: el cubo depende de QUE caracter
    cambia, no de cuanto.
    """
    if len(a) == len(b):
        i = next(k for k in range(len(a)) if a[k] != b[k])
        return ("sust", i, a[i], b[i])
    corta, larga = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(corta) and corta[i] == larga[i]:
        i += 1
    return ("ins", i, larga[i])


def clasificar(a, b):
    """En que cubo cae el par. Solo `errata` es candidato claro a fusionarse.

    EL ORDEN IMPORTA. La primera version miraba solo el ULTIMO caracter para detectar
    genero, y por eso mandaba `VENDEDOR`/`VENDEDORA` y `TRABAJADOR AGRICOLA`/`TRABAJADORA
    AGRICOLA` al cubo de erratas — donde no son erratas: son la misma ocupacion en
    femenino, y fusionarlas o no es una decision con consecuencias de equidad, no de
    ortografia. Se clasifican aparte para poder decidirlas aparte.
    """
    if _DIGITO.search(a) or _DIGITO.search(b):
        return "escalon_digito"
    if set(_ROMANO.findall(a)) != set(_ROMANO.findall(b)):
        return "escalon_romano"
    if "/A" in a or "/A" in b or "(A)" in a or "(A)" in b:
        return "genero"           # forma inclusiva: `TRABAJADOR/A`
    na = unicodedata.normalize("NFD", a).encode("ascii", "ignore")
    nb = unicodedata.normalize("NFD", b).encode("ascii", "ignore")
    if na == nb:
        return "tilde"
    d = _diferencia(a, b)
    if d[0] == "sust" and {d[2], d[3]} == {"O", "A"}:
        return "genero"           # OPERARIO / OPERARIA
    if d[0] == "ins" and d[2] == "A":
        return "genero"           # VENDEDOR / VENDEDORA, TRABAJADOR/TRABAJADORA
    if d[0] == "ins" and d[2] == "S":
        return "plural"
    if d[0] == "ins" and not d[2].isalnum():
        return "puntuacion"       # `VENDEDOR.` / `VENDEDOR`
    return "errata"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base", nargs="?", default="demo/base_v8.npz")
    ap.add_argument("--min-largo", type=int, default=8,
                    help="longitud minima; en cadenas cortas un caracter cambia el "
                         "significado (`SUB`/`SUR`) y la distancia deja de informar")
    ap.add_argument("--ver", type=int, default=25, help="ejemplos por cubo")
    a = ap.parse_args()

    # Solo los arrays que hacen falta: `Z` son 65.181x768 y no se usa aqui.
    with np.load(a.base, allow_pickle=True) as z:
        celdas = [str(c) for c in z["celdas"]]
        grupo = z["grupo"] if "grupo" in z.files else np.arange(len(celdas))
        nivel = z["nivel"]
        personas = z["personas"] if "personas" in z.files else np.zeros(len(celdas), int)
        emp = z["emp"]
    n = len(celdas)
    print(f"base: {n:,} titulos   {int(personas.sum()):,} personas (con duplicado por "
          f"grafia)   {len(set(grupo.tolist())):,} grupos tras la fusion semantica")

    # indice de variantes por borrado
    idx = defaultdict(list)
    for i, c in enumerate(celdas):
        if len(c) < a.min_largo:
            continue
        idx[c].append(i)
        for v in variantes_por_borrado(c):
            idx[v].append(i)
    print(f"claves de borrado indexadas: {len(idx):,}")

    vistos, cubos = set(), defaultdict(list)
    for lista in idx.values():
        if len(lista) < 2:
            continue
        for x in range(len(lista)):
            for y in range(x + 1, len(lista)):
                i, j = lista[x], lista[y]
                par = (i, j) if i < j else (j, i)
                if par in vistos:
                    continue
                vistos.add(par)
                ci, cj = celdas[par[0]], celdas[par[1]]
                if not distancia1(ci, cj):
                    continue
                if grupo[par[0]] == grupo[par[1]]:
                    cubos["ya_fusionados"].append(par)
                    continue
                ni, nj = nivel[par[0]], nivel[par[1]]
                if np.isfinite(ni) and np.isfinite(nj) and ni != nj:
                    cubos["distinto_escalon_lexico"].append(par)
                    continue
                cubos[clasificar(ci, cj)].append(par)

    print(f"\npares a distancia 1 (con {a.min_largo}+ caracteres): "
          f"{sum(len(v) for v in cubos.values()):,}\n")
    print(f"  {'cubo':<26} {'pares':>7} {'personas':>12} {'.fusionar?':>12}")
    veredicto = {"errata": "SI", "tilde": "SI", "plural": "SI",
                 "puntuacion": "SI", "genero": "a decidir",
                 "escalon_digito": "NO", "escalon_romano": "NO",
                 "distinto_escalon_lexico": "NO (ya bloqueado)",
                 "ya_fusionados": "ya lo estan"}
    for k in sorted(cubos, key=lambda k: -len(cubos[k])):
        gente = sum(int(personas[i]) + int(personas[j]) for i, j in cubos[k])
        print(f"  {k:<26} {len(cubos[k]):>7,} {gente:>12,} {veredicto.get(k,'?'):>12}")

    for k in ("errata", "genero", "tilde", "plural", "puntuacion",
              "escalon_digito", "escalon_romano"):
        if not cubos.get(k):
            continue
        print(f"\n{'=' * 78}\n{k.upper()}  ({len(cubos[k]):,} pares)\n{'=' * 78}")
        ordenados = sorted(cubos[k],
                           key=lambda p: -(int(personas[p[0]]) + int(personas[p[1]])))
        for i, j in ordenados[:a.ver]:
            print(f"  {celdas[i][:34]:<36} {int(emp[i]):>4}emp {int(personas[i]):>6}per")
            print(f"  {celdas[j][:34]:<36} {int(emp[j]):>4}emp {int(personas[j]):>6}per")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
