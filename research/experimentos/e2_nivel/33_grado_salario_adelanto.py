"""Criterio A de D-040, ADELANTO entre empresas: ¿el grado mayor paga mas? NO DECIDE.

El criterio (registrado en D-040, commit 2c620e8) decide con la version DENTRO DE EMPRESA, que
necesita los datos crudos de BigQuery y se corre al reconstruir la base. Esto es solo un adelanto
con `base_v15`: compara el centro de cada celda (log del sueldo, mezcla de empresas), asi que una
escala interna de grados se diluye entre empresas que no la comparten. Sirve para anticipar, no
para decidir.

Familias: titulos identicos tras la limpieza salvo un grado ORDINAL al final (1-9, I-X; el
romano se pasa a numero). Celdas con al menos MIN_EMP empresas. Para cada par de grados
consecutivos de una familia: diferencia de centros (grado mayor - grado menor). Media por
familia, y media entre familias con IC 95 % por bootstrap de familias. Los tres resultados del
criterio se aplican aqui solo como lectura. Las letras se reportan aparte.

SALIDA: 33_grado_salario_adelanto.txt (agregados, sin titulos)
"""
import importlib.util
import pathlib
import sys
from collections import defaultdict

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
spec = importlib.util.spec_from_file_location("e32", AQUI / "32_fusion_coseno_cross.py")
e32 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e32)

MIN_EMP = 3
B = 10_000
SEM = 20261007
ROM = {r: i + 1 for i, r in enumerate(["I", "II", "III", "IV", "V", "VI", "VII", "VIII",
                                        "IX", "X"])}


def grado_final(t):
    ws = t.split()
    if not ws:
        return None, None
    w = ws[-1]
    if w.isdigit() and len(w) <= 2 and 1 <= int(w) <= 9:
        v = int(w)
    elif w in ROM:
        v = ROM[w]
    elif len(w) == 1 and w.isalpha() and w not in "EYOU":
        return " ".join(ws[:-1]), "letra:" + w
    else:
        return None, None
    base = ws[:-1]
    if base and base[-1] in ("NIVEL", "GRADO", "CATEGORIA", "LEVEL", "CAT"):
        base = base[:-1]
    return " ".join(base), v


def main():
    b = np.load(RAIZ / "demo" / "base_v15.npz", allow_pickle=True)
    cel = [str(c) for c in b["celdas"]]
    m, emp, grupo = b["m"], b["emp"], b["grupo"]
    fam, letras = defaultdict(dict), defaultdict(dict)
    for i, c in enumerate(cel):
        if emp[i] < MIN_EMP:
            continue
        base, v = grado_final(e32.limpia(c))
        if base is None:
            continue
        if isinstance(v, int):
            if v not in fam[base] or emp[i] > emp[fam[base][v]]:
                fam[base][v] = i
        else:
            letras[base][v] = i
    difs, mismos_grupo = [], [0]
    for base, gs in fam.items():
        vs = sorted(gs)
        if len(vs) < 2:
            continue
        # `m` es del GRUPO: dos grados ya fusionados por coseno comparten centro y su
        # diferencia es 0 por construccion. Solo cuentan los pares en grupos distintos.
        d = [float(m[gs[b_]] - m[gs[a]]) for a, b_ in zip(vs[:-1], vs[1:])
             if grupo[gs[a]] != grupo[gs[b_]]]
        if d:
            difs.append(np.mean(d))
        else:
            mismos_grupo[0] += 1
    difs = np.array(difs)
    rng = np.random.default_rng(SEM)
    bs = np.array([rng.choice(difs, len(difs)).mean() for _ in range(B)])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    media = difs.mean()
    pct = lambda x: np.exp(x) - 1
    if pct(media) >= 0.05 and lo > 0:
        lectura = "ESCALON"
    elif pct(lo) > -0.05 and pct(hi) < 0.05:
        lectura = "EQUIVALENTE"
    else:
        lectura = "INCONCLUSO"
    n_let = sum(1 for g in letras.values() if len(g) >= 2)
    lineas = [
        "=" * 78,
        "33 · CRITERIO A DE D-040, ADELANTO ENTRE EMPRESAS (NO DECIDE)",
        "=" * 78,
        "familias con >= 2 grados ordinales al final en grupos distintos (celdas con >= {} empresas): {}".format(
            MIN_EMP, len(difs)),
        "diferencia media (grado mayor - menor, consecutivos): {:+.1%}   IC95 [{:+.1%}, {:+.1%}]"
        .format(pct(media), pct(lo), pct(hi)),
        "familias donde el grado mayor paga mas: {:.0%}".format((difs > 0).mean()),
        "familias excluidas porque sus grados ya estaban en el mismo grupo (mismo centro): {}"
        .format(mismos_grupo[0]),
        "lectura con los tres resultados del criterio: {}   (solo adelanto)".format(lectura),
        "familias con >= 2 letras al final (no deciden): {}".format(n_let),
        "",
        "La version que decide compara las MISMAS empresas con los dos grados (BigQuery).",
    ]
    (SAL / "33_grado_salario_adelanto.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))


if __name__ == "__main__":
    main()
