"""T-021: pruebas de equivalencia (TOST, IC 90 % dentro de +- margen) para T-013 y T-012b (registro, T-021).

    .venv/bin/python research/tesis/t21_equivalencia.py

Usa las predicciones guardadas: t13_pred_completo.npy, t13_base_qwen.npy y t12b_curva.parquet.
SALIDA: salidas/t21_equivalencia.txt
"""
import importlib.util
import pathlib

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
SAL = AQUI / "salidas"
MARGEN_NIVEL = 0.010        # exactitud, 1,0 punto
MARGEN_OPEN = 0.05          # exactitud balanceada
U_T012B = 0.1               # umbral de P(NINGUNO) elegido en calibra en T-012b
B = 2000


def veredicto(d0, bs, margen):
    lo, hi = np.nanpercentile(bs, [5, 95])
    lo95, hi95 = np.nanpercentile(bs, [2.5, 97.5])
    eq = -margen < lo and hi < margen
    minimo = max(abs(lo), abs(hi))
    return ("{:+.4f}  IC 90 % [{:+.4f}, {:+.4f}]  (IC 95 % [{:+.4f}, {:+.4f}])  margen +-{:.3f} -> {}\n"
            "    margen mas chico con el que seria equivalente: +-{:.4f}").format(
        d0, lo, hi, lo95, hi95, margen, "EQUIVALENTE" if eq else "no se puede afirmar equivalencia", minimo)


def nivel():
    spec = importlib.util.spec_from_file_location("t13", AQUI / "t13_laya_nivel.py")
    t13 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t13)
    _, niv, grupo, _, _, te = t13.particion()
    y = np.where(np.isfinite(niv), niv, 1).astype(int) - 1
    yt, gt = y[te], grupo[te]
    laya = np.load(SAL / "t13_pred_completo.npy").argmax(-1)
    qwen = np.load(SAL / "t13_base_qwen.npy")
    d = (laya == yt).astype(float) - (qwen == yt).astype(float)
    gru = np.unique(gt)
    pos = {g: np.flatnonzero(gt == g) for g in gru}
    rng = np.random.default_rng(20261019)
    bs = [d[np.concatenate([pos[g] for g in rng.choice(gru, len(gru))])].mean() for _ in range(B)]
    return ["T-013 · nivel: Laya ajuste completo {:.2%} - regresion sobre Qwen {:.2%} (prueba {:,} titulos, {:,} grupos)".format(
        (laya == yt).mean(), (qwen == yt).mean(), len(yt), len(gru)), "  " + veredicto(d.mean(), bs, MARGEN_NIVEL)]


def open_set():
    t = pd.read_parquet(SAL / "t12b_curva.parquet")
    tp = t[t["parte"] == "prueba"].reset_index(drop=True)
    con = (tp["clase"] != "nueva").to_numpy()            # en t12b_curva la clase se guardo como «con»

    def ok(rec, j):
        o = np.where(con, rec & (j == 1), ~rec).astype(float)
        o[con & rec & np.isnan(j)] = np.nan
        return o

    okL = ok(tp["pN"].to_numpy() < U_T012B, tp["j_L"].to_numpy())
    okA = ok(tp["s_A"].to_numpy() >= 0.90, tp["j_A"].to_numpy())

    def bal(ii):
        c = con[ii]
        return (0.5 * (np.nanmean(okL[ii][c]) + np.nanmean(okL[ii][~c]))
                - 0.5 * (np.nanmean(okA[ii][c]) + np.nanmean(okA[ii][~c])))

    rng = np.random.default_rng(20261021)
    bs = [bal(rng.integers(0, len(tp), len(tp))) for _ in range(B)]
    d0 = bal(np.arange(len(tp)))
    return ["T-012b · open set: Laya T-012b - sistema propuesto, exactitud balanceada (prueba {} con equivalente, {} nuevas)".format(
        int(con.sum()), int((~con).sum())), "  " + veredicto(d0, bs, MARGEN_OPEN)]


def main():
    out = ["T-021 · equivalencia con margen (TOST: IC 90 % entero dentro de +- margen)", ""] + nivel() + [""] + open_set()
    (SAL / "t21_equivalencia.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
