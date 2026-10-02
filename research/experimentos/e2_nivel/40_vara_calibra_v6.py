"""La vara de `calibra` con las etiquetas v6 y la exclusion de la capa 0 v1 (D-041, paso 2).

Mide en `21_paquete_v6/calibra.csv`, con las MISMAS funciones de `22` (plantilla, tokenizador,
fp32, media de las dos direcciones), el NLI sin entrenar y el coseno, y su diferencia con IC 95 %
por bootstrap pareado (10.000). El AUC del NLI congelado es el `AUC_BASE` nuevo que `22`
comprueba antes de entrenar la v3. Lo mismo sobre `21_paquete/calibra.csv` como control: tiene
que salir el 0,7346 de antes.

    .venv/bin/python 40_vara_calibra_v6.py

SALIDA: salidas/40_vara_calibra_v6.txt
"""
import contextlib
import importlib.util
import pathlib
import sys

import numpy as np

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
spec = importlib.util.spec_from_file_location("e22", AQUI / "22_entrenar_cross.py")
e22 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e22)
MODELO = RAIZ / "modelos" / "mdeberta-xnli"


def main():
    from transformers import AutoTokenizer
    e22.verificar_modelo(MODELO)
    tok = AutoTokenizer.from_pretrained(MODELO)
    juez = e22.construir(MODELO, False, "cpu")
    out = []

    def p(s=""):
        print(s, flush=True)
        out.append(s)

    p("40 · VARA DE `calibra` (NLI sin entrenar y coseno), D-041")
    for nombre in ("21_paquete", "21_paquete_v6"):
        _, cal, _, _ = e22.cargar_paquete(SAL / nombre)
        y = cal["y"].to_numpy()
        ab, ba = e22.puntuar(juez, tok, cal["comun"].tolist(), cal["raro"].tolist(), "cpu",
                             contextlib.nullcontext)
        nli = (ab + ba) / 2
        cos = cal["sim"].to_numpy(float)
        rng = np.random.default_rng(20261002)
        d = e22.auc(y, nli) - e22.auc(y, cos)
        lo, hi = e22.boot_diferencia(y, nli, cos, rng)
        p("\n{}: {} pares ({} si / {} no)".format(nombre, len(cal), int(y.sum()),
                                                  int((1 - y).sum())))
        p("   NLI sin entrenar  AUC {:.4f}".format(e22.auc(y, nli)))
        p("   coseno            AUC {:.4f}".format(e22.auc(y, cos)))
        p("   NLI - coseno      {:+.3f}  IC 95 % [{:+.3f}, {:+.3f}]".format(d, lo, hi))
    (SAL / "40_vara_calibra_v6.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
