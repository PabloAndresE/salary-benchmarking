#!/usr/bin/env bash
# Crea el dataset del producto (`benchmarking`) en BigQuery y, si se da un bucket, sube
# los artefactos de la version (base, juez, traductor) y la registra en `versiones`.
# Idempotente: se puede correr de nuevo sin duplicar nada.
#
# NO TOCA `benchmarking_tesis`: solo lee de ahi para congelar `marco_v31`.
#
# Uso:
#   infra/crear_dataset_benchmarking.sh                 # solo BigQuery
#   BUCKET=mi-bucket infra/crear_dataset_benchmarking.sh  # + artefactos en GCS
# Variables:
#   PROYECTO  (default act-cicd-stage-prueba)   DATASET  (default benchmarking)
#   LOCATION  (default us-central1)             VERSION  (default v1.3)
#   BASE, JUEZ, TRADUCTOR: rutas locales (default: las del H200, como construir_api.sh)
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
PROYECTO="${PROYECTO:-act-cicd-stage-prueba}"
DATASET="${DATASET:-benchmarking}"
LOCATION="${LOCATION:-us-central1}"
VERSION="${VERSION:-v1.3}"
BUCKET="${BUCKET:-}"
BASE="${BASE:-$RAIZ/../salary-benchmarking/demo/base_v31.npz}"
JUEZ="${JUEZ:-$RAIZ/../salary-benchmarking/modelos/juez_v3}"
TRADUCTOR="${TRADUCTOR:-$RAIZ/../salary-benchmarking/modelos/opus-mt-en-es}"
PY="${PY:-python3}"

consulta() { bq query --project_id="$PROYECTO" --location="$LOCATION" --use_legacy_sql=false --quiet "$@"; }

echo "== dataset $PROYECTO:$DATASET ($LOCATION)"
bq show --project_id="$PROYECTO" "$PROYECTO:$DATASET" >/dev/null 2>&1 || \
  bq mk --project_id="$PROYECTO" --dataset --location="$LOCATION" \
     --description "Salary Benchmarking - PRODUCTO (cargas, homologaciones, versiones). La tesis vive en benchmarking_tesis." \
     "$PROYECTO:$DATASET"

echo "== tablas de las cargas (desde src/persistence/tablas.py)"
PYTHONPATH="$RAIZ" "$PY" -c \
  "from src.persistence.tablas import ddl; print(ddl('$PROYECTO.$DATASET'))" \
  | consulta

echo "== versiones, marco_v31 y vistas"
sed -e "s/{proyecto}/$PROYECTO/g" -e "s/{dataset}/$DATASET/g" \
    "$RAIZ/infra/crear_dataset_benchmarking.sql" | consulta

if [ -z "$BUCKET" ]; then
  echo "== sin BUCKET: no se suben artefactos ni se registra la version"
  exit 0
fi

DEST="gs://$BUCKET/benchmarking/$VERSION"
echo "== artefactos a $DEST"
gcloud storage cp "$(readlink -f "$BASE")" "$DEST/base/$(basename "$BASE")" --project "$PROYECTO"
gcloud storage cp -r "$(readlink -f "$JUEZ")"/* "$DEST/modelos/juez/" --project "$PROYECTO"
gcloud storage cp -r "$(readlink -f "$TRADUCTOR")"/* "$DEST/modelos/opus-mt-en-es/" --project "$PROYECTO"
# la prima de direccion precalculada (infra/precalcular_prima.py), si esta junto a la base
PRIMA="$(dirname "$(readlink -f "$BASE")")/prima_direccion.json"
[ -f "$PRIMA" ] && gcloud storage cp "$PRIMA" "$DEST/base/prima_direccion.json" --project "$PROYECTO"

SHA="$(sha256sum "$(readlink -f "$BASE")" | cut -d' ' -f1)"
JUEZ_NOMBRE="$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1])).get('nombre',''))" "$(readlink -f "$JUEZ")/info.json" 2>/dev/null || true)"
COMMIT="$(git -C "$RAIZ" rev-parse --short HEAD)"
echo "== registrar $VERSION en versiones (si no estaba)"
consulta <<SQL
INSERT INTO \`$PROYECTO.$DATASET.versiones\`
SELECT '$VERSION', CURRENT_TIMESTAMP(), '$(basename "$BASE" .npz)', '$DEST/base/$(basename "$BASE")',
       '$SHA', '${JUEZ_NOMBRE:-juez_v3}', '$DEST/modelos/juez/', 'opus-mt-en-es',
       '$DEST/modelos/opus-mt-en-es/', '$PROYECTO.$DATASET.marco_v31', 'D-092', '$COMMIT',
       'primera version del producto desplegada'
FROM (SELECT 1)
WHERE NOT EXISTS (SELECT 1 FROM \`$PROYECTO.$DATASET.versiones\` WHERE version = '$VERSION');
SQL
echo "listo"
