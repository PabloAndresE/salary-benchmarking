"""Diagnostico (sin pinball) para T-003: (1) exactitud del clasificador de nivel con cada embedding; (2) proporcion de
los 10 vecinos (de otro grupo) con el mismo nivel que la consulta. Niveles = Qwen v3 por grupo (como el producto)."""
import pathlib
import sys

import numpy as np
import pandas as pd
import torch

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(AQUI))
import t01_recuperacion_qwen as t01  # noqa: E402
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402

SAL = AQUI / "salidas"


def normal(X):
    X = np.asarray(X, np.float32)
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def main():
    b = BaseReferencia.cargar(RAIZ / "demo" / "base_v31.npz", cargar_settings().get_sbu)
    b.nivel_por_grupo()
    niv = np.asarray(b.nivel, float)
    grupo = np.asarray(b.grupo)
    V = normal(b.Z)
    Qd = normal(np.load(SAL / "t01_emb_qwen_desc.npy"))
    Qt = normal(np.load(SAL / "t01_emb_qwen_titulo.npy"))
    Qc = normal(np.load(SAL / "t02_emb_qwen_consulta.npy"))
    ok = np.isfinite(niv)
    rng = np.random.default_rng(3)
    # particion por GRUPO (no por titulo) para que no se filtre
    gs = np.unique(grupo[ok])
    test_g = set(rng.choice(gs, len(gs) // 5, replace=False))
    te = ok & np.isin(grupo, list(test_g))
    tr = ok & ~te
    from sklearn.linear_model import LogisticRegression
    out = ["T-003 · DIAGNOSTICO DEL NIVEL (titulos con nivel {:,}; prueba por grupos {:,})".format(int(ok.sum()), int(te.sum()))]
    for nom, X in (("Vertex (titulo)", V), ("Qwen consulta (titulo + instruccion)", Qc), ("Qwen titulo", Qt),
                   ("Qwen titulo + descripcion", Qd)):
        clf = LogisticRegression(max_iter=2000, C=1.0).fit(X[tr], niv[tr].astype(int))
        acc = (clf.predict(X[te]) == niv[te].astype(int)).mean()
        out.append("   clasificador de nivel, {:<38} exactitud {:.1%}".format(nom, acc))
    # vecinos con el mismo nivel (consultas: 4.000 titulos con nivel)
    q = rng.choice(np.flatnonzero(ok), 4000, replace=False)
    for nom, Q, D in (("Vertex titulo -> titulo", V, V), ("Qwen consulta -> titulo+desc (T-002)", Qc, Qd),
                      ("Qwen consulta -> titulo", Qc, Qt)):
        Dg = torch.tensor(D, device="cuda", dtype=torch.float16)
        g = torch.tensor(grupo, device="cuda")
        igual = []
        for i in range(0, len(q), 500):
            ii = q[i:i + 500]
            s = (torch.tensor(Q[ii], device="cuda", dtype=torch.float16) @ Dg.T).float()
            s[g[ii].unsqueeze(1) == g.unsqueeze(0)] = -9
            top = s.topk(10, dim=1).indices.cpu().numpy()
            nv = niv[top]
            igual.append(np.nanmean(nv == niv[ii][:, None], axis=1))
        out.append("   vecinos top-10 con el mismo nivel, {:<36} {:.1%}".format(nom, np.concatenate(igual).mean()))
    (SAL / "t03_diagnostico_nivel.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
