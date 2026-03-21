"""
SME Dashboard — SQLite Database Reader

Read-only access to data/sme.db with caching and retry on lock.
"""

import json
import logging
import os
import sqlite3
import threading
import time
from functools import lru_cache
from typing import Optional

logger = logging.getLogger("dashboard.db")

DB_PATH = os.getenv("DB_PATH", "/data/sme.db")
CACHE_TTL_SEC = 60.0  # Increased to 60s since logs will handle live increments

_last_counts = {}
_last_counts_time = 0.0
_refresher_started = False
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _query_with_retry(sql: str, params: tuple = (), max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            conn = _connect()
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                wait = 0.1 * (2 ** attempt)
                logger.warning(f"[DB] Locked, retrying in {wait:.1f}s (attempt {attempt+1})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Database locked after max retries")


def _refresher_loop():
    """Background loop to update counts every 3s."""
    global _last_counts, _last_counts_time
    while True:
        try:
            # Perform query
            rows = _query_with_retry("SELECT status, COUNT(*) as cnt FROM papers GROUP BY status")
            counts = {row["status"]: row["cnt"] for row in rows}
            
            # Normalize to expected keys
            result = {
                "discovered": counts.get("discovered", 0),
                "downloaded": counts.get("downloaded", 0),
                "chunked": counts.get("chunked", 0),
                "embedded": counts.get("embedded", 0),
                "failed_download": counts.get("failed_download", 0),
                "failed_parse": counts.get("failed_parse", 0),
                "failed_storage": counts.get("failed_storage", 0),
                "failed_empty": counts.get("failed_empty", 0),
            }
            
            with _lock:
                _last_counts = result
                _last_counts_time = time.time()
                
        except Exception as e:
            logger.warning(f"[DB] Background refresher failed: {e}")
            # If DB is locked, we can fallback to JSON metrics in the loop too if we want,
            # but usually we just keep the last successful memory count.
            
        time.sleep(30) # Query much less frequently, logs handle the rest

def increment_count(status: str):
    """Increment an in-memory count based on log events."""
    global _last_counts
    with _lock:
        if status in _last_counts:
            _last_counts[status] += 1
        elif _last_counts: # If cache exists but status is missing (rare)
            _last_counts[status] = 1


def get_paper_counts() -> dict:
    """Get counts by status. Returns instantly from background cache."""
    global _refresher_started, _last_counts
    
    # Start refresher thread if needed
    if not _refresher_started:
        with _lock:
            if not _refresher_started:
                _refresher_started = True
                t = threading.Thread(target=_refresher_loop, daemon=True)
                t.start()
                logger.info("[DB] Background metrics refresher started (3s interval)")

    # Return last known counts instantly
    if _last_counts:
        return _last_counts

    # If no cache yet (first call), try one sync query OR fallback to JSON instantly
    # Falling back to JSON is faster for "first load" experience
    m = get_pipeline_run_metrics()
    return {
        "discovered": 0,
        "downloaded": m.get("download", {}).get("successful", 0),
        "chunked": m.get("chunking", {}).get("pdfs_processed", 0),
        "embedded": m.get("embedding", {}).get("pdfs_processed", 0),
        "failed_download": m.get("download", {}).get("failed", 0),
        "failed_parse": m.get("embedding", {}).get("pdfs_failed", 0),
        "failed_storage": 0,
        "failed_empty": 0,
    }


def get_pipeline_run_metrics() -> dict:
    """Read the official pipeline_metrics.json file for run-specific telemetry."""
    metrics_path = "/data/pipeline_metrics.json"
    if not os.path.exists(metrics_path):
        return {}
    try:
        with open(metrics_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[DB] Error reading pipeline metrics: {e}")
        return {}


def get_dlq_items(status: str = "pending") -> list[dict]:
    """Get Dead Letter Queue items."""
    rows = _query_with_retry(
        "SELECT id, paper_id, stage, error, retry_count, created_at, status "
        "FROM dead_letter_queue WHERE status = ? ORDER BY created_at DESC",
        (status,),
    )
    return [dict(row) for row in rows]


def retry_dlq_item(dlq_id: int):
    """Mark DLQ item as retried and reset paper status."""
    conn = _connect()
    try:
        # Get the item first
        row = conn.execute("SELECT * FROM dead_letter_queue WHERE id = ?", (dlq_id,)).fetchone()
        if not row:
            raise ValueError(f"DLQ item {dlq_id} not found")
        if row["status"] != "pending":
            raise ValueError(f"DLQ item {dlq_id} is already {row['status']}")

        conn.execute(
            "UPDATE dead_letter_queue SET status='retried', retry_count=retry_count+1 WHERE id=?",
            (dlq_id,),
        )
        conn.execute(
            "UPDATE papers SET status='downloaded', error_message=NULL WHERE unique_id=?",
            (row["paper_id"],),
        )
        conn.commit()
    finally:
        conn.close()


def skip_dlq_item(dlq_id: int):
    """Mark DLQ item as abandoned."""
    conn = _connect()
    try:
        conn.execute("UPDATE dead_letter_queue SET status='abandoned' WHERE id=?", (dlq_id,))
        conn.commit()
    finally:
        conn.close()


def get_drilldown(keyword: str, year: int) -> dict:
    """Legacy coverage drilldown. Avoid using for full matrices."""
    rows_total = _query_with_retry(
        "SELECT COUNT(*) as cnt FROM papers WHERE title LIKE ? AND year = ?",
        (f"%{keyword}%", year),
    )
    rows_embedded = _query_with_retry(
        "SELECT COUNT(*) as cnt FROM papers WHERE title LIKE ? AND year = ? AND status = 'embedded'",
        (f"%{keyword}%", year),
    )
    rows_sources = _query_with_retry(
        "SELECT source, COUNT(*) as cnt FROM papers WHERE title LIKE ? AND year = ? GROUP BY source",
        (f"%{keyword}%", year),
    )

    total = rows_total[0]["cnt"] if rows_total else 0
    embedded = rows_embedded[0]["cnt"] if rows_embedded else 0
    sources = {row["source"]: row["cnt"] for row in rows_sources}

    return {
        "keyword": keyword,
        "year": year,
        "papers_count": total,
        "embedded_count": embedded,
        "sources": sources,
        "gap_pct": round((1 - embedded / max(total, 1)) * 100, 1),
    }


def get_coverage_matrix_optimized(keywords: list[str], years: list[int]) -> dict:
    """
    Computes the entire coverage matrix INSTANTLY by reading the pipeline cache 
    `discovery_coverage.json` instead of executing any SQL queries.
    Returns: { "keyword": { year: pct_covered, ... } }
    """
    import json
    import hashlib
    import yaml
    
    if not keywords or not years:
        return {}
        
    # 1. Load config to get exact filters used in hashing
    try:
        config_path = os.getenv("CONFIG_PATH", "/config/acquisition_config.yaml")
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        filters = cfg.get("acquisition", {}).get("filters", {})
        source = cfg.get("acquisition", {}).get("source", "crossref")
    except Exception:
        filters = {}
        source = "crossref"

    # 2. Replicate generate_signature perfectly
    def generate_signature(src: str, kw: str, flt: dict) -> str:
        norm_source = src.lower().strip()
        norm_keyword = kw.lower().strip()
        filter_keys = sorted([k for k in flt.keys() if k not in ['min_year', 'max_year', 'from_updated_date']])
        
        filter_str_parts = []
        for k in filter_keys:
            val = flt[k]
            if isinstance(val, list):
                val = sorted([str(v).lower() for v in val])
                val_str = "|".join(val)
            else:
                val_str = str(val).lower()
            filter_str_parts.append(f"{k}:{val_str}")
            
        filter_sig = "|".join(filter_str_parts)
        raw_sig = f"source:{norm_source}|kw:{norm_keyword}|{filter_sig}"
        return hashlib.md5(raw_sig.encode()).hexdigest()

    # 3. Load discovery_coverage.json cache
    try:
        with open('/data/discovery_coverage.json', 'r') as f:
            coverage_data = json.load(f).get("signatures", {})
    except Exception as e:
        logger.error(f"[DB] Failed loading discovery JSON cache: {e}")
        coverage_data = {}

    result = {kw: {y: 0 for y in years} for kw in keywords}
    
    for kw in keywords:
        sig = generate_signature(source, kw, filters)
        intervals = coverage_data.get(sig, [])
        
        for yr in years:
            for interval in intervals:
                # Interval is usually [start, end]
                if len(interval) == 2 and interval[0] <= yr <= interval[1]:
                    # Assume 100% discovered for this grid cell if interval exists
                    result[kw][yr] = 100
                    break
                    
    return result
