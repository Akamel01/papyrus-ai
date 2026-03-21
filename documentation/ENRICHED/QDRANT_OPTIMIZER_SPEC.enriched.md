> [!IMPORTANT]
> **EVIDENCE SUMMARY: Qdrant Hardware Optimizer**
> authoritative runtime artifacts backing this specification:
> - **Hardware Resource Probing**: `src/indexing/qdrant_optimizer.py:L67-75`
>   - *Excerpt*: `system_ram = psutil.virtual_memory().total ... cpu_cores = os.cpu_count()`
> - **HNSW Graph Tier Scaling Limits**: `src/indexing/qdrant_optimizer.py:L220-250`
>   - *Excerpt*: `memory_limits = {"LUXURY": {"ef": 200, "m": 32}, "EXTREME": {"ef": 100, "m": 16}}`
> - **Rest API Readiness Gate Wait Loop**: `src/indexing/qdrant_optimizer.py:L310-330`
>   - *Excerpt*: `while not self._check_index_health(): time.sleep(10)`
> 

# Qdrant Auto-Tuning Optimizer Specification

> **System:** SME Research Assistant
> **Component:** `src/indexing/qdrant_optimizer.py`
> **Purpose:** Ensures the vector database is hardware-aware, highly performant, and correctly configured before serving traffic.

## 1. What It Entails

The Qdrant Optimizer is an autonomous startup diagnostic and auto-tuning module. It dynamically calculates optimal memory, graph connectivity, and quantization parameters for the vector database based on the host system's hardware capabilities.

### 1.1 Hardware Probing
Before the database client initializes, the optimizer probes the host:
- **System RAM (`psutil`)**: Available and total memory.
- **CPU Cores (`os.cpu_count`)**: Determines parallel segment counts.
- **GPU VRAM (`nvidia-smi`)**: Budgets memory for the embedding and reranking models to ensure sufficient headroom.

### 1.2 Memory Footprint Forecasting
The optimizer calculates the RAM requirements based on the estimated vector count and embedding dimensionality (typically 4096).
It forecasts three distinct footprints:
1. **Raw Data**: 32-bit floats.
2. **Quantized Data**: 8-bit integers (if scalar quantization is enabled).
3. **HNSW Graph**: Bidirectional links based on the `m` parameter.

### 1.3 Adaptive Tiers
Based on the forecast vs. actual available RAM, the optimizer assigns an operational tier:
- **TIER 1 (LUXURY)**: Raw vectors and graph fit comfortably in < 50% of available RAM. No quantization needed. Highest precision.
- **TIER 2 (BALANCED)**: Quantized vectors and graph fit in < 70% of RAM. Int8 Scalar Quantization is enabled, keeping original vectors on disk.
- **TIER 3 (CONSTRAINED)**: Quantized vectors and graph fit in < 90% of RAM. Reduces graph connectivity (`m`) and increases quantization oversampling to save RAM at the cost of slight latency.
- **TIER 4 (EXTREME)**: System is starving for RAM. Minimum parameters applied. System warns of DEGRADED performance.

### 1.4 Auto-Tuned Parameters
Depending on the assigned Tier, the optimizer tunes:
- **`m`**: HNSW connectivity (8 to 64).
- **`ef_construct`**: Index build effort (`m * 4`).
- **`ef_search`**: Search scope effort, capped by memory tier.
- **`quantization_type`**: Enables `int8` for non-luxury tiers.
- **`oversampling`**: Quantization correction factor (1.0 to 3.0 based on tier constraint).
- **`always_ram`**: Forces quantized vectors into RAM for fast scanning.

---

## 2. What Triggers It

The optimizer runs automatically during system startup via the data loader pipeline (`src/pipeline/loader.py`). 

### 2.1 The Connection Gate
Before probing, the optimizer executes a **MANDATORY Connection Gate** that blocks execution until Qdrant is fully reachable via its `/readyz` REST endpoint. This prevents downstream "Connection Refused" cascade failures.

### 2.2 The Index Readiness Gate
This is the most critical trigger logic protecting system latency.
1. The optimizer compares the actual collection configuration against the auto-generated optimal configuration.
2. It polls the database to check the ratio of `indexed_vectors_count` to total points.
3. **MANDATORY BLOCK**: The system will NOT proceed until the index is `≥ 95%` complete. 
    - *Why?* An incomplete HNSW graph causes Qdrant to fall back to a brute-force exact scatter-gather search. This inflates query latency from `<50ms` to `500ms–2s+` per query.

### 2.3 The "Grey" Status Wake-Up
If Qdrant crashes or is forcefully restarted during graph building, the internal optimizer status can become stuck in `grey` (paused), deadlocking the index creation. The Qdrant Optimizer detects this status and automatically fires a REST API `PATCH` payload to re-assert the `max_segment_size`, violently waking the Qdrant native optimizer back to `yellow` (building) or `green` (ready).

---

## 3. How to Enhance Performance & Avoid Latency

To ensure the system runs at peak performance and avoids wasting resources, observe the following:

### 3.1 Hardware Allocation (Keep in LUXURY/BALANCED)
To avoid quantization precision loss and latency hikes, ensure the host machine has enough RAM. The formula for the required "safe" RAM is:
`Target RAM = (Quantized Footprint + HNSW Graph Footprint) + 2.0GB Buffer`
If the host falls into the `CONSTRAINED` or `EXTREME` tier, you must either:
- Add physical RAM / increase Docker memory limits.
- Reduce the target vector count (limit the size of the ingested database).

### 3.2 Guarantee Index Readiness
Never use the `--skip-index-gate` flag in a production environment. Forcing the system to serve queries while the HNSW graph is still building guarantees brute-force search latency. Always wait for the gate to clear.

### 3.3 VRAM Headroom 
The optimizer calculates a GPU VRAM budget. If the VRAM headroom falls below `1.0 GB`, the system is at extreme risk of an Out-Of-Memory (OOM) crash during high-load cross-encoder reranking. 
- *Enhancement:* If VRAM is tight, disable GPU reranking or use remote embedding endpoints instead of local 4-bit loading.

### 3.4 Segment Size Tuning
The optimizer sets `segment_count` equal to the number of CPU cores (max 8) and caps `max_segment_size` at `500,000`. This prevents Qdrant's native optimizer from wasting CPU cycles constantly merging small segments during heavy streaming ingestion.





## 8. Analysis Discoveries & Codebase Links
During the evidence-first audit, the following undocumented or hardcoded logic boundaries were discovered:
- **Container Reservation Override:** The EXTREME degradation tier theoretically activates on edge (<8GB) nodes via `src/indexing/qdrant_optimizer.py:L220`. However, the orchestrator overrides this dynamically by strictly reserving 48GB in `docker-compose.yml:L41`, effectively neutralizing the optimizer's lower-bound testing natively.

## VERIFICATION PLAYBOOK
**Run the following tests to assert the logic claims in this specification:**
1. **Profile Current Quantization Assignment (Live System):**
   ```bash
   curl -s http://localhost:6333/collections/sme_knowledge | jq '.result.config.optimizer_config'
   ```
2. **Invoke Deadlock Recovery Webhook (Grey Status Wakeup):**
   ```bash
   curl -X PATCH http://localhost:6333/collections/sme_knowledge/cluster -d '{"read_only": false}'
   ```
