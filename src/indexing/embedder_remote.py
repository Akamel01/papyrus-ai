"""
SME Research Assistant - Remote Embedder

Adapter for running embeddings via Ollama API (Dockerized Model).
Uses batch /api/embed endpoint for maximum GPU utilization.
Auto-tunes batch size based on available VRAM at startup.
"""

import logging
import time
import subprocess
import threading
from typing import List, Optional
import httpx

from src.core.interfaces import Embedder
from src.core.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

# Absolute safety cap (never send more than this in one request)
ABSOLUTE_MAX_BATCH = 128

# Memory per text estimate: ~2 MB per 1024-token text at 4096-dim embedding
# (forward pass activations + embedding output)
VRAM_PER_TEXT_MB = 2.0


def _probe_gpu_vram_mb() -> Optional[float]:
    """Query nvidia-smi for total GPU VRAM in MB. Returns None if unavailable."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return float(result.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return None


def _compute_optimal_batch(total_vram_mb: float, model_vram_mb: float,
                           seq_length: int) -> int:
    """
    Compute optimal batch size from available VRAM.
    
    Formula:
        free_vram = total_vram - model_vram - overhead(500MB)
        batch_size = free_vram / vram_per_text
        vram_per_text scales with seq_length (base: 2MB at 1024 tokens)
    
    Reference values (from performance_upgrade_plan.md):
        RTX 4070 Super 12GB, model 4GB → free 7.5GB → batch ~60
        RTX 3090 24GB, model 4GB → free 19.5GB → batch ~156
        8GB GPU, model 4GB → free 3.5GB → batch ~28
    """
    overhead_mb = 500
    free_vram_mb = total_vram_mb - model_vram_mb - overhead_mb
    
    if free_vram_mb <= 0:
        return 8  # Minimum safe batch
    
    # Scale memory per text by sequence length
    scale = max(seq_length, 512) / 1024.0
    per_text = VRAM_PER_TEXT_MB * scale
    
    batch = int(free_vram_mb / per_text)
    batch = max(8, min(batch, ABSOLUTE_MAX_BATCH))
    return batch


class GPUHealthMonitor:
    """
    Background daemon that monitors GPU health and adjusts safe batch size.

    Checks every `interval` seconds via nvidia-smi.
    Auto-reduces batch size when VRAM > 90% or temp > 85°C.
    Auto-restores original batch when healthy.

    WARNING: There is a duplicate GPUHealthMonitor in src/pipeline/gpu_tuner.py.
    Running both monitors simultaneously causes GPU probe contention every 30s.

    TODO: Consolidate into a single shared GPUHealthMonitor with:
    - Batch size adjustment (this class's functionality)
    - Warning logging (gpu_tuner.py's functionality)
    - AutoTuner integration (gpu_tuner.py's functionality)

    Until consolidation, only use ONE monitor per runtime session.
    """
    
    def __init__(self, base_batch_size: int, interval: float = 30.0):
        self._base_batch = base_batch_size
        self._safe_batch = base_batch_size
        self._interval = interval
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._reduction_active = False
    
    def start(self):
        """Start background monitoring."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="GPUHealthMonitor",
            daemon=True
        )
        self._thread.start()
        logger.info(
            f"[GPU-HEALTH] Monitor started: interval={self._interval}s, "
            f"base_batch={self._base_batch}"
        )
    
    def stop(self):
        """Stop monitoring."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
    
    @property
    def safe_batch_size(self) -> int:
        """Thread-safe read of current safe batch size."""
        with self._lock:
            return self._safe_batch
    
    def update_base(self, new_base: int):
        """Update the base batch size (called after auto-tune)."""
        with self._lock:
            self._base_batch = new_base
            if not self._reduction_active:
                self._safe_batch = new_base
    
    def _monitor_loop(self):
        while not self._stop.wait(self._interval):
            try:
                metrics = self._probe_gpu()
                if metrics is None:
                    continue
                
                vram_pct = metrics.get("vram_pct", 0)
                temp = metrics.get("temp", 0)
                gpu_util = metrics.get("gpu_util", 0)
                
                with self._lock:
                    if vram_pct > 90 or temp > 85:
                        # STRESS: reduce batch by 50%
                        new_batch = max(8, self._base_batch // 2)
                        if self._safe_batch != new_batch:
                            logger.warning(
                                f"[GPU-HEALTH] STRESS detected: VRAM={vram_pct:.0f}%, "
                                f"temp={temp}°C. Reducing batch: {self._safe_batch} → {new_batch}"
                            )
                            self._safe_batch = new_batch
                            self._reduction_active = True
                    
                    elif self._reduction_active and vram_pct < 70 and temp < 75:
                        # HEALTHY: restore original
                        logger.info(
                            f"[GPU-HEALTH] Healthy: VRAM={vram_pct:.0f}%, temp={temp}°C. "
                            f"Restoring batch: {self._safe_batch} → {self._base_batch}"
                        )
                        self._safe_batch = self._base_batch
                        self._reduction_active = False
                    else:
                        logger.debug(
                            f"[GPU-HEALTH] OK: VRAM={vram_pct:.0f}%, temp={temp}°C, "
                            f"util={gpu_util}%, batch={self._safe_batch}"
                        )
                        
            except Exception as e:
                logger.debug(f"[GPU-HEALTH] Monitor error (non-fatal): {e}")
    
    def _probe_gpu(self) -> Optional[dict]:
        """Query nvidia-smi for GPU metrics."""
        try:
            result = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                if len(parts) >= 4:
                    mem_used = float(parts[0].strip())
                    mem_total = float(parts[1].strip())
                    temp = float(parts[2].strip())
                    gpu_util = float(parts[3].strip())
                    return {
                        "vram_pct": (mem_used / mem_total * 100) if mem_total > 0 else 0,
                        "temp": temp,
                        "gpu_util": gpu_util,
                        "mem_used_mb": mem_used,
                        "mem_total_mb": mem_total,
                    }
        except Exception:
            pass
        return None


class RemoteEmbedder(Embedder):
    """
    Embedder that delegates to an Ollama service.
    Uses the batch /api/embed endpoint for GPU efficiency.
    Auto-tunes batch size based on available VRAM.
    """
    
    def __init__(
        self,
        model_name: str,
        base_url: str = "http://localhost:11434",
        batch_size: int = 32,
        normalize: bool = True,
        max_seq_length: int = 4096,
        timeout: int = 300
    ):
        self.model_name = model_name
        self.base_url = base_url.rstrip('/')
        self._config_batch_size = batch_size  # User/config value (fallback)
        self.batch_size = batch_size
        self.normalize = normalize
        self.max_seq_length = max_seq_length
        self.timeout = timeout
        self._dimension = None
        self._max_batch_per_request = ABSOLUTE_MAX_BATCH  # Will be auto-tuned by load()
        self._gpu_monitor: Optional[GPUHealthMonitor] = None
        
        # Persistent HTTP client with connection pooling
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            limits=httpx.Limits(
                max_connections=16,
                max_keepalive_connections=8,
            ),
        )
        
        logger.info(
            f"RemoteEmbedder Initialized. Model: {model_name}, "
            f"URL: {base_url}, config_batch_size: {batch_size}"
        )

    def load(self):
        """
        'Load' the model, auto-tune batch size, and verify connection.
        """
        logger.info(f"RemoteEmbedder.load() called. Checking connection to {self.base_url}...")
        try:
            # Check if model exists
            response = self._client.get("/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                exists = any(m.get("name").startswith(self.model_name) for m in models)
                
                if exists:
                    logger.info(f"✅ Model '{self.model_name}' found on Ollama server.")
                else:
                    logger.warning(f"⚠️ Model '{self.model_name}' NOT found. Attempting to pull...")
                    self._pull_model()
            else:
                logger.warning(f"Failed to check models: {response.status_code}")
                
            # Warmup / Get Dimension
            self._dimension = len(self.embed_query("warmup"))
            logger.info(f"Remote Model ready. Dimension: {self._dimension}")
            
            # --- AUTO-TUNE BATCH SIZE ---
            self._auto_tune_batch_size()
            
            # --- START GPU HEALTH MONITOR ---
            self._gpu_monitor = GPUHealthMonitor(
                base_batch_size=self._max_batch_per_request,
                interval=30.0
            )
            self._gpu_monitor.start()
            
        except Exception as e:
            logger.error(f"RemoteEmbedder load failed: {e}")
            raise EmbeddingError(f"Failed to connect to Embedding Service: {e}")
        return self

    def _auto_tune_batch_size(self):
        """Dynamically set batch size: formula estimate → empirical sweep."""
        total_vram = _probe_gpu_vram_mb()
        if total_vram is None:
            logger.info(f"[AUTO-TUNE] nvidia-smi unavailable. Using config batch_size={self._config_batch_size}")
            return
        
        # Get model VRAM from Ollama /api/ps
        model_vram_mb = 0.0
        try:
            ps_resp = self._client.get("/api/ps")
            if ps_resp.status_code == 200:
                for m in ps_resp.json().get("models", []):
                    if m.get("name", "").startswith(self.model_name):
                        model_vram_mb = m.get("size_vram", 0) / (1024 * 1024)
                        break
        except Exception:
            pass
        
        if model_vram_mb == 0:
            model_vram_mb = 5000
            logger.info("[AUTO-TUNE] Could not read model VRAM from Ollama, estimating 5GB")
        
        # Step 1: Formula-based estimate
        formula_batch = _compute_optimal_batch(total_vram, model_vram_mb, self.max_seq_length)
        logger.info(
            f"[AUTO-TUNE] Formula estimate: GPU={total_vram:.0f}MB, "
            f"model={model_vram_mb:.0f}MB → batch={formula_batch} "
            f"(config was {self._config_batch_size})"
        )
        
        # Step 2: Empirical sweep — test actual throughput at increasing sizes
        optimal = self._empirical_batch_sweep(formula_batch)
        
        self._max_batch_per_request = optimal
        self.batch_size = optimal
        
        logger.info(
            f"[AUTO-TUNE] Final batch_size={optimal} "
            f"(formula={formula_batch}, config={self._config_batch_size})"
        )

    def _empirical_batch_sweep(self, formula_estimate: int) -> int:
        """
        Test increasing batch sizes to find optimal throughput.
        
        Sends 2 test batches per size with a short dummy text.
        Picks the size with highest texts/sec.
        Stops if a size causes timeout or OOM.
        
        Takes ~10-20 seconds at startup.
        """
        # Test sizes: powers of 2 up to formula estimate, capped at ABSOLUTE_MAX_BATCH
        safe_max = min(formula_estimate, ABSOLUTE_MAX_BATCH)
        
        test_sizes = []
        size = 8
        while size <= safe_max:
            test_sizes.append(size)
            size *= 2
        
        # Always include the formula estimate if safe
        if formula_estimate not in test_sizes and formula_estimate <= safe_max:
            test_sizes.append(formula_estimate)
        test_sizes.sort()
        
        if not test_sizes:
            return min(formula_estimate, ABSOLUTE_MAX_BATCH)
        
        logger.info(f"[BATCH-SWEEP] Testing batch sizes: {test_sizes}")
        
        best_size = test_sizes[0]
        best_rate = 0.0
        dummy_text = "This is a test sentence for batch size calibration. " * 10  # ~80 tokens
        
        for batch_size in test_sizes:
            texts = [dummy_text] * batch_size
            rates = []
            
            for trial in range(2):  # 2 trials per size
                try:
                    t0 = time.perf_counter()
                    self._embed_batch_request(texts)
                    elapsed = time.perf_counter() - t0
                    rate = batch_size / elapsed if elapsed > 0 else 0
                    rates.append(rate)
                except httpx.HTTPStatusError as e:
                    logger.warning(
                        f"[BATCH-SWEEP] batch_size={batch_size} caused HTTP {e.response.status_code}. "
                        f"Model limits reached. Stopping sweep."
                    )
                    return best_size
                except Exception as e:
                    logger.warning(
                        f"[BATCH-SWEEP] batch_size={batch_size} failed: {e}. "
                        f"Stopping sweep."
                    )
                    return best_size
            
            avg_rate = sum(rates) / len(rates)
            logger.info(
                f"[BATCH-SWEEP] size={batch_size}: {avg_rate:.0f} texts/sec "
                f"(trials: {[f'{r:.0f}' for r in rates]})"
            )
            
            if avg_rate > best_rate:
                best_rate = avg_rate
                best_size = batch_size
        
        logger.info(
            f"[BATCH-SWEEP] Optimal: batch_size={best_size} "
            f"({best_rate:.0f} texts/sec)"
        )
        return best_size

    def _pull_model(self):
        """Trigger model pull."""
        logger.info(f"Pulling {self.model_name}...")
        try:
            with httpx.stream("POST", f"{self.base_url}/api/pull", json={"model": self.model_name}, timeout=None) as r:
                for line in r.iter_lines():
                    pass
            logger.info("Pull complete.")
        except Exception as e:
            logger.error(f"Pull failed: {e}")

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            try:
                self._dimension = len(self.embed_query("dimension_check"))
            except:
                return 4096
        return self._dimension

    def _embed_batch_request(self, texts: List[str]) -> List[List[float]]:
        """
        Use Ollama /api/embed batch endpoint (single HTTP request for multiple texts).
        This is the key optimization: GPU processes all texts in one call.
        """
        try:
            response = self._client.post(
                "/api/embed",
                json={
                    "model": self.model_name,
                    "input": texts,
                },
            )
            if response.status_code == 200:
                data = response.json()
                embeddings = data.get("embeddings", [])
                if len(embeddings) != len(texts):
                    raise EmbeddingError(
                        f"Expected {len(texts)} embeddings, got {len(embeddings)}"
                    )
                return embeddings
            else:
                logger.error(f"Ollama /api/embed failed: {response.text[:200]}")
                raise EmbeddingError(f"Ollama error: {response.status_code}")
        except httpx.TimeoutException:
            raise EmbeddingError(f"Ollama timeout after {self.timeout}s for batch of {len(texts)}")
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(f"Batch embed request failed: {e}")

    def _embed_single(self, text: str) -> List[float]:
        """Generate embedding for one text (fallback for single queries)."""
        result = self._embed_batch_request([text])
        return result[0]

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Batch embed using Ollama /api/embed.
        
        Splits into sub-batches of _max_batch_per_request (auto-tuned from VRAM)
        to prevent OOM. Each sub-batch is a single GPU-efficient HTTP request.
        """
        if not texts:
            return []
        
        all_embeddings = []
        total = len(texts)
        
        # Use GPU health monitor's safe batch size if available
        if self._gpu_monitor:
            batch_cap = self._gpu_monitor.safe_batch_size
        else:
            batch_cap = self._max_batch_per_request
        
        for start in range(0, total, batch_cap):
            end = min(start + batch_cap, total)
            batch = texts[start:end]
            
            t0 = time.perf_counter()
            embeddings = self._embed_batch_request(batch)
            elapsed = time.perf_counter() - t0
            
            all_embeddings.extend(embeddings)
            
            rate = len(batch) / elapsed if elapsed > 0 else 0
            logger.info(
                f"[EMBED] Batch {start//batch_cap + 1}: "
                f"{len(batch)} texts in {elapsed:.1f}s ({rate:.0f} texts/s) "
                f"[{end}/{total}]"
            )
                    
        return all_embeddings

    def embed_query(self, query: str) -> List[float]:
        """Embed single query."""
        instruction = "Instruct: Given a research query, retrieve relevant academic papers.\nQuery: "
        return self._embed_single(f"{instruction}{query}")

    def embed_batch(self, texts: List[str], show_progress: bool = True) -> List[List[float]]:
        return self.embed(texts)

    def __del__(self):
        """Clean up HTTP client and GPU monitor."""
        try:
            if self._gpu_monitor:
                self._gpu_monitor.stop()
            self._client.close()
        except Exception:
            pass
