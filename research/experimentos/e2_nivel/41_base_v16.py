"""La base v16 (D-040, D-041) y su informe de cambios regla por regla, contra la v15.

LA v16 = la v15 con tres cambios, nada mas:
    - capa 0 v1 (`capa0.nueva("v1")`): abreviaturas, plural, erratas y genero aprobados por el
      autor, y las LETRAS de grado al final fuera (D-041). Los numeros se quedan.
    - sin fusion por coseno (`umbral_fusion=None`, criterio B de D-040);
    - candados con el nivel de la rubrica (criterio C) y el CANDADO DE GRADO numerico (D-041).
Lo demas (erratas D-025/D-031 y genero D-026 como pasadas, datos, embeddings, padron) es igual.

DATOS: los de la v15: `nomina_features`, `en_clean`, 2024-2025, con el objetivo y el filtro de
`evaluacion.datos`. EMBEDDINGS: los vectores de `demo/base_v15.npz` (Vertex, la misma cache que
`demo/emb_base.npz`); si aparece un titulo que no esta, se para.

INFORME (sin RUC ni sueldos individuales: solo agregados y titulos):
    1. cuantos grupos y cuanta gente por grupo, v15 contra v16;
    2. lo que aporta cada regla de la capa 0: titulos que dejan de estar solos si la regla esta
       (ablacion: la capa 0 entera contra la capa 0 sin esa regla);
    3. lo que aportan las pasadas de errata y genero, y lo que bloquea el candado de grado;
    4. % de personas que cambian de grupo (su titulo queda junto a otros titulos que en la v15);
    5. el desplazamiento de cada banda (p10/p25/p50/p75 en exp(dif) - 1), mediana entre los
       titulos que cambian, y cuantos titulos y personas tienen alguna banda que se mueve > 5 %.

    python3 41_base_v16.py          (Python del sistema: BigQuery; `gcloud auth login`)

SALIDAS: demo/base_v16.npz, salidas/41_base_v16.txt
"""
import collections
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.evaluacion import datos  # noqa: E402
from benchmarking.producto import capa0 as c0mod  # noqa: E402
from benchmarking.producto.base_referencia import (BaseReferencia, _fusionar_capa0,  # noqa
                                                   _fusionar_erratas, _fusionar_genero)
from benchmarking.producto.nivel import nivel_rubrica  # noqa: E402

PROYECTO, DATASET = "act-cicd-stage-prueba", "benchmarking_tesis"
SBU = {2024: 460.0, 2025: 470.0}
V15 = RAIZ / "demo" / "base_v15.npz"
V16 = RAIZ / "demo" / "base_v16.npz"
UMBRAL_BANDA = 0.05
BANDAS = ("p10", "p25", "p50", "p75")


class _Ajustes:
    @staticmethod
    def get_sbu(anio):
        return SBU.get(int(anio), np.nan)


def cargar_marco():
    from google.cloud import bigquery
    cli = bigquery.Client(project=PROYECTO)
    m = datos.cargar_marco(cli, PROYECTO, DATASET, anios=(2024, 2025))
    return datos.marco_evaluable(datos.agregar_objetivo(m, _Ajustes))


def embeddings(celdas, b15):
    emb = {str(c): z for c, z in zip(b15["celdas"], b15["Z"])}
    faltan = [c for c in celdas if c not in emb]
    if faltan:
        from benchmarking.evaluacion.embeddings import CacheArchivo
        cache = CacheArchivo(str(RAIZ / "demo" / "emb_base.npz"))
        for c in list(faltan):
            v = cache.leer(("text-multilingual-embedding-002", "CLUSTERING", c))
            if v is not None:
                emb[c] = v
        faltan = [c for c in celdas if c not in emb]
    if faltan:
        raise SystemExit("ALTO: {} titulos sin embedding (p. ej. {}). Hay que embeberlos con "
                         "Vertex antes.".format(len(faltan), faltan[:5]))
    return emb


def miembros(celdas, grupo):
    """titulo -> frozenset de los titulos de su grupo."""
    por_g = collections.defaultdict(list)
    for c, g in zip(celdas, grupo):
        por_g[int(g)].append(c)
    return {c: frozenset(por_g[int(g)]) for c, g in zip(celdas, grupo)}


