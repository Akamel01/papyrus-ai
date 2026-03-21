"""
SME Dashboard — YAML Config Manager

Handles: read, validate, save (atomic + backup), revert, version listing.
Optimistic locking via ETag (SHA-256 of file content).
"""

import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("dashboard.config")

CONFIG_PATH = os.getenv("CONFIG_PATH", "/config/acquisition_config.yaml")
BACKUP_DIR = os.getenv("CONFIG_BACKUP_DIR", "/data/config_backups")
MAX_BACKUPS = 30

# YAML tags that must be rejected (security)
FORBIDDEN_TAGS = ["!!python", "!!exec", "!!import", "!!ruby", "!!perl", "!!java"]

# Keys that require Admin role to modify
ADMIN_ONLY_KEYS = {
    "apis.openalex.api_key",
    "apis.semantic_scholar.api_key",
    "emails",
    "embedding.remote_url",
    "embedding.vector_store.host",
    "state",
    "logging",
    "scheduling",
    "error_handling.pdf_fallback_chain",
}


def compute_etag(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()[:16]}"


def read_config() -> dict:
    """Read raw YAML and return {yaml, etag}."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return {"yaml": content, "etag": compute_etag(content)}


def validate_config(yaml_text: str) -> dict:
    """
    Validate YAML text. Returns {valid, errors[], warnings[]}.
    """
    errors = []
    warnings = []

    # 1. Security check — forbidden tags
    for tag in FORBIDDEN_TAGS:
        if tag in yaml_text:
            errors.append({"line": 0, "col": 0, "msg": f"Forbidden YAML tag: {tag}"})
            return {"valid": False, "errors": errors, "warnings": warnings}

    # 2. Syntax parse
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        line = getattr(e, "problem_mark", None)
        errors.append({
            "line": line.line + 1 if line else 0,
            "col": line.column if line else 0,
            "msg": str(e),
        })
        return {"valid": False, "errors": errors, "warnings": warnings}

    if not isinstance(data, dict):
        errors.append({"line": 1, "col": 0, "msg": "Config must be a YAML mapping"})
        return {"valid": False, "errors": errors, "warnings": warnings}

    # 3. Required sections
    required_sections = ["acquisition", "processing", "embedding"]
    for section in required_sections:
        if section not in data:
            errors.append({"line": 0, "col": 0, "msg": f"Missing required section: {section}"})

    # 4. Type checks for known fields
    acq = data.get("acquisition", {})
    if acq:
        kw = acq.get("keywords", [])
        if not isinstance(kw, list) or len(kw) == 0:
            errors.append({"line": 0, "col": 0, "msg": "acquisition.keywords must be a non-empty list"})

        filters = acq.get("filters", {})
        max_kw = filters.get("max_per_keyword", 0)
        if isinstance(max_kw, (int, float)) and max_kw > 100000:
            warnings.append({
                "line": 0, "col": 0,
                "msg": f"max_per_keyword={max_kw:,} is very high — may cause long discovery runs",
            })

    emb = data.get("embedding", {})
    if emb:
        if not emb.get("model_name"):
            errors.append({"line": 0, "col": 0, "msg": "embedding.model_name is required"})
        if not emb.get("collection_name"):
            errors.append({"line": 0, "col": 0, "msg": "embedding.collection_name is required"})

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def save_config(yaml_text: str, client_etag: str, user_id: str) -> dict:
    """
    Save config with optimistic locking, backup, and audit.
    Returns {ok, new_etag, backup_path}.
    Raises ValueError on ETag mismatch, validation failure.
    """
    # 1. ETag check
    current = read_config()
    if client_etag != current["etag"]:
        raise ValueError("Config modified by another user. Refresh to see latest version.")

    # 2. Validate
    result = validate_config(yaml_text)
    if not result["valid"]:
        raise ValueError(f"Validation failed: {result['errors']}")

    # 3. Backup current
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"{timestamp}_{user_id}.yaml"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    shutil.copy2(CONFIG_PATH, backup_path)

    # 4. Scrub secrets in backup
    _scrub_secrets(backup_path)

    # 5. Atomic write
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(yaml_text)
    os.replace(tmp_path, CONFIG_PATH)

    # 6. Prune old backups
    _prune_backups()

    new_etag = compute_etag(yaml_text)
    logger.info(f"[CONFIG] Saved by {user_id} (backup={backup_name})")

    return {"ok": True, "new_etag": new_etag, "backup_path": backup_name}


def list_versions() -> list[dict]:
    """List available config backups."""
    if not os.path.exists(BACKUP_DIR):
        return []
    versions = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.endswith(".yaml"):
            parts = f.replace(".yaml", "").split("_", 2)
            user = parts[2] if len(parts) > 2 else "unknown"
            fpath = os.path.join(BACKUP_DIR, f)
            versions.append({
                "filename": f,
                "timestamp": os.path.getmtime(fpath),
                "user": user,
                "path": f,
            })
    return versions[:MAX_BACKUPS]


def revert_config(version_path: str, user_id: str) -> dict:
    """Revert config to a specific backup version."""
    full_path = os.path.join(BACKUP_DIR, os.path.basename(version_path))
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Version not found: {version_path}")

    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    # The backup has scrubbed secrets — need to restore from current
    # This is a known limitation: reverts restore structure but Admin must re-enter keys
    return save_config(content, read_config()["etag"], user_id)


def _scrub_secrets(filepath: str):
    """Replace API keys in backup with ***REDACTED***."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    # Scrub api_key values
    content = re.sub(
        r'(api_key:\s*["\']?)([^"\'\n]+)(["\']?)',
        r'\1***REDACTED***\3',
        content,
    )
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def _prune_backups():
    """Keep only MAX_BACKUPS most recent backups."""
    if not os.path.exists(BACKUP_DIR):
        return
    files = sorted(
        [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith(".yaml")],
        key=os.path.getmtime,
        reverse=True,
    )
    for old_file in files[MAX_BACKUPS:]:
        os.remove(old_file)
        logger.info(f"[CONFIG] Pruned old backup: {os.path.basename(old_file)}")
