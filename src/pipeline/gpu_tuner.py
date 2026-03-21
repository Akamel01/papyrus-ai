"""
SME Research Assistant - GPU Tuner & Health Monitor

Probes GPU VRAM via nvidia-smi, recommends optimal OLLAMA_NUM_PARALLEL,
and provides a background health monitor thread for long pipeline runs.

Phase 3 of the performance upgrade plan (Section 4).
"""

import logging
import subprocess
import threading
import time
import json
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, Callable

logger = logging.getLogger(__name__)


def probe_gpu() -> Optional[Dict[str, float]]:
    """
    Probe GPU stats via nvidia-smi.
    
    Returns:
        Dict with keys: vram_total_mb, vram_used_mb, vram_free_mb,
                        gpu_util_pct, temperature_c, gpu_name
        None if nvidia-smi is not available.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode != 0:
            logger.warning(f"[GPU-PROBE] nvidia-smi failed: {result.stderr.strip()}")
            return None
        
        line = result.stdout.strip().split("\n")[0]  # First GPU
        parts = [p.strip() for p in line.split(",")]
        
        if len(parts) < 6:
            logger.warning(f"[GPU-PROBE] Unexpected nvidia-smi format: {line}")
            return None
        
        info = {
            "gpu_name": parts[0],
            "vram_total_mb": float(parts[1]),
            "vram_used_mb": float(parts[2]),
            "vram_free_mb": float(parts[3]),
            "gpu_util_pct": float(parts[4]),
            "temperature_c": float(parts[5]),
        }
        
        logger.info(
            f"[GPU-PROBE] {info['gpu_name']} | "
            f"VRAM: {info['vram_used_mb']:.0f}/{info['vram_total_mb']:.0f} MB "
            f"({info['vram_free_mb']:.0f} MB free) | "
            f"Util: {info['gpu_util_pct']:.0f}% | "
            f"Temp: {info['temperature_c']:.0f}°C"
        )
        
        return info
        
    except FileNotFoundError:
        logger.warning("[GPU-PROBE] nvidia-smi not found — no GPU monitoring available")
        return None
    except Exception as e:
        logger.warning(f"[GPU-PROBE] Probe failed: {e}")
        return None


def recommend_parallel(
    vram_total_mb: float,
    vram_used_mb: float,
    per_slot_mb: float = 400.0,
    reranker_reserve_mb: float = 2000.0,
    max_parallel: int = 16,
) -> int:
    """
    Calculate recommended OLLAMA_NUM_PARALLEL based on available VRAM.
    
    Args:
        vram_total_mb: Total GPU VRAM in MB
        vram_used_mb: Currently used VRAM in MB (includes model weights)
        per_slot_mb: Estimated VRAM per parallel embedding slot (~400 MB)
        reranker_reserve_mb: VRAM reserved for the reranker model (~2 GB)
        max_parallel: Maximum safe parallelism
    
    Returns:
        Recommended OLLAMA_NUM_PARALLEL value (minimum 2)
    """
    # Available VRAM = total - used - reserve for reranker
    available_mb = vram_total_mb - vram_used_mb - reranker_reserve_mb
    
    if available_mb <= 0:
        logger.warning(
            f"[GPU-TUNER] No headroom for parallelism increase: "
            f"total={vram_total_mb:.0f}, used={vram_used_mb:.0f}, "
            f"reserve={reranker_reserve_mb:.0f}"
        )
        return 2  # Minimum safe value
    
    # Calculate safe parallel slots
    safe_parallel = int(available_mb / per_slot_mb)
    recommended = max(2, min(safe_parallel, max_parallel))
    
    logger.info(
        f"[GPU-TUNER] VRAM headroom: {available_mb:.0f} MB | "
        f"Per-slot: {per_slot_mb:.0f} MB | "
        f"Recommended OLLAMA_NUM_PARALLEL: {recommended} "
        f"(current headroom supports up to {safe_parallel})"
    )
    
    return recommended


def startup_gpu_report() -> Dict:
    """
    Run at pipeline startup. Probes GPU, logs recommendation.
    
    Returns:
        Dict with probe results and recommendation, or empty dict if no GPU.
    """
    gpu_info = probe_gpu()
    
    if not gpu_info:
        logger.info("[GPU-TUNER] No GPU detected — skipping auto-tune")
        return {}
    
    recommended = recommend_parallel(
        vram_total_mb=gpu_info["vram_total_mb"],
        vram_used_mb=gpu_info["vram_used_mb"],
    )
    
    report = {
        **gpu_info,
        "recommended_parallel": recommended,
    }
    
    return report


class GPUHealthMonitor:
    """
    Background thread that periodically checks GPU health during pipeline runs.
    
    Logs warnings when VRAM > 90% or temperature > 85°C.
    
    Usage:
        monitor = GPUHealthMonitor(interval_sec=30)
        monitor.start()
        # ... run pipeline ...
        monitor.stop()
    """
    
    def __init__(self, interval_sec: float = 30.0, vram_warn_pct: float = 90.0, temp_warn_c: float = 85.0,
                 auto_tuner: Optional['AutoTuner'] = None):
        self.interval_sec = interval_sec
        self.vram_warn_pct = vram_warn_pct
        self.temp_warn_c = temp_warn_c
        self.auto_tuner = auto_tuner
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._check_count = 0
        self._warn_count = 0
    
    def start(self):
        """Start the health monitor background thread."""
        if self._thread and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="GPUHealthMonitor",
            daemon=True
        )
        self._thread.start()
        logger.info(
            f"[GPU-HEALTH] Monitor started (interval={self.interval_sec}s, "
            f"vram_warn={self.vram_warn_pct}%, temp_warn={self.temp_warn_c}°C)"
        )
    
    def stop(self):
        """Stop the health monitor."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info(
            f"[GPU-HEALTH] Monitor stopped | "
            f"checks={self._check_count}, warnings={self._warn_count}"
        )
    
    def _monitor_loop(self):
        """Background loop that probes GPU at intervals."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self.interval_sec)
            if self._stop_event.is_set():
                break
            
            self._check_count += 1
            gpu_info = probe_gpu()
            
            if not gpu_info:
                continue
            
            # Check VRAM usage
            vram_pct = (gpu_info["vram_used_mb"] / gpu_info["vram_total_mb"]) * 100
            if vram_pct > self.vram_warn_pct:
                self._warn_count += 1
                logger.warning(
                    f"[GPU-HEALTH] ⚠️ VRAM HIGH: {vram_pct:.1f}% "
                    f"({gpu_info['vram_used_mb']:.0f}/{gpu_info['vram_total_mb']:.0f} MB)"
                )
                # Phase 5: Trigger auto-tuner if available
                if self.auto_tuner:
                    self.auto_tuner.check_vram_pressure(gpu_info)
            
            # Check temperature
            if gpu_info["temperature_c"] > self.temp_warn_c:
                self._warn_count += 1
                logger.warning(
                    f"[GPU-HEALTH] ⚠️ TEMP HIGH: {gpu_info['temperature_c']:.0f}°C "
                    f"(threshold: {self.temp_warn_c}°C)"
                )
            
            # Periodic info log (every 4th check = ~2 min at 30s interval)
            if self._check_count % 4 == 0:
                logger.info(
                    f"[GPU-HEALTH] VRAM: {vram_pct:.1f}% | "
                    f"Temp: {gpu_info['temperature_c']:.0f}°C | "
                    f"Util: {gpu_info['gpu_util_pct']:.0f}%"
                )


# =============================================================================
# Phase 5: AutoTuner — Runtime Batch Adjustment & Rollback Ladder
# =============================================================================

class AutoTuner:
    """
    Manages runtime batch/queue sizing with a 5-level rollback ladder.
    
    Level 0 (stable):    Use tuned params
    Level 1 (warning):   VRAM > 85% for 30s → reduce batch 25%
    Level 2 (critical):  OOM detected → reduce batch 50%, clear cache
    Level 3 (emergency): 3 OOMs in 5 min → batch=1, alert
    Level 4 (halt):      5 OOMs in 10 min → halt pipeline
    
    Safety: NEVER increases batch during a run — only decreases.
    """
    
    LEVEL_NAMES = ["stable", "warning", "critical", "emergency", "halt"]
    
    def __init__(
        self,
        initial_batch: int = 4,
        log_path: str = "data/auto_tuner_log.jsonl",
        config_path: str = "data/auto_tuned_config.json",
        vram_pressure_pct: float = 85.0,
        vram_pressure_cooldown: float = 300.0,  # 5 min
    ):
        self.initial_batch = initial_batch
        self.current_batch = initial_batch
        self.log_path = log_path
        self.config_path = config_path
        self.vram_pressure_pct = vram_pressure_pct
        self.vram_pressure_cooldown = vram_pressure_cooldown
        
        self.level = 0  # Current rollback level
        self._oom_timestamps: list = []  # Timestamps of recent OOMs
        self._last_vram_action: float = 0.0  # Timestamp of last VRAM reduction
        self._lock = threading.Lock()
        self._halt_event = threading.Event()
        
        logger.info(
            f"[AUTO-TUNE] Initialized: batch={initial_batch}, "
            f"vram_pressure={vram_pressure_pct}%"
        )
    
    @property
    def is_halted(self) -> bool:
        """Whether the auto-tuner has triggered a pipeline halt."""
        return self._halt_event.is_set()
    
    def get_current_batch_size(self) -> int:
        """Get the dynamically adjusted batch size (thread-safe)."""
        with self._lock:
            return self.current_batch
    
    def check_vram_pressure(self, gpu_info: Dict[str, float]) -> None:
        """
        Called by GPUHealthMonitor when VRAM exceeds warning threshold.
        Escalates to Level 1 if sustained.
        """
        with self._lock:
            now = time.time()
            
            # Cooldown check — don't reduce again within cooldown period
            if (now - self._last_vram_action) < self.vram_pressure_cooldown:
                return
            
            vram_pct = (gpu_info["vram_used_mb"] / gpu_info["vram_total_mb"]) * 100
            
            if vram_pct > self.vram_pressure_pct and self.level < 1:
                self.level = 1
                old_batch = self.current_batch
                self.current_batch = max(1, int(self.current_batch * 0.75))  # Reduce 25%
                self._last_vram_action = now
                
                logger.warning(
                    f"[AUTO-TUNE] Level 1 (warning): VRAM {vram_pct:.1f}% > {self.vram_pressure_pct}% | "
                    f"Batch: {old_batch} → {self.current_batch}"
                )
                self._persist_state("reduce_batch_25pct", "vram_pressure", gpu_info)
    
    def report_oom(self) -> None:
        """
        Called when an OOM or Ollama 500 (VRAM) error occurs.
        Escalates through Levels 2-4.
        """
        with self._lock:
            now = time.time()
            self._oom_timestamps.append(now)
            
            # Clean old OOM timestamps (keep last 10 minutes)
            self._oom_timestamps = [t for t in self._oom_timestamps if (now - t) < 600]
            
            recent_5min = sum(1 for t in self._oom_timestamps if (now - t) < 300)
            recent_10min = len(self._oom_timestamps)
            
            # Level 4: 5 OOMs in 10 min → halt
            if recent_10min >= 5:
                self.level = 4
                self.current_batch = 1
                self._halt_event.set()
                logger.critical(
                    f"[AUTO-TUNE] Level 4 (HALT): {recent_10min} OOMs in 10 min | "
                    f"Pipeline halt requested. DLQ preserved."
                )
                self._persist_state("halt_pipeline", f"{recent_10min}_ooms_10min")
                return
            
            # Level 3: 3 OOMs in 5 min → batch=1
            if recent_5min >= 3:
                old_batch = self.current_batch
                self.level = 3
                self.current_batch = 1
                logger.error(
                    f"[AUTO-TUNE] Level 3 (emergency): {recent_5min} OOMs in 5 min | "
                    f"Batch: {old_batch} → 1"
                )
                self._persist_state("emergency_batch_1", f"{recent_5min}_ooms_5min")
                return
            
            # Level 2: Single OOM → reduce batch 50%
            old_batch = self.current_batch
            self.level = max(self.level, 2)
            self.current_batch = max(1, int(self.current_batch * 0.5))
            
            logger.warning(
                f"[AUTO-TUNE] Level 2 (critical): OOM detected | "
                f"Batch: {old_batch} → {self.current_batch} | "
                f"OOMs in last 5min: {recent_5min}, 10min: {recent_10min}"
            )
            self._persist_state("reduce_batch_50pct", "oom_detected")
    
    def _persist_state(self, action: str, trigger: str, gpu_info: Optional[Dict] = None) -> None:
        """Append a tuning decision to the JSONL log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": self.level,
            "level_name": self.LEVEL_NAMES[self.level],
            "action": action,
            "trigger": trigger,
            "old_batch": self.initial_batch,
            "current_batch": self.current_batch,
        }
        if gpu_info:
            entry["vram_used_mb"] = gpu_info.get("vram_used_mb", 0)
            entry["vram_total_mb"] = gpu_info.get("vram_total_mb", 0)
        
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"[AUTO-TUNE] Failed to persist state: {e}")
    
    def get_summary(self) -> str:
        """Return a human-readable summary of the auto-tuner state."""
        return (
            f"Level={self.level} ({self.LEVEL_NAMES[self.level]}), "
            f"Batch={self.current_batch} (initial={self.initial_batch}), "
            f"OOMs={len(self._oom_timestamps)}"
        )


