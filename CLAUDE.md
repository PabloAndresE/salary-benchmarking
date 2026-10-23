# Salary Benchmarking — backend

Referencias salariales de mercado: una nomina entra (`POST /informes`) y sale, en la misma
respuesta, la referencia de cada cargo homologado contra la base de estudios salariales
(65.181 puestos, 6.722 empresas), con su banda, su confianza y la lectura de equidad interna.

## Comandos <!-- FROZEN -->

```bash
uv sync                          # dependencias (uv.lock versionado)
uv run pytest                    # tests
uv run ruff check --fix && uv run black .
uv run pre-commit install        # uv lock --check, ruff --fix, black
uv run python run_server.py      # arranque local en :8080
```

## Tooling <!-- FROZEN -->

uv (no pip ni poetry) · Ruff + black, line-length 120 · Pydantic v2 · pytest · pre-commit ·
Python 3.14, FastAPI + Uvicorn · versiones exactas (`==`) en `pyproject.toml` ·
restricciones de seguridad en `[tool.uv] constraint-dependencies`.

## Stack de este servicio

- **Dominio pesado en memoria**: la base de referencia (`.npz`, 190 MB), un cross-encoder
  ("juez", 1,1 GB) y un traductor MarianMT (300 MB), todo en CPU con PyTorch.
- **Vertex AI** (`text-multilingual-embedding-002`) para embeber los titulos que la base
  no conoce.
- **BigQuery** (`act-cicd-stage-prueba.benchmarking`) para guardar las nominas cargadas.
- **GCS** (`gs://act-cicd-stage-prueba-benchmarking/benchmarking/<version>/`) para los
  artefactos de cada version: se bajan al arrancar.

## Arranque local

```bash
# artefactos de la version, a una carpeta local (gitignored)
uv run python -c "import pathlib; from src.infrastructure.artefactos import bajar; \
  bajar(url='gs://act-cicd-stage-prueba-benchmarking/benchmarking/v1.3', destino=pathlib.Path('artefactos'))"
GUARDAR_NOMINAS=no LOG_FORMAT=local GRPC_DNS_RESOLVER=native \
  BASE_REFERENCIA=artefactos/base/base_v31.npz JUEZ=artefactos/modelos/juez \
  TRADUCTOR=artefactos/modelos/opus-mt-en-es uv run python run_server.py
```

O sin bajar nada a mano: `ARTEFACTOS_GCS=gs://.../v1.3 uv run python run_server.py`.
Hace falta ADC (`gcloud auth application-default login`) con acceso a Vertex, BigQuery y
el bucket.

## Variables de entorno

| Variable | Default | Para que |
|---|---|---|
| `ARTEFACTOS_GCS` | — | version a bajar del bucket al arrancar |
| `ARTEFACTOS_DIR` | `/tmp/artefactos` | a donde se bajan |
| `BASE_REFERENCIA`, `JUEZ`, `TRADUCTOR` | (los bajados) | rutas locales; mandan sobre lo bajado |
| `GUARDAR_NOMINAS` | `si` | `no` apaga el registro de nominas en BigQuery |
| `BENCHMARKING_DATASET` | `act-cicd-stage-prueba.benchmarking` | destino de las nominas |
| `BQ_PROJECT`, `VERTEX_LOCATION`, `VERTEX_MODELO_EMBEDDINGS` | staging, `us-central1`, `text-multilingual-embedding-002` | |
| `CORS_ORIGINS` | puertos locales | origenes del front, separados por coma |
| `VERSION_API`, `VERSION_BASE` | `dev`, nombre de la base | viajan a cada carga guardada |
| `LOG_FORMAT`, `LOG_LEVEL` | `json`, `INFO` | `local` para leer los logs en una terminal |
| `GRPC_DNS_RESOLVER` | `native` (en la imagen) | el resolver c-ares de gRPC fallaba contra Vertex |
| `OMP_NUM_THREADS` | `4` (en la imagen) | torch usa todos los nucleos que ve |

Las banderas de decisiones (D-0xx: `JUEZ_VECINOS`, `TIPEO`, `TAMANO`, `PRIMA_DIRECCION`...)
estan documentadas donde se leen, en `src/infrastructure/motor.py`. Todas vienen
encendidas: son la v1.3.

## La red de seguridad del refactor

`tests/foto/foto.py` graba las respuestas de una API en marcha y compara otra contra ellas,
valor por valor. Los datos de la foto son reales y viven FUERA del repo
(`~/fotos-benchmarking/`). Todo cambio que toque el dominio se compara contra la foto
antes del commit.

## Reglas del repo

`.claude/rules/`: `architecture.md`, `coding-standards.md`, `testing.md`,
`technical-debt.md`, `domain.md`, `integrations.md`. Se actualizan en el MISMO commit que
el cambio que describen, y describen lo que es cierto hoy.
