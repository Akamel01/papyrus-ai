"""
SME Research Assistant — Qdrant Auto-Tuning Optimizer

Probes hardware at startup, calculates optimal HNSW/quantization/memory parameters,
validates collection configuration, and enforces the Index Readiness Gate.

Memory Tiers:
  TIER 1 (LUXURY):      raw vectors fit in <50% RAM          → no quantization needed
  TIER 2 (BALANCED):    quantized+graph fit in <70% RAM       → SQ int8, mmap originals
  TIER 3 (CONSTRAINED): quantized+graph fit in <90% RAM       → reduced m, higher oversampling
  TIER 4 (EXTREME):     quantized+graph > 90% RAM             → degraded, warn user
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────
TIERS = ("LUXURY", "BALANCED", "CONSTRAINED", "EXTREME")

# Index readiness gate
INDEX_READINESS_THRESHOLD = 0.95   # indexed_vectors / total ≥ 95%
INDEX_READINESS_TIMEOUT   = 1800   # 30 minutes max wait
INDEX_READINESS_POLL_SEC  = 5      # poll every 5 seconds

# Tuning report output path
DEFAULT_REPORT_DIR = "data"
REPORT_FILENAME    = "tuning_report.json"


# ──────────────────────────────────────────────────────────────────────────────
# Hardware probing
# ──────────────────────────────────────────────────────────────────────────────
def probe_hardware(config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Probe current hardware: RAM, CPU, GPU VRAM, disk type.
    Falls back to values from *config* if probing fails.

    Returns dict with keys:
        available_ram_gb, total_ram_gb, cpu_cores, gpu_vram_gb, disk_type
    """
    config = config or {}
    hw = {}

    # ── RAM ──
    try:
        import psutil
        mem = psutil.virtual_memory()
        hw["available_ram_gb"] = round(mem.available / (1024 ** 3), 2)
        hw["total_ram_gb"]     = round(mem.total / (1024 ** 3), 2)
        logger.info(
            f"[HARDWARE] RAM: {hw['total_ram_gb']:.1f} GB total, "
            f"{hw['available_ram_gb']:.1f} GB available"
        )
    except Exception as e:
        fallback = config.get("hardware", {}).get("system_ram_gb", 64)
        hw["total_ram_gb"]     = fallback
        hw["available_ram_gb"] = fallback * 0.6   # conservative estimate
        logger.warning(
            f"[HARDWARE] RAM probe failed ({e}). "
            f"Using config fallback: {fallback} GB total"
        )

    # ── CPU ──
    hw["cpu_cores"] = os.cpu_count() or 4
    logger.info(f"[HARDWARE] CPU cores: {hw['cpu_cores']}")

    # ── GPU VRAM ──
    # ── GPU VRAM ──
    try:
        import subprocess
        # Use nvidia-smi to avoid importing torch (heavy) just for a probe
        # Returns: "NVIDIA GeForce RTX 3090, 24576"
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            encoding="utf-8"
        )
        name, mem_str = output.strip().split(", ", 1)
        hw["gpu_name"] = name
        hw["gpu_vram_gb"] = round(int(mem_str) / 1024, 2)
        logger.info(
            f"[HARDWARE] GPU: {hw['gpu_name']} — "
            f"{hw['gpu_vram_gb']:.1f} GB VRAM (via nvidia-smi)"
        )
    except Exception as e:
        # If nvidia-smi fails, assume no GPU or rely on config fallback
        hw["gpu_vram_gb"] = config.get("hardware", {}).get("gpu_vram_gb", 0)
        hw["gpu_name"]    = "unknown/none"
        if "No such file" not in str(e): # Don't log spam if just not installed
            logger.warning(f"[HARDWARE] GPU probe failed (nvidia-smi): {e}")

    # ── Disk type (hardcoded per user — NVMe SSD) ──
    hw["disk_type"] = "NVMe SSD"

    logger.info(f"[HARDWARE] ✅ Probe Complete: RAM={hw['total_ram_gb']}GB (Avail: {hw['available_ram_gb']}GB) | CPU={hw['cpu_cores']} cores | GPU={hw.get('gpu_name', 'None')} ({hw.get('gpu_vram_gb', 0)}GB VRAM)")
    return hw


