"""T-026: el aporte de cada pieza por regimen de estimacion (directo vs analogia).

    .venv/bin/python research/tesis/t26_regimen.py

Reanalisis de las corridas de T-025: mismos contrastes, estratificados por `directa`.
El estrato lo fija el SISTEMA FINAL, no cada variante, para que el contraste siga siendo
pareado (una variante puede mover una celda de analogia a directa).

Exploratorio, no confirmatorio (ver T-026 en registro_decisiones.md).
SALIDA: salidas/t26_regimen.txt
"""
import importlib.util
import pathlib

import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
FINAL = "qwen_laya_e5"
QUITAR = [("abl_sin_qwen", "sin Qwen (busqueda y consulta en Vertex)"),
          ("abl_sin_juez", "sin cross-encoder en la banda"),
          ("abl_sin_laya", "sin Laya (nivel por regresion sobre Qwen)"),
          ("abl_sin_e5", "sin e5 (vecinos de la analogia en Vertex)")]
ESTRATOS = [(False, "ANALOGIA  (directa=False)"), (True, "DIRECTO   (directa=True)")]


def c77():
    spec = importlib.util.spec_from_file_location("c77", E2 / "77_comparar_v2.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def leer_full(m, v, cols):
    return pd.read_parquet(E2 / "salidas" / ("54_" + v + m.SUF))[cols]


def lectura(lo, hi):
    return "APORTA" if lo > 0 else ("ESTORBA" if hi < 0 else "no se distingue")


def main():
    m = c77()
    estrato = leer_full(m, FINAL, ["empresa", "cargo", "directa"])
    base = leer_full(m, FINAL, ["empresa", "cargo", "pinball"])

    out = ["T-026 - aporte de cada pieza por regimen de estimacion (validacion, 1.442 empresas apartadas)",
           "EXPLORATORIO: el corte se eligio despues de conocer T-025. Descriptivo, no adopta ni retira nada.",
           ""]
    rep = base.merge(estrato, on=["empresa", "cargo"])
    for val, nom in ESTRATOS:
        s = rep[rep["directa"] == val]
        out.append("  {:<26} votos {:>7,}   pinball medio {:.5f}".format(nom, len(s), s["pinball"].mean()))
    out += ["", "QUITANDO UNA PIEZA (corrida - final; > 0 = quitarla empeora). Union calculada DENTRO de cada estrato.", ""]

    for v, nombre in QUITAR:
        if not (E2 / "salidas" / ("54_" + v + m.SUF)).exists():
            out.append("  {:<44} (falta la corrida)".format(nombre))
            continue
        var = leer_full(m, v, ["empresa", "cargo", "pinball"])
        d = base.merge(var, on=["empresa", "cargo"], suffixes=("", "_a")).merge(estrato, on=["empresa", "cargo"])
        d["d"] = d["pinball_a"] - d["pinball"]
        out.append("  " + nombre)
        for val, nom in ESTRATOS:
            u = d[(d["directa"] == val) & (d["d"].abs() > 1e-6)]
            if len(u) == 0:
                out.append("     {:<26} no actua".format(nom))
                continue
            x, lo, hi = m.dos_vias(u, "d")
            tot = d[d["directa"] == val]
            xt, lot, hit = m.dos_vias(tot, "d")
            out.append("     {:<26} votos {:>6,}  {:+.5f} [{:+.5f}, {:+.5f}] -> {:<16} | todos los del estrato "
                       "{:+.5f} [{:+.5f}, {:+.5f}]".format(nom, len(u), x, lo, hi, lectura(lo, hi), xt, lot, hit))
        out.append("")

    (AQUI / "salidas" / "t26_regimen.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
