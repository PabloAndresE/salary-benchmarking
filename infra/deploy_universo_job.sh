#!/usr/bin/env bash
# Despliega y ejecuta el job de Cloud Run que llena el universo (benchmarking_tesis.nomina_features).
# Reanudable/idempotente: reejecutar continúa desde lo ya escrito (estado = tabla destino).
#
# Prerrequisitos (una sola vez, requieren permisos de admin):
#   1. APIs habilitadas: run, cloudbuild, artifactregistry, secretmanager, bigquery.
#   2. Repo de Artifact Registry (abajo se crea si falta).
#   3. IAM de la service account del job ($JOB_SA):
#        - roles/bigquery.jobUser        en act-cicd-stage-prueba
#        - roles/bigquery.dataEditor     en act-cicd-stage-prueba (dataset benchmarking_tesis)
#        - roles/bigquery.dataViewer     en act-actuafast (dataset actuafastv2)  <-- CROSS-PROJECT
#        - roles/secretmanager.secretAccessor en el secreto benchmarking-pipeline-salt
set -euo pipefail

PROJECT="act-cicd-stage-prueba"
REGION="us-central1"
REPO="benchmarking"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/pipeline:latest"
JOB="benchmarking-universo"
# SA del job = Compute default de act-cicd-stage-prueba (projectNumber 383942996286).
JOB_SA="${JOB_SA:-383942996286-compute@developer.gserviceaccount.com}"

echo "== 1. Habilitar APIs =="
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com bigquery.googleapis.com \
  --project "$PROJECT"

echo "== 2. Artifact Registry (crear si falta) =="
gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format=docker \
    --location "$REGION" --project "$PROJECT" --description "Imágenes del pipeline de benchmarking"

echo "== 3. Build + push (Cloud Build, usa Dockerfile.pipeline) =="
gcloud builds submit --config infra/cloudbuild.pipeline.yaml \
  --substitutions=_IMAGE="$IMAGE" --project "$PROJECT" .

echo "== 4. Crear/actualizar el job de Cloud Run =="
gcloud run jobs deploy "$JOB" \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT" \
  --service-account "$JOB_SA" \
  --set-secrets "PIPELINE_SALT=benchmarking-pipeline-salt:latest" \
  --args "construir-universo,--batch-size=500,--concurrencia=8" \
  --task-timeout=24h --max-retries=3 --memory=2Gi --cpu=2

echo "== 5. Ejecutar =="
gcloud run jobs execute "$JOB" --region "$REGION" --project "$PROJECT"
echo "Lanzado. Monitorear: gcloud run jobs executions list --job $JOB --region $REGION --project $PROJECT"
