"""T-009: candidatos que propone Qwen, etiquetados por GLM (rubrica v7), para reentrenar el cross-encoder.

    .venv/bin/python research/tesis/t09_pares_qwen.py armar       los ~5.000 pares (GPU 1)
    .venv/bin/python research/tesis/t09_pares_qwen.py etiquetar   GLM en los dos ordenes (8 peticiones a la vez)

Para cada titulo de base_v31, sus primeros 3 vecinos de OTRO grupo con coseno de Qwen (consulta Q-instr -> documento
Q-d) >= 0,70; se muestrean ~5.000 en tres tramos iguales. Exclusiones de `53` (registro, T-009).

SALIDAS (fuera del repo: titulos de clientes): salidas/t09_pares_qwen.parquet, t09_glm.parquet, t09_pares_qwen.txt
"""
import importlib.util
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
E2 = RAIZ / "research/experimentos/e2_nivel"
SAL = AQUI / "salidas"
SEM = 20261013
TRAMOS = ((0.70, 0.74), (0.74, 0.78), (0.78, 1.01))
POR_TRAMO = 1700
POR_TITULO = 3
VALIDA = 0.15


def cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, E2 / archivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def vecinos_qwen(k=40):
    import torch
    Qd = torch.from_numpy(np.load(SAL / "t01_emb_qwen_desc.npy")).to("cuda:1", torch.float16)
    Qc = torch.from_numpy(np.load(SAL / "t02_emb_qwen_consulta.npy")).to("cuda:1", torch.float16)
    Qd = torch.nn.functional.normalize(Qd.float(), dim=1).half()
    Qc = torch.nn.functional.normalize(Qc.float(), dim=1).half()
    V, S = [], []
    for i in range(0, len(Qc), 4096):
        s, v = (Qc[i:i + 4096] @ Qd.T).float().topk(k, dim=1)
        V.append(v.cpu().numpy())
        S.append(s.cpu().numpy())
    return np.vstack(V), np.vstack(S)


def armar():
    e43, e52 = cargar("e43", "43_perdida_vertex.py"), cargar("e52", "52_validacion_glm.py")
    b = np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)
    tit = np.array([str(c) for c in b["celdas"]], dtype=object)
    grupo = np.asarray(b["grupo"])
    Zv = np.asarray(b["Z"], dtype=np.float32)
    Zv /= np.linalg.norm(Zv, axis=1, keepdims=True)
    desc = pd.read_csv(E2 / "salidas" / "46_descripciones.csv", keep_default_na=False)
    con_desc = {t for t, r in zip(desc["titulo"].astype(str), desc["respuesta"])
                if json.loads(r).get("descripcion", "").strip()}
    es_cargo = np.array([t in con_desc for t in tit])
    fuera = e52.ya_juzgados()
    v = pd.read_csv(E2 / "salidas" / "52_validacion_mapa.csv")
    fuera |= {frozenset((a, c)) for a, c in zip(v["a"], v["b"])}
    p53 = pd.read_parquet(E2 / "salidas" / "53_pares_v4.parquet")
    fuera |= {frozenset((a, c)) for a, c in zip(p53["a"], p53["b"])}
    prueba = set()
    for f, a, c in (("13e_pares_400.csv", "comun", "raro"), ("20_pares_400.csv", "comun", "raro"),
                    ("29_prueba2_pares.csv", "comun", "raro")):
        d = e52.leer(E2 / "salidas" / f)
        if "particion" in d:
            d = d[d["particion"].isin(["prueba", "prueba2"])]
        prueba |= set(d[a]) | set(d[c])
    V, S = vecinos_qwen()
    filas, vistos = [], set()
    for i in range(len(tit)):
        if not es_cargo[i] or tit[i] in prueba:
            continue
        n, gs = 0, set()
        for j, s in zip(V[i], S[i]):
            if s < TRAMOS[0][0] or n == POR_TITULO:
                break
            j = int(j)
            if grupo[j] == grupo[i] or grupo[j] in gs:
                continue
            gs.add(grupo[j])
            q = (min(i, j), max(i, j))
            if (q in vistos or not es_cargo[j] or tit[j] in prueba or frozenset((tit[i], tit[j])) in fuera
                    or e43.bloqueado(tit[i], tit[j])):
                continue
            vistos.add(q)
            filas.append((i, j, float(s)))
            n += 1
    d = pd.DataFrame(filas, columns=["i", "j", "cos_qwen"])
    d["tramo"] = pd.cut(d["cos_qwen"], [t[0] for t in TRAMOS] + [TRAMOS[-1][1]], right=False,
                        labels=["{:.2f}-{:.2f}".format(*t) for t in TRAMOS]).astype(str)
    print("candidatos validos: {:,}".format(len(d)), d["tramo"].value_counts().to_dict())
    rng = np.random.default_rng(SEM)
    t = pd.concat([g.iloc[rng.permutation(len(g))[:POR_TRAMO]] for _, g in d.groupby("tramo")], ignore_index=True)
    # particion por GRUPO: cada grupo entero en entrena o valida; los pares que cruzan se tiran
    gr = np.unique(grupo)
    val = set(rng.choice(gr, int(len(gr) * VALIDA), replace=False).tolist())
    pa = np.array(["valida" if grupo[i] in val else "entrena" for i in t["i"]])
    pb = np.array(["valida" if grupo[j] in val else "entrena" for j in t["j"]])
    t = t[pa == pb].copy()
    t["particion"] = pa[pa == pb]
    t["a"], t["b"] = tit[t["i"]], tit[t["j"]]
    t["cos_vertex"] = np.einsum("ij,ij->i", Zv[t["i"]], Zv[t["j"]])
    t.to_parquet(SAL / "t09_pares_qwen.parquet", index=False)
    print("pares: {:,}".format(len(t)), t["tramo"].value_counts().to_dict(), t["particion"].value_counts().to_dict())
    print("coseno de Vertex: mediana {:.3f}; < 0,90: {:.0%}".format(t["cos_vertex"].median(),
                                                                     (t["cos_vertex"] < 0.90).mean()))


