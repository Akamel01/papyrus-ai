"""
SME Dashboard — Audit Logger

Append-only JSONL audit log for all sensitive operations.
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("dashboard.audit")

AUDIT_FILE = os.getenv("AUDIT_FILE", "/data/audit_log.jsonl")


def log_audit(user_id: str, action: str, detail: dict = None, ip: str = None):
    """Append an audit entry."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "action": action,
        "detail": detail or {},
        "ip": ip,
    }
    try:
        os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"[AUDIT] Failed to write: {e}")


def read_audit(
    user: str = None,
    action: str = None,
    from_ts: str = None,
    to_ts: str = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Read and filter audit entries."""
    if not os.path.exists(AUDIT_FILE):
        return {"items": [], "total": 0}

    entries = []
    with open(AUDIT_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if user and entry.get("user_id") != user:
                    continue
                if action and entry.get("action") != action:
                    continue
                if from_ts and entry.get("timestamp", "") < from_ts:
                    continue
                if to_ts and entry.get("timestamp", "") > to_ts:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    entries.reverse()  # newest first
    total = len(entries)
    start = (page - 1) * page_size
    return {"items": entries[start : start + page_size], "total": total}
