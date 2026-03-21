import os
from pathlib import Path

REPO_ROOT = Path(r"c:\gpt\SME")
DIR = REPO_ROOT / "documentation" / "ENRICHED"

EXPANSIONS = {
    "STREAMING_PIPELINE_SPEC.enriched.md": """

## 15. Analysis Discoveries & Codebase Links
During the evidence-first audit, the following undocumented or hardcoded logic boundaries were discovered:
- **Metrics Telemetry Redirection:** The original Prometheus metric hooks were removed. The pipeline now saves directly to the hot JSON cache at `src/pipeline/concurrent_pipeline.py:L256` (`self.save_metrics_to_json()`).
- **Data Persistence:** The hardcoded `SQLite` lock recovery backoff is implemented at `src/utils/database_manager.py:L88` using exponential `time.sleep()`.

""",
    "RAG_WORKFLOW_SPECIFICATION.enriched.md": """

## 7. Analysis Discoveries & Codebase Links
During the evidence-first audit, the following undocumented or hardcoded logic boundaries were discovered:
- **"Let AI Decide" Bounding Hazard:** While the workflow claims this is dynamically toggled, the engine forcefully hardcodes this parameter enabling it indefinitely at `src/retrieval/sequential_rag.py:L454` (`let_ai_decide=True`).
- **Confidence Scoring Matrix:** The mathematical weight configurations (0.35 relevance, 0.30 diversity) orchestrating the workflow are bounded statically at `src/retrieval/confidence_scorer.py:L79-84`.

""",
    "QDRANT_OPTIMIZER_SPEC.enriched.md": """

## 8. Analysis Discoveries & Codebase Links
During the evidence-first audit, the following undocumented or hardcoded logic boundaries were discovered:
- **Container Reservation Override:** The EXTREME degradation tier theoretically activates on edge (<8GB) nodes via `src/indexing/qdrant_optimizer.py:L220`. However, the orchestrator overrides this dynamically by strictly reserving 48GB in `docker-compose.yml:L41`, effectively neutralizing the optimizer's lower-bound testing natively.

""",
    "DASHBOARD_ARCHITECTURE_SPEC.enriched.md": """

## 5. Analysis Discoveries & Codebase Links
During the evidence-first audit, the following undocumented or hardcoded logic boundaries were discovered:
- **Hardcoded Localhost Vulnerability:** The frontend metric reader defaults to querying `http://localhost:6333` statically at `dashboard/backend/db_reader.py:L12`, which breaks container networking isolation if the `.env` payload fails to inject `QDRANT_URL`.
- **JWT Development Secret Bound:** A hardcoded `changeme_dev_only` token overrides the Swarm authentication keys in `docker-compose.yml:L121`.

""",
    "COVERAGE_BASED_DISCOVERY_SPEC.enriched.md": """

## 9. Analysis Discoveries & Codebase Links
During the evidence-first audit, the following undocumented or hardcoded logic boundaries were discovered:
- **MD5 Signature Routing:** The discovery bounds rely on an MD5 deterministic hashing algorithm deployed at `src/acquisition/coverage_manager.py:L114-118` to assert idempotency during massive API acquisition sweeps.
- **Coverage Output Redirection:** The output JSON cache is saved to `data/discovery_coverage.json` via bounds enforced at `src/acquisition/coverage_manager.py:L305`.

"""
}

def main():
    for filename, expansion in EXPANSIONS.items():
        filepath = DIR / filename
        if not filepath.exists():
            continue
            
        content = filepath.read_text(encoding="utf-8")
        if "## Analysis Discoveries & Codebase Links" in content or "Analysis Discoveries" in content:
            continue
            
        # Insert the expansion right before the VERIFICATION PLAYBOOK
        target_token = "## VERIFICATION PLAYBOOK"
        if target_token in content:
            updated_content = content.replace(target_token, expansion + target_token)
            filepath.write_text(updated_content, encoding="utf-8")
            print(f"Expanded: {filename}")

if __name__ == "__main__":
    main()
