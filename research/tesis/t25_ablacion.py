"""T-025: tabla de ablacion del sistema final en la banda (validacion; registro, T-025).

    .venv/bin/python research/tesis/t25_ablacion.py

Usa las salidas de `54_pinball.py` (entorno venv) y el bootstrap en dos vias de `77_comparar_v2.py`.
SALIDA: salidas/t25_ablacion.txt
"""
import importlib.util
import pathlib

import numpy as np

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
FINAL = "qwen_laya_e5"
QUITAR = [("abl_sin_qwen", "sin Qwen (busqueda y consulta en Vertex)"),
          ("abl_sin_juez", "sin cross-encoder en la banda"),
          ("abl_sin_laya", "sin Laya (nivel por regresion sobre Qwen)"),
          ("abl_sin_e5", "sin e5 (vecinos de la analogia en Vertex)")]
CADENA = [("nivel_v3", "producto (nucleo)"), ("qwen_inverso", "+ Qwen y su nivel (T-006)"),
          ("qwen_laya", "+ Laya en el nivel (T-014)"), ("qwen_laya_e5", "+ e5 en la analogia (T-015) = final")]


def c77():
    spec = importlib.util.spec_from_file_location("c77", E2 / "77_comparar_v2.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def diferencia(m, a, b):
    """pinball(a) - pinball(b) en la union de votos donde difieren; IC en dos vias."""
    d = m.leer(b).merge(m.leer(a), on=["empresa", "cargo"], suffixes=("", "_a"))
    d["d"] = d["pinball_a"] - d["pinball"]
    u = d[d["d"].abs() > 1e-6]
    if len(u) == 0:
        return 0, 0.0, 0.0, 0.0, (0.0, 0.0, 0.0)
    x, lo, hi = m.dos_vias(u, "d")
    return len(u), x, lo, hi, m.dos_vias(d, "d")       # ademas: sobre TODOS los votos (sumable entre pasos)


def lectura(lo, hi, quitar=True):
    if quitar:
        return "APORTA" if lo > 0 else ("ESTORBA" if hi < 0 else "no se distingue")
    return "MEJORA" if hi < 0 else ("EMPEORA" if lo > 0 else "no se distingue")


def main():
    m = c77()
    out = ["T-025 · ablacion del sistema final en la banda (validacion: empresas apartadas del 80 %)", "",
           "1. QUITANDO UNA PIEZA DEL SISTEMA FINAL (corrida - final; > 0 = quitarla empeora)"]
    for v, nombre in QUITAR:
        if not (E2 / "salidas" / ("54_" + v + m.SUF)).exists():
            out.append("  {:<44} (falta la corrida)".format(nombre))
            continue
        n, x, lo, hi, t = diferencia(m, v, FINAL)
        out.append("  {:<44} votos {:>6,}  {:+.5f} [{:+.5f}, {:+.5f}] -> {:<16} | todos los votos {:+.5f} [{:+.5f}, {:+.5f}]".format(
            nombre, n, x, lo, hi, lectura(lo, hi), *t))
    out += ["", "2. ACUMULATIVA (cada paso frente al anterior y frente al producto; < 0 = mejora)"]
    for (a, na), (b, nb) in zip(CADENA[1:], CADENA[:-1]):
        n, x, lo, hi, t = diferencia(m, a, b)
        n2, x2, lo2, hi2, t2 = diferencia(m, a, CADENA[0][0])
        out.append("  {:<40} paso (votos {:,}) {:+.5f} [{:+.5f}, {:+.5f}] {:<16} | todos los votos: paso {:+.5f} [{:+.5f}, "
                   "{:+.5f}], frente al producto {:+.5f} [{:+.5f}, {:+.5f}]".format(
                       na, n, x, lo, hi, lectura(lo, hi, quitar=False), *t, *t2))
    (AQUI / "salidas" / "t25_ablacion.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
