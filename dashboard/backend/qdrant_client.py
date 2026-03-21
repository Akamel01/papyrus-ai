"""
SME Dashboard — Qdrant Client

Stats polling, caching, snapshot trigger with safeguards.
"""

import asyncio
import logging
import os
import time
from typing import Optional

import httpx
import psutil

logger = logging.getLogger("dashboard.qdrant")

QDRANT_URL = os.getenv("QDRANT_URL", "http://sme_qdrant:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "sme_papers_v2")
CACHE_TTL = 5.0  # seconds

# Snapshot safeguards
MIN_FREE_DISK_GB = 60.0  # Require at least 60 GB free before snapshotting (collection is ~57 GB)
MAX_SNAPSHOTS = 2  # Keep at most 2 snapshots; auto-delete oldest beyond this

_stats_cache: Optional[dict] = None
_stats_cache_time: float = 0.0
_consecutive_failures: int = 0
_snapshot_in_progress: bool = False


async def get_stats() -> dict:
    """Get collection stats with caching and staleness tracking."""
    global _stats_cache, _stats_cache_time, _consecutive_failures

    now = time.time()
    if _stats_cache and (now - _stats_cache_time) < CACHE_TTL:
        return {**_stats_cache, "stale": False}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{QDRANT_URL}/collections/{COLLECTION}")

        if resp.status_code != 200:
            raise RuntimeError(f"Qdrant HTTP {resp.status_code}")

        data = resp.json().get("result", {})
        _stats_cache = {
            "vectors_count": data.get("points_count", data.get("vectors_count", 0)),
            "segments_count": data.get("segments_count", 0),
            "status": data.get("status", "unknown"),
            "disk_usage_bytes": data.get("disk_data_size", 0),
        }
        _stats_cache_time = now
        _consecutive_failures = 0
        return {**_stats_cache, "stale": False}

    except Exception as e:
        _consecutive_failures += 1
        logger.warning(f"[QDRANT] Stats fetch failed ({_consecutive_failures}x): {e}")

        if _stats_cache:
            age = int(now - _stats_cache_time)
            return {**_stats_cache, "stale": True, "stale_seconds": age}

        return {
            "vectors_count": 0,
            "segments_count": 0,
            "status": "unreachable",
            "stale": True,
            "error": str(e),
        }


async def trigger_snapshot() -> dict:
    """
    Create a Qdrant collection snapshot with safeguards:
    1. Only one snapshot at a time
    2. Disk space check before starting
    3. Auto-cleanup of old snapshots (keep MAX_SNAPSHOTS)
    """
    global _snapshot_in_progress

    # --- Guard 1: Concurrent snapshot limit ---
    if _snapshot_in_progress:
        raise RuntimeError("A snapshot is already in progress. Wait for it to complete.")

    # --- Guard 2: Disk space check ---
    try:
        disk = psutil.disk_usage("/data")
        free_gb = disk.free / 1e9
        if free_gb < MIN_FREE_DISK_GB:
            raise RuntimeError(
                f"Insufficient disk space for snapshot. "
                f"Free: {free_gb:.1f} GB, required: {MIN_FREE_DISK_GB} GB. "
                f"A snapshot of this collection requires ~{_get_collection_size_gb():.0f} GB."
            )
    except OSError:
        logger.warning("[QDRANT] Could not check disk space; proceeding anyway")

    # --- Guard 3: Auto-cleanup old snapshots before creating new one ---
    await _cleanup_old_snapshots()

    # --- Create snapshot ---
    _snapshot_in_progress = True
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(f"{QDRANT_URL}/collections/{COLLECTION}/snapshots")
        if resp.status_code != 200:
            raise RuntimeError(f"Snapshot failed: HTTP {resp.status_code} — {resp.text[:200]}")
        result = resp.json().get("result", {})
        logger.info(f"[QDRANT] Snapshot created: {result}")
        return result
    except Exception:
        raise
    finally:
        _snapshot_in_progress = False


async def list_snapshots() -> list:
    """List all existing snapshots for the collection."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{QDRANT_URL}/collections/{COLLECTION}/snapshots")
        if resp.status_code != 200:
            return []
        return resp.json().get("result", [])
    except Exception as e:
        logger.warning(f"[QDRANT] Failed to list snapshots: {e}")
        return []


async def delete_snapshot(snapshot_name: str) -> bool:
    """Delete a specific snapshot by name."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{QDRANT_URL}/collections/{COLLECTION}/snapshots/{snapshot_name}"
            )
        if resp.status_code == 200:
            logger.info(f"[QDRANT] Deleted snapshot: {snapshot_name}")
            return True
        logger.warning(f"[QDRANT] Failed to delete snapshot {snapshot_name}: HTTP {resp.status_code}")
        return False
    except Exception as e:
        logger.warning(f"[QDRANT] Failed to delete snapshot {snapshot_name}: {e}")
        return False


async def _cleanup_old_snapshots():
    """Delete oldest snapshots if count exceeds MAX_SNAPSHOTS - 1 (to make room for new one)."""
    snapshots = await list_snapshots()
    if len(snapshots) < MAX_SNAPSHOTS:
        return

    # Sort by creation time (oldest first)
    snapshots.sort(key=lambda s: s.get("creation_time", ""))
    to_delete = snapshots[:len(snapshots) - MAX_SNAPSHOTS + 1]

    for snap in to_delete:
        name = snap.get("name", "")
        if name:
            logger.info(f"[QDRANT] Auto-cleaning old snapshot: {name}")
            await delete_snapshot(name)


def _get_collection_size_gb() -> float:
    """Estimate collection size from cached stats."""
    if _stats_cache and _stats_cache.get("disk_usage_bytes"):
        return _stats_cache["disk_usage_bytes"] / 1e9
    return 50.0  # Conservative default
