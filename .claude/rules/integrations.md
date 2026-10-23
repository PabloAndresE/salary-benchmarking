# Integraciones

## Vertex AI — embeddings

- `src/integrations/vertex/vertex_client.py`; modelo `text-multilingual-embedding-002`
  (`VERTEX_MODELO_EMBEDDINGS`), region `us-central1`.
- Se llama solo para titulos que la base no conoce (y sus traducciones). El cliente se
  crea en el primer uso; el calentamiento del arranque lo deja listo.
- Autenticacion: ADC (en Cloud Run, la cuenta de servicio del servicio; rol
  `roles/aiplatform.user`). Sin credenciales en el repo.
- Si falla: `/puestos` responde 503 ("no se pudo embeber"); el arranque sigue (sin
  calentamiento). SDK deprecado: ver technical-debt.

## BigQuery — nominas cargadas

- `src/persistence/bigquery_client.py`, dataset `BENCHMARKING_DATASET`
  (`act-cicd-stage-prueba.benchmarking`), tablas `cargas`, `nomina_filas`,
  `homologaciones` (esquema en `persistence/tablas.py`; las crea
  `infra/crear_dataset_benchmarking.sh`).
- Streaming (`insert_rows_json`) con `insertId` = `id_carga:tabla:fila`.
- Roles: `roles/bigquery.jobUser` (proyecto) y `roles/bigquery.dataEditor` (dataset).
- Si falla: el informe sale igual; ERROR en el log con el `id_carga`.

## GCS — artefactos

- `gs://act-cicd-stage-prueba-benchmarking/benchmarking/<version>/` (`ARTEFACTOS_GCS`):
  `base/<base>.npz`, `base/prima_direccion.json`, `modelos/juez/`, `modelos/opus-mt-en-es/`.
- Se bajan al arrancar (`src/infrastructure/artefactos.py`). Rol:
  `roles/storage.objectViewer` en el bucket.
- Si falla: la instancia no arranca (sin base no hay servicio).
