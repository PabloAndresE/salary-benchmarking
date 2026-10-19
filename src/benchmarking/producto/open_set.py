"""Open set (tesis, T-010b): un titulo que no esta en la base se RECONOCE (equivale a un cargo de la base) o queda
como DESCONOCIDO (un cargo nuevo de verdad).

Lo mismo que se midio en `research/tesis/t10b_open_set.py` (sistema propuesto):

1. Qwen3-Embedding-8B embebe el titulo como consulta (`Instruct: ... Query:<titulo>`, ultimo token, 64 tokens) y
   propone los grupos mas cercanos entre los documentos «titulo: descripcion» de la base (4.096 dimensiones).
2. Se toman los primeros `N_CAND` grupos distintos sin candado (nivel de la rubrica, seniority, compatibilidad de la
   capa 0), como `43_perdida_vertex.bloqueado`.
3. El cross-encoder reentrenado en T-009 puntua cada par; si el mejor llega a `UMBRAL` (0,90, elegido en calibra en
   T-010b) el titulo queda «reconocido» con ese equivalente; si no, «desconocido».

No cambia la banda: la referencia salarial sigue saliendo de `BaseReferencia.referenciar` como siempre (T-009 midio
que reconocer mas no la mejora). Solo agrega QUE CARGO ES. Necesita GPU para Qwen; sin los archivos o sin torch no se
carga y la API sigue como antes.
"""
import pathlib
import threading

import numpy as np

from . import juez as juez_mod
from .capa0 import compatibles
from .nivel import nivel_rubrica, seniority_lexica

TAREA = ("Dado un titulo de cargo escrito en una nomina de una empresa de Ecuador, recupera el cargo equivalente "
         "del catalogo salarial")
N_CAND = 10
K_VECINOS = 400
UMBRAL = 0.90


def bloqueado(a: str, b: str) -> bool:
    na, nb = nivel_rubrica(a), nivel_rubrica(b)
    if na and nb and na != nb:
        return True
    if seniority_lexica(a) != seniority_lexica(b):
        return True
    return not compatibles(a, b)


class OpenSet:
    def __init__(self, base, ruta_qwen, ruta_docs, ruta_juez, dispositivo="cuda", umbral=UMBRAL):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.base, self.umbral, self.dispositivo = base, float(umbral), dispositivo
        D = np.load(ruta_docs, mmap_mode="r")
        if D.shape[0] != len(base.celdas):
            raise ValueError("los documentos de Qwen ({}) no son los de esta base ({} titulos)".format(
                D.shape[0], len(base.celdas)))
        # en GPU, fp16; en CPU (sin GPU libre), fp32: el fp16 en CPU es lento
        self.tipo = torch.float16 if str(dispositivo).startswith("cuda") else torch.float32
        self.D = torch.nn.functional.normalize(torch.from_numpy(np.asarray(D, dtype=np.float32)).to(dispositivo),
                                               dim=1).to(self.tipo)
        self.tok = AutoTokenizer.from_pretrained(ruta_qwen, padding_side="left")
        self.m = AutoModel.from_pretrained(ruta_qwen, dtype=torch.bfloat16).to(dispositivo).eval()
        self.juez = juez_mod.cargar(ruta_juez, dispositivo)
        if self.juez is None:
            raise ValueError("no se pudo cargar el cross-encoder de " + str(ruta_juez))
        self.grupo = np.asarray(base.grupo)
        self._lock = threading.Lock()
        self.nombre = "Qwen3-Embedding-8B + {} (umbral {})".format(pathlib.Path(ruta_juez).parent.name, self.umbral)

    def _consultas(self, titulos):
        import torch
        textos = ["Instruct: {}\nQuery:{}".format(TAREA, t) for t in titulos]
        with torch.no_grad():
            x = self.tok(textos, padding=True, truncation=True, max_length=64, return_tensors="pt").to(self.dispositivo)
            h = self.m(**x).last_hidden_state[:, -1]
            return torch.nn.functional.normalize(h.float(), dim=-1).to(self.tipo)

    def _en_base(self, t):
        b = self.base
        return t in b.idx or (getattr(b, "capa0", None) is not None and b._por_capa0(t) is not None)

    def reconocer(self, titulos):
        """Una lista de dicts, uno por titulo: estado (en_base | reconocido | desconocido | vacio), equivalente,
        p (P del cross-encoder del mejor candidato) y candidatos (los 3 mejores con su P)."""
        out = [None] * len(titulos)
        nuevos = []
        for k, t in enumerate(titulos):
            t = str(t or "").strip().upper()
            if not t:
                out[k] = {"estado": "vacio", "equivalente": None, "p": None, "candidatos": []}
            elif self._en_base(t):
                out[k] = {"estado": "en_base", "equivalente": None, "p": None, "candidatos": []}
            else:
                nuevos.append((k, t))
        if not nuevos:
            return out
        unicos = sorted({t for _, t in nuevos})
        with self._lock:                         # una GPU y un modelo: las consultas van de a una
            Q = self._consultas(unicos)
            s, v = (Q @ self.D.T).float().topk(K_VECINOS, dim=1)
        s, v = s.cpu().numpy(), v.cpu().numpy()
        cand = {}
        for i, t in enumerate(unicos):
            c, gs = [], set()
            for j, sim in zip(v[i], s[i]):
                g = int(self.grupo[j])
                if g in gs:
                    continue
                gs.add(g)
                cj = str(self.base.celdas[j])
                if cj == t or bloqueado(t, cj):
                    continue
                c.append((cj, float(sim)))
                if len(c) == N_CAND:
                    break
            cand[t] = c
        pares = [(t, cj) for t in unicos for cj, _ in cand[t]]
        P = dict(zip(pares, self.juez.P(pares))) if pares else {}
        res = {}
        for t in unicos:
            ps = sorted(((P[(t, cj)], cj) for cj, _ in cand[t]), reverse=True)
            mejor = ps[0] if ps else (0.0, None)
            ok = mejor[1] is not None and mejor[0] >= self.umbral
            res[t] = {"estado": "reconocido" if ok else "desconocido",
                      "equivalente": mejor[1] if ok else None,
                      "p": round(float(mejor[0]), 3) if ps else None,
                      "candidatos": [{"cargo": cj, "p": round(float(p), 3)} for p, cj in ps[:3]]}
        for k, t in nuevos:
            out[k] = res[t]
        return out


def cargar(base, ruta_qwen, ruta_docs, ruta_juez, dispositivo="cuda", umbral=UMBRAL):
    """El open set, o None si falta algo (pesos, documentos, torch o GPU): la API sigue sin el."""
    try:
        if not all(pathlib.Path(p).exists() for p in (ruta_qwen, ruta_docs, ruta_juez)):
            return None
        return OpenSet(base, ruta_qwen, ruta_docs, ruta_juez, dispositivo, umbral)
    except Exception as e:                                   # noqa: BLE001 - se informa y la API sigue
        print("[open set] no se pudo cargar: {!r}".format(e), flush=True)
        return None
