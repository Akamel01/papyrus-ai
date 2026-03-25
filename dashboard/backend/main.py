"""
SME Pipeline Dashboard — FastAPI Backend
Entry point. Registers all routes, CORS, WebSocket, Prometheus, and startup tasks.
"""

import asyncio
import logging
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import config_routes, run_routes, db_routes, qdrant_routes
from routes import metrics_routes, dlq_routes, audit_routes, auth_routes, ws_routes
from routes import documents_routes
from routes.documents_routes import set_ws_manager as set_docs_ws_manager
from metrics_collector import MetricsCollector
from ws_manager import WSManager
from prometheus_metrics import (
    prometheus_middleware, metrics_endpoint,
    update_pipeline_gauge, update_ws_clients_gauge,
    update_qdrant_gauge, update_gpu_gauges,
)
from rate_limiter import rate_limit_middleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("dashboard")

app = FastAPI(
    title="SME Pipeline Dashboard API",
    version="1.0.0",
    description="Operations dashboard for the SME research paper embedding pipeline.",
)

# --- CORS ---
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Prometheus middleware ---
app.middleware("http")(prometheus_middleware)

# --- Rate limiting middleware ---
app.middleware("http")(rate_limit_middleware)

# --- Shared state ---
ws_manager = WSManager()
metrics_collector = MetricsCollector()

# --- Register routes ---
app.include_router(auth_routes.router, prefix="/api/auth", tags=["Auth"])
app.include_router(config_routes.router, prefix="/api/config", tags=["Config"])
app.include_router(run_routes.router, prefix="/api/run", tags=["Run Control"])
app.include_router(db_routes.router, prefix="/api/db", tags=["Database"])
app.include_router(qdrant_routes.router, prefix="/api/qdrant", tags=["Qdrant"])
app.include_router(metrics_routes.router, prefix="/api/metrics", tags=["Metrics"])
app.include_router(dlq_routes.router, prefix="/api/dlq", tags=["DLQ"])
app.include_router(audit_routes.router, prefix="/api/audit", tags=["Audit"])
app.include_router(documents_routes.router, prefix="/api/documents", tags=["Documents"])
app.include_router(ws_routes.router, tags=["WebSocket"])


# --- Prometheus /metrics endpoint ---
@app.get("/metrics", include_in_schema=False)
async def get_metrics():
    return metrics_endpoint()


# --- Background tasks ---
async def _metrics_broadcast_loop():
    """Push system metrics to all WebSocket clients every 1s."""
    while True:
        try:
            data = await metrics_collector.collect()
            
            # --- Added: Include DB counts in broadcast for high-frequency updates ---
            from db_reader import get_paper_counts
            data["counts"] = get_paper_counts()
            
            await ws_manager.broadcast({"type": "metrics.update", "payload": data})
            # Update Prometheus gauges from collected metrics
            gpu = data.get("gpu")
            if gpu:
                update_gpu_gauges(gpu.get("util_pct", 0), gpu.get("vram_used_mb", 0))
        except Exception as e:
            logger.warning(f"Metrics broadcast error: {e}")
        await asyncio.sleep(1.0)


async def _metrics_sample_loop():
    """Record metrics samples every 30s for projection calculations."""
    from routes.metrics_routes import record_sample
    while True:
        try:
            await record_sample()
        except Exception as e:
            logger.warning(f"Metrics sample error: {e}")
        await asyncio.sleep(10.0)


async def _pipeline_gauge_loop():
    """Update Prometheus pipeline gauge and broadcast pipeline/qdrant state every 5s."""
    from command_runner import tracker
    last_state = None
    while True:
        try:
            status = tracker.get_status()
            update_pipeline_gauge(status.get("running", False), status.get("mode"))
            update_ws_clients_gauge(ws_manager.client_count)

            # Always broadcast run status so dashboard doesn't need to poll
            run_payload = {
                "running": status.get("running", False),
                "mode": status.get("mode"),
                "pid": status.get("pid"),
                "uptime_sec": status.get("uptime_sec"),
            }
            await ws_manager.broadcast({"type": "run.update", "payload": run_payload})

            # Also broadcast state-change event for logging on transitions
            current_state = (status.get("running"), status.get("mode"), status.get("pid"))
            if current_state != last_state:
                await ws_manager.broadcast({
                    "type": "pipeline.state_change",
                    "payload": {**run_payload, "timestamp": time.time()}
                })
                last_state = current_state
                logger.info(f"[WS] Pipeline state change broadcast: running={status.get('running')}")

            # Fetch and broadcast qdrant stats (reuses cached client)
            try:
                import qdrant_client as qc
                q_payload = await qc.get_stats()
                await ws_manager.broadcast({"type": "qdrant.update", "payload": q_payload})
            except Exception:
                pass  # Qdrant stats are best-effort

        except Exception as e:
            logger.debug(f"Pipeline gauge loop error: {e}")
        await asyncio.sleep(5.0)


@app.on_event("startup")
async def startup():
    logger.info("Dashboard backend starting...")
    # Wire WebSocket manager into route modules
    from routes.ws_routes import set_ws_manager
    set_ws_manager(ws_manager)
    set_docs_ws_manager(ws_manager)  # Enable real-time document status updates
    asyncio.create_task(_metrics_broadcast_loop())
    asyncio.create_task(_metrics_sample_loop())
    asyncio.create_task(_pipeline_gauge_loop())
    logger.info("Dashboard backend ready — http://0.0.0.0:8400/docs")


# --- Health checks ---
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/healthz")
async def healthz():
    """Deep health check for monitoring/alerting."""
    import psutil
    checks = {}

    # 1. Self
    checks["api"] = "ok"

    # 2. Config readable
    try:
        from config_manager import read_config
        read_config()
        checks["config"] = "ok"
    except Exception as e:
        checks["config"] = f"fail: {e}"

    # 3. Qdrant reachable
    try:
        import httpx
        resp = await httpx.AsyncClient(timeout=3.0).get(
            f"{os.getenv('QDRANT_URL', 'http://sme_qdrant:6333')}/collections"
        )
        checks["qdrant"] = "ok" if resp.status_code == 200 else f"http {resp.status_code}"
    except Exception as e:
        checks["qdrant"] = f"fail: {e}"

    # 4. Disk space
    try:
        disk = psutil.disk_usage("/data")
        free_gb = disk.free / 1e9
        checks["disk_free_gb"] = round(free_gb, 1)
        checks["disk"] = "ok" if free_gb > 10 else "warn" if free_gb > 5 else "critical"
    except Exception:
        checks["disk"] = "unknown"

    # 5. Pipeline status
    try:
        from command_runner import tracker
        status = tracker.get_status()
        checks["pipeline"] = "running" if status.get("running") else "stopped"
    except Exception:
        checks["pipeline"] = "unknown"

    overall = "ok" if all(v in ("ok", "stopped", "running") or isinstance(v, (int, float)) for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}

