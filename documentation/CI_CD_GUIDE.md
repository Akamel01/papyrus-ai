# SME Research Assistant - CI/CD Guide

**Version:** 1.0
**Last Updated:** March 2026

---

## Table of Contents

1. [Overview](#overview)
2. [CI Pipeline](#ci-pipeline)
3. [CD Pipeline](#cd-pipeline)
4. [Auto-Deploy Webhook](#auto-deploy-webhook)
5. [GitHub Container Registry](#github-container-registry)
6. [Secrets Management](#secrets-management)
7. [Monitoring and Debugging](#monitoring-and-debugging)
8. [Rollback Procedures](#rollback-procedures)

---

## Overview

The SME Research Assistant uses a fully automated CI/CD pipeline built on GitHub Actions with webhook-based auto-deployment.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CI/CD PIPELINE ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
│  │  GitHub  │───▶│  GitHub  │───▶│  Docker  │───▶│   Production     │  │
│  │   Push   │    │  Actions │    │ Registry │    │   (papyrus-ai)   │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────────────┘  │
│       │              │                │                   │             │
│       │         ┌────┴────┐      ┌────┴────┐        ┌────┴────┐       │
│       │         │  Lint   │      │  Scan   │        │ Monitor │       │
│       │         │  Test   │      │  Push   │        │  Alert  │       │
│       │         │  Build  │      │         │        │         │       │
│       │         └─────────┘      └─────────┘        └─────────┘       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Pipeline Flow

```
Developer Push → CI Pipeline → Build Images → Push to GHCR
                                                    │
                                                    ▼
                              workflow_run webhook triggered
                                                    │
                                                    ▼
                    Cloudflare Tunnel → deploy-hook:9000
                                                    │
                                                    ▼
                    docker compose pull && docker compose up -d
```

---

## CI Pipeline

### Location: `.github/workflows/ci.yml`

### Trigger Events

```yaml
on:
  push:
    branches: [main, develop, 'feature/**']
  pull_request:
    branches: [main, develop]
```

### Pipeline Stages

#### Stage 1: Code Quality

**Purpose:** Ensure code adheres to style guidelines

| Check | Tool | Configuration |
|-------|------|---------------|
| Linting | Ruff | `ruff.toml` |
| Formatting | Black | Default settings |
| Import Sorting | isort | Default settings |

**Commands:**
```bash
ruff check . --output-format=github
black --check .
isort --check-only .
```

**Behavior:** `continue-on-error: true` - Pipeline continues even if linting fails, allowing builds while code quality is improved.

#### Stage 2: Security Scan

**Purpose:** Detect vulnerabilities and secrets

| Check | Tool | Severity |
|-------|------|----------|
| Filesystem Scan | Trivy | CRITICAL, HIGH |
| Python Security | Bandit | Low-level warnings |
| Secret Detection | TruffleHog | All secrets |

**Commands:**
```bash
trivy fs . --severity CRITICAL,HIGH
bandit -r src/ app/ -ll
```

#### Stage 3: Unit Tests

**Purpose:** Validate individual components

**Dependencies:** Requires `lint` stage to pass

**Commands:**
```bash
pytest tests/unit/ \
    --cov=src --cov=app \
    --cov-report=xml \
    -v
```

**Coverage:** Reports uploaded to Codecov

#### Stage 4: Integration Tests

**Purpose:** Validate component interactions

**Dependencies:** Requires `unit-tests` stage

**Services Started:**
- Redis (7.4-alpine)
- Qdrant (v1.12.6)

**Commands:**
```bash
pytest tests/integration/ -v --tb=short -x
```

#### Stage 5: Docker Build

**Purpose:** Build and publish container images

**Dependencies:** Requires `security` and `integration-tests`

**Services Built:**

| Service | Context | Image |
|---------|---------|-------|
| app | `.` | `ghcr.io/akamel01/papyrus-ai/app` |
| auth | `./services/auth` | `ghcr.io/akamel01/papyrus-ai/auth` |
| dashboard-backend | `./dashboard/backend` | `ghcr.io/akamel01/papyrus-ai/dashboard-backend` |
| dashboard-ui | `./dashboard/frontend` | `ghcr.io/akamel01/papyrus-ai/dashboard-ui` |

**Tags Generated:**
- Branch name (e.g., `main`, `develop`)
- PR number (for pull requests)
- Git SHA (short hash)
- `latest` (for default branch only)

---

## CD Pipeline

### Location: `.github/workflows/cd.yml`

### Trigger

Currently configured for **manual deployment only**:

```yaml
on:
  # Auto-deploy disabled until DEPLOY_SSH_KEY is configured
  # push:
  #   branches: [main]
  workflow_dispatch:
    inputs:
      environment:
        description: 'Deployment environment'
        required: true
        default: 'production'
```

### Deployment Process

When triggered manually:

1. **Pre-Deploy Checks:** Verify CI passed
2. **SSH Connection:** Connect to production server
3. **Pull Images:** `docker compose pull`
4. **Create Backup:** Run backup script
5. **Rolling Update:** Restart services one by one
6. **Health Check:** Verify services are healthy

---

## Auto-Deploy Webhook

### Architecture

The auto-deploy system bypasses traditional SSH deployment in favor of a webhook-based approach suitable for local machine + Cloudflare Tunnel setups.

```
GitHub CI Completes (success)
        │
        ▼
workflow_run webhook
        │
        ▼
https://papyrus-ai.net/deploy-webhook/webhook
        │
        ▼
Cloudflare Tunnel → deploy-hook:9000
        │
        ▼
HMAC-SHA256 Signature Verification
        │
        ▼
Background Task: docker compose pull && up -d
```

### Deploy Hook Service

**Location:** `services/deploy-hook/`

**Files:**
- `main.py` - FastAPI webhook handler
- `Dockerfile` - Container with Docker CLI
- `requirements.txt` - Python dependencies

### Key Features

#### HMAC Signature Verification

All webhooks must include valid GitHub signature:

```python
def verify_signature(payload: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

#### Event Filtering

Only deploys on:
- Event type: `workflow_run`
- Action: `completed`
- Conclusion: `success`

```python
if event != "workflow_run":
    return {"status": "ignored", "reason": "event"}
if action != "completed":
    return {"status": "ignored", "reason": "action"}
if conclusion != "success":
    return {"status": "ignored", "reason": "conclusion"}
```

#### Background Deployment

Deployment runs asynchronously to prevent webhook timeout:

```python
background_tasks.add_task(run_deploy)
return {"status": "deploying", "workflow": workflow_name}
```

### Docker Compose Configuration

```yaml
deploy-hook:
  build: ./services/deploy-hook
  container_name: sme_deploy_hook
  environment:
    - DEPLOY_WEBHOOK_SECRET=${DEPLOY_WEBHOOK_SECRET}
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
    - .:/opt/sme:ro
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:9000/health"]
  restart: unless-stopped
```

### Cloudflare Tunnel Route

```yaml
# config/cloudflared-config.yml
ingress:
  - hostname: papyrus-ai.net
    path: /deploy-webhook.*
    service: http://deploy-hook:9000
  # Main routes follow...
```

### Health Endpoint

```bash
curl https://papyrus-ai.net/deploy-webhook/health
# {"status":"healthy","service":"deploy-hook","timestamp":"..."}
```

### GitHub Webhook Configuration

**Settings:** https://github.com/Akamel01/papyrus-ai/settings/hooks

| Setting | Value |
|---------|-------|
| Payload URL | `https://papyrus-ai.net/deploy-webhook/webhook` |
| Content type | `application/json` |
| Secret | Value of `DEPLOY_WEBHOOK_SECRET` |
| Events | `Workflow runs` only |

---

## GitHub Container Registry

### Image URLs

All images are published to GitHub Container Registry (GHCR):

| Service | Image URL |
|---------|-----------|
| App | `ghcr.io/akamel01/papyrus-ai/app` |
| Auth | `ghcr.io/akamel01/papyrus-ai/auth` |
| Dashboard Backend | `ghcr.io/akamel01/papyrus-ai/dashboard-backend` |
| Dashboard UI | `ghcr.io/akamel01/papyrus-ai/dashboard-ui` |

### Pulling Images

To use pre-built images instead of building locally:

```yaml
# docker-compose.override.yml
services:
  app:
    image: ghcr.io/akamel01/papyrus-ai/app:latest
    build: !reset null

  auth:
    image: ghcr.io/akamel01/papyrus-ai/auth:latest
    build: !reset null
```

### Authentication

For private repositories, authenticate with GitHub:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

---

## Secrets Management

### GitHub Repository Secrets

| Secret | Purpose | Required |
|--------|---------|----------|
| `GITHUB_TOKEN` | Auto-provided, GHCR push | Yes (automatic) |
| `DEPLOY_SSH_KEY` | SSH deployment (CD) | No (webhook-based) |
| `SLACK_WEBHOOK_URL` | Deployment notifications | Optional |

### Environment Variables

| Variable | File | Purpose |
|----------|------|---------|
| `JWT_SECRET` | `.env` | JWT signing |
| `MASTER_ENCRYPTION_KEY` | `.env` | API key encryption |
| `DEPLOY_WEBHOOK_SECRET` | `.env` | Webhook verification |

### Generating Secrets

```bash
# JWT Secret
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Master Encryption Key
python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

# Webhook Secret
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Monitoring and Debugging

### CI Pipeline Status

Check pipeline status:
```bash
gh run list --repo Akamel01/papyrus-ai --limit 5
```

View specific run:
```bash
gh run view <run_id> --log
```

### Deploy Hook Logs

```bash
# View recent logs
docker compose logs --tail=50 deploy-hook

# Follow logs in real-time
docker compose logs -f deploy-hook
```

### Webhook Delivery History

View at: https://github.com/Akamel01/papyrus-ai/settings/hooks

Click on the webhook → "Recent Deliveries" tab

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Webhook 401 | Invalid signature | Verify `DEPLOY_WEBHOOK_SECRET` matches |
| Webhook 404 | Path not routed | Check cloudflared config, restart tunnel |
| Deploy hangs | Docker socket access | Verify volume mount for docker.sock |
| Images not found | GHCR auth | Check packages:write permission |

---

## Rollback Procedures

### Quick Rollback

Stop auto-deploy and revert to previous working state:

```bash
# Stop deploy-hook to prevent auto-deploy
docker compose stop deploy-hook

# Revert to previous image
docker compose pull  # Gets latest
# OR specify a specific tag:
docker compose -f docker-compose.yml -f - up -d <<EOF
services:
  app:
    image: ghcr.io/akamel01/papyrus-ai/app:previous_sha
EOF
```

### Full Rollback

If you need to restore from backup:

```bash
# Stop services
docker compose down

# Restore database backups
./scripts/restore.sh --latest

# Start with previous code
git checkout HEAD~1
docker compose up -d
```

### Disable Auto-Deploy

```bash
# Temporarily stop
docker compose stop deploy-hook

# Permanently remove
docker compose rm deploy-hook
```

---

## Workflow Files Reference

### CI Workflow Structure

```yaml
# .github/workflows/ci.yml
name: CI Pipeline

on:
  push:
    branches: [main, develop, 'feature/**']
  pull_request:
    branches: [main, develop]

jobs:
  lint:
    name: Code Quality
    runs-on: ubuntu-latest
    # Linting steps...

  security:
    name: Security Scan
    runs-on: ubuntu-latest
    # Security scan steps...

  unit-tests:
    name: Unit Tests
    needs: [lint]
    # Test steps...

  integration-tests:
    name: Integration Tests
    needs: [unit-tests]
    services:
      redis: ...
      qdrant: ...
    # Integration test steps...

  build:
    name: Build Docker Images
    needs: [security, integration-tests]
    permissions:
      contents: read
      packages: write
    strategy:
      matrix:
        service: [app, auth, dashboard-backend, dashboard-ui]
    # Build and push steps...
```

### Adding New Services to CI

To add a new service to the build matrix:

1. Add to matrix in `.github/workflows/ci.yml`:
```yaml
strategy:
  matrix:
    service: [app, auth, dashboard-backend, dashboard-ui, new-service]
```

2. Update context mapping:
```yaml
context: ${{ matrix.service == 'new-service' && './path/to/service' || ... }}
```

---

## Best Practices

### Commit Conventions

Use conventional commits for automatic changelog:

```
<type>(<scope>): <description>

Types:
- feat: New feature
- fix: Bug fix
- docs: Documentation
- style: Formatting
- refactor: Code restructure
- test: Tests
- chore: Maintenance
- ci: CI/CD changes
```

### Branch Strategy

```
main (production)
  │
  ├── develop (staging)
  │     │
  │     ├── feature/xxx
  │     └── bugfix/zzz
  │
  └── hotfix/critical-fix
```

### Testing Before Push

```bash
# Run full check locally
ruff check .
black --check .
pytest tests/
docker compose build
```

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Manual deployment
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues
