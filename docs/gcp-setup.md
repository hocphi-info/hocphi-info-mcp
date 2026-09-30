# GCP setup (one time)

Goal: a project where GitHub Actions can deploy the container to Cloud Run **without any
stored key**, and where an idle service costs $0.

## Cost model (why this stays free)

- Cloud Run is deployed with `--min-instances=0`: no request, no instance, no charge
  (request-based billing). The first call after a quiet period pays a cold start (a few
  seconds); the server is stateless so that is the only cost of scaling to zero.
- `--max-instances=2` is the hard ceiling on spend and on abuse.
- Free tier per month: 180k vCPU-seconds, 360k GiB-seconds, 2M requests. A learning
  project stays far below it.
- Artifact Registry: 0.5 GiB free. The cleanup policy keeps the 3 newest images
  (each ~50 MB).
- A **budget alert only emails you, it does not stop spending.** The real guard is
  `max-instances` plus not exposing anything that can bill (no Cloud SQL, no load balancer,
  no static IP, no `min-instances`).

## Steps

1. **Project and billing** (done in the console): create the project, link a billing
   account, create a budget (1 USD) with email alerts.
2. **Install and log in to `gcloud`:**
   ```bash
   gcloud auth login
   ```
   If `gcloud: command not found`, open a new terminal or add the SDK's `bin/` to `PATH`.
3. **Run the script** (idempotent; re-running is safe):
   ```bash
   infra/setup-gcp.sh <PROJECT_ID>
   ```
   Use the project **ID** (e.g. `project-3841b1f2-...`), not the display name.
4. **Copy the printed values** into GitHub: repo `hocphi-info/hocphi-info-mcp` →
   Settings → Secrets and variables → Actions → **Variables** (they are identifiers, not
   secrets): `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DEPLOYER_SA`,
   `GCP_RUNTIME_SA`.

## What the script creates

| Resource | Why | Permissions |
|---|---|---|
| APIs: run, artifactregistry, iam, iamcredentials, sts | needed to deploy and to exchange the GitHub token | – |
| Artifact Registry repo `hocphi` (asia-southeast1) | image storage, keep 3 newest | – |
| SA `mcp-runtime` | identity the server runs as | **none** (it only calls a public REST API) |
| SA `mcp-deployer` | identity GitHub Actions impersonates | `run.admin` (project), `artifactregistry.writer` (this repo only), `serviceAccountUser` (on `mcp-runtime` only) |
| Workload Identity pool `github` + provider `github-actions` | keyless GitHub OIDC login | provider accepts **only** `assertion.repository == hocphi-info/hocphi-info-mcp` |

`run.admin` rather than `run.developer` because `--allow-unauthenticated` (a public MCP
server) edits the service's IAM policy. The project holds just this one service.

## Verify

```bash
gcloud artifacts repositories list --location asia-southeast1
gcloud iam service-accounts list
gcloud iam workload-identity-pools providers describe github-actions \
  --location global --workload-identity-pool github --format='value(attributeCondition)'
```

The last command must print `assertion.repository=='hocphi-info/hocphi-info-mcp'`. If it is
empty, any GitHub repo could request tokens: re-run the script.

## Teardown

Deleting the project removes everything and stops all billing:

```bash
gcloud projects delete <PROJECT_ID>
```

## Deploying

After the variables are set, releases are a tag push:

```bash
git tag v0.1.0 && git push --tags
```

`deploy.yml` runs CI, builds the image, pushes it to Artifact Registry, deploys to Cloud
Run (`--min-instances=0 --max-instances=2`) and smoke-tests the live URL. It can also be
started by hand from the Actions tab. `smoke.yml` repeats the smoke test daily.

The service URL is `https://hocphi-info-mcp-<project number>.asia-southeast1.run.app/mcp`.
`ALLOWED_HOSTS` is set to that host automatically; a custom domain must be added to it.

Cloud Run also prints a second, hashed alias (`hocphi-info-mcp-<hash>-as.a.run.app`). The
server rejects it with `421 Invalid Host` on purpose (`ALLOWED_HOSTS`), so always use the
URL above.