def etiquetar():
    sys.modules["vllm"] = None
    e51 = cargar("e51", "51_etiquetador_local.py")
    t = pd.read_parquet(SAL / "t09_pares_qwen.parquet").reset_index(drop=True)
    sis, sha = e51.sistema()
    filas = [(k, o, a, b) for k, (x, y) in enumerate(zip(t["a"], t["b"]))
             for o, a, b in (("ab", x, y), ("ba", y, x))]
    t0 = time.time()
    textos = e51.correr_api("glm-5.3-flash", filas, sis)
    out = []
    for (k, o, a, b), s in zip(filas, textos):
        try:
            r = json.loads(s)
            out.append((k, o, r["mismo"], r["paso"], r["razon"]))
        except (ValueError, KeyError, TypeError):
            out.append((k, o, "", "", str(s)[:200]))
    r = pd.DataFrame(out, columns=["k", "orden", "mismo", "paso", "razon"])
    w = r.pivot_table(index="k", columns="orden", values="mismo", aggfunc="first")
    pw = r.pivot_table(index="k", columns="orden", values="paso", aggfunc="first")
    t["glm_ab"], t["glm_ba"] = w["ab"].reindex(t.index).to_numpy(), w["ba"].reindex(t.index).to_numpy()
    t["paso_ab"], t["paso_ba"] = pw["ab"].reindex(t.index).to_numpy(), pw["ba"].reindex(t.index).to_numpy()
    t["coherente"] = (t["glm_ab"] == t["glm_ba"]) & t["glm_ab"].isin(["si", "no"])
    t["etiqueta"] = np.where(t["coherente"], (t["glm_ab"] == "si").astype(float), np.nan)
    t["rubrica_sha"], t["modelo"] = sha, "zai-org/GLM-5.3-Flash"
    t.to_parquet(SAL / "t09_glm.parquet", index=False)
    lineas = ["T-009 · candidatos de Qwen etiquetados por GLM (rubrica v7, sha {})".format(sha),
              "{:,} pares en {:.0f} min; coherentes {:.1%}".format(len(t), (time.time() - t0) / 60,
                                                                 t["coherente"].mean())]
    for e_, g in t.groupby("tramo"):
        c = g[g["coherente"]]
        lineas.append("   coseno Qwen {}  n={:>5}  coherentes {:.0%}  `si` de GLM {:.0%}".format(
            e_, len(g), g["coherente"].mean(), c["etiqueta"].mean()))
    (SAL / "t09_pares_qwen.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))


if __name__ == "__main__":
    etiquetar() if sys.argv[1:] == ["etiquetar"] else armar()
