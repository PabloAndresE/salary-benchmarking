"""Los artefactos de una version —base, juez, traductor y prima— bajados del bucket al
arrancar.

    ARTEFACTOS_GCS=gs://act-cicd-stage-prueba-benchmarking/benchmarking/v1.3

Asi la imagen es la de cualquier backend (codigo + dependencias) y la version de la base
se elige por configuracion. Se bajan en paralelo a `ARTEFACTOS_DIR` (por defecto
`/tmp/artefactos`; en Cloud Run `/tmp` es memoria, y cuenta contra el limite de la
instancia: ~1,6 GB).

Sin `ARTEFACTOS_GCS` no hace nada: en local valen las rutas de `BASE_REFERENCIA`, `JUEZ`
y `TRADUCTOR` de siempre. Lo que ya este definido en el entorno MANDA sobre lo bajado.

Disposicion en el bucket (la que escribe `infra/crear_dataset_benchmarking.sh`):

    <version>/base/<base>.npz
    <version>/base/prima_direccion.json      (opcional)
    <version>/modelos/juez/...
    <version>/modelos/opus-mt-en-es/...
"""

import logging
import os
import pathlib
import time

logger = logging.getLogger(__name__)

TROZO_GRANDE = 100 * 1024 * 1024


def _partir(url: str) -> tuple[str, str]:
    if not url.startswith("gs://"):
        raise ValueError(f"ARTEFACTOS_GCS tiene que empezar por gs://: {url!r}")
    bucket, _, prefijo = url[5:].partition("/")
    return bucket, prefijo.strip("/")


def preparar_artefactos() -> pathlib.Path | None:
    url = os.getenv("ARTEFACTOS_GCS", "")
    if not url:
        return None
    destino = pathlib.Path(os.getenv("ARTEFACTOS_DIR", "/tmp/artefactos"))
    t0 = time.perf_counter()
    bajar(url=url, destino=destino)
    bases = sorted((destino / "base").glob("*.npz"))
    if len(bases) != 1:
        raise RuntimeError(f"se esperaba UNA base en {url}/base/ y hay {len(bases)}")
    os.environ.setdefault("BASE_REFERENCIA", str(bases[0]))
    os.environ.setdefault("JUEZ", str(destino / "modelos" / "juez"))
    os.environ.setdefault("TRADUCTOR", str(destino / "modelos" / "opus-mt-en-es"))
    logger.info("artefactos de %s listos en %.1fs", url, time.perf_counter() - t0)
    return destino


def bajar(*, url: str, destino: pathlib.Path, hilos: int = 16) -> int:
    """Baja todo lo que cuelga de `url` a `destino`, en paralelo. Devuelve cuantos."""
    from google.cloud import storage
    from google.cloud.storage import transfer_manager

    nombre_bucket, prefijo = _partir(url)
    bucket = storage.Client().bucket(nombre_bucket)
    blobs = [b for b in bucket.list_blobs(prefix=prefijo + "/") if not b.name.endswith("/")]
    if not blobs:
        raise RuntimeError(f"no hay artefactos en {url}")
    # Los GRANDES (el juez es UN archivo de 1,1 GB) se bajan por trozos en paralelo: en
    # paralelo por archivo, uno solo de ese tamano no se acelera.
    grandes = [x for x in blobs if (x.size or 0) > TROZO_GRANDE]
    chicos = [x for x in blobs if (x.size or 0) <= TROZO_GRANDE]
    for blob in grandes:
        ruta = destino / blob.name[len(prefijo) + 1 :]
        ruta.parent.mkdir(parents=True, exist_ok=True)
        transfer_manager.download_chunks_concurrently(
            blob, str(ruta), chunk_size=64 * 1024 * 1024, max_workers=hilos, worker_type=transfer_manager.THREAD
        )
    relativos = [x.name[len(prefijo) + 1 :] for x in chicos]
    resultados = transfer_manager.download_many_to_path(
        bucket,
        relativos,
        destination_directory=str(destino),
        blob_name_prefix=prefijo + "/",
        max_workers=hilos,
        worker_type=transfer_manager.THREAD,
    )
    fallos = [(r, e) for r, e in zip(relativos, resultados) if isinstance(e, Exception)]
    if fallos:
        raise RuntimeError(f"no se pudieron bajar {len(fallos)} artefactos: {fallos[:3]}")
    return len(blobs)
