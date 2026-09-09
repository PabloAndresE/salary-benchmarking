"""Pares de titulos que sólo se diferencian en el genero gramatical.

    python research/herramientas/genero.py demo/base_v8.npz

POR QUE IMPORTA. Una celda del modelo es una cadena de texto, y las empresas escriben
`ENFERMERA` o `ENFERMERO` segun su convencion de RR.HH. Para que las dos acaben en la
misma celda tiene que superarse el umbral de coseno de 0,95, y ahi el comportamiento sale
arbitrario: `ENFERMERAS`/`ENFERMEROS` lo superan y quedan juntos, `ENFERMERA`/`ENFERMERO`
no y quedan separados. No hay razon de fondo — es donde cayo el coseno.

LA CONSECUENCIA. Dos personas con el mismo oficio reciben referencias distintas segun como
tecleo el titulo su empleador. Y como el titulo es un PROXY DE GENERO, el modelo acaba
segmentando por genero sin que nadie lo haya decidido — justo lo que la regla de "`sexo`
nunca es una variable" existe para impedir. Fusionar no mete el genero en el modelo:
saca el proxy que hoy esta dentro.

LO QUE ESTA HERRAMIENTA NO MIDE. La brecha salarial. Las dos celdas son empleadores
DISTINTOS —`ENFERMERA` tiene 240 empresas y `ENFERMERO` 67, con poco solape— y aqui no hay
control por empresa, tamano, sector ni antiguedad. Para eso esta la descomposicion Oaxaca
de D-011, que usa la columna `sexo`. Lo que se mide aqui es cuanto difieren dos CELDAS que
deberian ser una.

LIMITE CONOCIDO: solo detecta pares a distancia de edicion 1, que en castellano cubre casi
todo el genero de los oficios (O/A y +A). Se escapan formas irregulares.
"""
import argparse
import sys
from collections import defaultdict

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, "src")
from benchmarking.producto.base_referencia import _distancia1  # noqa: E402


def par_genero(a, b):
    """(femenino, masculino) si el par es INEQUIVOCAMENTE de genero, o None.

    Se exige que la vocal este al final de su palabra —admitiendo la S del plural— y se
    excluyen las formas inclusivas (`TRABAJADOR/A`, `CAJERO (A)`), que no son un par sino
    una tercera grafia y merecen tratarse aparte.
    """
    if any(t in a or t in b for t in ("/", "(", ")")):
        return None

    def fin(s, i):
        resto = s[i + 1:]
        j = 0
        while j < len(resto) and resto[j] == "S":
            j += 1
        return j >= len(resto) or not resto[j].isalpha()

    if len(a) == len(b):
        i = next((k for k in range(len(a)) if a[k] != b[k]), None)
        if i is not None and {a[i], b[i]} == {"O", "A"} and fin(a, i):
            return (a, b) if a[i] == "A" else (b, a)
        return None
    corta, larga = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(corta) and corta[i] == larga[i]:
        i += 1
    if larga[i] == "A" and fin(larga, i) and i > 0 and corta[i - 1] in "RNL":
        return (larga, corta)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base", nargs="?", default="demo/base_v8.npz")
    ap.add_argument("--min-emp", type=int, default=10,
                    help="empresas exigidas en AMBOS lados para comparar el pago")
    ap.add_argument("--ver", type=int, default=20)
    a = ap.parse_args()

    with np.load(a.base, allow_pickle=True) as z:
        celdas = [str(c) for c in z["celdas"]]
        grupo = z["grupo"]
        personas, emp, m = z["personas"], z["emp"], z["m"]
    pos = {c: i for i, c in enumerate(celdas)}

    idx = defaultdict(list)
    for i, c in enumerate(celdas):
        if len(c) >= 6:
            idx[c].append(i)
            for k in range(len(c)):
                idx[c[:k] + c[k + 1:]].append(i)

    juntos, sueltos, vistos = [], [], set()
    for lista in idx.values():
        for x in range(len(lista)):
            for y in range(x + 1, len(lista)):
                p = tuple(sorted((lista[x], lista[y])))
                if p in vistos:
                    continue
                vistos.add(p)
                ca, cb = celdas[p[0]], celdas[p[1]]
                if not _distancia1(ca, cb):
                    continue
                g = par_genero(ca, cb)
                if not g:
                    continue
                (juntos if grupo[p[0]] == grupo[p[1]] else sueltos).append(g)

    print(f"base: {len(celdas):,} titulos\n")
    print("LA INCONSISTENCIA: pares de genero, segun donde cayo el coseno")
    print(f"  {'':<34} {'pares':>7} {'etiquetas unicas':>18}")
    for nom, lst in (("ya FUSIONADOS por semantica", juntos),
                     ("SUELTOS, en celdas distintas", sueltos)):
        etq = {t for par in lst for t in par}
        print(f"  {nom:<34} {len(lst):>7,} {len(etq):>18,}")
    tot = len(juntos) + len(sueltos)
    if tot:
        print(f"  {'':<34} {'':>7} el {len(juntos)/tot:.0%} de los pares ya esta junto")

    # .hay patron singular/plural, como sugiere ENFERMERA/ENFERMERAS?
    plural = lambda p: p[0].rstrip().endswith("S") and p[1].rstrip().endswith("S")
    print(f"\n  de los ya fusionados, en plural: "
          f"{sum(plural(p) for p in juntos):,} de {len(juntos):,}")
    print(f"  de los sueltos,        en plural: "
          f"{sum(plural(p) for p in sueltos):,} de {len(sueltos):,}")

    filas = []
    for f, ma in sueltos:
        i, j = pos[f], pos[ma]
        if emp[i] >= a.min_emp and emp[j] >= a.min_emp and np.isfinite(m[i]) \
                and np.isfinite(m[j]):
            filas.append((f, ma, int(emp[i]), int(emp[j]), int(personas[i]),
                          int(personas[j]), float(m[i] - m[j])))
    print(f"\nSUELTOS con {a.min_emp}+ empresas en ambos lados: {len(filas)}")
    if not filas:
        return 0
    d = np.array([r[6] for r in filas])
    print(f"  diferencia del centro (femenino - masculino)")
    print(f"    mediana {np.exp(np.median(d))-1:+.1%}   "
          f"p25/p75 {np.exp(np.quantile(d,.25))-1:+.1%} / "
          f"{np.exp(np.quantile(d,.75))-1:+.1%}")
    print(f"    |desvio| mediano {np.exp(np.median(np.abs(d)))-1:.1%}   "
          f"el femenino paga menos en {(d<0).sum()} de {len(d)} ({(d<0).mean():.0%})")
    print(f"\n  {'femenino':<26} {'masculino':<24} {'empF':>5} {'empM':>5} "
          f"{'perF':>6} {'perM':>6} {'dif':>8}")
    for r in sorted(filas, key=lambda r: -abs(r[6]))[:a.ver]:
        print(f"  {r[0][:25]:<26} {r[1][:23]:<24} {r[2]:>5} {r[3]:>5} {r[4]:>6} "
              f"{r[5]:>6} {np.exp(r[6])-1:>+7.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
