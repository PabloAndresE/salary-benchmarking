# Salary Benchmarking: imagen del estandar de backends (codigo + dependencias). La base y
# los modelos NO van dentro: se bajan del bucket al arrancar (ARTEFACTOS_GCS), asi la
# version de la base se elige por configuracion y la imagen pesa ~1 GB menos.
FROM python:3.14.9-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencias primero: cambian poco y su capa se reutiliza entre builds
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY run_server.py ./

# Usuario sin privilegios. La API no escribe en disco salvo los artefactos en /tmp.
RUN useradd --system --uid 10001 --no-create-home benchmarking
USER benchmarking

ENV PATH="/app/.venv/bin:$PATH" \
    # el resolver c-ares de gRPC fallaba contra Vertex; el nativo no
    GRPC_DNS_RESOLVER=native \
    # torch usa todos los nucleos que ve; se acota a los de la instancia
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    ARTEFACTOS_DIR=/tmp/artefactos \
    PORT=8080

# Smoke: si falta un archivo de datos del paquete, falla el BUILD y no el arranque
RUN python -c "import src.main"

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
