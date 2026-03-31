"""
Webhook receiver for GitHub Actions auto-deploy.
Listens for workflow_run events and triggers docker compose update.
"""
import os
import hmac
import hashlib
import subprocess
import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, APIRouter

app = FastAPI(title="Deploy Hook")
router = APIRouter()
logger = logging.getLogger("deploy-hook")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

WEBHOOK_SECRET = os.environ.get("DEPLOY_WEBHOOK_SECRET", "")
DEPLOY_DIR = "/opt/sme"


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature using HMAC-SHA256."""
    if not WEBHOOK_SECRET:
        logger.warning("DEPLOY_WEBHOOK_SECRET not configured")
        return False
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def run_deploy():
    """Execute deployment commands.

    Note: We exclude deploy-hook from restart to avoid killing ourselves mid-deployment.
    The deploy-hook service will be updated on the next deployment cycle.
    """
    logger.info(f"Starting deployment at {datetime.now().isoformat()}")

    # Services safe to restart from inside the container (named volumes only, no host-path mounts).
    # Excluded: caddy, cloudflared — host-path FILE mounts break when docker compose resolves
    #   paths from /opt/sme (not a real host path in WSL2).
    # Excluded: dashboard-backend — host-path DIRECTORY mounts (./config, ./src) also break,
    #   causing empty /config inside container and 404 on /api/config.
    # Excluded: deploy-hook — avoid self-restart mid-deployment.
    # Note: app, auth use named volumes only in production compose → safe.
    services = [
        "app", "auth", "dashboard-ui", "gpu-exporter"
    ]

    try:
        # Pull new images for all services
        logger.info("Pulling latest images...")
        result = subprocess.run(
            ["docker", "compose", "pull"],
            cwd=DEPLOY_DIR,
            check=True,
            timeout=300,
            capture_output=True,
            text=True
        )
        logger.info(f"Pull output: {result.stdout}")

        # Restart services with new images (excluding deploy-hook)
        logger.info(f"Restarting services: {', '.join(services)}")
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "--no-deps"] + services,
            cwd=DEPLOY_DIR,
            check=True,
            timeout=180,
            capture_output=True,
            text=True
        )
        logger.info(f"Up output: {result.stdout}")

        logger.info("Deployment completed successfully")
        return True
    except subprocess.TimeoutExpired as e:
        logger.error(f"Deployment timed out: {e}")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"Deployment failed: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Deployment error: {e}")
        return False


@router.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle GitHub webhook events."""
    payload = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(payload, signature):
        logger.warning("Invalid webhook signature received")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    logger.info(f"Received GitHub event: {event}")

    if event != "workflow_run":
        return {"status": "ignored", "reason": f"event={event}"}

    data = await request.json()
    action = data.get("action", "")
    workflow_name = data.get("workflow_run", {}).get("name", "unknown")
    conclusion = data.get("workflow_run", {}).get("conclusion", "")

    logger.info(f"Workflow: {workflow_name}, action: {action}, conclusion: {conclusion}")

    if action != "completed":
        return {"status": "ignored", "reason": f"action={action}"}

    if conclusion != "success":
        return {"status": "ignored", "reason": f"conclusion={conclusion}"}

    # Trigger deployment in background
    logger.info("Triggering deployment...")
    background_tasks.add_task(run_deploy)
    return {"status": "deploying", "workflow": workflow_name}


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "deploy-hook",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/")
async def root():
    """Root endpoint."""
    return {"service": "deploy-hook", "version": "1.0.0"}


# Mount router at both root and /deploy-webhook for flexibility
app.include_router(router)
app.include_router(router, prefix="/deploy-webhook")
