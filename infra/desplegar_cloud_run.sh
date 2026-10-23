#!/usr/bin/env bash
# Despliega el backend en Cloud Run. Idempotente: se puede correr en cada version.
#
#   CORS_ORIGINS=https://front.ejemplo.com infra/desplegar_cloud_run.sh
#
# Hace, en este orden:
#   1. habilita las APIs (Run, Artifact Registry, Cloud Build, Vertex AI)
#   2. crea la cuenta de servicio y le da SOLO lo que usa: Vertex, BigQuery (el dataset
#      del producto) y lectura del bucket de artefactos
#   3. construye la imagen con Cloud Build desde el Dockerfile y la sube a Artifact Registry
#   4. despliega el servicio bajo demanda (0 instancias en reposo)
#
# Requisitos: `gcloud auth login` con permisos de administracion en el proyecto, y el
# dataset y los artefactos ya creados (`infra/crear_dataset_benchmarking.sh`).
#
# Variables (todas con default de staging):
#   PROYECTO   act-cicd-stage-prueba          REGION     us-central1
#   SERVICIO   salary-benchmarking-backend    REPO       benchmark (Artifact Registry)
#   VERSION    la de pyproject.toml           ARTEFACTOS gs://act-cicd-stage-prueba-benchmarking/benchmarking/v1.3
#   DATASET    benchmarking                   BUCKET     act-cicd-stage-prueba-benchmarking
#   CORS_ORIGINS  origenes del front, separados por coma (sin esto, solo localhost)
#   PUBLICO    no | si   (no: exige identidad de Google para llamar; ver docs/despliegue.md)
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
PROYECTO="${PROYECTO:-act-cicd-stage-prueba}"
REGION="${REGION:-us-central1}"
SERVICIO="${SERVICIO:-salary-benchmarking-backend}"
REPO="${REPO:-benchmark}"
VERSION="${VERSION:-v$(grep -m1 '^version' "$RAIZ/pyproject.toml" | cut -d'"' -f2)}"
DATASET="${DATASET:-benchmarking}"
BUCKET="${BUCKET:-act-cicd-stage-prueba-benchmarking}"
ARTEFACTOS="${ARTEFACTOS:-gs://$BUCKET/benchmarking/v1.3}"
CORS_ORIGINS="${CORS_ORIGINS:-}"
PUBLICO="${PUBLICO:-no}"
SA="benchmarking-api@$PROYECTO.iam.gserviceaccount.com"
IMAGEN="$REGION-docker.pkg.dev/$PROYECTO/$REPO/$SERVICIO:$VERSION"

echo "== $SERVICIO $VERSION -> $PROYECTO ($REGION)"

echo "== 1. APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  aiplatform.googleapis.com bigquery.googleapis.com --project "$PROYECTO"

echo "== 2. cuenta de servicio y permisos"
gcloud iam service-accounts describe "$SA" --project "$PROYECTO" >/dev/null 2>&1 || \
  gcloud iam service-accounts create benchmarking-api --project "$PROYECTO" \
    --display-name "Salary Benchmarking backend"
for ROL in roles/aiplatform.user roles/bigquery.jobUser; do
  gcloud projects add-iam-policy-binding "$PROYECTO" --member "serviceAccount:$SA" --role "$ROL" \
    --condition None --quiet >/dev/null
done
# BigQuery: escribir SOLO en el dataset del producto
bq add-iam-policy-binding --member="serviceAccount:$SA" --role="roles/bigquery.dataEditor" \
  "$PROYECTO:$DATASET" >/dev/null
# GCS: leer SOLO el bucket de artefactos
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$SA" \
  --role roles/storage.objectViewer --project "$PROYECTO" >/dev/null

echo "== 3. imagen $IMAGEN"
gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROYECTO" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION" --project "$PROYECTO"
gcloud builds submit "$RAIZ" --tag "$IMAGEN" --project "$PROYECTO" --region "$REGION"

echo "== 4. Cloud Run"
AUTH="--no-allow-unauthenticated"
[ "$PUBLICO" = "si" ] && AUTH="--allow-unauthenticated"
# `^|^` al principio: el separador pasa a ser `|`, y CORS_ORIGINS puede llevar comas
ENVS="^|^ARTEFACTOS_GCS=$ARTEFACTOS|BENCHMARKING_DATASET=$PROYECTO.$DATASET|BQ_PROJECT=$PROYECTO|VERSION_API=$VERSION"
[ -n "$CORS_ORIGINS" ] && ENVS="$ENVS|CORS_ORIGINS=$CORS_ORIGINS"
# BAJO DEMANDA: 0 instancias en reposo. 4 vCPU (el informe escala con los nucleos hasta ~8) y
# 8 GiB: ~3,3 GB del motor + ~1,6 GB de artefactos en /tmp, que en Cloud Run es memoria.
# Sin estado entre peticiones (el informe es sincrono), asi que puede escalar.
# La sonda de arranque por defecto (TCP, 240 s) espera a que el motor este cargado.
gcloud run deploy "$SERVICIO" --image "$IMAGEN" --region "$REGION" --project "$PROYECTO" \
  --service-account "$SA" $AUTH \
  --cpu 4 --memory 8Gi --min-instances 0 --max-instances 3 --concurrency 8 \
  --timeout 300 --cpu-boost --execution-environment gen2 \
  --set-env-vars "$ENVS"

URL="$(gcloud run services describe "$SERVICIO" --region "$REGION" --project "$PROYECTO" --format 'value(status.url)')"
echo "== listo: $URL"
echo "   prueba: curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" $URL/salud"
