"""T-015: los vectores del e5 ajustado (D-045, `48_bi_encoder_B3/semilla_1`) para los 65.181 titulos de base_v31.
    CUDA_VISIBLE_DEVICES=N .venv/bin/python research/tesis/t15_e5_base.py      -> salidas/t15_e5_base_v31.npy
"""
import pathlib

import numpy as np
import torch

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
MODELO = RAIZ / "research/experimentos/e2_nivel/salidas/48_bi_encoder_B3/semilla_1"


def main():
    from transformers import AutoModel, AutoTokenizer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(MODELO)
    mod = AutoModel.from_pretrained(MODELO).to(dev).eval()
    celdas = [str(c) for c in np.load(RAIZ / "demo" / "base_v31.npz", allow_pickle=True)["celdas"]]
    out = []
    with torch.no_grad():
        for i in range(0, len(celdas), 512):
            t = tok(["query: " + x for x in celdas[i:i + 512]], padding=True, truncation=True, max_length=32,
                    return_tensors="pt").to(dev)
            h = mod(**t).last_hidden_state
            k = t["attention_mask"].unsqueeze(-1).to(h.dtype)
            out.append(torch.nn.functional.normalize((h * k).sum(1) / k.sum(1), dim=-1).cpu().numpy())
    E = np.vstack(out).astype(np.float32)
    np.save(AQUI / "salidas" / "t15_e5_base_v31.npy", E)
    print("e5 ajustado: {} x {} en {}".format(*E.shape, dev))


if __name__ == "__main__":
    main()