def solos_unidos(atomos):
    """Titulos que comparten atomo con otro titulo."""
    cnt = collections.Counter(atomos)
    return sum(1 for a in atomos if cnt[a] > 1)


def main():
    t0 = time.time()
    out = []

    def p(s=""):
        print(s, flush=True)
        out.append(s)

    marco = cargar_marco()
    celdas = sorted(set(marco["cargo_norm"].astype(str)))
    per_t = marco.groupby(marco["cargo_norm"].astype(str))["id_hash"].nunique()
    b15 = np.load(V15, allow_pickle=True)
    emb = embeddings(celdas, b15)

    p("=" * 78)
    p("41 · BASE v16: CAPA 0 v1, SIN FUSION POR COSENO, CANDADO DE GRADO (D-040, D-041)")
    p("=" * 78)
    p("filas evaluables 2024-2025: {:,}; titulos: {:,}; personas: {:,}".format(
        len(marco), len(celdas), int(marco["id_hash"].nunique())))
    c15 = [str(c) for c in b15["celdas"]]
    p("titulos de la v15: {:,}; en comun: {:,}".format(len(c15), len(set(c15) & set(celdas))))

    capa0 = c0mod.nueva("v1")
    print("\nconstruyendo la v16...")
    b16 = BaseReferencia.construir(marco, emb, _Ajustes.get_sbu, umbral_fusion=None,
                                   capa0=capa0)
    b16.guardar(V16)
    p("guardada en demo/base_v16.npz ({:.0f} s)".format(time.time() - t0))

    # --- 1. grupos ----------------------------------------------------------------------
    g15 = dict(zip(c15, b15["grupo"].astype(int)))
    g16 = dict(zip(b16.celdas, np.asarray(b16.grupo).astype(int)))
    comunes = [c for c in celdas if c in g15 and c in g16]
    p("\n1. GRUPOS")
    for nom, g in (("v15", g15), ("v16", g16)):
        gs = pd.Series({c: g[c] for c in comunes})
        tam = gs.value_counts()
        p("   {}: {:,} grupos para {:,} titulos; titulos en grupos de 2+: {:,}; grupo mas "
          "grande: {} titulos".format(nom, gs.nunique(), len(gs),
                                      int(tam[tam > 1].sum()), int(tam.max())))

    # --- 2. lo que aporta cada regla de la capa 0 (ablacion) ---------------------------
    p("\n2. CAPA 0 v1, REGLA POR REGLA (titulos que comparten atomo con otro titulo)")
    llenos = solos_unidos([capa0.atomo(c) for c in celdas])
    p("   capa 0 entera: {:,} titulos unidos".format(llenos))
    def variante(**cambio):
        kw = dict(plural=dict(capa0.plural), erratas=capa0.erratas,
                  abreviaturas=capa0.abreviaturas, genero=capa0.genero, letras=True,
                  version="v1")
        kw.update(cambio)
        if not kw["plural"]:
            kw["plural"] = {"\0": "\0"}          # vacio no: `preparar` lo recalcularia
        return c0mod.Capa0(**kw).preparar(celdas)

    for nom, cambio in (("abreviaturas", dict(abreviaturas={})), ("plural", dict(plural={})),
                        ("erratas (diccionario)", dict(erratas={})),
                        ("genero (diccionario)", dict(genero={})),
                        ("letras de grado (D-041)", dict(letras=False))):
        n = solos_unidos([variante(**cambio).atomo(x) for x in celdas])
        p("   sin {:<26} {:>7,} unidos   aporta {:>6,}".format(nom, n, llenos - n))
    n = solos_unidos([variante(abreviaturas={}, plural={}, erratas={}, genero={},
                               letras=False).atomo(x) for x in celdas])
    p("   solo puntuacion y codigo inicial: {:,} unidos".format(n))
    p("   (las aportaciones no suman el total: un titulo puede necesitar dos reglas)")

    # --- 3. pasadas y candado -----------------------------------------------------------
    p("\n3. PASADAS DE TEXTO Y CANDADO DE GRADO (desde cero, sin recuento de empresas fresco)")
    atomos = [capa0.atomo(c) for c in celdas]
    gnum = [c0mod.grado_numerico(c) for c in celdas]
    niv = np.array([nivel_rubrica(c) or np.nan for c in celdas], dtype=float)
    emp_t = marco.groupby(marco["cargo_norm"].astype(str))["empresa_ruc"].nunique()
    for nom, gr in (("con candado", gnum), ("sin candado", None)):
        g, n_c0 = _fusionar_capa0(atomos, np.arange(len(celdas)), grados=gr)
        emp_g = collections.Counter()
        for c, k in zip(celdas, g):
            emp_g[int(k)] += int(emp_t.get(c, 0))
        g, n_err = _fusionar_erratas(celdas, g, niv, dict(emp_g), grados=gr)
        g, fm = _fusionar_genero(celdas, g, niv, dict(emp_g), grados=gr)
        p("   {}: capa 0 {:,} uniones; errata {:,}; genero {:,}; grupos {:,}".format(
            nom, n_c0, n_err, len(fm), len(set(g.tolist()))))
    n_num = sum(1 for x in gnum if x)
    p("   titulos con numero de grado: {:,} ({:,} personas)".format(
        n_num, int(sum(per_t.get(c, 0) for c, x in zip(celdas, gnum) if x))))

    # --- 4. personas que cambian de grupo ----------------------------------------------
    m15, m16 = miembros(c15, b15["grupo"]), miembros(b16.celdas, b16.grupo)
    cambia = [c for c in comunes if m15[c] != m16[c]]
    tot = int(per_t.sum())
    p("\n4. QUIEN CAMBIA DE GRUPO (su titulo queda con otros titulos que en la v15)")
    p("   titulos: {:,} de {:,} ({:.1%}); personas: {:,} de {:,} ({:.1%})".format(
        len(cambia), len(comunes), len(cambia) / len(comunes),
        int(per_t[cambia].sum()), tot, per_t[cambia].sum() / tot))
    sep = [c for c in cambia if len(m16[c]) < len(m15[c])]
    jun = [c for c in cambia if len(m16[c]) > len(m15[c])]
    p("   grupo mas chico (lo separa quitar el coseno): {:,} titulos, {:,} personas".format(
        len(sep), int(per_t[sep].sum())))
    p("   grupo mas grande (lo junta la capa 0):        {:,} titulos, {:,} personas".format(
        len(jun), int(per_t[jun].sum())))

    # --- 5. bandas ---------------------------------------------------------------------
    i15 = {c: i for i, c in enumerate(c15)}
    i16 = {c: i for i, c in enumerate(b16.celdas)}
    B15 = np.asarray(b15["bandas"], float)
    B16 = np.asarray(b16.bandas, float)
    d = np.array([B16[i16[c]] - B15[i15[c]] for c in cambia])
    pct = np.expm1(d)
    p("\n5. BANDAS DE LOS TITULOS QUE CAMBIAN (exp(dif) - 1)")
    for k, nb in enumerate(BANDAS):
        col = pct[:, k]
        col = col[np.isfinite(col)]
        p("   {}: mediana {:+.1%}; mediana del valor absoluto {:.1%}; p90 del absoluto "
          "{:.1%}".format(nb, np.median(col), np.median(np.abs(col)),
                          np.percentile(np.abs(col), 90)))
    mueve = np.nanmax(np.abs(pct), axis=1) > UMBRAL_BANDA
    tm = [c for c, x in zip(cambia, mueve) if x]
    p("   alguna banda se mueve > 5 %: {:,} titulos ({:.1%} de los que cambian), {:,} personas "
      "({:.1%} del total)".format(len(tm), len(tm) / max(len(cambia), 1),
                                  int(per_t[tm].sum()), per_t[tm].sum() / tot))
    top = sorted(tm, key=lambda c: -per_t[c])[:15]
    p("   los 15 con mas personas (p50 v15 -> v16, en multiplos del SBU):")
    for c in top:
        a, b = np.exp(B15[i15[c]][2]), np.exp(B16[i16[c]][2])
        p("      {:<45} {:>6,} pers.  {:5.2f} -> {:5.2f}  ({:+.0%})  grupo {} -> {} titulos".format(
            c[:45], int(per_t[c]), a, b, b / a - 1, len(m15[c]), len(m16[c])))
    p("\n({:.0f} s)".format(time.time() - t0))
    (SAL / "41_base_v16.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
