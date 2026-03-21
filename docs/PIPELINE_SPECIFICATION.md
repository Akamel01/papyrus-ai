# Autonomous Embedding Update Pipeline - Technical Specification

## Overview

The Autonomous Embedding Update Pipeline is a fully automated system for discovering, downloading, parsing, and embedding academic papers into a vector database (Qdrant). It features **graceful stop-and-go capability** - the pipeline can be interrupted at any point and will automatically resume from where it left off.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DOCKER CONTAINER (sme_app)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   entrypoint.sh                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ 1. Check pipeline_state.json                                        │   │
│   │ 2. If IN_PROGRESS → Resume in background                            │   │
│   │ 3. Start Streamlit UI                                               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                               │                                             │
│              ┌────────────────┴────────────────┐                            │
│              ▼                                 ▼                            │
│   ┌──────────────────────┐         ┌──────────────────────┐                 │
│   │ autonomous_update.py │         │     Streamlit UI     │                 │
│   │   (Background)       │         │    (Foreground)      │                 │
│   └──────────────────────┘         └──────────────────────┘                 │
│              │                                                              │
│   ┌──────────┴──────────────────────────────────────────────────────────┐   │
│   │                     PIPELINE STAGES                                  │   │
│   ├──────────────────────────────────────────────────────────────────────┤   │
│   │  STAGE 1: DISCOVERY                                                  │   │
│   │  ├─ Query OpenAlex, Semantic Scholar, arXiv APIs                     │   │
│   │  ├─ Deduplicate by DOI                                               │   │
│   │  └─ Cache to discovery_cache.json                                    │   │
│   ├──────────────────────────────────────────────────────────────────────┤   │
│   │  STAGE 2: DOWNLOAD                                                   │   │
│   │  ├─ Check skip_existing (DataBase/Papers/*.pdf)                      │   │
│   │  ├─ Download PDFs with retry + Unpaywall fallback                    │   │
│   │  └─ Save to DataBase/Papers/{doi}.pdf                                │   │
│   ├──────────────────────────────────────────────────────────────────────┤   │
│   │  STAGE 3-5: PARSE → EMBED → STORE                                    │   │
│   │  ├─ Parse PDFs (PyMuPDF)                                             │   │
│   │  ├─ Chunk (800 tokens, 150 overlap)                                  │   │
│   │  ├─ Embed (Qwen3-Embedding-8B, 4-bit quantized, GPU)                 │   │
│   │  └─ Upsert to Qdrant                                                 │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Graceful Stop-And-Go System

### State Machine

The pipeline maintains its state in `data/pipeline_state.json`:

```json
{
  "run_id": "abc12345",
  "status": "IN_PROGRESS",
  "current_phase": "EMBEDDING",
  "phases": {
    "DISCOVERY": {"status": "COMPLETED", "items_total": 150},
    "DOWNLOAD": {"status": "COMPLETED", "items_processed": 140, "items_failed": 10},
    "EMBEDDING": {"status": "IN_PROGRESS", "items_processed": 50, "items_total": 140}
  },
  "graceful_shutdown": false,
  "updated_at": "2026-01-31T19:15:00Z"
}
```

### Signal Handling

| Signal | Action |
|--------|--------|
| SIGTERM | Save state, set `graceful_shutdown: true`, exit cleanly |
| SIGINT | Same as SIGTERM |
| Process crash | State already saved at last checkpoint |

### Resume Logic

| Saved Phase | Resume Action |
|-------------|---------------|
| DISCOVERY (incomplete) | Restart discovery (fast, stateless) |
| DOWNLOAD (incomplete) | Load discovery cache, `skip_existing` handles resumption |
| EMBEDDING (incomplete) | `embedding_progress.txt` tracks processed PDFs |
| COMPLETED | Do nothing |

---

## File Structure

```
C:\gpt\SME\
├── config/
│   ├── acquisition_config.yaml    # Pipeline configuration
│   └── docker_config.yaml         # Docker/embedding configuration
├── data/
│   ├── pipeline_state.json        # [NEW] Phase-level state
│   ├── discovery_cache.json       # Cached discovered papers
│   ├── embedding_progress.txt     # Processed PDF paths
│   ├── embedding_failures.txt     # Failed items
│   └── autonomous_update.log      # Pipeline logs
├── DataBase/Papers/               # Downloaded PDFs (52K+ papers)
├── scripts/
│   ├── autonomous_update.py       # Main pipeline script
│   └── entrypoint.sh              # [NEW] Docker entrypoint
├── src/pipeline/
│   ├── __init__.py
│   └── state_manager.py           # [NEW] PipelineState class
└── Dockerfile                     # Modified for auto-resume
```

---

## Configuration

### Key Settings (`config/acquisition_config.yaml`)

```yaml
acquisition:
  keywords: ["emergency medicine", "trauma surgery", ...]
  
  apis:
    openalex:
      enabled: true
      requests_per_minute: 100
    semantic_scholar:
      enabled: true
      api_key: null
    arxiv:
      enabled: true
  
  download:
    skip_existing: true      # ← Prevents re-downloading 52K papers
    retry_failed: true
    max_retries: 5
    timeout_seconds: 120

  state:
    progress_file: "data/embedding_progress.txt"
    failed_downloads_file: "data/failed_downloads.jsonl"
    discovery_cache_file: "data/discovery_cache.json"
```

### Embedding Settings (`config/docker_config.yaml`)

```yaml
embedding:
  model_name: "Qwen/Qwen3-Embedding-8B"
  device: "cuda"
  batch_size: 4
  dimension: 4096
  quantization: "4bit"
```

---

## Usage

### Run Full Pipeline
```bash
python scripts/autonomous_update.py
```

### Resume Interrupted Run
```bash
python scripts/autonomous_update.py --resume
```

### Run Specific Stages
```bash
python scripts/autonomous_update.py --discover-only
python scripts/autonomous_update.py --download-only
python scripts/autonomous_update.py --embed-only
```

### Test Mode (10 papers)
```bash
python scripts/autonomous_update.py --test
```

---

## Docker Integration

The container automatically resumes incomplete runs on startup via `entrypoint.sh`:

1. Check `data/pipeline_state.json`
2. If `status: "IN_PROGRESS"` → Resume in background
3. Start Streamlit UI as main process

### Rebuild After Changes
```bash
docker-compose build app
docker-compose up -d
```
