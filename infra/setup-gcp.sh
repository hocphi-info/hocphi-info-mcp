#!/usr/bin/env bash
# One-time GCP setup for hocphi-info-mcp. Safe to re-run: every step checks
# whether the resource already exists first.
#
# Usage:   infra/setup-gcp.sh <PROJECT_ID>
# Needs:   gcloud logged in (`gcloud auth login`) as an Owner of the project,
#          and billing already linked to it (docs/gcp-setup.md, step 1-2).
#
# What it creates (nothing here costs money by itself):
#   - the APIs Cloud Run + Artifact Registry + keyless GitHub auth need
#   - an Artifact Registry Docker repo, keeping only the 3 newest images
#   - a runtime service account with NO roles (the server only calls a public API)
#   - a deployer service account with the minimum roles to ship a release
#   - a Workload Identity pool/provider so GitHub Actions can deploy WITHOUT a
#     stored key, restricted to this one repository
set -euo pipefail

PROJECT_ID="${1:-${PROJECT_ID:-}}"
if [[ -z "$PROJECT_ID" ]]; then
  echo "usage: $0 <PROJECT_ID>" >&2
  exit 2
fi

REGION="${REGION:-asia-southeast1}"
GITHUB_REPO="${GITHUB_REPO:-hocphi-info/hocphi-info-mcp}"
AR_REPO="hocphi"
POOL="github"
PROVIDER="github-actions"
RUNTIME_SA="mcp-runtime"
DEPLOYER_SA="mcp-deployer"

RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOYER_EMAIL="${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

log() { printf '\n==> %s\n' "$*"; }

# A just-created service account can take a few seconds to be visible to IAM
# ("PERMISSION_DENIED ... or it may not exist"), so retry instead of failing.
retry() {
  local n
  for n in 1 2 3 4 5 6; do
    "$@" && return 0
    echo "  (attempt ${n} failed, IAM may still be propagating; retrying in 10s)" >&2
    sleep 10
  done
  return 1
}

log "Project ${PROJECT_ID}, region ${REGION}, repo ${GITHUB_REPO}"
gcloud config set project "$PROJECT_ID" >/dev/null

# Cloud Run can't be deployed to a project without billing, so fail early with a
# clear message instead of a confusing API error 3 steps later.
if [[ "$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)')" != "True" ]]; then
  echo "Billing is not enabled on ${PROJECT_ID}. Link a billing account first (docs/gcp-setup.md)." >&2
  exit 1
fi

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

log "Enable APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com

log "Artifact Registry repo '${AR_REPO}' (keep the 3 newest images: free tier is 0.5 GiB)"
if ! gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format docker \
    --location "$REGION" \
    --description "hocphi-info-mcp images"
fi
POLICY_FILE="$(mktemp)"
trap 'rm -f "$POLICY_FILE"' EXIT
# "Keep" beats "Delete", so: keep the 3 newest versions, delete everything else.
cat >"$POLICY_FILE" <<'JSON'
[
  {"name": "keep-3-newest", "action": {"type": "Keep"},
   "mostRecentVersions": {"keepCount": 3}},
  {"name": "delete-the-rest", "action": {"type": "Delete"},
   "condition": {"tagState": "any"}}
]
JSON
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" \
  --location "$REGION" --policy "$POLICY_FILE" --no-dry-run

log "Runtime service account ${RUNTIME_EMAIL} (no roles on purpose)"
if ! gcloud iam service-accounts describe "$RUNTIME_EMAIL" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME_SA" \
    --display-name "hocphi-info-mcp runtime (no permissions)"
fi

log "Deployer service account ${DEPLOYER_EMAIL}"
if ! gcloud iam service-accounts describe "$DEPLOYER_EMAIL" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$DEPLOYER_SA" \
    --display-name "hocphi-info-mcp deployer (GitHub Actions)"
fi
# run.admin (not developer) because `--allow-unauthenticated` edits the service's
# IAM policy. Scoped to this project, which only contains this one service.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${DEPLOYER_EMAIL}" --role roles/run.admin \
  --condition None >/dev/null
# Push images: only into our one repo, not project-wide.
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" \
  --location "$REGION" \
  --member "serviceAccount:${DEPLOYER_EMAIL}" --role roles/artifactregistry.writer \
  >/dev/null
# Deploying a revision "as" the runtime SA requires actAs on it, and only on it.
retry gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_EMAIL" \
  --member "serviceAccount:${DEPLOYER_EMAIL}" --role roles/iam.serviceAccountUser \
  >/dev/null

log "Workload Identity pool '${POOL}' + GitHub provider (keyless auth)"
if ! gcloud iam workload-identity-pools describe "$POOL" --location global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL" \
    --location global --display-name "GitHub Actions"
fi
# The attribute condition is the real security boundary: without it ANY GitHub
# repo could ask for a token from this provider. Only our repo passes.
PROVIDER_ARGS=(
  --location global
  --workload-identity-pool "$POOL"
  --issuer-uri "https://token.actions.githubusercontent.com"
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository"
  --attribute-condition "assertion.repository=='${GITHUB_REPO}'"
)
if gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --location global --workload-identity-pool "$POOL" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" "${PROVIDER_ARGS[@]}"
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" "${PROVIDER_ARGS[@]}"
fi
# Let identities from this repo (and only this repo) impersonate the deployer SA.
retry gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_EMAIL" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_REPO}" \
  >/dev/null

PROVIDER_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"

cat <<EOF

Done. Add these as GitHub *variables* (not secrets: none of them is secret) on
${GITHUB_REPO}  ->  Settings -> Secrets and variables -> Actions -> Variables:

  GCP_PROJECT_ID          ${PROJECT_ID}
  GCP_REGION              ${REGION}
  GCP_WIF_PROVIDER        ${PROVIDER_NAME}
  GCP_DEPLOYER_SA         ${DEPLOYER_EMAIL}
  GCP_RUNTIME_SA          ${RUNTIME_EMAIL}

Image path used by the deploy workflow:
  ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/hocphi-info-mcp
EOF
