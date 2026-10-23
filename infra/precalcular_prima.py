"""Precalcula la prima de direccion (D-092) de una base y la deja junto a ella.

    BASE_REFERENCIA=artefactos/base/base_v31.npz JUEZ=no CALENTAR=no \
        uv run python infra/precalcular_prima.py

Es la MISMA cuenta que hace el servicio al arrancar sin prima guardada
(`BaseReferencia.estimar_prima_direccion`), con los mismos embeddings de Vertex. Se guarda
a toda precision: la foto de respuestas compara valor por valor.
"""

import json
import os

from src.config.logging_config import setup_logging
from src.infrastructure.motor import ruta_prima_direccion

os.environ["PRIMA_DIRECCION_ARCHIVO"] = "/nonexistent"  # que el motor la CALCULE, no que la lea
os.environ.setdefault("CALENTAR", "no")

from src.infrastructure.motor import iniciar_motor  # noqa: E402

setup_logging()
m = iniciar_motor()
os.environ.pop("PRIMA_DIRECCION_ARCHIVO")
if not m.base.prima_direccion:
    raise SystemExit("no se pudo estimar la prima (sin traductor, sin Vertex o sin pares)")
med, var = m.base.prima_direccion
destino = ruta_prima_direccion(m.ruta_base)
destino.write_text(json.dumps({"mediana": med, "varianza": var, "base": os.path.basename(m.ruta_base)}, indent=2))
print(f"prima {med!r} / {var!r} -> {destino}")
