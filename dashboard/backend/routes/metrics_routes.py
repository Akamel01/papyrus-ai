"""Metrics routes: system, projection, history, coverage."""
import json
import os
import statistics
import time
from datetime import datetime, timezone
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, Query

from auth import require_viewer, TokenPayload
from metrics_collector import MetricsCollector
import db_reader

router = APIRouter()
collector = MetricsCollector()

# --- In-memory time series store (last 24h, sampled every 30s) ---
_series: list[dict] = []  # [{ts, cpu, ram, gpu_util, embedded_count}]
_MAX_SERIES = 2880  # 24h × 60min × 2 samples/min


def record_sample():
    """Called periodically to record a metrics sample."""
    data = collector.collect()
    counts = db_reader.get_paper_counts()
    entry = {
        "ts": time.time(),
        "cpu": data.get("cpu_pct", 0),
        "ram": data.get("ram_pct", 0),
        "gpu_util": data.get("gpu", {}).get("util_pct", 0) if data.get("gpu") else 0,
        "embedded_count": counts.get("embedded", 0),
    }
    _series.append(entry)
    if len(_series) > _MAX_SERIES:
        _series.pop(0)


@router.get("/system")
async def system_metrics(_user: TokenPayload = Depends(require_viewer)):
    return collector.collect()


@router.get("/projection")
async def projection(
    window_sec: int = Query(3600, ge=60, le=86400),
    _user: TokenPayload = Depends(require_viewer),
):
    """Compute throughput projection based on integral window delta."""
    now = time.time()
    samples = [s for s in _series if (now - s["ts"]) <= window_sec]

    # --- 1. Official Session Rate (Matches Console Logs) ---
    official = db_reader.get_pipeline_run_metrics()
    session_rate = 0.0
    session_uptime = 0.0
    session_stored = 0
    
    if official:
        session_uptime = official.get("uptime_seconds", 0)
        session_stored = official.get("embedding", {}).get("pdfs_processed", 0)
        if session_uptime > 0:
            session_rate = (session_stored / session_uptime) * 3600

    if len(samples) < 2:
        return {
            "rate_per_hr": round(session_rate, 1),
            "mean_per_day": round(session_rate * 24),
            "window_rate_per_hr": 0,
            "window_sec": window_sec,
            "samples": 0,
            "session_uptime": round(session_uptime),
            "session_stored": session_stored
        }

    # --- 2. Rolling Window Rate (Real-time performance) ---
    first = samples[0]
    last = samples[-1]
    
    total_dt = last["ts"] - first["ts"]
    window_rate = 0.0
    if total_dt > 0:
        total_dp = last["embedded_count"] - first["embedded_count"]
        window_rate = (total_dp / total_dt) * 3600

    # Confidence interval (on window rate)
    deltas = []
    for i in range(1, len(samples)):
        dt = samples[i]["ts"] - samples[i - 1]["ts"]
        if dt > 0:
            d_p = samples[i]["embedded_count"] - samples[i - 1]["embedded_count"]
            deltas.append((d_p / dt) * 3600)
    
    std_rate = statistics.stdev(deltas) if len(deltas) > 1 else 0
    margin = 1.96 * (std_rate / (len(deltas) ** 0.5)) if deltas else 0

    return {
        "rate_per_hr": round(session_rate, 1), # Default to session rate for primary metric
        "mean_per_day": round(session_rate * 24),
        "window_rate_per_hr": round(window_rate, 1),
        "lower95": max(0, round((window_rate - margin) * 24)),
        "upper95": round((window_rate + margin) * 24),
        "window_sec": window_sec,
        "samples": len(samples),
        "session_uptime": round(session_uptime),
        "session_stored": session_stored,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/history")
async def history(
    range: str = Query("1h", regex="^(1h|6h|24h|7d)$"),
    _user: TokenPayload = Depends(require_viewer),
):
    """Return time-series data for charts."""
    now = time.time()
    durations = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}
    cutoff = now - durations.get(range, 3600)

    filtered = [s for s in _series if s["ts"] >= cutoff]
    return {
        "timestamps": [s["ts"] for s in filtered],
        "cpu": [s["cpu"] for s in filtered],
        "ram": [s["ram"] for s in filtered],
        "gpu_util": [s["gpu_util"] for s in filtered],
        "throughput": [s.get("embedded_count", 0) for s in filtered],
    }


CONFIG_PATH = os.getenv("CONFIG_PATH", "/config/acquisition_config.yaml")


@router.get("/coverage")
async def coverage(_user: TokenPayload = Depends(require_viewer)):
    """Build coverage matrix from config keywords × year range."""
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = yaml.safe_load(f)
        keywords = cfg.get("acquisition", {}).get("keywords", [])
    except Exception:
        keywords = []

    if not keywords:
        return {"keywords": [], "years": [], "matrix": [], "updated_at": None}

    current_year = datetime.now().year
    years = list(range(2020, current_year + 1))

    # Single pass fast matrix lookup
    opt_matrix = db_reader.get_coverage_matrix_optimized(keywords, years)

    matrix = []
    for kw in keywords:
        row = []
        for yr in years:
            row.append(opt_matrix.get(kw, {}).get(yr, 0))
        matrix.append(row)

    return {
        "keywords": keywords,
        "years": years,
        "matrix": matrix,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
