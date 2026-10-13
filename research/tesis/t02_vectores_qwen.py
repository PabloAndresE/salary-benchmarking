"""T-002: los vectores de consulta de Qwen (titulo con instruccion) de todos los titulos de la base, y el umbral del
juez equivalente al 0,90 de Vertex: el coseno consulta -> base (otro grupo) que deja la misma proporcion de titulos con
un vecino por encima (metodo de D-057).

    CUDA_VISIBLE_DEVICES=1 ../../.venv/bin/python t02_vectores_qwen.py

SALIDAS: salidas/t02_emb_qwen_consulta.npy (orden de base_v31), salidas/t02_umbral.json
"""
import json
import pathlib
import sys

import numpy as np
import torch

AQUI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import t01_recuperacion_qwen as t01  # noqa: E402

SAL = AQUI / "salidas"


def max_otro_grupo(Q, D, grupo, lote=512):
    """Para cada fila de Q, el coseno maximo con un titulo de OTRO grupo (el propio grupo excluido)."""
    Dg = torch.tensor(D, device="cuda", dtype=torch.float16)
    g = torch.tensor(grupo, device="cuda")
    out = []
    for i in range(0, len(Q), lote):
        s = (torch.tensor(Q[i:i + lote], device="cuda", dtype=torch.float16) @ Dg.T).float()
        propio = g[i:i + lote].unsqueeze(1) == g.unsqueeze(0)
        s[propio] = -9.0
        out.append(s.max(1).values.cpu().numpy())
    return np.concatenate(out)


def main():
    celdas, grupo, Zv = t01.cargar_base()
    destino = SAL / "t02_emb_qwen_consulta.npy"
    if destino.exists():
        Qc = np.load(destino)
    else:
        m = t01.Qwen()
        Qc = m(["Instruct: {}\nQuery:{}".format(t01.TAREA, c) for c in celdas], largo=64)
        np.save(destino, Qc)
    Qd = np.load(SAL / "t01_emb_qwen_desc.npy")
    Zv = (Zv / np.linalg.norm(Zv, axis=1, keepdims=True)).astype(np.float16)
    mv = max_otro_grupo(Zv, Zv, grupo)
    prop = float((mv >= 0.90).mean())
    mq = max_otro_grupo(Qc, Qd, grupo)
    umbral = float(np.quantile(mq, 1 - prop))
    r = {"proporcion_vertex_090": round(prop, 4), "umbral_qwen": round(umbral, 4),
         "coseno_qwen_mediano": round(float(np.median(mq)), 4), "coseno_vertex_mediano": round(float(np.median(mv)), 4)}
    (SAL / "t02_umbral.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    print(r)


if __name__ == "__main__":
    main()
