"""Los ~10.000 pares que etiquetara el LLM (D-035) para ajustar el cross. Paso 4 del plan.

Mismo censo que `13e` --todos los pares de grupos en 0,90-1,01 de coseno--, y la misma
estratificacion por tramos, a escala. Lo que cambia son cuatro cosas, y las cuatro
existen para que la comparacion final contra `prueba` siga significando algo:

1. SE EXCLUYEN ENTEROS LOS CARGOS DEL PATRON DE ORO. No solo los 400 pares de `13e` y los
   48 de `13a`: cualquier par que toque uno de sus grupos. Si el cross se entrena con
   `SUPERVISOR CALIDAD` en un par, luego no se puede decir que acierta `SUPERVISOR
   CALIDAD` en `prueba` porque generaliza: lo vio. Por grupo y no por texto, como en `13e`.

2. PARTICION POR CARGO, NO POR PAR. Cada grupo cae entero en `entrena` o en `valida`, y los
   pares que cruzan de uno a otro se tiran. Un mismo cargo sale en muchos pares; si
   estuviera en los dos lados, `valida` mediria memoria y no generalizacion.

3. TOPE DE APARICIONES POR CARGO. `ASISTENTE ADMINISTRATIVO` tiene cientos de vecinos en la
   banda; sin tope se comeria el lote. Con tope, el mismo presupuesto cubre mas cargos.

4. NEGATIVOS DIFICILES, SOBREMUESTREADOS. En `calibra` solo el 28% de los pares son `no`,
   y los `no` son los que ensenan al modelo donde esta la frontera. Los pares con senal
   lexica de ser distintos --escalon distinto en `RANGOS`, o antiguedad distinta en
   `SENIORIDAD`-- pesan `PESO_DIFICIL` veces mas al muestrear. Es una senal para ELEGIR que
   pedir, no una etiqueta: la etiqueta la pone el LLM con la rubrica.

ESTRATOS (mismas fronteras que `13e`; las fracciones son topes, ver `ESTRATOS`):

    alto    >= 0,97        todo lo que hay (~30)   el producto YA fusiona casi todo
    banda   0,93 - 0,97    hasta el 70%, en tramos; lo que un tramo no llena pasa al otro
    bajo    0,90 - 0,93    el resto, hasta 10.000  el producto NO los fusiona, y es donde
                                                   mas pares del mismo cargo se deja

SALIDAS (en .gitignore: llevan titulos de clientes)

    16_pares_10000.csv   todo: grupos, sim, estrato, particion, senal lexica
    16_para_llm.csv      lo unico que ve el LLM: n, comun, raro

No se regenera si ya hay respuestas del LLM para este lote: los `n` dejarian de apuntar
a los mismos pares.
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.producto.nivel import nivel_lexico, seniority_lexica  # noqa: E402

BASE = RAIZ / "demo" / "base_v15.npz"
SAL = pathlib.Path(__file__).resolve().parent / "salidas"
ORO_400 = SAL / "13e_pares_400.csv"
ORO_48 = SAL / "13_para_juzgar.csv"
SALIDA = SAL / "16_pares_10000.csv"
PARA_LLM = SAL / "16_para_llm.csv"
RESPUESTAS = SAL / "16_respuestas_llm.csv"
SEM = 20260925
PASO = 512

TOTAL = 10_000
# Las fracciones son TOPES, no cuotas. Medido en la primera corrida: tras excluir el oro y
# partir por cargo quedan 30 pares en `alto` (el producto ya fusiona casi todo lo que pasa
# de 0,97), ~9.300 en `banda` y ~44.000 en `bajo`. Asi que `alto` entra entero, `banda`
# hasta donde da, y lo que falte se rellena de `bajo` --que es ademas donde el producto
# se deja mas pares del mismo cargo sin juntar--.
ESTRATOS = {"bajo": (0.90, 0.93, 0.25), "banda": (0.93, 0.97, 0.70),
            "alto": (0.97, 1.01, 0.05)}
N_TRAMOS_BANDA = 4
P_VALIDA = 0.30          # de los GRUPOS; de los pares cae ~0,3^2 frente a ~0,7^2
CUOTA_VALIDA = 0.15      # de los pares
TOPE_POR_CARGO = 8
PESO_DIFICIL = 3.0
LINEA = "=" * 78


def censo(cel, Z, g, emp):
    """Todos los pares de grupos en 0,90-1,01, un representante por grupo. Igual que 13e."""
    rep = {}
    for i in range(len(cel)):
        gi = int(g[i])
        if gi not in rep or (-emp[i], len(cel[i])) < (-emp[rep[gi]], len(cel[rep[gi]])):
            rep[gi] = i
    reps = np.array(sorted(rep.values()))
    lo = min(a for a, _, _ in ESTRATOS.values())
    hi = max(b for _, b, _ in ESTRATOS.values())
    filas, vistos = [], set()
    for a in range(0, len(reps), PASO):
        sub = reps[a:a + PASO]
        S = Z[sub] @ Z.T
        for r, i in enumerate(sub):
            s = S[r]
            for j in np.flatnonzero((s >= lo) & (s < hi) & (g != g[i])):
                par = tuple(sorted((int(g[i]), int(g[j]))))
                if par in vistos:
                    continue
                vistos.add(par)
                a_i, b_i = (i, int(j)) if emp[i] >= emp[j] else (int(j), i)
                filas.append((int(g[a_i]), int(g[b_i]), cel[a_i], cel[b_i],
                              round(float(s[j]), 4), int(emp[a_i]), int(emp[b_i])))
        if (a // PASO) % 20 == 0:
            print("  {:,}/{:,} grupos, {:,} pares".format(a, len(reps), len(filas)),
                  flush=True)
    return pd.DataFrame(filas, columns=["g_comun", "g_raro", "comun", "raro", "sim",
                                        "emp_comun", "emp_raro"])


def grupos_del_oro(cel, g):
    """Los grupos de cualquier titulo que aparezca en el patron de oro (400 y 48)."""
    fuera = set()
    m = pd.read_csv(ORO_400, sep=";", encoding="utf-8-sig", dtype=str)
    fuera |= set(m.g_comun.astype(int)) | set(m.g_raro.astype(int))
    if ORO_48.exists():
        ix = {c: int(g[i]) for i, c in enumerate(cel)}
        v = pd.read_csv(ORO_48, sep=None, engine="python", encoding="utf-8-sig", dtype=str)
        v.columns = [c.strip() for c in v.columns]
        fuera |= {ix[t] for t in list(v.comun) + list(v.raro) if t in ix}
    return fuera


def dificil(a, b):
    """Senal lexica de ser puestos distintos. Solo para elegir que pedir."""
    na, nb = nivel_lexico(a), nivel_lexico(b)
    escalon = na is not None and nb is not None and na == na and nb == nb and na != nb
    return bool(escalon or seniority_lexica(a) != seniority_lexica(b))


def muestrear(pool, cuantos, cuenta, rng):
    """Muestreo ponderado sin reemplazo (claves de Efraimidis-Spirakis) con tope por cargo."""
    if pool.empty or cuantos <= 0:
        return pool.iloc[:0]
    w = np.where(pool.dificil, PESO_DIFICIL, 1.0)
    orden = np.argsort(-np.log(rng.random(len(pool))) / w)
    tomados = []
    for k in orden:
        f = pool.iloc[k]
        if cuenta.get(f.g_comun, 0) < TOPE_POR_CARGO and cuenta.get(f.g_raro, 0) < TOPE_POR_CARGO:
            tomados.append(k)
            cuenta[f.g_comun] = cuenta.get(f.g_comun, 0) + 1
            cuenta[f.g_raro] = cuenta.get(f.g_raro, 0) + 1
            if len(tomados) == cuantos:
                break
    return pool.iloc[tomados]


def main():
    if RESPUESTAS.exists():
        sys.exit("{} ya existe: regenerar el lote cambiaria a que par apunta cada `n`."
                 .format(RESPUESTAS))
    print(LINEA)
    print("LOTE DE {:,} PARES PARA EL LLM".format(TOTAL))
    print(LINEA)
    d = np.load(BASE, allow_pickle=True)
    cel = np.array([str(c) for c in d["celdas"]])
    Z = d["Z"].astype(np.float32)
    Z /= np.linalg.norm(Z, axis=1, keepdims=True)
    g, emp = d["grupo"].astype(np.int64), d["emp"]

    cache = SAL / "16_censo.parquet"      # en .gitignore; se rehace si cambia la base
    if cache.exists() and cache.stat().st_mtime > BASE.stat().st_mtime:
        t = pd.read_parquet(cache)
        print("  (censo en cache)")
    else:
        t = censo(cel, Z, g, emp)
        t.to_parquet(cache, index=False)
    print("\n  censo 0,90-1,01          : {:,} pares".format(len(t)))

    fuera = grupos_del_oro(cel, g)
    antes = len(t)
    t = t[~t.g_comun.isin(fuera) & ~t.g_raro.isin(fuera)].reset_index(drop=True)
    print("  fuera por tocar el oro   : {:,} pares ({:,} grupos del oro)".format(
        antes - len(t), len(fuera)))

    rng = np.random.default_rng(SEM)
    todos = np.union1d(t.g_comun.unique(), t.g_raro.unique())
    valida = set(todos[rng.random(len(todos)) < P_VALIDA].tolist())
    en_v = t.g_comun.isin(valida).to_numpy(), t.g_raro.isin(valida).to_numpy()
    t["particion"] = np.where(en_v[0] & en_v[1], "valida",
                              np.where(~en_v[0] & ~en_v[1], "entrena", ""))
    print("  cruzan entrena/valida    : {:,} pares (se tiran)".format(
        int((t.particion == "").sum())))
    t = t[t.particion != ""].reset_index(drop=True)

    t["estrato"] = pd.cut(t.sim, [ESTRATOS["bajo"][0], ESTRATOS["banda"][0],
                                  ESTRATOS["alto"][0], ESTRATOS["alto"][1]],
                          labels=list(ESTRATOS), include_lowest=True).astype(str)
    lo, hi, _ = ESTRATOS["banda"]
    t["tramo"] = pd.cut(t.sim, np.linspace(lo, hi, N_TRAMOS_BANDA + 1),
                        include_lowest=True, labels=False)
    t["dificil"] = [dificil(a, b) for a, b in zip(t.comun, t.raro)]

    print("\n  marco tras exclusiones, por estrato y particion:")
    print(pd.crosstab(t.estrato, t.particion).to_string().replace("\n", "\n    ")
          .join(["    ", ""]))

    trozos = []
    for part, cuota in (("entrena", 1 - CUOTA_VALIDA), ("valida", CUOTA_VALIDA)):
        cuenta, meta, propios = {}, int(round(TOTAL * cuota)), []
        for est in ("alto", "banda", "bajo"):
            n_est = int(round(TOTAL * cuota * ESTRATOS[est][2]))
            pool = t[(t.particion == part) & (t.estrato == est)]
            if est == "banda":
                # Los tramos de arriba tienen pocos pares: lo que no llenan pasa al siguiente.
                resto = n_est
                for k in reversed(range(N_TRAMOS_BANDA)):
                    q = resto // (k + 1)
                    x = muestrear(pool[pool.tramo == k], q, cuenta, rng)
                    propios.append(x)
                    resto -= len(x)
            else:
                propios.append(muestrear(pool, n_est, cuenta, rng))
        # Relleno hasta la meta con lo que queda de `bajo`, con el mismo peso y el mismo tope.
        hechos = sum(len(x) for x in propios)
        if hechos < meta:
            usados = set(pd.concat(propios).index)
            pool = t[(t.particion == part) & (t.estrato == "bajo") & ~t.index.isin(usados)]
            propios.append(muestrear(pool, meta - hechos, cuenta, rng))
        trozos += propios
    m = pd.concat(trozos).drop(columns=["tramo"])
    m = m.sample(frac=1.0, random_state=SEM).reset_index(drop=True)
    m.insert(0, "n", range(1, len(m) + 1))

    print("\n  muestra: {:,} pares".format(len(m)))
    print("    por particion : {}".format(m.particion.value_counts().to_dict()))
    print("    por estrato   : {}".format(m.estrato.value_counts().to_dict()))
    print("    senal dificil : {:.1%} en la muestra, {:.1%} en el marco".format(
        m.dificil.mean(), t.dificil.mean()))
    cnt = pd.concat([m.g_comun, m.g_raro]).value_counts()
    print("    cargos        : {:,} distintos; el que mas sale, {} veces".format(
        len(cnt), int(cnt.max())))
    print("    grupos del oro en la muestra: {}".format(
        int(m.g_comun.isin(fuera).sum() + m.g_raro.isin(fuera).sum())))
    if len(m) < TOTAL * 0.98:
        print("  AVISO: faltan pares; el tope por cargo o la particion vacian algun tramo.")

    m.to_csv(SALIDA, index=False, encoding="utf-8-sig", sep=";")
    m[["n", "comun", "raro"]].to_csv(PARA_LLM, index=False, encoding="utf-8-sig", sep=";")
    print("\n  -> {}\n  -> {}  (lo que ve el LLM)".format(SALIDA, PARA_LLM))


if __name__ == "__main__":
    main()