# ──────────────────────────────────────────────────────────────────────────────
# Memory footprint calculations
# ──────────────────────────────────────────────────────────────────────────────
def calculate_footprints(
    vector_count: int,
    dimension: int,
    m: int = 32,
) -> Dict[str, float]:
    """
    Calculate memory footprints in GB.

    Args:
        vector_count: number of vectors in collection
        dimension:    embedding dimension (e.g. 4096)
        m:            HNSW connectivity parameter

    Returns:
        Dict with raw_gb, quantized_gb, hnsw_gb, total_qdrant_gb
    """
    raw_gb       = vector_count * dimension * 4 / 1e9       # float32
    quantized_gb = vector_count * dimension * 1 / 1e9       # int8
    hnsw_gb      = vector_count * 2 * m * 8 / 1e9           # bidirectional links
    total_gb     = quantized_gb + hnsw_gb

    logger.info(
        f"[FOOTPRINT] ✅ Calculation Success: Vectors={vector_count:,} | Dim={dimension} | m={m}\n"
        f"            -> Raw Data: {raw_gb:.2f} GB\n"
        f"            -> Quantized: {quantized_gb:.2f} GB\n"
        f"            -> Graph (HNSW): {hnsw_gb:.2f} GB\n"
        f"            -> Total Est. RAM: {total_gb:.2f} GB"
    )
    return {
        "raw_gb":           round(raw_gb, 3),
        "quantized_gb":     round(quantized_gb, 3),
        "hnsw_gb":          round(hnsw_gb, 3),
        "total_qdrant_gb":  round(total_gb, 3),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Tier selection
# ──────────────────────────────────────────────────────────────────────────────
def determine_tier(
    footprints: Dict[str, float],
    available_ram_gb: float,
) -> str:
    """
    Select memory tier based on absolute footprint-to-RAM differences.

    Returns one of: LUXURY, BALANCED, CONSTRAINED, EXTREME
    """
    raw_gb   = footprints["raw_gb"]
    total_gb = footprints["total_qdrant_gb"]

    # Assign tiers demanding a 2GB buffer of free RAM
    if available_ram_gb > (raw_gb + 2.0):
        tier = "LUXURY"
    elif available_ram_gb > (total_gb + 2.0):
        tier = "BALANCED"
    elif available_ram_gb > total_gb:
        tier = "CONSTRAINED"
    else:
        tier = "EXTREME"

    logger.info(
        f"[TIER] Selected tier: {tier}  "
        f"(total_qdrant={total_gb:.2f} GB / available_ram={available_ram_gb:.1f} GB  "
        f"ratio={total_gb / available_ram_gb:.2%})"
    )
    if tier == "EXTREME":
        logger.warning(
            "[TIER] ⚠️  EXTREME tier — performance will be DEGRADED. "
            "Consider adding more RAM or reducing vector count."
        )
    return tier


# ──────────────────────────────────────────────────────────────────────────────
# HNSW parameter auto-calculation
# ──────────────────────────────────────────────────────────────────────────────
def compute_optimal_m(dimension: int, tier: str) -> int:
    """Compute optimal HNSW m based on embedding dimension and memory tier."""
    if dimension <= 512:
        base_m = 12
    elif dimension <= 1024:
        base_m = 16
    elif dimension <= 2048:
        base_m = 24
    elif dimension <= 4096:
        base_m = 32
    else:
        base_m = 48

    tier_adj = {"LUXURY": 8, "BALANCED": 0, "CONSTRAINED": -8, "EXTREME": -16}
    m = max(8, min(64, base_m + tier_adj.get(tier, 0)))

    logger.info(f"[HNSW] Optimal m={m}  (dim={dimension}, tier={tier})")
    return m


def compute_ef_construct(m: int) -> int:
    """ef_construct = m × 4  (standard formula for high-quality index build)."""
    ef_c = m * 4
    logger.info(f"[HNSW] ef_construct={ef_c}  (m={m} × 4)")
    return ef_c


def compute_ef_search(top_k_initial: int, m: int, tier: str) -> int:
    """
    Compute search-time ef.
    ef = max(top_k × 2, m × 8, 128)  capped by tier.
    """
    base_ef = max(top_k_initial * 2, m * 8, 128)
    tier_cap = {"LUXURY": 1024, "BALANCED": 512, "CONSTRAINED": 256, "EXTREME": 128}
    ef = min(base_ef, tier_cap.get(tier, 512))
    logger.info(
        f"[HNSW] ef_search={ef}  "
        f"(top_k={top_k_initial}, m={m}, tier={tier}, cap={tier_cap.get(tier)})"
    )
    return ef


def compute_oversampling(tier: str) -> float:
    """Quantization oversampling factor by tier."""
    values = {"LUXURY": 1.0, "BALANCED": 2.0, "CONSTRAINED": 3.0, "EXTREME": 3.0}
    v = values.get(tier, 2.0)
    logger.info(f"[QUANTIZATION] oversampling={v}  (tier={tier})")
    return v


def compute_optimal_params(
    dimension: int,
    tier: str,
    top_k_initial: int,
    cpu_cores: int,
) -> Dict[str, Any]:
    """
    Compute all optimal parameters for a given tier.

    Returns dict with:
        m, ef_construct, ef_search, oversampling,
        on_disk_vectors, use_quantization, always_ram,
        quantile, segment_count, full_scan_threshold
    """
    m           = compute_optimal_m(dimension, tier)
    ef_c        = compute_ef_construct(m)
    ef_s        = compute_ef_search(top_k_initial, m, tier)
    oversampling = compute_oversampling(tier)

    # Whether to use quantization and on_disk vectors
    use_quant = tier != "LUXURY"
    on_disk   = tier != "LUXURY"
    always_ram = tier in ("BALANCED", "CONSTRAINED")  # keep quantized in RAM

    params = {
        # HNSW
        "m":                    m,
        "ef_construct":         ef_c,
        "ef_search":            ef_s,
        "full_scan_threshold":  20000,
        "max_indexing_threads": 0,       # use all cores
        "hnsw_on_disk":         False,   # graph always in RAM
        # Quantization
        "use_quantization":     use_quant,
        "quantization_type":    "int8",
        "quantile":             0.99,
        "always_ram":           always_ram,
        "oversampling":         oversampling,
        "rescore":              True,
        # Vectors
        "on_disk_vectors":      on_disk,
        # Optimizer
        "segment_count":        min(cpu_cores, 8),
        "max_segment_size":     500_000,
        "indexing_threshold":   200_000,  # User-requested bulk threshold to reduce mid-stream I/O locks
        "flush_interval_sec":   5,
    }

    logger.info(
        f"[PARAMS] ✅ Optimization Complete for TIER={tier}:\n"
        f"          • HNSW: m={m}, ef_c={ef_c}, ef_s={ef_s}\n"
        f"          • Quantization: {'Enabled (int8)' if use_quant else 'Disabled'} (Oversample={oversampling})\n"
        f"          • Storage: {'RAM + Disk' if on_disk else 'RAM Only'}\n"
        f"          • Segments: {params['segment_count']} (Max Size: {params['max_segment_size']})"
    )
    return params


# ──────────────────────────────────────────────────────────────────────────────
# Public API for Optimizer
# ──────────────────────────────────────────────────────────────────────────────
def get_optimal_config(
    vector_count: int = 100_000,
    dimension: int = 4096,
    available_ram_gb: Optional[float] = None,
    tier: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get optimal Qdrant configuration for a given vector count and dimension.
    
    Args:
        vector_count: Estimated number of vectors
        dimension: Embedding dimension
        available_ram_gb: Override available RAM (if None, probes system)
        tier: Force a specific tier (optional)
        
    Returns:
        Dict containing optimal parameters and tier info.
    """
    # 1. Hardware Probe
    hw = probe_hardware()
    if available_ram_gb is None:
        available_ram_gb = hw["available_ram_gb"]
        
    # 2. Footprints
    footprints = calculate_footprints(vector_count, dimension)
    
    # 3. Tier Selection
    if not tier:
        tier = determine_tier(footprints, available_ram_gb)
        
    # 4. Compute Params
    import os
    cpu_cores = os.cpu_count() or 4
    
    params = compute_optimal_params(
        dimension=dimension,
        tier=tier,
        top_k_initial=200, 
        cpu_cores=cpu_cores
    )
    
    # Enrich with tier info
    params["tier"] = tier
    params["footprints"] = footprints
    params["available_ram_gb"] = available_ram_gb
    params["hardware"] = hw
    
    # Nested structure for HNSW config convenience (for VectorStore consumption)
    params["hnsw_config"] = {
        "m": params["m"],
        "ef_construct": params["ef_construct"],
        "full_scan_threshold": params["full_scan_threshold"],
        "max_indexing_threads": params["max_indexing_threads"],
        "on_disk": params["hnsw_on_disk"]
    }
    
    # Nested structure for Quantization config convenience
    if params["use_quantization"]:
        params["quantization_config"] = {
            "scalar": {
                "type": params["quantization_type"],
                "quantile": params["quantile"],
                "always_ram": params["always_ram"]
            }
        }
    else:
        params["quantization_config"] = None
        
    # Storage config convenience
    params["storage_config"] = {
        "on_disk": params["on_disk_vectors"]
    }
    
    # Optimizer config convenience
    params["optimizer_config"] = {
        "default_segment_number": params["segment_count"],
        "max_segment_size": params["max_segment_size"]
    }

    return params


# ──────────────────────────────────────────────────────────────────────────────
# Collection inspection & validation
# ──────────────────────────────────────────────────────────────────────────────
def get_collection_info(client, collection_name: str) -> Dict[str, Any]:
    """
    Retrieve current collection state from Qdrant.

    Returns dict with vector_count, indexed_vectors_count, dimension,
    optimizer_status, and current config details.
    """
    try:
        info = client.get_collection(collection_name)
        vector_count   = info.points_count or 0
        indexed_count  = info.indexed_vectors_count or 0

        # Extract optimizer status
        opt_status = "unknown"
        if hasattr(info, "optimizer_status") and info.optimizer_status:
            opt_obj = info.optimizer_status
            if hasattr(opt_obj, "status"):
                opt_status = str(opt_obj.status)
            else:
                opt_status = str(opt_obj)

        # Extract collection config
        config_detail = {}
        if hasattr(info, "config") and info.config:
            cfg = info.config
            # HNSW
            if hasattr(cfg, "hnsw_config") and cfg.hnsw_config:
                hnsw = cfg.hnsw_config
                config_detail["hnsw_m"]           = getattr(hnsw, "m", None)
                config_detail["hnsw_ef_construct"] = getattr(hnsw, "ef_construct", None)
                config_detail["hnsw_on_disk"]      = getattr(hnsw, "on_disk", None)
            # Quantization
            if hasattr(cfg, "quantization_config") and cfg.quantization_config:
                q = cfg.quantization_config
                if hasattr(q, "scalar") and q.scalar:
                    config_detail["quantization_type"]  = str(getattr(q.scalar, "type", "none"))
                    config_detail["quantization_quantile"] = getattr(q.scalar, "quantile", None)
                    config_detail["quantization_always_ram"] = getattr(q.scalar, "always_ram", None)
            # Optimizer
            if hasattr(cfg, "optimizer_config") and cfg.optimizer_config:
                opt = cfg.optimizer_config
                config_detail["segment_count"]   = getattr(opt, "default_segment_number", None)
                config_detail["max_segment_size"] = getattr(opt, "max_segment_size", None)

        # Extract vectors config (on_disk, dimension)
        if hasattr(info, "config") and info.config:
            params_config = getattr(info.config, "params", None)
            if params_config:
                vectors_cfg = getattr(params_config, "vectors", None)
                if vectors_cfg and hasattr(vectors_cfg, "size"):
                    config_detail["dimension"] = vectors_cfg.size
                    config_detail["on_disk_vectors"] = getattr(vectors_cfg, "on_disk", None)

        result = {
            "vector_count":          vector_count,
            "indexed_vectors_count": indexed_count,
            "optimizer_status":      opt_status,
            "config":                config_detail,
        }

        completeness = (indexed_count / vector_count * 100) if vector_count > 0 else 100.0
        if config_detail:
             dim_log = config_detail.get('dimension', 'Unknown')
             quant_log = config_detail.get('quantization_type', 'None')
        else:
             dim_log = "Unknown"
             quant_log = "Unknown"

        logger.info(
            f"[COLLECTION] ✅ Inspection Success for '{collection_name}':\n"
            f"            -> Count: {vector_count:,} vectors\n"
            f"            -> Indexed: {indexed_count:,} ({completeness:.1f}%)\n"
            f"            -> Dimension: {dim_log}\n"
            f"            -> Status: {opt_status}"
        )
        if config_detail:
            logger.info(f"[COLLECTION] Current config: {json.dumps(config_detail, default=str)}")

        return result

    except Exception as e:
        logger.error(f"[COLLECTION] Failed to inspect {collection_name}: {e}")
        return {
            "vector_count": 0,
            "indexed_vectors_count": 0,
            "optimizer_status": "error",
            "config": {},
            "error": str(e),
        }


def validate_config(
    current: Dict[str, Any],
    optimal: Dict[str, Any],
) -> Tuple[bool, list]:
    """
    Compare current collection config against optimal parameters.

    Returns (matches: bool, deltas: list[str] of mismatches).
    """
    deltas = []
    checks = [
        ("hnsw_m",              optimal["m"],             "HNSW m"),
        ("hnsw_ef_construct",   optimal["ef_construct"],  "HNSW ef_construct"),
        ("hnsw_on_disk",        optimal["hnsw_on_disk"],  "HNSW on_disk"),
    ]

    if optimal["use_quantization"]:
        checks.append(("quantization_type", f"ScalarType.{optimal['quantization_type'].upper()}", "Quantization type"))
        checks.append(("quantization_always_ram", optimal["always_ram"], "Quantization always_ram"))

    for key, expected, label in checks:
        actual = current.get(key)
        if actual is not None and str(actual) != str(expected):
            deltas.append(f"{label}: current={actual}, optimal={expected}")

    # Check on_disk vectors
    actual_on_disk = current.get("on_disk_vectors")
    if actual_on_disk is not None and actual_on_disk != optimal["on_disk_vectors"]:
        deltas.append(f"Vectors on_disk: current={actual_on_disk}, optimal={optimal['on_disk_vectors']}")

    matches = len(deltas) == 0
    if matches:
        logger.info("[VALIDATE] ✅ Collection config matches optimal parameters")
    else:
        logger.warning(f"[VALIDATE] ⚠️  Config mismatches detected ({len(deltas)}):")
        for d in deltas:
            logger.warning(f"  • {d}")

    return matches, deltas


# ──────────────────────────────────────────────────────────────────────────────
# Index Readiness Gate (MANDATORY — blocks startup)
# ──────────────────────────────────────────────────────────────────────────────
def wait_for_index_ready(
    client,
    collection_name: str,
    threshold: float = INDEX_READINESS_THRESHOLD,
    timeout_sec: int = INDEX_READINESS_TIMEOUT,
    poll_sec: int    = INDEX_READINESS_POLL_SEC,
) -> bool:
    """
    Block until the HNSW index is ≥ threshold% complete, or timeout.

    An incomplete HNSW index causes brute-force fallback with EXTREME latency
    (500ms–2s+ per query). This gate is MANDATORY — the system must NOT serve
    queries until the index is ready.

    Args:
        client:          Qdrant client instance
        collection_name: collection to check
        threshold:       minimum indexed/total ratio (default 0.95)
        timeout_sec:     max seconds to wait (default 1800 = 30 min)
        poll_sec:        polling interval (default 5s)

    Returns:
        True if index is ready; False if timeout exceeded.
    """
    logger.info(
        f"[INDEX-GATE] 🔒 Checking index readiness for '{collection_name}' "
        f"(threshold={threshold:.0%}, timeout={timeout_sec}s)..."
    )

    start = time.time()
    last_log = 0

    while True:
        try:
            info = client.get_collection(collection_name)
            total   = info.points_count or 0
            indexed = info.indexed_vectors_count or 0
            
            opt_status = "unknown"
            if hasattr(info, "optimizer_status") and info.optimizer_status:
                opt_status = str(getattr(info.optimizer_status, "status", info.optimizer_status))

            if total == 0:
                logger.info("[INDEX-GATE] Collection is empty — gate passes (no vectors to index)")
                return True

            completeness = indexed / total
            elapsed      = time.time() - start

            # Log progress every 30 seconds
            if elapsed - last_log >= 30 or completeness >= threshold:
                logger.info(
                    f"[INDEX-GATE] Progress: {indexed:,}/{total:,} = {completeness:.1%}  "
                    f"optimizer={opt_status}  elapsed={elapsed:.0f}s"
                )
                last_log = elapsed

            if completeness >= threshold:
                logger.info(
                    f"[INDEX-GATE] ✅ Index READY — {completeness:.1%} complete "
                    f"({indexed:,}/{total:,}) in {elapsed:.1f}s"
                )
                return True

            # === AUTOMATED GREY WAKE-UP ===
            # If Qdrant restarts ungracefully mid-optimization, it boots "grey" and deadlocks.
            if opt_status == "grey":
                logger.warning(f"[INDEX-GATE] ⚠️  Optimizer is GREY (paused). Attempting REST API wake-up call...")
                try:
                    import httpx
                    import json
                    # Re-asserting the current max_segment_size forces Qdrant to instantly wake up to 'yellow'
                    current_max_seg = info.config.optimizer_config.max_segment_size if hasattr(info, 'config') else 200000
                    host = client._rest_uri if hasattr(client, '_rest_uri') else "http://qdrant:6333"
                    url = f"{host}/collections/{collection_name}"
                    
                    # Full payload: re-assert segment size + ensure indexing/memmap thresholds are sane
                    payload = {
                        "optimizers_config": {
                            "max_segment_size": current_max_seg,
                            "indexing_threshold": 200000,
                            "memmap_threshold": 20000,
                        }
                    }
                    response = httpx.patch(url, json=payload, timeout=5.0)
                    
                    if response.status_code == 200:
                        logger.info("[INDEX-GATE] ✅ Wake-up signal sent successfully")
                    else:
                        logger.warning(f"[INDEX-GATE] ⚠️  Wake-up signal failed with {response.status_code}: {response.text}")
                except Exception as ex:
                    logger.error(f"[INDEX-GATE] ❌ Failed to send wake-up signal: {ex}")

            if elapsed >= timeout_sec:
                logger.error(
                    f"[INDEX-GATE] ❌ TIMEOUT after {timeout_sec}s — "
                    f"index only {completeness:.1%} complete ({indexed:,}/{total:,}). "
                    f"System CANNOT serve queries with an incomplete index! "
                    f"The HNSW graph is not fully built, causing brute-force fallback "
                    f"with 500ms–2s+ latency per query."
                )
                return False

        except Exception as e:
            logger.warning(f"[INDEX-GATE] Probe failed: {e}. Retrying in {poll_sec}s...")

        time.sleep(poll_sec)


# ──────────────────────────────────────────────────────────────────────────────
# Tuning report
# ──────────────────────────────────────────────────────────────────────────────
def generate_report(
    hardware: Dict,
    collection_info: Dict,
    footprints: Dict,
    tier: str,
    optimal_params: Dict,
    config_match: bool,
    config_deltas: list,
    index_ready: bool,
    report_dir: str = DEFAULT_REPORT_DIR,
) -> str:
    """
    Write a JSON tuning report for full reproducibility & debugging.
    Returns the path to the written file.
    """
    report = {
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "hardware":     hardware,
        "collection": {
            "vector_count":          collection_info.get("vector_count", 0),
            "indexed_vectors_count": collection_info.get("indexed_vectors_count", 0),
            "optimizer_status":      collection_info.get("optimizer_status", "unknown"),
        },
        "footprints":        footprints,
        "tier":              tier,
        "optimal_params":    optimal_params,
        "config_match":      config_match,
        "config_deltas":     config_deltas,
        "index_ready":       index_ready,
    }

    path = Path(report_dir) / REPORT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"[REPORT] Tuning report written to {path}")
    return str(path)


# ──────────────────────────────────────────────────────────────────────────────
# VRAM budget analysis
# ──────────────────────────────────────────────────────────────────────────────
def log_vram_budget(gpu_vram_gb: float, config: Optional[Dict] = None) -> None:
    """Log the GPU VRAM budget analysis for the user."""
    if gpu_vram_gb <= 0:
        logger.info("[VRAM] No GPU detected — embedding/reranking will use CPU")
        return

    is_remote = False
    if config:
        is_remote = bool(config.get("embedding", {}).get("remote_url"))

    embedder_idle  = 4.0 if not is_remote else 0.0   # Qwen3-8B 4-bit vs Remote
    embedder_peak  = 5.0 if not is_remote else 0.0   # + activation memory
    reranker_idle  = 1.1   # BGE-reranker-v2-m3 fp16
    reranker_peak  = 2.0   # + activation memory
    cuda_overhead  = 0.5

    total_idle = embedder_idle + reranker_idle + cuda_overhead
    total_peak = max(embedder_peak, embedder_idle) + reranker_idle + cuda_overhead  # sequential

    headroom = gpu_vram_gb - total_peak

    logger.info(
        f"[VRAM] Budget analysis for {gpu_vram_gb:.1f} GB VRAM:\n"
        f"  Embedder (4-bit):  {embedder_idle:.1f} GB idle / {embedder_peak:.1f} GB peak\n"
        f"  Reranker (fp16):   {reranker_idle:.1f} GB idle / {reranker_peak:.1f} GB peak\n"
        f"  CUDA overhead:     {cuda_overhead:.1f} GB\n"
        f"  Total idle:        {total_idle:.1f} GB\n"
        f"  Peak (sequential): {total_peak:.1f} GB\n"
        f"  Headroom:          {headroom:.1f} GB  {'✅' if headroom > 1.0 else '⚠️'}"
    )

    if headroom < 1.0:
        logger.warning(
            "[VRAM] ⚠️  Less than 1 GB headroom! Consider unloading reranker "
            "when not in use, or using CPU for reranking."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Connection Gate (MANDATORY — blocks startup until DB is reachable)
# ──────────────────────────────────────────────────────────────────────────────
def wait_for_connection(host: str = "qdrant", port: int = 6333, timeout: int = 60) -> bool:
    """
    Block until Qdrant is reachable on the network.
    Retries every 2 seconds until timeout.
    """
    from qdrant_client import QdrantClient
    import time
    
    logger.info(f"[CONNECTION-GATE] ⏳ Waiting for Qdrant at {host}:{port} (timeout={timeout}s)...")
    start = time.time()
    
    while True:
        try:
            # Strict check: Use Qdrant's /readyz endpoint (returns 200 OK only when fully ready)
            import urllib.request
            url = f"http://{host}:{port}/readyz"
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.getcode() == 200:
                    logger.info(f"[CONNECTION-GATE] ✅ Qdrant is READY at {host}:{port}")
                    return True
                else:
                    raise ConnectionError(f"Qdrant returned status {response.getcode()}")
        except Exception as e:
            elapsed = time.time() - start
            if elapsed >= timeout:
                logger.error(f"[CONNECTION-GATE] ❌ TIMEOUT waiting for Qdrant: {e}")
                return False
            
            # Log only every 10 seconds to reduce noise
            if int(elapsed) % 10 == 0:
                logger.warning(f"[CONNECTION-GATE] Connection failed: {e}. Retrying... ({int(elapsed)}s)")
            
            time.sleep(2)


# ──────────────────────────────────────────────────────────────────────────────
# Main orchestrator: run_startup_optimization
# ──────────────────────────────────────────────────────────────────────────────
def run_startup_optimization(
    client=None,
    collection_name: str = "sme_papers_v2",
    config: Optional[Dict] = None,
    skip_index_gate: bool = False,
) -> Dict[str, Any]:
    """
    Full startup optimization flow:
      1. Probe hardware
      2. Inspect collection
      3. Calculate footprints → select tier → compute optimal params
      4. Validate current config against optimal
      5. Index readiness gate (MANDATORY unless skip_index_gate=True)
      6. Write tuning report
      7. Return optimal search params for use at search-time

    Args:
        client:          Qdrant client instance
        collection_name: collection to optimize
        config:          application config dict (for fallback hardware values
                         and retrieval.top_k_initial)
        skip_index_gate: skip the blocking index readiness check (testing only)

    Returns:
        Dict with keys:
            tier, optimal_params, search_params, index_ready,
            config_match, collection_info, hardware
    """
    print("DEBUG: entering run_startup_optimization", flush=True)
    
    # ── Step 0: Connection Gate ──
    # Ensure Qdrant is reachable before doing anything else.
    # This prevents "Connection refused" errors in downstream components.
    if not wait_for_connection(host="qdrant", port=6333, timeout=120):
        return {"status": "FAILED", "error": "Could not connect to Qdrant"}

    # Initialize default client if not provided (for main.py usage)
    if client is None:
        try:
            from qdrant_client import QdrantClient
            # Use 'qdrant' hostname for Docker
            host = "qdrant"
            client = QdrantClient(host=host, port=6333, timeout=10)
        except Exception as e:
            logger.error(f"[OPTIMIZER] Failed to initialize default client: {e}")
            return {"status": "FAILED", "error": str(e)}

    logger.info(f"[OPTIMIZER] 🚀 Starting hardware probe & config check for '{collection_name}'...")
    config = config or {}

    logger.info("=" * 72)
    logger.info("[OPTIMIZER] 🚀 Starting Qdrant auto-tuning optimization")
    logger.info("=" * 72)

    # ── Step 1: Probe hardware ──
    hardware = probe_hardware(config)
    log_vram_budget(hardware.get("gpu_vram_gb", 0), config)

    # ── Step 2: Inspect collection ──
    coll_info = get_collection_info(client, collection_name)

    if coll_info.get("error"):
        error_msg = str(coll_info["error"])
        # If collection doesn't exist, that's fine (we will create it).
        # Qdrant returns 404 or "Not found" in the message.
        if "404" in error_msg or "not found" in error_msg.lower():
            logger.warning(
                f"[OPTIMIZER] Collection '{collection_name}' not found. "
                f"It will be created on first upsert."
            )
            # Still compute params for when collection IS created
            dimension = config.get("embedding", {}).get("dimension", 4096)
            # Use a minimal vector count for footprint calculation
            vector_count = 0
        else:
            # This is a REAL error (e.g. connection refused, filesystem error, etc.)
            logger.error(f"[OPTIMIZER] ❌ CRITICAL: Failed to inspect collection: {error_msg}")
            return {
                "status": "FAILED",
                "error": f"Qdrant Health Check Failed: {error_msg}. Check container logs."
            }
    else:
        vector_count = coll_info["vector_count"]
        dimension    = coll_info["config"].get(
            "dimension",
            config.get("embedding", {}).get("dimension", 4096)
        )

    # ── Step 3: Calculate footprints & tier ──
    # Use dimension from config if collection is empty/new
    if dimension is None or dimension == 0:
        dimension = config.get("embedding", {}).get("dimension", 4096)

    top_k_initial = config.get("retrieval", {}).get("top_k_initial", 200)

    # For footprint calculation, use actual vector count if > 0, else use a
    # reasonable estimate to pre-compute params
    calc_count = vector_count if vector_count > 0 else 100_000
    footprints = calculate_footprints(calc_count, dimension, m=32)
    tier       = determine_tier(footprints, hardware["available_ram_gb"])

    # ── Step 4: Compute optimal params ──
    optimal = compute_optimal_params(
        dimension=dimension,
        tier=tier,
        top_k_initial=top_k_initial,
        cpu_cores=hardware["cpu_cores"],
    )

    # ── Step 5: Validate current config ──
    config_match = True
    config_deltas = []
    if coll_info.get("config"):
        config_match, config_deltas = validate_config(coll_info["config"], optimal)
        if not config_match:
            logger.warning(
                "[OPTIMIZER] ⚠️  Collection config does NOT match optimal. "
                "To apply optimal config, the collection must be recreated:\n"
                "  1. Create new collection with optimal config\n"
                "  2. Scroll all points from old → new\n"
                "  3. Wait for index build\n"
                "  4. Swap collections\n"
                "Use the migration tool or set recreate=True in create_collection()."
            )

    # ── Step 6: Index readiness gate ──
    index_ready = True
    if vector_count > 0 and not skip_index_gate:
        index_ready = wait_for_index_ready(client, collection_name)
        if not index_ready:
            logger.error(
                "[OPTIMIZER] ❌ INDEX NOT READY — system is starting in DEGRADED mode. "
                "Queries will experience extreme latency until the index is built!"
            )
    elif vector_count == 0:
        logger.info("[OPTIMIZER] Collection is empty — index gate passes (nothing to index)")
    else:
        logger.info("[OPTIMIZER] Index gate skipped (skip_index_gate=True)")

    # ── Step 7: Write tuning report ──
    report_dir = config.get("system", {}).get("data_dir", DEFAULT_REPORT_DIR)
    report_path = generate_report(
        hardware=hardware,
        collection_info=coll_info,
        footprints=footprints,
        tier=tier,
        optimal_params=optimal,
        config_match=config_match,
        config_deltas=config_deltas,
        index_ready=index_ready,
        report_dir=report_dir,
    )

    # ── Build search params for callers ──
    search_params = {
        "hnsw_ef":      optimal["ef_search"],
        "exact":        False,
        "oversampling": optimal["oversampling"],
        "rescore":      optimal["rescore"],
    }

    # ── Summary ──
    status = "✅ OPTIMAL" if config_match and index_ready else "⚠️  SUBOPTIMAL"
    logger.info("=" * 72)
    logger.info(
        f"[OPTIMIZER] {status} — Tier={tier}, m={optimal['m']}, "
        f"ef_search={optimal['ef_search']}, oversampling={optimal['oversampling']}"
    )
    if not config_match:
        logger.info(f"[OPTIMIZER] Config deltas: {len(config_deltas)} mismatches")
    if not index_ready:
        logger.info("[OPTIMIZER] ⚠️  Index is NOT ready")
    logger.info(f"[OPTIMIZER] Report: {report_path}")
    logger.info("=" * 72)

    return {
        "tier":            tier,
        "optimal_params":  optimal,
        "search_params":   search_params,
        "index_ready":     index_ready,
        "config_match":    config_match,
        "config_deltas":   config_deltas,
        "collection_info": coll_info,
        "hardware":        hardware,
        "footprints":      footprints,
        "report_path":     report_path,
    }
