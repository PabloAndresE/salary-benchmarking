"""D-057: tiempos de embeber un titulo (la consulta) y un lote (un informe): Vertex (red) contra e5 local.

    GRPC_DNS_RESOLVER=native ../../../.venv/bin/python 67_tiempos_embedding.py

SALIDA: salidas/67_tiempos_embedding.txt
"""
import pathlib
import sys
import time

import numpy as np
import torch

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.evaluacion import embeddings  # noqa: E402

b = np.load(RAIZ / "demo" / "base_v22.npz", allow_pickle=True)
rng = np.random.default_rng(1)
titulos = [str(c) + " X" for c in rng.choice(b["celdas"], 2000, replace=False)]   # ' X': fuera de cualquier cache


def medir(f, textos, reps):
    t = []
    for r in range(reps):
        a = time.perf_counter()
        f(textos[r * len(textos) // reps:(r + 1) * len(textos) // reps] if len(textos) > reps else textos)
        t.append(time.perf_counter() - a)
    return np.median(t)


def e5(disp):
    from transformers import AutoModel, AutoTokenizer
    ruta = AQUI / "salidas" / "48_bi_encoder_B3" / "semilla_1"
    tok = AutoTokenizer.from_pretrained(ruta)
    mod = AutoModel.from_pretrained(ruta).to(disp).eval()

    def f(textos):
        with torch.no_grad():
            t = tok(["query: " + x for x in textos], padding=True, truncation=True, max_length=32,
                    return_tensors="pt").to(disp)
            h = mod(**t).last_hidden_state
            k = t["attention_mask"].unsqueeze(-1).to(h.dtype)
            v = torch.nn.functional.normalize((h * k).sum(1) / k.sum(1), dim=-1).cpu()
        if disp == "cuda":
            torch.cuda.synchronize()
        return v
    f(titulos[:8])                                       # calentar
    return f


s = cargar_settings()
cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
vertex = lambda textos: embeddings.embeber(list(textos), cli, s.vertex_embedding_model)   # noqa: E731
vertex(titulos[:2])
out = ["67 · TIEMPOS DE EMBEBER (mediana de varias repeticiones)"]
torch.set_num_threads(8)
for nombre, f in (("Vertex (red)", vertex), ("e5 local, GPU", e5("cuda")), ("e5 local, CPU 8 hilos", e5("cpu"))):
    uno = medir(lambda x: f(x[:1]), [titulos[i] for i in range(10)], 10)
    lote = medir(lambda x: f(x[:500]), titulos[1000:1500], 1)
    out.append("   {:<24} 1 titulo {:>8.1f} ms   500 titulos {:>7.2f} s".format(nombre, uno * 1000, lote))
    print(out[-1], flush=True)
(AQUI / "salidas" / "67_tiempos_embedding.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
