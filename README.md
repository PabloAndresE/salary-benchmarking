# Salary Benchmarking — backend

Referencias salariales de mercado para las nominas de los clientes. Una nomina entra
(`POST /informes`) y sale, en la misma respuesta, la referencia de mercado de cada cargo
—homologado contra una base de estudios salariales de 6.722 empresas—, su banda, su
confianza y la lectura de equidad interna.

- **Contrato HTTP**: [`docs/api.md`](docs/api.md) (y `GET /docs` en el servicio).
- **Desplegar**: [`docs/despliegue.md`](docs/despliegue.md).
- **Comandos, arranque local y variables**: [`CLAUDE.md`](CLAUDE.md).
- **Reglas del repo** (arquitectura, convenciones, tests, deuda): `.claude/rules/`.
- **Decisiones de metodo** (D-001...D-092): [`docs/registro_decisiones.md`](docs/registro_decisiones.md).

```bash
uv sync
uv run pytest
ARTEFACTOS_GCS=gs://act-cicd-stage-prueba-benchmarking/benchmarking/v1.3 \
  GUARDAR_NOMINAS=no LOG_FORMAT=local uv run python run_server.py
```

Python 3.14 · FastAPI · PyTorch (CPU) · Vertex AI · BigQuery · Cloud Run.