def derive_startup_config(
    gpu_info: Optional[Dict] = None,
    cpu_cores: Optional[int] = None,
    config_path: str = "data/auto_tuned_config.json",
) -> Dict:
    """
    Derive optimal pipeline params from hardware at startup.
    Persists to JSON for next restart.
    
    Returns:
        Dict with derived params (embed_batch_size, parser_workers,
        store_workers, qdrant_batch_size, queue sizes).
    """
    import os as _os
    cores = cpu_cores or _os.cpu_count() or 4
    
    # Base batch size from VRAM
    if gpu_info and gpu_info.get("vram_free_mb", 0) > 0:
        # Estimate: ~100 MB per batch item for embedding
        safe_batch = max(2, int(gpu_info["vram_free_mb"] / 400))
        safe_batch = min(safe_batch, 256)  # Cap at 256
    else:
        safe_batch = 4  # Conservative default
    
    config = {
        "embed_batch_size": safe_batch,
        "parser_workers": max(2, int(cores * 0.8)),
        "download_workers": 20, # Boost supply chain
        "store_workers": max(1, min(4, int(cores * 0.1))),
        "qdrant_batch_size": min(safe_batch * 4, 500),
        "queue_size_parsed": 100,
        "queue_size_embedded": 100,
        "derived_at": datetime.now(timezone.utc).isoformat(),
        "cpu_cores": cores,
        "gpu_name": gpu_info.get("gpu_name", "none") if gpu_info else "none",
        "vram_free_mb": gpu_info.get("vram_free_mb", 0) if gpu_info else 0,
    }
    
    # Persist
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        logger.info(f"[AUTO-TUNE] Startup config persisted to {config_path}")
    except Exception as e:
        logger.warning(f"[AUTO-TUNE] Failed to persist config: {e}")
    
    logger.info(
        f"[AUTO-TUNE] Derived config: batch={config['embed_batch_size']}, "
        f"parser_workers={config['parser_workers']}, "
        f"store_workers={config['store_workers']}, "
        f"qdrant_batch={config['qdrant_batch_size']}"
    )
    
    return config
