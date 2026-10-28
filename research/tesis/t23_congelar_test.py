"""T-023, paso 0: congelar la lista de empresas del test intocado (sha256) sin leer ningun sueldo del test.

    .venv/bin/python research/tesis/t23_congelar_test.py

Comprueba que la particion de hoy es la de siempre (5.770 empresas de entrenamiento = 4.328 + 1.442 de los logs de
`54_pinball`) y la cobertura de los titulos del test en `base_v31` (solo texto).
SALIDA (fuera del repo, 600): salidas/t23_empresas_test.json; imprime el sha256 para el registro.
"""
import os
import pathlib
import sys

import numpy as np

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "research/experimentos/e2_nivel"))
from benchmarking.evaluacion import splits  # noqa: E402


def main():
    import importlib.util
    spec = importlib.util.spec_from_file_location("e41", RAIZ / "research/experimentos/e2_nivel/41_base_v16.py")
    e41 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e41)
    mk = e41.cargar_marco()[["empresa_ruc", "segmento", "ciiu_n1", "cargo_norm"]]    # sin `y`: nada de sueldos
    test = splits.empresas_test(mk)
    ruta = SAL / "t23_empresas_test.json"
    sha = splits.guardar(test, ruta)
    os.chmod(ruta, 0o600)
    en = mk["empresa_ruc"].isin(test)
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    celdas = {str(c) for c in b["celdas"]}
    tt = set(mk.loc[en, "cargo_norm"].astype(str))
    solo_test = tt - set(mk.loc[~en, "cargo_norm"].astype(str))
    print("empresas {:,}; test {:,}; entrenamiento {:,} (esperado 5.770)".format(
        mk["empresa_ruc"].nunique(), len(test), mk.loc[~en, "empresa_ruc"].nunique()))
    print("filas: test {:,}; entrenamiento {:,}".format(int(en.sum()), int((~en).sum())))
    print("titulos del test {:,}: en base_v31 {:.1%}; solo en el test {:,} (en base_v31 {:.1%})".format(
        len(tt), np.mean([t in celdas for t in tt]), len(solo_test),
        np.mean([t in celdas for t in solo_test]) if solo_test else float("nan")))
    print("sha256", sha)


if __name__ == "__main__":
    main()
