# SME Research Assistant - Architecture Documentation

**Version:** 1.0
**Last Updated:** March 2026

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Service Architecture](#service-architecture)
3. [Directory Structure](#directory-structure)
4. [Core Components](#core-components)
5. [Database Architecture](#database-architecture)
6. [Self-Healing Architecture](#self-healing-architecture)
7. [Network Topology](#network-topology)
8. [Technology Stack](#technology-stack)

---

## System Overview

The SME Research Assistant is a multi-user RAG (Retrieval-Augmented Generation) system designed for academic literature research. It combines semantic search, keyword search (BM25), and LLM-powered generation to help researchers explore and synthesize academic papers.

### High-Level Architecture

```
                           INTERNET
                              │
                              ▼
                    ┌─────────────────┐
                    │ Cloudflare      │
                    │ Tunnel (HTTPS)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Caddy (Reverse  │
                    │ Proxy) :80      │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ Auth Service  │   │ Streamlit App │   │ Dashboard     │
│ :8000         │   │ :8501         │   │ UI: :3000     │
└───────────────┘   └───────┬───────┘   │ API: :8400    │
                            │           └───────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ Qdrant        │   │ Ollama        │   │ Redis         │
│ Vector DB     │   │ (Embeddings)  │   │ (Cache)       │
│ :6333         │   │ :11434        │   │ :6379         │
└───────────────┘   └───────────────┘   └───────────────┘
```

---

## Service Architecture

### Docker Services (docker-compose.yml)

| Service | Container Name | Port(s) | Purpose |
|---------|----------------|---------|---------|
| **init-validator** | sme_init_validator | - | Self-healing mount validation |
| **caddy** | sme_caddy | 8080:80 | Reverse proxy, request routing |
| **app** | sme_app | 8501, 8502 | Streamlit chat interface |
| **auth** | sme_auth | 8000 | User authentication, JWT tokens |
| **dashboard-ui** | sme_dashboard_ui | 3000 | React dashboard frontend |
| **dashboard-backend** | sme_dashboard_api | 8400 | FastAPI dashboard API |
| **qdrant** | sme_qdrant | 6333, 6334 | Vector database |
| **ollama** | sme_ollama | 11434 | Embedding model, LLM serving |
| **redis** | sme_redis | 6379 | Query/result caching |
| **cloudflared** | sme_tunnel | - | HTTPS tunnel for remote access |
| **deploy-hook** | sme_deploy_hook | 9000 | Webhook-based auto-deployment |
| **gpu-exporter** | sme_gpu_exporter | - | GPU metrics collection |

### Self-Healing Mount Validator

The `init-validator` service automatically detects and repairs corrupted Docker bind mounts before dependent services start.

**Problem Solved:** Docker can create directories instead of files when bind mount sources don't exist, causing "not a directory" errors.

**How It Works:**
```
┌─────────────────────────────────────────────────────────────┐
│                   SELF-HEALING FLOW                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  docker-compose up                                           │
│         │                                                    │
│         ▼                                                    │
│  init-validator starts                                       │
│         │                                                    │
│         ▼                                                    │
│  Check: Is Caddyfile a directory?                           │
│         │                                                    │
│    ┌────┴────┐                                              │
│    │ YES     │ NO                                           │
│    ▼         ▼                                              │
│  rm -rf    Continue                                         │
│  cp from   checking...                                      │
│  template                                                   │
│         │                                                    │
│         ▼                                                    │
│  Check: Is cloudflared-config.yml a directory?              │
│         │                                                    │
│    ┌────┴────┐                                              │
│    │ YES     │ NO                                           │
│    ▼         ▼                                              │
│  rm -rf    Continue                                         │
│  cp from   checking...                                      │
│  template                                                   │
│         │                                                    │
│         ▼                                                    │
│  Check: cloudflared-credentials.json (sensitive)            │
│         │                                                    │
│    ┌────┴────┐                                              │
│    │ CORRUPT │ OK                                           │
│    ▼         ▼                                              │
│  EXIT 1   EXIT 0 (success)                                  │
│  (manual  └──► caddy, cloudflared can start                │
│   fix)                                                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Protected Files:**
| File | Auto-Repair | Notes |
|------|-------------|-------|
| `services/caddy/Caddyfile` | Yes | Restored from `.templates/Caddyfile` |
| `config/cloudflared-config.yml` | Yes | Restored from `.templates/cloudflared-config.yml` |
| `config/cloudflared-credentials.json` | No | Sensitive - requires manual restoration |

**Templates Directory:** `.templates/` contains backup copies of non-sensitive config files. Templates are auto-synced via git pre-commit hook when config files are committed.

### Service Dependencies

```
init-validator ──► caddy ──┬──► auth
                           │
cloudflared ──┬──► caddy ──┼──► app ──┬──► qdrant
              │            ├──► app ──┬──► qdrant
              │            │          ├──► ollama
              │            │          └──► redis
              │            └──► dashboard-backend ──► qdrant
              │
              └──► deploy-hook ──► docker.sock (for compose commands)
```

### CI/CD Flow

```
GitHub Actions ──► Build Images ──► Push to GHCR
                                        │
                                        ▼
                        workflow_run webhook triggered
                                        │
                                        ▼
cloudflared ──► deploy-hook:9000 ──► docker compose pull && up
```

---

## Directory Structure

```
SME/
├── app/                          # Streamlit chat application
│   ├── main.py                   # Main Streamlit entry point
│   ├── components/               # UI components
│   │   ├── chat.py              # Chat interface components
│   │   ├── sidebar.py           # Sidebar controls
│   │   ├── sidebar_config.py    # Sidebar configuration dataclass
│   │   ├── quick_upload.py      # Session-only document uploads
│   │   ├── rag_wrapper.py       # RAG pipeline wrappers
│   │   └── auth_ui.py           # Login/register components
│   └── pages/                    # Streamlit pages
│       └── settings.py          # User settings page
│
├── config/                       # Configuration files
│   ├── config.yaml              # Main system configuration
│   ├── acquisition_config.yaml  # Paper discovery settings
│   └── depth_presets.yaml       # Research depth presets
│
├── docker/                       # Docker build assets
│   └── Dockerfile.base          # Pre-baked base image (CUDA + PyTorch)
│
├── data/                         # Runtime data (gitignored)
│   ├── auth.db                  # User authentication database
│   ├── sme.db                   # Paper metadata database
│   ├── chat_history.db          # Chat history
│   ├── bm25_index_tantivy/      # BM25 keyword index
│   ├── user_documents/          # User-uploaded documents (per-user subdirs)
│   └── pipeline_state.json      # Pipeline progress
│
├── DataBase/                     # Paper storage
│   ├── Papers/                  # Legacy papers (all users)
│   └── UpdatedPapers/           # New papers per user
│
├── documentation/                # This documentation folder
│
├── .templates/                   # Config file templates (for self-healing)
│   ├── Caddyfile                # Caddy reverse proxy template
│   └── cloudflared-config.yml   # Cloudflare tunnel config template
│
├── scripts/                      # Utility scripts
│   ├── run_pipeline.py          # Full acquisition pipeline
│   ├── ingest_papers.py         # Manual PDF import
│   ├── rebuild_bm25.py          # BM25 index rebuild
│   ├── migrate_db.py            # Database migrations
│   ├── install-hooks.sh         # Install git pre-commit hooks
│   ├── validate-mounts.sh       # Pre-flight mount validation
│   └── fix-mounts.sh            # Manual mount recovery script
│
├── services/                     # Docker service configs
│   ├── auth/                    # Auth service
│   │   ├── main.py             # FastAPI auth endpoints
│   │   ├── models.py           # SQLAlchemy models
│   │   ├── crypto.py           # Fernet encryption
│   │   └── Dockerfile
│   ├── caddy/
│   │   └── Caddyfile           # Reverse proxy config
│   ├── deploy-hook/             # Auto-deploy webhook
│   │   ├── main.py             # FastAPI webhook handler
│   │   ├── Dockerfile          # Container with Docker CLI
│   │   └── requirements.txt
│   ├── dashboard-backend/
│   │   ├── main.py             # Dashboard API
│   │   └── routes/
│   │       ├── documents_routes.py  # User document management API
│   │       ├── config_routes.py
│   │       ├── run_routes.py
│   │       └── ws_routes.py
│   └── dashboard-ui/
│       └── src/
│           └── pages/
│               ├── MyDocuments.tsx  # User document management UI
│               ├── Dashboard.tsx
│               ├── RunControls.tsx
│               └── ConfigEditor.tsx
│
├── src/                          # Core application code
│   ├── acquisition/             # Paper discovery & download
│   │   ├── discovery.py        # API searches
│   │   ├── downloader.py       # PDF download
│   │   └── apis/               # API clients
│   │       ├── openalex.py
│   │       ├── semantic_scholar.py
│   │       └── unpaywall.py
│   │
│   ├── indexing/                # Document indexing
│   │   ├── indexer.py          # Main indexing pipeline
│   │   ├── bm25_tantivy.py     # Tantivy BM25 index
│   │   ├── bm25_index.py       # Standard BM25 index
│   │   └── chunker.py          # Document chunking
│   │
│   ├── pipeline/                # Concurrent processing pipeline
│   │   ├── concurrent_pipeline.py  # Main pipeline orchestrator
│   │   └── bm25_worker.py      # Background BM25 indexing worker
│   │
│   ├── ingestion/               # PDF processing
│   │   ├── pdf_parser.py       # PDF text extraction
│   │   └── quality_scorer.py   # Parse quality scoring
│   │
│   ├── retrieval/               # Search & retrieval
│   │   ├── hybrid_search.py    # BM25 + semantic fusion
│   │   ├── hyde.py             # Hypothetical document embeddings
│   │   ├── vector_store.py     # Qdrant operations
│   │   ├── reranker.py         # Cross-encoder reranking
│   │   └── sequential/         # Multi-round RAG
│   │       ├── search.py       # Sequential search
│   │       └── processor.py    # Response generation
│   │
│   ├── generation/              # LLM generation
│   │   ├── llm.py              # LLM client wrapper
│   │   ├── prompts.py          # Prompt templates
│   │   └── citation.py         # Citation formatting
│   │
│   ├── embedding/               # Vector embeddings
│   │   └── embedder.py         # Ollama embedding client
│   │
│   └── storage/                 # Database operations
│       ├── paper_db.py         # Paper metadata CRUD
│       └── cache.py            # Redis caching
│
├── docker-compose.yml            # Service orchestration
├── docker-compose.dev.yml        # Development overrides (bind mounts)
├── Dockerfile                    # Main app container
├── .env.example                  # Environment template
├── requirements.txt              # Python dependencies
└── USER_GUIDE.md                 # End-user documentation
```

---

## Core Components

### 1. Authentication System (`services/auth/`)

**Purpose:** Multi-user authentication with encrypted API key storage

**Key Classes:**
- `User` - SQLAlchemy model for user accounts
- `UserAPIKey` - Encrypted API key storage
- `RateLimiter` - Request rate limiting and login lockout

**Endpoints:**
- `POST /api/auth/register` - Create new account
- `POST /api/auth/login` - Authenticate and get JWT
- `POST /api/auth/refresh` - Refresh access token
- `GET /api/auth/me` - Get current user info
- `PUT /api/auth/me/keys` - Store encrypted API keys

### 2. RAG Pipeline (`src/retrieval/`)

**Purpose:** Hybrid search combining semantic and keyword retrieval

**Pipeline Flow:**
```
Query → HyDE Generation → Embedding → Vector Search
                                           │
                                           ▼
                                     BM25 Search → Fusion → Rerank → Top-K Results
```

**Key Classes:**
- `HybridSearcher` - Combines BM25 + semantic search
- `HyDESearch` - Generates hypothetical documents for better retrieval
- `SequentialSearchOrchestrator` - Multi-round reasoning
- `CrossEncoderReranker` - BGE reranker for final scoring

### 2b. Two-Stage Fact Extraction (`src/academic_v2/`)

**Purpose:** Evidence-First generation with smart fact extraction

**Architecture:**
```
CONFIG: max_facts (depth-aware: 40/80/150)
           │
           ▼
    DERIVE: max_chunks = max_facts / density + buffer
           │
           ▼
    DERIVE: top_k_rerank = max_chunks * 1.25
           │
           ▼
┌──────────────────────────────────────────────────────┐
│              TWO-STAGE LIBRARIAN                      │
├──────────────────────────────────────────────────────┤
│  Stage 1: Sample 8 chunks → estimate density          │
│           (e.g., 24 facts / 8 chunks = 3.0)          │
│                         │                             │
│                         ▼                             │
│  Stage 2: Process remaining chunks                    │
│           EARLY STOP when facts >= max_facts          │
│                         │                             │
│                         ▼                             │
│  Output: Exactly max_facts (deduplicated)             │
└──────────────────────────────────────────────────────┘
           │
           ▼
    Architect (no internal cap needed)
           │
           ▼
    Drafter generates section
```

**Key Components:**
- `ExtractionParams` - Derived parameters from config + depth
- `Librarian.extract_facts_with_early_stop()` - Two-stage extraction
- `AcademicEngine.generate_section_v2()` - Uses extraction params

**Benefits:**
- 30-50% reduction in LLM calls (early stopping)
- Single config parameter (`max_facts`) controls entire pipeline
- Depth-aware: Low=40, Medium=80, High=150 facts
- Section mode: Per-section targets (25/40/60 facts)

### 3. Document Processing (`src/indexing/`, `src/ingestion/`)

**Purpose:** Parse, chunk, and embed academic papers

**Pipeline:**
```
PDF → Parse (pymupdf4llm) → Chunk (800 tokens) → Embed (Qwen3) → Store (Qdrant)
                                                                      │
                                                                      ▼
                                                               BM25 Index (Tantivy)
```

**Key Classes:**
- `PDFParser` - Text extraction with quality scoring
- `HierarchicalChunker` - Section-aware chunking
- `Indexer` - Orchestrates embedding and storage

### 4. BM25 Streaming Pipeline (`src/pipeline/`)

**Purpose:** Non-blocking BM25 indexing that runs in parallel with the embedding pipeline

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────────────┐
│                    CONCURRENT PIPELINE ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Papers ──► ChunkWorker ──► EmbedWorker ──► StoreWorker                 │
│                                                   │                      │
│                                         on_success callback             │
│                                                   │                      │
│                                                   ▼                      │
│                                            bm25_queue                    │
│                                                   │                      │
│  Resume Thread ────────────────────────────────► │                      │
│  (background)                                     │                      │
│                                                   ▼                      │
│                                            BM25Worker                    │
│                                                   │                      │
│                                                   ▼                      │
│                                        Tantivy Index + SQLite            │
│                                        (bm25_indexed=1)                  │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key Components:**

| Component | Purpose |
|-----------|---------|
| `BM25Worker` | Background worker consuming from bm25_queue |
| `BM25IndexItem` | Data transfer object (paper_id, chunk_ids, texts) |
| `bm25_queue` | Thread-safe queue connecting StoreWorker → BM25Worker |
| Resume Thread | Async background thread for indexing backlog at startup |

**Features:**
- **Non-blocking startup:** Pipeline starts immediately, resume runs in background
- **Batch commits:** Accumulates items before Tantivy commit (default: 50 papers or 5s timeout)
- **SQLite tracking:** `bm25_indexed` column enables resume on restart
- **Graceful shutdown:** Flushes remaining items on sentinel signal

**Tantivy Writer Lock Management (Persistent Writer Pattern):**

On Windows, file locks are not released immediately even after `del writer` + `gc.collect()`. To avoid `LockBusy` errors, the BM25Worker uses a **persistent writer** that is acquired once at startup and reused for all batches:

```python
# BM25Worker lifecycle
def run(self):
    try:
        self._acquire_writer()  # Once at start
        while not shutdown:
            batch = collect_items_from_queue()
            self._flush_batch(batch)  # Uses self._writer
    finally:
        self._release_writer()  # Once at end

def _flush_batch(self, batch):
    # Reuse persistent writer - no lock acquisition needed
    for item in batch:
        self._writer.add_document(doc)
    self._writer.commit()  # Commit keeps writer open
```

**Key Points:**
- Writer is acquired **once** at BM25Worker start
- `commit()` is called between batches but writer stays open
- Writer is only released on graceful shutdown
- This prevents `LockBusy` errors on Windows

### 5. Generation (`src/generation/`)

**Purpose:** LLM-powered response generation with citations

**Key Classes:**
- `OllamaClient` - LLM API wrapper
- `PromptBuilder` - Context-aware prompt construction
- `CitationFormatter` - APA citation generation

### 6. Quick Upload (`app/components/quick_upload.py`)

**Purpose:** Session-only document uploads for immediate use in chat

**Features:**
- Upload PDF, MD, TXT, DOCX files directly in sidebar
- 10MB limit per file, max 3 files per session
- Text extraction via PyMuPDF (PDF) and python-docx (DOCX)
- Cleared on page refresh (session-only storage)
- Always included in context regardless of knowledge source toggle

**Usage Flow:**
```
User uploads file → Text extraction → Session state storage → Prepended to RAG context
```

### 7. My Documents (`dashboard/backend/routes/documents_routes.py`)

**Purpose:** Persistent user document upload with full embedding pipeline

**Features:**
- Upload PDF, MD, DOCX files (50MB limit)
- Manual "Process" trigger for embedding
- Cascading delete (Qdrant → BM25 → SQLite → Disk)
- Real-time status updates via WebSocket
- Full user isolation (user_id filtering)

**Status Flow:**
```
pending → processing → ready
                   ↘ failed
```

### 8. Knowledge Source Integration (`src/retrieval/hybrid_search.py`)

**Purpose:** Unified toggle for selecting knowledge sources

**Knowledge Source Options:**
| Option | Behavior |
|--------|----------|
| `shared_only` | Search only shared KB (user_id is NULL) |
| `user_only` | Search only user's embedded documents |
| `both` | Search both sources with proper isolation |

**Context Priority (when "Both" selected):**
1. Quick Uploads (session docs) - Always included, highest priority
2. My Documents (user's embedded) - High priority
3. Shared KB (streaming pipeline) - Normal priority

**Implementation:**
- Qdrant: IsNull condition for shared docs, FieldCondition for user docs
- BM25: Filter during hydration phase from Qdrant

### 9. Deploy Hook Service (`services/deploy-hook/`)

**Purpose:** Webhook-based auto-deployment triggered by GitHub CI success

**Architecture:**
```
GitHub workflow_run webhook
        │
        ▼
https://papyrus-ai.net/deploy-webhook/webhook
        │
        ▼
Cloudflare Tunnel → deploy-hook:9000
        │
        ▼
HMAC-SHA256 Signature Verification
        │
        ▼
Background: docker compose pull && up -d
```

**Key Features:**
- HMAC-SHA256 signature verification (GitHub webhook security)
- Only deploys on CI success (filters event type, action, conclusion)
- Async background deployment (prevents webhook timeout)
- Health check endpoint at `/deploy-webhook/health`

**Endpoints:**
- `POST /deploy-webhook/webhook` - Receive GitHub webhook
- `GET /deploy-webhook/health` - Health check
- `GET /deploy-webhook/` - Service info

**Configuration:**
```yaml
# docker-compose.yml
deploy-hook:
  build: ./services/deploy-hook
  environment:
    - DEPLOY_WEBHOOK_SECRET=${DEPLOY_WEBHOOK_SECRET}
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
    - .:/opt/sme:ro
```

---

## Database Architecture

### 1. Authentication Database (`data/auth.db` - SQLite)

```sql
-- User accounts
CREATE TABLE users (
    id TEXT PRIMARY KEY,           -- UUID
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,   -- bcrypt
    display_name TEXT,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP,
    last_login TIMESTAMP
);

-- Encrypted API keys
CREATE TABLE user_api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    key_name TEXT NOT NULL,        -- 'openalex', 'semantic_scholar'
    encrypted_value BLOB,          -- Fernet encrypted
    created_at TIMESTAMP
);

-- User preferences
CREATE TABLE user_preferences (
    user_id TEXT PRIMARY KEY,
    preferred_model TEXT DEFAULT 'gpt-oss:120b-cloud',
    research_depth TEXT DEFAULT 'comprehensive',
    settings_json TEXT             -- JSON blob for extensibility
);
```

### 2. Paper Database (`data/sme.db` - SQLite)

```sql
-- Paper metadata
CREATE TABLE papers (
    id TEXT PRIMARY KEY,           -- DOI or generated ID
    title TEXT NOT NULL,
    authors TEXT,                  -- JSON array
    abstract TEXT,
    year INTEGER,
    doi TEXT,
    source TEXT,                   -- 'openalex', 'semantic_scholar', etc.
    pdf_path TEXT,
    status TEXT,                   -- 'discovered', 'downloaded', 'embedded', 'failed'
    user_id TEXT,                  -- Owner (NULL = legacy shared)
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Processing status
CREATE TABLE processing_status (
    paper_id TEXT PRIMARY KEY,
    parse_status TEXT,
    chunk_count INTEGER,
    embed_status TEXT,
    error_message TEXT,
    processed_at TIMESTAMP
);
```

### 3. Vector Database (Qdrant - `sme_papers_v2` collection)

**Point Structure:**
```json
{
    "id": "uuid",
    "vector": [0.123, ...],        // 4096 dimensions
    "payload": {
        "paper_id": "10.1234/example",
        "chunk_index": 0,
        "text": "chunk content...",
        "title": "Paper Title",
        "authors": ["Author 1"],
        "year": 2024,
        "section": "Introduction",
        "user_id": "user-uuid"     // For data isolation
    }
}
```

**Index Configuration:**
- HNSW: m=32, ef_construct=128, ef_search=400
- Scalar quantization: int8, quantile=0.99
- On-disk payload for memory efficiency

### 4. BM25 Index (Tantivy - `data/bm25_index_tantivy/`)

**Schema:**
- `chunk_id` (stored) - Unique chunk identifier
- `text` (indexed, tokenized) - Chunk content for search
- `paper_id` (stored) - Parent paper reference

---

## Self-Healing Architecture

The system implements a three-layer self-healing architecture to ensure minimal downtime and automatic recovery from failures.

### Layer 1: Docker Health Checks

All services have HTTP health checks that Docker monitors. Unhealthy containers are automatically restarted.

| Service | Endpoint | Interval | Restart Policy |
|---------|----------|----------|----------------|
| Streamlit App | `/_stcore/health` | 30s | always |
| Dashboard API | `/health` | 30s | always |
| Dashboard UI | `/` (wget) | 30s | always |
| Caddy | `/` (wget) | 30s | always |
| Qdrant | TCP :6333 | 10s | always |
| Redis | `redis-cli ping` | 10s | always |
| Ollama | TCP :11434 | 30s | always |
| Auth | `/health` | 30s | always |

**Service Dependencies:**
Services start in order based on health conditions:
```
init-validator (completes) → Redis/Qdrant/Ollama (healthy) → App (healthy) → Dashboard → Caddy → Cloudflared
```

### Layer 2: Pipeline Watchdog with Circuit Breaker

The pipeline process (paper ingestion) is monitored by a watchdog with exponential backoff and circuit breaker pattern.

**Circuit Breaker States:**
```
CLOSED ──► OPEN ──► HALF_OPEN ──► CLOSED
   │         │          │            │
   │    (5 failures)    │      (success)
   │         │          │
   │    (5 min cooldown)│
   └─────────────────────────────────┘
        (stability: 60s uptime)
```

**Backoff Schedule:**
| Failure # | Wait Time |
|-----------|-----------|
| 1 | 10s |
| 2 | 20s |
| 3 | 40s |
| 4 | 80s |
| 5+ | Circuit OPEN (5 min) |

**State Persistence:**
Failure metadata is persisted to `/app/data/pipeline_state_internal.json`:
```json
{
  "mode": "stream",
  "restart_count": 3,
  "consecutive_failures": 2,
  "circuit_breaker_state": "CLOSED",
  "last_error": "Process died unexpectedly"
}
```

### Layer 3: Init Validator (Startup Repair)

The `init-validator` container runs before all services and repairs common configuration issues.

**Auto-Repaired Files:**
| File | Template | Action |
|------|----------|--------|
| `config/config.yaml` | `.templates/config.yaml.template` | Restore if missing/corrupt |
| `services/caddy/Caddyfile` | `.templates/Caddyfile` | Restore if missing/corrupt |
| `config/cloudflared-config.yml` | `.templates/cloudflared-config.yml` | Restore if missing/corrupt |

**Not Auto-Repaired (Sensitive):**
- `config/cloudflared-credentials.json` - Contains tunnel secrets, requires manual regeneration

**Repair Logic:**
```bash
if [ -d /path/to/file ]; then
  # File is a directory (Docker mount error) - delete and restore
  rm -rf /path/to/file
  cp /template /path/to/file
elif [ ! -f /path/to/file ]; then
  # File missing - restore from template
  cp /template /path/to/file
fi
```

### Recovery Scenarios

| Scenario | Detection | Recovery | Downtime |
|----------|-----------|----------|----------|
| Service hang | Health check (90s) | Docker restart | ~2 min |
| Service crash | Immediate | Docker restart | ~30s |
| Pipeline crash | Watchdog (10s) | Backoff restart | 10s-5min |
| Config missing | Startup | Template restore | 0s |
| Config corrupt | Startup | Template restore | 0s |

---

## Network Topology

### Docker Network (`sme_network`)

All services communicate via internal Docker network. External access only through Caddy (port 8080).

### Port Mapping

| External | Internal | Service |
|----------|----------|---------|
| 8080 | 80 | Caddy |
| 8502 | 8501 | Streamlit (direct) |
| - | 6333 | Qdrant |
| - | 11434 | Ollama |
| - | 6379 | Redis |
| - | 8000 | Auth |
| - | 3000 | Dashboard UI |
| - | 8400 | Dashboard API |

### Cloudflare Tunnel

```
Internet ──► Cloudflare Edge ──► Tunnel ──► Caddy:80
                                    │
                                    └─► HTTPS termination at Cloudflare
```

---

## Technology Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| **Orchestration** | Docker Compose | v2+ | Service management |
| **Reverse Proxy** | Caddy | 2.x | Routing, static files |
| **Frontend** | Streamlit | 1.32+ | Chat interface |
| **Frontend** | React | 18.x | Dashboard |
| **API** | FastAPI | 0.110+ | Auth & Dashboard APIs |
| **Vector DB** | Qdrant | 1.8+ | Semantic search |
| **BM25 Index** | Tantivy | 0.21+ | Keyword search |
| **Embedding** | Ollama | 0.1.x | qwen3-embedding:8b |
| **LLM** | Ollama | 0.1.x | gpt-oss:120b-cloud |
| **Cache** | Redis | 7.x | Query caching |
| **Database** | SQLite | 3.x | Auth, papers metadata |
| **PDF Parsing** | pymupdf4llm | 0.0.x | PDF text extraction |
| **Reranking** | BGE-reranker-v2-m3 | - | Cross-encoder reranking |
| **Tunnel** | Cloudflare | latest | HTTPS remote access |

---

## Related Documentation

- [API_REFERENCE.md](API_REFERENCE.md) - Complete API documentation
- [DATA_FLOWS.md](DATA_FLOWS.md) - Data pipeline details
- [CONFIGURATION.md](CONFIGURATION.md) - Configuration reference
- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) - Extension guide
- [SECURITY.md](SECURITY.md) - Security model and audit
