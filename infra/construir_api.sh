#!/usr/bin/env bash
# Arma el contexto de build de la API (codigo + modelos + base) y construye la imagen.
#
# Los modelos y la base no viven en git. Se toman de rutas locales (por defecto, las del
# H200) o, en Cloud Build, de lo que se haya bajado antes de GCS a esas mismas rutas.
#
# Uso:
#   infra/construir_api.sh [etiqueta]
# Variables:
#   BASE      base serializada        (default: ../salary-benchmarking/demo/base_v31.npz)
#   JUEZ      carpeta del juez        (default: ../salary-benchmarking/modelos/juez_v3)
#   TRADUCTOR carpeta del traductor   (default: ../salary-benchmarking/modelos/opus-mt-en-es)
#   MOTOR     docker | podman | buildah (default: el primero que exista)
#   SOLO_CONTEXTO=1  arma el contexto y no construye
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
ETIQUETA="${1:-benchmarking-api:local}"
BASE="${BASE:-$RAIZ/../salary-benchmarking/demo/base_v31.npz}"
JUEZ="${JUEZ:-$RAIZ/../salary-benchmarking/modelos/juez_v3}"
TRADUCTOR="${TRADUCTOR:-$RAIZ/../salary-benchmarking/modelos/opus-mt-en-es}"

CTX="$(mktemp -d)"
trap 'rm -rf "$CTX"' EXIT

cp "$RAIZ/Dockerfile.api" "$RAIZ/requirements-api.txt" "$CTX/"
cp -r "$RAIZ/src" "$CTX/src"
find "$CTX/src" -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$CTX/artefactos/modelos" "$CTX/artefactos/base"
# -L: `juez_v3` es un enlace simbolico; a la imagen va el modelo, no el enlace
cp -rL "$JUEZ" "$CTX/artefactos/modelos/juez"
cp -rL "$TRADUCTOR" "$CTX/artefactos/modelos/opus-mt-en-es"
cp -L "$BASE" "$CTX/artefactos/base/base_referencia.npz"
# La imagen corre con un usuario sin privilegios, y COPY conserva los permisos de origen
# (la base del H200 es solo de root). Se arreglan aqui y no con un `chmod` en el
# Dockerfile, que duplicaria 1,6 GB en una capa nueva.
chmod -R a+rX "$CTX/artefactos" "$CTX/src"
du -sh "$CTX/artefactos/modelos/"* "$CTX/artefactos/base/"*

if [ "${SOLO_CONTEXTO:-0}" = 1 ]; then
  trap - EXIT
  echo "contexto: $CTX"
  exit 0
fi

MOTOR="${MOTOR:-$(command -v docker || command -v podman || command -v buildah || true)}"
[ -n "$MOTOR" ] || { echo "no hay docker, podman ni buildah"; exit 1; }
case "$(basename "$MOTOR")" in
  buildah) "$MOTOR" bud --layers -f "$CTX/Dockerfile.api" -t "$ETIQUETA" "$CTX" ;;
  *)       "$MOTOR" build -f "$CTX/Dockerfile.api" -t "$ETIQUETA" "$CTX" ;;
esac
