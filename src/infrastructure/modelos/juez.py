"""El juez de «mismo cargo» (cross-encoder v3, D-042) dentro del producto.

Hace EXACTAMENTE lo que hizo al medirse (`research/experimentos/e2_nivel/22_entrenar_cross.py`):
cada titulo va en la plantilla `El puesto de trabajo es {Titulo}.` (con `str.title()`), el par se
puntua en los dos ordenes, P(mismo) = P(A=>B) * P(B=>A) (modo direccional; promedio si el modelo es
simetrico), y se calibra con la temperatura del modelo (`info.json`). fp32, largo maximo 64.

Uso en la consulta (D-046, D-048): un titulo nuevo que no esta en la base ni por la capa 0 se juzga
contra los grupos cercanos (coseno >= 0,90, la zona en que la v3 se valido); si alguno tiene
P >= 0,5 y ningun candado lo impide, el titulo recibe los datos de ese grupo. Ver
`BaseReferencia.referenciar`.

Sin `torch` / `transformers`, o sin los pesos, el juez no se carga y el producto sigue como antes.
"""
import json
import pathlib

import numpy as np

MAXLEN = 64


class Juez:
    def __init__(self, ruta, dispositivo="auto", lote=128):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.ruta = pathlib.Path(ruta)
        info = json.loads((self.ruta / "info.json").read_text(encoding="utf-8"))
        self.modo = info["modo"]
        self.T = float(info["temperatura"])
        self.plantilla = info.get("plantilla", "El puesto de trabajo es {}.")
        self.nombre = info.get("nombre", self.ruta.name)
        if dispositivo == "auto":
            dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
        self.dispositivo, self.lote = dispositivo, lote
        self.tok = AutoTokenizer.from_pretrained(self.ruta)
        self.m = AutoModelForSequenceClassification.from_pretrained(
            self.ruta, dtype=torch.float32).to(dispositivo).eval()
        etq = [self.m.config.id2label[i].lower() for i in range(self.m.config.num_labels)]
        self.i_ent = next(k for k, e in enumerate(etq) if "entail" in e)
        self.cache = {}

    def _frase(self, t):
        return self.plantilla.format(str(t).title())

    def _entail(self, a, b):
        import torch
        out = []
        with torch.no_grad():
            for i in range(0, len(a), self.lote):
                x = self.tok([self._frase(t) for t in a[i:i + self.lote]],
                             [self._frase(t) for t in b[i:i + self.lote]], padding=True,
                             truncation=True, max_length=MAXLEN, return_tensors="pt").to(self.dispositivo)
                p = torch.softmax(self.m(**x).logits.float(), -1)[:, self.i_ent]
                out.append(p.cpu().numpy())
        return np.concatenate(out) if out else np.zeros(0)

    def P(self, pares):
        """P(mismo cargo) calibrada para cada par (a, b), con cache."""
        falta = list(dict.fromkeys(q for q in pares if q not in self.cache))
        if falta:
            a, b = [q[0] for q in falta], [q[1] for q in falta]
            ab, ba = self._entail(a, b), self._entail(b, a)
            s = (ab + ba) / 2 if self.modo == "simetrico" else ab * ba
            z = np.log(np.clip(s, 1e-6, 1 - 1e-6) / np.clip(1 - s, 1e-6, 1))
            for q, v in zip(falta, 1 / (1 + np.exp(-z / self.T))):
                self.cache[q] = float(v)
        return np.array([self.cache[q] for q in pares], dtype=float)


def cargar(ruta, dispositivo="auto"):
    """El juez de `ruta`, o None si no se puede (sin pesos o sin torch): el producto sigue sin el."""
    try:
        if not (pathlib.Path(ruta) / "model.safetensors").exists():
            return None
        return Juez(ruta, dispositivo)
    except Exception as e:                                   # noqa: BLE001 - se informa y se sigue
        print("[juez] no se pudo cargar {}: {!r}".format(ruta, e), flush=True)
        return None
