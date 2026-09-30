#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:?Usage: bash scripts/setup_gcp_cloudrun.sh PROJECT_ID [REGION]}"
REGION="${2:-europe-north1}"
REPOSITORY="canecorsoancestry"
DEPLOY_SA_NAME="canecorsoancestry-deploy"
RUNTIME_SA_NAME="canecorsoancestry-runtime"
POOL_ID="github"
PROVIDER_ID="canecorsoancestry"
GITHUB_REPOSITORY="eghosa001/canecorsoancestry"
DB_SECRET="canecorsoancestry-database-url"
DJANGO_SECRET="canecorsoancestry-django-secret"

gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
DEPLOY_SA="$DEPLOY_SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
RUNTIME_SA="$RUNTIME_SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

echo "Enabling Google Cloud APIs..."
gcloud services enable   run.googleapis.com   artifactregistry.googleapis.com   iamcredentials.googleapis.com   sts.googleapis.com   secretmanager.googleapis.com

if ! gcloud artifacts repositories describe "$REPOSITORY"   --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPOSITORY"     --repository-format=docker     --location="$REGION"     --description="Cane Corso Ancestry Cloud Run images"
fi

cleanup_policy="$(mktemp)"
trap 'rm -f "$cleanup_policy"' EXIT
cat > "$cleanup_policy" <<'JSON'
[
  {
    "name": "delete-old-images",
    "action": {"type": "Delete"},
    "condition": {
      "tagState": "any",
      "olderThan": "14d"
    }
  },
  {
    "name": "keep-three-images",
    "action": {"type": "Keep"},
    "mostRecentVersions": {
      "keepCount": 3
    }
  }
]
JSON

gcloud artifacts repositories set-cleanup-policies "$REPOSITORY"   --location="$REGION"   --policy="$cleanup_policy"   --no-dry-run >/dev/null

for sa in "$DEPLOY_SA_NAME" "$RUNTIME_SA_NAME"; do
  if ! gcloud iam service-accounts describe     "$sa@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$sa"       --display-name="$sa"
  fi
done

gcloud projects add-iam-policy-binding "$PROJECT_ID"   --member="serviceAccount:$DEPLOY_SA"   --role="roles/run.admin" >/dev/null

gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY"   --location="$REGION"   --member="serviceAccount:$DEPLOY_SA"   --role="roles/artifactregistry.writer" >/dev/null

gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA"   --member="serviceAccount:$DEPLOY_SA"   --role="roles/iam.serviceAccountUser" >/dev/null

for secret in "$DB_SECRET" "$DJANGO_SECRET"; do
  if ! gcloud secrets describe "$secret" >/dev/null 2>&1; then
    gcloud secrets create "$secret" --replication-policy=automatic >/dev/null
  fi

  gcloud secrets add-iam-policy-binding "$secret"     --member="serviceAccount:$DEPLOY_SA"     --role="roles/secretmanager.secretVersionManager" >/dev/null

  gcloud secrets add-iam-policy-binding "$secret"     --member="serviceAccount:$RUNTIME_SA"     --role="roles/secretmanager.secretAccessor" >/dev/null
done

if ! gcloud iam workload-identity-pools describe "$POOL_ID"   --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL_ID"     --location=global     --display-name="GitHub Actions"
fi

if ! gcloud iam workload-identity-pools providers describe "$PROVIDER_ID"   --workload-identity-pool="$POOL_ID"   --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID"     --workload-identity-pool="$POOL_ID"     --location=global     --issuer-uri="https://token.actions.githubusercontent.com"     --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository"     --attribute-condition="assertion.repository=='$GITHUB_REPOSITORY'"
fi

gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA"   --role="roles/iam.workloadIdentityUser"   --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_ID/attribute.repository/$GITHUB_REPOSITORY" >/dev/null

PROVIDER_NAME="$(gcloud iam workload-identity-pools providers describe "$PROVIDER_ID"   --workload-identity-pool="$POOL_ID"   --location=global   --format='value(name)')"

cat <<EOF

Google Cloud Run setup complete.

Add these GitHub repository variables:
  GCP_PROJECT_ID=$PROJECT_ID
  GCP_REGION=$REGION
  GCP_WORKLOAD_IDENTITY_PROVIDER=$PROVIDER_NAME
  GCP_SERVICE_ACCOUNT=$DEPLOY_SA

Existing GitHub secrets remain:
  CLOUDFLARE_API_TOKEN
  SUPABASE_DATABASE_URL
  DJANGO_SECRET_KEY

Then run the "Cloud Run deploy" workflow with target=preview.
EOF
