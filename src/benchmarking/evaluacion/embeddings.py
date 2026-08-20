"""Embeddings del texto de cargo, via Vertex AI, con cache.

Tres cuidados que no son opcionales:

- **Solo se embeben textos UNICOS.** Hay 68.504 titulos distintos entre 1,14 M de filas:
  embeber por fila seria 17x mas caro y lento sin ganar nada.
- **La revision del modelo entra en la clave de cache.** El spec de clustering 11 lo
  exige: si Google cambia el modelo sin avisar, los resultados dejan de ser reproducibles
  y hay que enterarse.
- **El tipo de tarea tambien entra en la clave.** `CLUSTERING` y `SEMANTIC_SIMILARITY`
  devuelven vectores distintos para el mismo texto; mezclarlos en un cache seria comparar
  cosas que no son comparables.

LIMITE MEDIDO de estos vectores (D-012, `mediciones.md` 14): **codifican el area y NO la
jerarquia**. Pares que solo se diferencian en el rango puntuan 0,857 y pares que solo se
diferencian en el area, 0,764 — un gerente y un auxiliar del mismo area se parecen mas que
dos jefes de areas distintas. El nivel tiene que venir de otra senal.
"""
import io
import os

import numpy as np

LOTE = 250              # limite practico de la API por peticion
TAREA = "CLUSTERING"    # el uso real es agrupar, no buscar ni comparar pares


class CacheMemoriaEmb:
    """Solo para tests y para scripts de un solo uso. NUNCA en produccion: 68.504
    vectores de 768 dimensiones son ~210 MB, y se perderian al terminar el proceso."""

    def __init__(self):
        self._d = {}

    def leer(self, clave):
        return self._d.get(clave)

    def guardar(self, clave, vector):
        self._d[clave] = vector

    def volcar(self):
        pass


class CacheArchivo:
    """Cache persistente en un unico `.npz`, local o en GCS (`gs://bucket/ruta.npz`).

    Un solo objeto y no uno por texto: con 68.504 etiquetas, 68.504 objetos en GCS son
    horas de latencia y un coste de operaciones absurdo frente a un archivo de 210 MB.

    Se carga entero al construir y se escribe al llamar `volcar()`. Quien lo use debe
    volcar explicitamente — asi un fallo a mitad de corrida no deja el cache a medias.
    """

    def __init__(self, ruta):
        self.ruta = str(ruta)
        self._d = {}
        self._sucio = False
        datos = self._leer_bytes()
        if datos:
            with np.load(io.BytesIO(datos), allow_pickle=False) as z:
                self._d = {k: z[k] for k in z.files}

    def _leer_bytes(self):
        if self.ruta.startswith("gs://"):
            from google.cloud import storage
            bucket, _, nombre = self.ruta[5:].partition("/")
            blob = storage.Client().bucket(bucket).blob(nombre)
            return blob.download_as_bytes() if blob.exists() else None
        return open(self.ruta, "rb").read() if os.path.exists(self.ruta) else None

    @staticmethod
    def _clave(clave):
        # numpy solo admite nombres de texto: se aplana la tupla (modelo, tarea, texto).
        return "\x1f".join(clave)

    def leer(self, clave):
        return self._d.get(self._clave(clave))

    def guardar(self, clave, vector):
        self._d[self._clave(clave)] = np.asarray(vector, dtype=np.float32)
        self._sucio = True

    def volcar(self):
        if not self._sucio:
            return
        buf = io.BytesIO()
        np.savez_compressed(buf, **self._d)
        datos = buf.getvalue()
        if self.ruta.startswith("gs://"):
            from google.cloud import storage
            bucket, _, nombre = self.ruta[5:].partition("/")
            storage.Client().bucket(bucket).blob(nombre).upload_from_string(
                datos, content_type="application/octet-stream")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(self.ruta)) or ".", exist_ok=True)
            with open(self.ruta, "wb") as fh:
                fh.write(datos)
        self._sucio = False


def embeber(textos, cliente, modelo, cache=None, lote=LOTE, tarea=TAREA):
    """Matriz (len(textos) x d) alineada fila a fila con `textos`.

    Las filas repetidas comparten vector: se resuelve por diccionario, no por llamada.

    Las cadenas VACIAS no se envian: Vertex responde `400 The text content is empty` y
    tumba el lote entero. Como `sorted()` las pone primero, basta una sola para que muera
    la primera peticion. Reciben el vector cero, que en un espacio centrado significa
    "sin informacion" — que es exactamente lo que un centro de costo en blanco aporta.
    """
    unicos = sorted({str(t) for t in textos})
    vacios = [t for t in unicos if not t.strip()]
    vectores, pendientes = {}, []
    for t in unicos:
        if not t.strip():
            continue
        v = cache.leer((modelo, tarea, t)) if cache is not None else None
        if v is None:
            pendientes.append(t)
        else:
            vectores[t] = np.asarray(v, dtype=float)

    for i in range(0, len(pendientes), lote):
        trozo = pendientes[i:i + lote]
        for t, emb in zip(trozo, cliente.get_embeddings(trozo)):
            v = np.asarray(emb.values, dtype=float)
            vectores[t] = v
            if cache is not None:
                cache.guardar((modelo, tarea, t), v)

    if vacios:
        dim = len(next(iter(vectores.values()))) if vectores else 1
        for t in vacios:
            vectores[t] = np.zeros(dim, dtype=float)

    return np.vstack([vectores[str(t)] for t in textos])


def cliente_vertex(modelo, proyecto, location, tarea=TAREA):
    """Cliente real de Vertex. Se aisla aqui para que los tests no lo importen.

    Devuelve un envoltorio con `get_embeddings(list[str])` para que `embeber` no dependa
    del SDK: el tipo de tarea se fija aqui y no en cada llamada.
    """
    import vertexai
    from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

    vertexai.init(project=proyecto, location=location)
    modelo_vertex = TextEmbeddingModel.from_pretrained(modelo)

    class _Cliente:
        def get_embeddings(self, textos):
            return modelo_vertex.get_embeddings(
                [TextEmbeddingInput(t, tarea) for t in textos])

    return _Cliente()
