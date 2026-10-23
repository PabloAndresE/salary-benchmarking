"""El UNICO punto de acceso a BigQuery del servicio.

Se escribe por STREAMING (`insert_rows_json`), no con load jobs: tarda ~0,5 s frente a
~10 s de tres load jobs, y cabe dentro de la peticion sincrona del informe. Las tablas
tienen que existir: las crea `infra/crear_dataset_benchmarking.sh`.

El cliente se crea en el primer uso (estandar): los tests corren sin credenciales.
"""

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _cliente(proyecto: str):
    from google.cloud import bigquery

    return bigquery.Client(project=proyecto)


def insertar_filas(*, dataset: str, tabla: str, filas: list[dict], claves: list[str] | None = None) -> None:
    """Anade `filas` a `dataset.tabla`. `claves` son los `insertId` de BigQuery: con ellos
    un reintento de la misma fila no la duplica (deduplicacion de mejor esfuerzo)."""
    if not filas:
        return
    errores = _cliente(dataset.split(".")[0]).insert_rows_json(f"{dataset}.{tabla}", filas, row_ids=claves)
    if errores:
        raise RuntimeError(f"BigQuery rechazo {len(errores)} filas de {tabla}: {errores[:3]}")
