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
6. [Network Topology](#network-topology)
7. [Technology Stack](#technology-stack)

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
| **caddy** | sme_caddy | 8080:80 | Reverse proxy, request routing |
| **app** | sme_app | 8501, 8502 | Streamlit chat interface |
| **auth** | sme_auth | 8000 | User authentication, JWT tokens |
| **dashboard-ui** | sme_dashboard_ui | 3000 | React dashboard frontend |
| **dashboard-backend** | sme_dashboard_backend | 8400 | FastAPI dashboard API |
| **qdrant** | sme_qdrant | 6333, 6334 | Vector database |
| **ollama** | sme_ollama | 11434 | Embedding model, LLM serving |
| **redis** | sme_redis | 6379 | Query/result caching |
| **cloudflared** | sme_cloudflared | - | HTTPS tunnel for remote access |

### Service Dependencies

```
cloudflared ──► caddy ──┬──► auth
                        ├──► app ──┬──► qdrant
                        │          ├──► ollama
                        │          └──► redis
                        └──► dashboard-backend ──► qdrant
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
│   │   └── auth_ui.py           # Login/register components
│   └── pages/                    # Streamlit pages
│       └── settings.py          # User settings page
│
├── config/                       # Configuration files
│   ├── config.yaml              # Main system configuration
│   ├── acquisition_config.yaml  # Paper discovery settings
│   └── depth_presets.yaml       # Research depth presets
│
├── data/                         # Runtime data (gitignored)
│   ├── auth.db                  # User authentication database
│   ├── sme.db                   # Paper metadata database
│   ├── chat_history.db          # Chat history
│   ├── bm25_index_tantivy/      # BM25 keyword index
│   └── pipeline_state.json      # Pipeline progress
│
├── DataBase/                     # Paper storage
│   ├── Papers/                  # Legacy papers (all users)
│   └── UpdatedPapers/           # New papers per user
│
├── documentation/                # This documentation folder
│
├── scripts/                      # Utility scripts
│   ├── run_pipeline.py          # Full acquisition pipeline
│   ├── ingest_papers.py         # Manual PDF import
│   ├── rebuild_bm25.py          # BM25 index rebuild
│   └── migrate_db.py            # Database migrations
│
├── services/                     # Docker service configs
│   ├── auth/                    # Auth service
│   │   ├── main.py             # FastAPI auth endpoints
│   │   ├── models.py           # SQLAlchemy models
│   │   ├── crypto.py           # Fernet encryption
│   │   └── Dockerfile
│   ├── caddy/
│   │   └── Caddyfile           # Reverse proxy config
│   ├── dashboard-backend/
│   │   └── main.py             # Dashboard API
│   └── dashboard-ui/
│       └── src/                # React frontend
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

### 4. Generation (`src/generation/`)

**Purpose:** LLM-powered response generation with citations

**Key Classes:**
- `OllamaClient` - LLM API wrapper
- `PromptBuilder` - Context-aware prompt construction
- `CitationFormatter` - APA citation generation

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
