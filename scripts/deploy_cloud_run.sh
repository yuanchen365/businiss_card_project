#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="business-card-sync"
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-}"
REGION="${GOOGLE_CLOUD_REGION:-asia-east1}"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "GOOGLE_CLOUD_PROJECT environment variable is required" >&2
  exit 1
fi

gcloud config set project "${PROJECT_ID}"

echo "Building container image ${IMAGE}..."
gcloud builds submit --tag "${IMAGE}" .

echo "Deploying Cloud Run service ${SERVICE_NAME} in ${REGION}..."
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --platform=managed \
  --region="${REGION}" \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_SCOPES=${GOOGLE_SCOPES:-https://www.googleapis.com/auth/contacts,openid,https://www.googleapis.com/auth/userinfo.email}" \
  --set-env-vars="VISION_API_KEY=${VISION_API_KEY:-}" \
  --set-env-vars="OCR_FALLBACK=${OCR_FALLBACK:-tesseract}" \
  --set-env-vars="STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY:-}" \
  --set-env-vars="STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET:-}" \
  --set-env-vars="STRIPE_PRICE_MONTHLY=${STRIPE_PRICE_MONTHLY:-}" \
  --set-env-vars="STRIPE_PRICE_CREDITS=${STRIPE_PRICE_CREDITS:-}" \
  --set-env-vars="STRIPE_CREDIT_PACK_AMOUNT=${STRIPE_CREDIT_PACK_AMOUNT:-50}" \
  --set-env-vars="SECRET_KEY=${SECRET_KEY:-change-me}" \
  --set-env-vars="GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:-}" \
  --set-env-vars="GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET:-}" \
  --set-env-vars="GOOGLE_REDIRECT_URI=${GOOGLE_REDIRECT_URI:-}" \
  --set-env-vars="OAUTHLIB_INSECURE_TRANSPORT=0"

echo "Deployment complete."
