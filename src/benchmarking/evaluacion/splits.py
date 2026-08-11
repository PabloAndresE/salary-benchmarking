"""Particion train/test por EMPRESA.

Por empresa y no por fila: una persona pertenece a una empresa y recurre entre anios,
asi que partir por filas dejaria a sus companeros en los dos lados y el leave-company-out
de la referencia no probaria nada.

Nota del spec: como train y test no comparten empresas, el leave-company-out de
`referencia.predecir` NUNCA se activa en la evaluacion real. No es un error — es red de
seguridad, y si se activa en CV dentro del train —. Pero la defensa activa es ESTE split,
no aquel filtro.
"""
import hashlib
import json
import numpy as np

SEMILLA = 20260805


def empresas_test(df, frac=0.2, semilla=SEMILLA):
    emp = (df[["empresa_ruc", "segmento", "ciiu_n1"]]
           .drop_duplicates(subset=["empresa_ruc"]).sort_values("empresa_ruc")
           .reset_index(drop=True))
    emp["estrato"] = emp["segmento"].astype(str) + "|" + emp["ciiu_n1"].astype(str)
    rng = np.random.default_rng(semilla)
    elegidas = []
    for _, grupo in emp.groupby("estrato", sort=True):
        rucs = grupo["empresa_ruc"].tolist()
        # al menos una por estrato: sin esto, 5 de los 70 estratos reales desaparecen del
        # test y la estratificacion falla donde mas hace falta. Cuesta 0,1 puntos.
        n = max(1, int(round(len(rucs) * frac)))
        idx = rng.permutation(len(rucs))[:n]
        elegidas.extend(rucs[i] for i in sorted(idx))
    return set(elegidas)


def partir(df, empresas_de_test):
    en_test = df["empresa_ruc"].isin(empresas_de_test)
    return df[~en_test].copy(), df[en_test].copy()


def guardar(empresas, ruta):
    """Persiste el listado y devuelve su sha256, que va al pre-registro.

    El hash es la prueba de que el test-set no se cambio despues de congelar. Si no
    coincide en la verificacion final, todos los resultados quedan invalidados.
    """
    lista = sorted(str(e) for e in empresas)
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump({"empresas_test": lista}, fh, ensure_ascii=False, indent=2)
    return hashlib.sha256("\n".join(lista).encode("utf-8")).hexdigest()


def cargar(ruta):
    with open(ruta, encoding="utf-8") as fh:
        return set(json.load(fh)["empresas_test"])
