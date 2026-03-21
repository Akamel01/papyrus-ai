"""
SME Dashboard — Prometheus Metrics Middleware

Exposes request count, latency histograms, and pipeline status gauge
at /metrics for Prometheus scraping.
"""

import time
from typing import Callable

from fastapi import Request, Response
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# --- Metrics definitions ---

REQUEST_COUNT = Counter(
    "dashboard_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "dashboard_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

PIPELINE_RUNNING = Gauge(
    "dashboard_pipeline_running",
    "Whether the pipeline is currently running (1=yes, 0=no)",
)

PIPELINE_MODE = Gauge(
    "dashboard_pipeline_mode",
    "Current pipeline mode (0=stopped, 1=stream, 2=embed-only, 3=test)",
)

WEBSOCKET_CLIENTS = Gauge(
    "dashboard_websocket_clients",
    "Number of connected WebSocket clients",
)

QDRANT_VECTORS = Gauge(
    "dashboard_qdrant_vectors_total",
    "Total vectors in Qdrant collection",
)

DB_PAPERS_EMBEDDED = Gauge(
    "dashboard_db_papers_embedded",
    "Number of papers with status 'embedded'",
)

GPU_UTILIZATION = Gauge(
    "dashboard_gpu_utilization_percent",
    "GPU utilization percentage",
)

GPU_VRAM_USED_MB = Gauge(
    "dashboard_gpu_vram_used_mb",
    "GPU VRAM used in MB",
)

MODE_MAP = {"stream": 1, "embed-only": 2, "test": 3}


async def prometheus_middleware(request: Request, call_next: Callable) -> Response:
    """Middleware to track request count and latency."""
    # Skip metrics endpoint itself to avoid recursion
    if request.url.path == "/metrics":
        return await call_next(request)

    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start

    endpoint = request.url.path
    # Normalize dynamic path segments
    if "/dlq/" in endpoint:
        endpoint = "/api/dlq/{id}"

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status=response.status_code,
    ).inc()

    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=endpoint,
    ).observe(elapsed)

    return response


def metrics_endpoint():
    """Generate Prometheus metrics output."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


def update_pipeline_gauge(running: bool, mode: str = None):
    """Update pipeline status gauges. Called from status checks."""
    PIPELINE_RUNNING.set(1 if running else 0)
    PIPELINE_MODE.set(MODE_MAP.get(mode, 0) if running else 0)


def update_ws_clients_gauge(count: int):
    """Update WebSocket client count gauge."""
    WEBSOCKET_CLIENTS.set(count)


def update_qdrant_gauge(vectors: int):
    """Update Qdrant vector count gauge."""
    QDRANT_VECTORS.set(vectors)


def update_db_gauge(embedded: int):
    """Update DB embedded count gauge."""
    DB_PAPERS_EMBEDDED.set(embedded)


def update_gpu_gauges(util_pct: float, vram_used_mb: float):
    """Update GPU gauges."""
    GPU_UTILIZATION.set(util_pct)
    GPU_VRAM_USED_MB.set(vram_used_mb)
