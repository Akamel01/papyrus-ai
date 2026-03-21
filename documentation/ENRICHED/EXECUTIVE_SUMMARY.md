# Phase 1 Discovery: Runtime-Related Files

Target: List all files in `documentation/` and top-level runtime-related files.

| Path | Purpose | Verifiable from Repo? |
|---|---|---|
| `documentation/COVERAGE_BASED_DISCOVERY_SPEC.md` | Documents semantic gap tracking logic for avoiding API quota bloat. | Pending Phase 2/3 (Static/Runtime Audit) |
| `documentation/DASHBOARD_ARCHITECTURE_SPEC.md` | Documents React/FastAPI realtime monitoring flow. | Pending Phase 2/3 |
| `documentation/QDRANT_OPTIMIZER_SPEC.md` | Documents HNSW/Memory scaling rules based on OS RAM. | Pending Phase 2/3 |
| `documentation/RAG_WORKFLOW_SPECIFICATION.md` | Documents the core extraction->drafting cascade logic. | Pending Phase 2/3 |
| `documentation/STREAMING_PIPELINE_SPEC.md` | Documents concurrent queues for ingestion. | Pending Phase 2/3 |
| `Dockerfile` | Defines container runtime environment. | Yes (Static parse in Phase 2) |
| `docker-compose.yml` | Orchestrates Qdrant/Ollama/App services. | Yes (Static parse in Phase 2) |
| `start.bat` | Bootstraps the pipeline on Windows hosts. | Yes (Static parse in Phase 2) |
| `scripts/entrypoint.sh` | Bootstraps the pipeline dynamically inside Docker. | Yes (Static parse in Phase 2) |
| `config/config.yaml` | Core global app limits/bounds | Yes (Static Mapping in Phase 2) |
| `config/acquisition_config.yaml` | API Keys / Ingestion targets | Yes (Static Mapping in Phase 2) |
| `config/docker_config.yaml` | Container limits and network mappings | Yes (Static Mapping in Phase 2) |
| `config/prompts.yaml` | LLM text prompt library | Yes (Static Mapping in Phase 2) |
| `scripts/autonomous_update.py` | Primary background ingestion orchestrator | Yes (Symbol Mapping in Phase 2) |
| `scripts/pipeline_api.py` | Core dashboard backend API server | Yes (Symbol Mapping in Phase 2) |
| `scripts/fast_ingest.py` | Rapid ingestion testing script | Yes (Symbol Mapping in Phase 2) |
| `scripts/full_ingest.py` | Deep ingestion testing script | Yes (Symbol Mapping in Phase 2) |
| `scripts/build_bm25_tantivy.py` | Standalone CLI for disk-backed BM25 indices | Yes (Symbol Mapping in Phase 2) |

## Next Steps
Phase 2 (`Static Analysis & Symbol Mapping`) will systematically parse all `src/` and `scripts/` logic inside the repository. It will output `SYSTEM_SYMBOLS_MAP.json` linking all 100% verifiable code references back to the documentation. We will then analyze the config files to flag hardcoded strings into `HARDCODED_LITERALS.csv`.
