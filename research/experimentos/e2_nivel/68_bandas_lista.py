"""Bandas de una lista de cargos con el producto vigente (Vertex, `base_v22`) y con e5 (`base_e5`, D-057).

Misma configuracion que la API: juez en la consulta y en los vecinos, nivel por grupo y su candado, el
mismo cargo = la misma banda en ingles y en espanol (traduccion local), rango de mercado p25-p75 de la
banda de empresas. El titulo se consulta como la API: `strip().upper()`.

    GRPC_DNS_RESOLVER=native ../../../.venv/bin/python 68_bandas_lista.py lista.txt salida.md

La salida contiene bandas de mercado: va fuera del repo (`demo/`).
"""
import collections
import datetime as dt
import pathlib
import sys

import numpy as np
import torch

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.evaluacion import embeddings  # noqa: E402
from benchmarking.producto import idioma  # noqa: E402
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402
from benchmarking.producto.juez import cargar as cargar_juez  # noqa: E402

COMO = {"datos directos": "datos directos", "por analogia": "analogía", "por traduccion": "traducción"}


def codificador_e5():
    from transformers import AutoModel, AutoTokenizer
    ruta = SAL / "48_bi_encoder_B3" / "semilla_1"
    tok = AutoTokenizer.from_pretrained(ruta)
    mod = AutoModel.from_pretrained(ruta).eval()

    def f(textos):
        with torch.no_grad():
            t = tok(["query: " + x for x in textos], padding=True, truncation=True, max_length=32,
                    return_tensors="pt")
            h = mod(**t).last_hidden_state
            k = t["attention_mask"].unsqueeze(-1).to(h.dtype)
            return torch.nn.functional.normalize((h * k).sum(1) / k.sum(1), dim=-1).numpy()
    return f


def consultar(ruta_base, titulos, embeber, cos_juez=None, anio=None):
    s = cargar_settings()
    base = BaseReferencia.cargar(ruta_base, s.get_sbu)
    base.juez = cargar_juez(RAIZ / "modelos" / "juez_v3")
    base.juez_vecinos = True
    base.nivel_por_grupo()
    base.candado_nivel = True
    if cos_juez:
        base.cos_juez = cos_juez
    base.traductor = idioma.cargar(RAIZ / "modelos" / "opus-mt-en-es")
    base.idioma_sueldo = "siempre"
    base.idioma_prima = None
    emb = {c: base.Z[i] for i, c in enumerate(base.celdas)}
    nuevos = [t for t in titulos if t not in emb]
    nuevos += [x for x in base.traducciones_a_embeber(titulos) if x not in emb]
    if nuevos:
        emb.update(dict(zip(nuevos, embeber(nuevos))))
    return base.referenciar(titulos, emb, anio=anio or dt.date.today().year).set_index("cargo")


def usd(x):
    return "—" if x is None or not np.isfinite(x) else "${:,.0f}".format(x).replace(",", ".")


def main(lista, salida):
    originales = [line.strip() for line in open(lista, encoding="utf-8") if line.strip()]
    titulos = [t.upper() for t in originales]
    s = cargar_settings()
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
    v = consultar(RAIZ / "demo" / "base_v22.npz", titulos,
                  lambda x: embeddings.embeber(x, cli, s.vertex_embedding_model))
    e = consultar(RAIZ / "demo" / "base_e5.npz", titulos, codificador_e5(), cos_juez=0.8258)
    L = ["# Bandas de mercado: e5 frente a Vertex ({})".format(dt.date.today().isoformat()), "",
         "Misma configuración que la API (base con nivel de Qwen v3, ancho recalibrado; el mismo cargo da la "
         "misma banda en inglés y en español). Lo único que cambia es el modelo que busca los cargos "
         "parecidos: **Vertex** (el producto de hoy, `base_v22`) o **e5 ajustado** (`base_e5`, D-057, en "
         "medición).", "",
         "- **Rango** = p25–p75 de lo que pagan **las empresas** por el cargo (el 50 % central); **ref.** = la "
         "mediana.",
         "- **Ancho** = p75 / p25: cuántas veces el tope del rango supera su piso (menos es más angosto).",
         "- **Cómo**: *directos* (el cargo, o su equivalente en español, tiene ≥ 3 empresas) o *analogía* "
         "(cargos parecidos, ajustados por nivel). Confianza **BAJA** = referencia orientativa.", "",
         "| # | Cargo | Vertex: equivalente · cómo | Vertex: ref. · rango | e5: equivalente · cómo "
         "| e5: ref. · rango | Ancho Vertex → e5 |",
         "|---|---|---|---|---|---|---|"]
    anchos = []
    for i, (o, t) in enumerate(zip(originales, titulos), 1):
        a, b = v.loc[t], e.loc[t]
        ra = a.get("equivalente") or a.get("cargo_base") or "—"
        rb = b.get("equivalente") or b.get("cargo_base") or "—"
        wa, wb = a["rango_hasta"] / a["rango_desde"], b["rango_hasta"] / b["rango_desde"]
        anchos.append((wa, wb, b["base"]))
        L.append("| {} | {} | {} · {} | {} · {}–{} | {} · {} | {} · {}–{} | ×{:.2f} → ×{:.2f} |".format(
            i, o, ra, COMO.get(a["base"], a["base"]), usd(a["referencia"]), usd(a["rango_desde"]),
            usd(a["rango_hasta"]), rb, COMO.get(b["base"], b["base"]), usd(b["referencia"]),
            usd(b["rango_desde"]), usd(b["rango_hasta"]), wa, wb))
    wa = np.array([x[0] for x in anchos])
    wb = np.array([x[1] for x in anchos])
    cuenta = collections.Counter(COMO.get(x[2], x[2]) for x in anchos)
    L += ["", "**Resumen** ({} cargos): ancho mediano del rango ×{:.2f} con Vertex y ×{:.2f} con e5; más angosto con e5 "
          "en {} de {}. Con e5: {}.".format(len(anchos), np.median(wa), np.median(wb), int((wb < wa - 1e-9).sum()),
                                            len(anchos), ", ".join("{} por {}".format(n, k) for k, n in cuenta.items())),
          "", "*Una lista de cargos no mide la calidad: eso lo dice el pinball sobre empresas apartadas (D-057).*"]
    pathlib.Path(salida).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
