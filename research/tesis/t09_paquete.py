"""T-009: el paquete para reentrenar el cross-encoder con `22_entrenar_cross.py --grilla v2`.

    .venv/bin/python research/tesis/t09_paquete.py

plata = la de la v3 (`21_paquete_v6/plata.csv`) + los pares lejanos de `53` (GLM, rubrica v7) + los candidatos de Qwen
(`t09_glm.parquet`, GLM, rubrica v7); de GLM solo los coherentes en los dos ordenes (D-047). La `calibra` y la
comprobacion de `prueba`, las de `21_paquete_v6`. En las filas de GLM el `motivo` va vacio: los pasos de la v7 no son
los de la v6 y la cabeza de motivo ignora el vacio. Particion de `53` por grupo de base_v31 (15 % valida, por crc32);
los pares que cruzan se tiran.

SALIDA (fuera del repo): research/experimentos/e2_nivel/salidas/t09_paquete/
"""
import hashlib
import importlib.util
import json
import pathlib
import shutil
import zlib

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
V6 = E2 / "salidas" / "21_paquete_v6"
OUT = E2 / "salidas" / "t09_paquete"


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, E2 / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sha12(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:12]


def main():
    e16, e52 = cargar("e16", "16_lote_de_10000.py"), cargar("e52", "52_validacion_glm.py")
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    grupo = dict(zip((str(c) for c in b["celdas"]), np.asarray(b["grupo"]).tolist()))
    plata = pd.read_csv(V6 / "plata.csv", dtype=str, keep_default_na=False)
    cols = list(plata.columns)

    def a_plata(d, origen, estrato, sim):
        d = d[d["coherente"]].copy()
        return pd.DataFrame({
            "n": "", "comun": d["a"].to_numpy(), "raro": d["b"].to_numpy(), "particion": d["particion"].to_numpy(),
            "estrato": estrato, "dificil": [str(e16.dificil(x, y)) for x, y in zip(d["a"], d["b"])],
            "sim": np.round(sim.loc[d.index].to_numpy(float), 4).astype(str),
            "mismo_ab": d["glm_ab"].to_numpy(), "mismo_ba": d["glm_ba"].to_numpy(), "paso_ab": "", "paso_ba": "",
            "etiqueta": d["etiqueta"].astype(float).to_numpy(), "origen": origen, "motivo": ""})

    g53 = pd.read_parquet(E2 / "salidas" / "53_glm_v4.parquet")
    val = lambda t: grupo.get(t) is not None and zlib.crc32(str(grupo[t]).encode()) % 100 < 15  # noqa: E731
    pa = np.array(["valida" if val(t) else "entrena" for t in g53["a"]])
    pb = np.array(["valida" if val(t) else "entrena" for t in g53["b"]])
    g53 = g53[pa == pb].copy()
    g53["particion"] = pa[pa == pb]
    n53 = a_plata(g53, "glm_53", "glm53:" + g53.loc[g53["coherente"], "estrato"].to_numpy().astype(object),
                  g53["cos"])
    gq = pd.read_parquet(AQUI / "salidas" / "t09_glm.parquet")
    nq = a_plata(gq, "glm_qwen", "qwen:" + gq.loc[gq["coherente"], "tramo"].to_numpy().astype(object),
                 gq["cos_vertex"])
    nueva = pd.concat([plata, n53[cols], nq[cols]], ignore_index=True)
    clave = [frozenset((x, y)) for x, y in zip(nueva["comun"], nueva["raro"])]
    nueva = nueva[~pd.Series(clave).duplicated().to_numpy()].reset_index(drop=True)
    nueva["n"] = np.arange(1, len(nueva) + 1)
    # comprobacion dura: ningun par ni titulo de `prueba` / `prueba 2`
    prueba_t, prueba_p = set(), set()
    for f, a, c in (("13e_pares_400.csv", "comun", "raro"), ("20_pares_400.csv", "comun", "raro"),
                    ("29_prueba2_pares.csv", "comun", "raro")):
        d = e52.leer(E2 / "salidas" / f)
        if "particion" in d:
            d = d[d["particion"].isin(["prueba", "prueba2"])]
        prueba_t |= set(d[a]) | set(d[c])
        prueba_p |= {frozenset((x, y)) for x, y in zip(d[a], d[c])}
    nuevas = nueva[nueva["origen"].str.startswith("glm")]
    toca = sum(1 for x, y in zip(nuevas["comun"], nuevas["raro"])
               if x in prueba_t or y in prueba_t or frozenset((x, y)) in prueba_p)
    if toca:
        raise SystemExit("ALTO: {} pares nuevos tocan `prueba`".format(toca))
    OUT.mkdir(exist_ok=True)
    nueva.to_csv(OUT / "plata.csv", index=False)
    shutil.copy(V6 / "calibra.csv", OUT / "calibra.csv")
    man = json.loads((V6 / "manifiesto.json").read_text(encoding="utf-8"))
    man["decision"] = "T-009 (tesis): plata de 21_paquete_v6 + GLM coherente de 53 y de los candidatos de Qwen"
    man["t09"] = {"plata_v6": len(plata), "glm_53_coherentes": len(n53), "glm_qwen_coherentes": len(nq),
                  "total_sin_repetir": len(nueva), "por_particion": nueva["particion"].value_counts().to_dict(),
                  "por_origen": nueva["origen"].value_counts().to_dict(),
                  "si_glm_53": float(n53["etiqueta"].mean()), "si_glm_qwen": float(nq["etiqueta"].mean()),
                  "pares_nuevos_que_tocan_prueba": toca,
                  "fuentes_sha256_12": {"53_glm_v4.parquet": sha12(E2 / "salidas" / "53_glm_v4.parquet"),
                                        "t09_glm.parquet": sha12(AQUI / "salidas" / "t09_glm.parquet"),
                                        "21_paquete_v6/plata.csv": sha12(V6 / "plata.csv")}}
    (OUT / "manifiesto.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(man["t09"], indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
