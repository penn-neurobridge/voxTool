# AWS deployment guide for voxTool web prototype

**Stack:** React (S3 + CloudFront) + Flask (Elastic Beanstalk) + S3 (scan data)  
**CI/CD:** GitHub Actions on `web-app` (dev) and `main` (prod)

Based on Zack's AWS Webapp Deployment Guide, adapted for voxTool:

- No PostgreSQL (annotations and scans use filesystem / S3 later)
- Long-running NIfTI processing (600s gunicorn timeout)
- Paths: `web/backend`, `web/frontend`

## Prerequisites

1. **AWS account** with admin or PowerUser access (lab/CNT account is fine).
2. **Terraform** >= 1.5 installed locally.
3. **GitHub repo** admin access to add Actions secrets.
4. Optional: access to [neuronova](https://github.com/penn-cnt/neuronova) for reference (repo is private — ask Zack for CNT org access).

## Architecture

```
Developer → GitHub (web-app / main) → GitHub Actions
                                      ├─ S3 sync + CloudFront invalidation (frontend)
                                      └─ EB zip deploy (backend)

User → CloudFront (React) → Elastic Beanstalk (Flask API) → local disk + S3 data bucket
```

| Component | Dev | Prod |
|-----------|-----|------|
| Frontend bucket | `voxtool-dev-frontend` | `voxtool-prod-frontend` |
| Data bucket | `voxtool-dev-data` | `voxtool-prod-data` |
| EB app | `voxtool-dev-app` | `voxtool-prod-app` |
| EB env | `voxtool-dev-env` | `voxtool-prod-env` |
| Git branch | `web-app` | `main` |

## Step 1: Provision infrastructure with Terraform

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set flask_secret_key (see example file)

terraform init

# Dev environment
terraform workspace new dev || terraform workspace select dev
terraform apply -var="environment=dev"

# Prod environment (after dev works)
terraform workspace new prod || terraform workspace select prod
terraform apply -var="environment=prod"
```

After each apply, note the outputs:

```bash
terraform output cloudfront_url
terraform output elastic_beanstalk_url
terraform output -raw github_actions_access_key
terraform output -raw github_actions_secret_key
terraform output cloudfront_distribution_id
```

**Update CORS** after first deploy — re-apply with your CloudFront URL:

```bash
terraform apply -var="environment=dev" \
  -var='cors_allowed_origins=https://YOUR-CLOUDFRONT-ID.cloudfront.net,http://localhost:3000'
```

## Step 2: GitHub Actions secrets

In **GitHub → Settings → Secrets and variables → Actions**, add:

| Secret | Source |
|--------|--------|
| `AWS_ACCESS_KEY_ID` | `terraform output -raw github_actions_access_key` |
| `AWS_SECRET_ACCESS_KEY` | `terraform output -raw github_actions_secret_key` |
| `CLOUDFRONT_ID_DEV` | dev workspace `cloudfront_distribution_id` |
| `CLOUDFRONT_ID_PROD` | prod workspace `cloudfront_distribution_id` |
| `REACT_APP_API_URL_DEV` | dev `elastic_beanstalk_url` (e.g. `http://voxtool-dev-env.eba-....us-east-1.elasticbeanstalk.com`) |
| `REACT_APP_API_URL_PROD` | prod EB URL |

Use `http://` for EB default URLs until you add custom domains + HTTPS on the API (Phase 8 in Zack's guide). Browsers may block mixed content when the frontend is HTTPS (CloudFront) and the API is HTTP — see troubleshooting below.

## Step 3: First deploy

1. Push backend changes to `web-app` → triggers **Deploy Backend**.
2. In GitHub Actions, manually run **Deploy Frontend** (`workflow_dispatch`) or push a frontend change.
3. Open the CloudFront URL from Terraform output.
4. Hit the EB URL `/api/health` — should return `{"status":"ok",...}`.

## Step 4: Upload demo scan data (optional)

NIfTI files are excluded from the EB zip deploy. For the bundled demo:

```bash
aws s3 cp web/backend/data/example.nii.gz s3://voxtool-dev-data/scans/example.nii.gz
```

**Note:** The backend still reads from local `data/` today. A follow-up task is wiring `DATA_S3_BUCKET` for persistent scan storage on EB (instances are ephemeral). Until then, uploads via the UI persist only on the running instance.

## Local development (unchanged)

```bash
# Terminal 1
cd web/backend && python app.py

# Terminal 2
cd web/frontend && npm start
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| EB health "Severe" | Check `/api/health`; view EB logs → Request last 100 lines → `web.stdout.log` |
| CORS errors | Update `cors_allowed_origins` in Terraform and re-apply |
| Mixed content (HTTPS frontend, HTTP API) | Short-term: test API over HTTP directly; long-term: custom domain + ACM cert on EB (Zack's Phase 8) |
| Uploads disappear after redeploy | Expected until S3-backed storage is implemented |
| Zip deploy can't find `application.py` | Zip must contain files at root (workflow handles this) |

## What's not included yet

- **RDS / PostgreSQL** — not needed; voxTool uses JSON files for annotations.
- **Route 53 / custom domain** — add `route53.tf` when you have a domain (see Zack's guide Phase 8).
- **S3-backed scan I/O** — Terraform creates the data bucket; backend code still uses local paths.
- **ECS / Step Functions** — optional for async NIfTI jobs (Zack's Phase 6).

## Questions for the team

Before going to production, confirm with Nishant/Zack:

1. Which **AWS account** should host this (personal vs CNT lab)?
2. Should we rename branch `web-app` → `dev` to match neuronova conventions?
3. Do you have a **custom domain** (e.g. `voxtool.penn.edu`)?
4. **Instance size** — `t3.small` may be tight for large NIfTI volumes; consider `t3.medium` or `m6i.large`.
5. Can Zack grant **neuronova repo access** so we can align Terraform with their working setup?
