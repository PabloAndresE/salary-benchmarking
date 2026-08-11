"""Los embeddings, .separan el NIVEL o solo el AREA?

La pregunta que decide si hace falta normalizar los cargos antes de agrupar. El arquetipo
es rol-familia x NIVEL, y los embeddings estan dominados por el tema: `JEFE DE VENTAS` y
`ASISTENTE DE VENTAS` hablan los dos de ventas.

Ya se midio que el emparejamiento por CARACTERES invierte la jerarquia —AUXILIAR DE
SERVICIOS GENERALES -> JEFE DE SERVICIOS GENERALES puntuaba 0,79—, pero eso era TF-IDF.
Suponerlo de los embeddings sin medirlo seria repetir el error de D-010.

El diseno: pares construidos con etiquetas REALES del marco.

  par de NIVEL : misma area, distinto rango   (AUXILIAR DE BODEGA / JEFE DE BODEGA)
  par de AREA  : mismo rango, distinta area   (JEFE DE BODEGA   / JEFE DE VENTAS)

Si los pares de nivel salen MAS parecidos que los de area, el embedding ignora la
jerarquia y hace falta ayuda externa. Si los separa, nos ahorramos el paso.
"""
import argparse
import itertools
import re

import numpy as np
import pandas as pd
from google.cloud import bigquery

MODELO = "text-multilingual-embedding-002"
REGION = "us-central1"

# Rangos ordenados. El numero es el nivel aproximado; solo se usa para no comparar
# sinonimos del mismo escalon (AUXILIAR/AYUDANTE) como si fueran jerarquia.
RANGOS = {
    "AYUDANTE": 1, "AUXILIAR": 1, "OPERARIO": 1, "OBRERO": 1, "ASISTENTE": 1,
    "TECNICO": 2, "ANALISTA": 2,
    "SUPERVISOR": 3, "COORDINADOR": 3, "ESPECIALISTA": 3,
    "JEFE": 4, "SUBGERENTE": 4,
    "GERENTE": 5, "DIRECTOR": 5,
}
_PATRON = re.compile(rf"^({'|'.join(RANGOS)})\s+(?:DE\s+|DEL\s+)?(.+)$")


def descomponer(etiqueta):
    """('JEFE DE BODEGA') -> ('JEFE', 'BODEGA'), o None si no lleva rango explicito."""
    m = _PATRON.match(etiqueta.strip().upper())
    return (m.group(1), m.group(2).strip()) if m else None


def cargar_etiquetas(limite=4000):
    cl = bigquery.Client()
    q = f"""
    SELECT cargo_norm, COUNT(*) n
    FROM `act-cicd-stage-prueba.benchmarking_tesis.nomina_features`
    WHERE en_clean AND anio_valoracion IN (2024, 2025) AND cargo_norm IS NOT NULL
    GROUP BY cargo_norm ORDER BY n DESC LIMIT {int(limite)}
    """
    return cl.query(q).to_dataframe()


def construir_pares(etiquetas, max_pares=400):
    """Pares de nivel y de area, con etiquetas reales."""
    partes = {}
    for e in etiquetas:
        d = descomponer(e)
        if d:
            partes.setdefault(d[1], {})[d[0]] = e

    nivel, area = [], []
    for _, porrango in partes.items():
        for a, b in itertools.combinations(sorted(porrango), 2):
            if RANGOS[a] != RANGOS[b]:                     # jerarquia real, no sinonimos
                nivel.append((porrango[a], porrango[b], abs(RANGOS[a] - RANGOS[b])))

    por_rango = {}
    for resto, porrango in partes.items():
        for rango, etiqueta in porrango.items():
            por_rango.setdefault(rango, []).append((resto, etiqueta))
    for rango, lista in por_rango.items():
        for (r1, e1), (r2, e2) in itertools.combinations(sorted(lista)[:30], 2):
            if r1 != r2:
                area.append((e1, e2, 0))

    rng = np.random.default_rng(20260805)
    def muestra(xs):
        if len(xs) <= max_pares:
            return xs
        return [xs[i] for i in rng.choice(len(xs), max_pares, replace=False)]
    return muestra(nivel), muestra(area)


def embeber(textos):
    import vertexai
    from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput
    vertexai.init(project="act-cicd-stage-prueba", location=REGION)
    modelo = TextEmbeddingModel.from_pretrained(MODELO)
    salida = []
    for i in range(0, len(textos), 100):
        lote = [TextEmbeddingInput(t, "CLUSTERING") for t in textos[i:i + 100]]
        salida.extend(e.values for e in modelo.get_embeddings(lote))
    X = np.asarray(salida, dtype=float)
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=4000)
    args = ap.parse_args()

    df = cargar_etiquetas(args.limite)
    print(f"etiquetas cargadas: {len(df):,} (cubren {df.n.sum():,} personas)")
    nivel, area = construir_pares(df["cargo_norm"].tolist())
    print(f"pares de NIVEL: {len(nivel):,}   pares de AREA: {len(area):,}")
    if not nivel or not area:
        print("no hay pares suficientes; subir --limite")
        return

    textos = sorted({t for p in (nivel, area) for a, b, _ in p for t in (a, b)})
    print(f"textos a embeber: {len(textos):,}")
    X = embeber(textos)
    pos = {t: i for i, t in enumerate(textos)}
    sim = lambda a, b: float(X[pos[a]] @ X[pos[b]])

    s_nivel = np.array([sim(a, b) for a, b, _ in nivel])
    s_area = np.array([sim(a, b) for a, b, _ in area])

    print("\n=== SIMILITUD COSENO ===")
    print(f"pares de NIVEL (misma area, distinto rango): "
          f"media={s_nivel.mean():.4f}  mediana={np.median(s_nivel):.4f}")
    print(f"pares de AREA  (mismo rango, distinta area): "
          f"media={s_area.mean():.4f}  mediana={np.median(s_area):.4f}")
    print(f"\nDIFERENCIA (area - nivel): {s_area.mean() - s_nivel.mean():+.4f}")

    for salto in sorted({d for _, _, d in nivel}):
        s = np.array([sim(a, b) for a, b, d in nivel if d == salto])
        print(f"  salto de {salto} escalon(es): media={s.mean():.4f}  (n={len(s)})")

    print("\n=== LECTURA ===")
    if s_nivel.mean() > s_area.mean():
        print("El embedding considera MAS parecidos dos cargos que solo se diferencian en")
        print("el RANGO que dos del mismo rango en areas distintas. Esta dominado por el")
        print("tema y NO codifica la jerarquia: el nivel necesita una senal aparte.")
    else:
        print("El embedding separa el rango mejor que el area. La jerarquia esta")
        print("codificada y no hace falta normalizar los cargos por ese motivo.")

    print("\nlos 8 pares de NIVEL mas parecidos (los que mas confundiria):")
    for i in np.argsort(-s_nivel)[:8]:
        a, b, d = nivel[i]
        print(f"  {s_nivel[i]:.4f}  {a}  <->  {b}")


if __name__ == "__main__":
    main()
