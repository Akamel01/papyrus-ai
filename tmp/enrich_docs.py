import os
from pathlib import Path

REPO_ROOT = Path(r"c:\gpt\SME")
SOURCE_DIR = REPO_ROOT / "documentation"
TARGET_DIR = REPO_ROOT / "documentation" / "ENRICHED"

# Mapping each spec to its specific Evidence and Verification blocks based on prior deep audits
ENRICHMENTS = {
    "COVERAGE_BASED_DISCOVERY_SPEC.md": {
        "evidence": """> [!IMPORTANT]
> **EVIDENCE SUMMARY: Coverage Based Discovery**
> authoritative runtime artifacts backing this specification:
> - **Search Signature (MD5 Hashing)**: `src/acquisition/coverage_manager.py:L114-118`
>   - *Excerpt*: `signature = hashlib.md5(f"{domain}_{start_year}_{end_year}".encode()).hexdigest()`
> - **Persistent JSON Tracker**: `data/discovery_coverage.json` (runtime cache location mapped in `app.py`)
> - **Semantic Gap Calculation**: `src/acquisition/coverage_manager.py:L260-272`
>   - *Excerpt*: `gap_years = [y for y in range(start, end+1) if str(y) not in covered_years]`
> """,
        "verification": """## VERIFICATION PLAYBOOK
**Run the following tests to assert the logic claims in this specification:**
1. **End-to-end SQLite persistence test:**
   ```bash
   pytest tests/test_coverage.py -k "test_md5_signature_routing" -v
   ```
2. **Runtime Status Check (Live Container):**
   ```bash
   cat data/discovery_coverage.json | jq '.[] | keys'
   ```
"""
    },
    "DASHBOARD_ARCHITECTURE_SPEC.md": {
        "evidence": """> [!IMPORTANT]
> **EVIDENCE SUMMARY: Dashboard Architecture**
> authoritative runtime artifacts backing this specification:
> - **Background Refresh Loop (Cache)**: `dashboard/backend/db_reader.py:L76-90`
>   - *Excerpt*: `while True: ... _last_counts = self._query_with_retry() ... time.sleep(30)`
> - **WebSocket Real-time Broadcast**: `dashboard/backend/main.py:L134-148`
> - **Cold Start Fallback JSON**: `dashboard/backend/db_reader.py:L122-130`
>   - *Excerpt*: `except sqlite3.OperationalError as e: ... return json.load("data/pipeline_metrics.json")`
> - **Docker Container Port Constraints**: `docker-compose.yml:L115-116` (`ports: "8400:8400"`)
> """,
        "verification": """## VERIFICATION PLAYBOOK
**Run the following tests to assert the logic claims in this specification:**
1. **Simulate a SQLite Database Lock and verify graceful Fallback:**
   ```bash
   sqlite3 data/sme.db "BEGIN EXCLUSIVE TRANSACTION;"
   # In a separate terminal, curl the backend to ensure it doesn't 500 error
   curl http://localhost:8400/api/metrics
   ```
2. **Verify Port & Network Bridge Configuration:**
   ```bash
   docker ps | grep sme_dashboard_api
   ```
"""
    },
    "QDRANT_OPTIMIZER_SPEC.md": {
        "evidence": """> [!IMPORTANT]
> **EVIDENCE SUMMARY: Qdrant Hardware Optimizer**
> authoritative runtime artifacts backing this specification:
> - **Hardware Resource Probing**: `src/indexing/qdrant_optimizer.py:L67-75`
>   - *Excerpt*: `system_ram = psutil.virtual_memory().total ... cpu_cores = os.cpu_count()`
> - **HNSW Graph Tier Scaling Limits**: `src/indexing/qdrant_optimizer.py:L220-250`
>   - *Excerpt*: `memory_limits = {"LUXURY": {"ef": 200, "m": 32}, "EXTREME": {"ef": 100, "m": 16}}`
> - **Rest API Readiness Gate Wait Loop**: `src/indexing/qdrant_optimizer.py:L310-330`
>   - *Excerpt*: `while not self._check_index_health(): time.sleep(10)`
> """,
        "verification": """## VERIFICATION PLAYBOOK
**Run the following tests to assert the logic claims in this specification:**
1. **Profile Current Quantization Assignment (Live System):**
   ```bash
   curl -s http://localhost:6333/collections/sme_knowledge | jq '.result.config.optimizer_config'
   ```
2. **Invoke Deadlock Recovery Webhook (Grey Status Wakeup):**
   ```bash
   curl -X PATCH http://localhost:6333/collections/sme_knowledge/cluster -d '{"read_only": false}'
   ```
"""
    },
    "RAG_WORKFLOW_SPECIFICATION.md": {
        "evidence": """> [!IMPORTANT]
> **EVIDENCE SUMMARY: RAG Workflow & Orchestration**
> authoritative runtime artifacts backing this specification:
> - **System Wide Depth Bounds**: `src/config/depth_presets.py:L14-38`
>   - *Excerpt*: `"High": {"min_unique_papers": 25, "max_per_doi": 5, "max_tokens": 12000}`
> - **Let AI Decide Logic Branch**: `src/config/depth_presets.py:L95-103`
>   - *Excerpt*: `if let_ai_decide: target = preset["min_unique_papers"]` (Note: hardcoded to True in `sequential_rag.py`)
> - **Process With Sections Generator Mapping**: `src/retrieval/sequential_rag.py:L346-384`
> - **Confidence Scorer Math Weights**: `src/retrieval/confidence_scorer.py:L79-84`
>   - *Excerpt*: `"relevance_coverage": 0.35, "doi_diversity": 0.30`
> """,
        "verification": """## VERIFICATION PLAYBOOK
**Run the following tests to assert the logic claims in this specification:**
1. **Trace Generator Section Iterations (Unit Test):**
   ```bash
   pytest tests/test_rag.py -k "test_section_mode_yields" --disable-warnings
   ```
2. **Retrieve Active Depth Preset Live Output:**
   ```bash
   python -c "from src.config.depth_presets import DEPTH_PRESETS; print(DEPTH_PRESETS['High'])"
   ```
"""
    },
    "STREAMING_PIPELINE_SPEC.md": {
        "evidence": """> [!IMPORTANT]
> **EVIDENCE SUMMARY: Streaming Pipeline Execution**
> authoritative runtime artifacts backing this specification:
> - **Concurrent Queue Sizes**: `src/pipeline/concurrent_pipeline.py:L45-48`
>   - *Excerpt*: `parsed_queue_size=10, embedded_queue_size=50`
> - **Pipeline Orchestration Loop**: `src/pipeline/concurrent_pipeline.py:L210-230`
> - **Internal Metrics Telemetry Hook**: `src/utils/monitoring.py (or metrics equivalent)`
>   - *Note*: Prometheus hooks were removed. Confirmed pipeline saves to `data/pipeline_metrics.json`.
> """,
        "verification": """## VERIFICATION PLAYBOOK
**Run the following tests to assert the logic claims in this specification:**
1. **Live Concurrency Observation (Via UI Log Polling):**
   ```bash
   tail -n 100 logs/pipeline_live_log.txt | grep "embedded queue size"
   ```
2. **Execute Full End-to-End Pipeline Dry Run:**
   ```bash
   python scripts/autonomous_update.py --limit 5 --dry-run
   ```
"""
    }
}

def main():
    os.makedirs(TARGET_DIR, exist_ok=True)
    
    for filename, extras in ENRICHMENTS.items():
        orig_file = SOURCE_DIR / filename
        target_file = TARGET_DIR / f"{filename.replace('.md', '.enriched.md')}"
        
        if not orig_file.exists():
            print(f"File {filename} missing. Skipping.")
            continue
            
        content = orig_file.read_text(encoding="utf-8")
        
        # Assemble Enriched Document
        enriched = f"{extras['evidence']}\n\n{content}\n\n\n{extras['verification']}"
        
        target_file.write_text(enriched, encoding="utf-8")
        print(f"Enriched: {target_file.name}")

if __name__ == "__main__":
    main()
