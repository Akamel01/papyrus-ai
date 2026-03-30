# SME Research Assistant - Development Guide

**Version:** 1.0
**Last Updated:** March 2026

---

## Table of Contents

1. [Development Setup](#development-setup)
2. [Project Structure](#project-structure)
3. [Adding New Features](#adding-new-features)
4. [Extending the Pipeline](#extending-the-pipeline)
5. [Testing](#testing)
6. [Debugging](#debugging)
7. [Common Tasks](#common-tasks)

---

## Development Setup

### Prerequisites

- Python 3.11+
- Docker Desktop with Docker Compose v2+
- NVIDIA GPU with CUDA support (for local development)
- Git

### Local Development Environment

```bash
# Clone the repository
git clone <repo-url>
cd SME

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: .\venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Dev dependencies

# Copy environment template
cp .env.example .env
# Edit .env with your secrets

# Install git hooks (IMPORTANT: enables auto-sync for config templates)
./scripts/install-hooks.sh

# Start infrastructure services only
docker compose up -d redis qdrant ollama

# Run the app locally (outside Docker)
streamlit run app/main.py
```

### Git Hooks Setup

The project uses a pre-commit hook to automatically sync config templates when you commit changes. This ensures the self-healing mount system always has up-to-date templates.

```bash
# One-time setup (run after cloning)
./scripts/install-hooks.sh

# What it does:
# When you commit changes to config files, templates auto-update:
git add services/caddy/Caddyfile
git commit -m "Update Caddy routing"
# Output: [hook] Synced: services/caddy/Caddyfile -> .templates/Caddyfile
```

**Tracked config files:**
- `services/caddy/Caddyfile` → `.templates/Caddyfile`
- `config/cloudflared-config.yml` → `.templates/cloudflared-config.yml`

### Docker Development

**Fast Development Workflow (Recommended):**

For code-only changes (no `requirements.txt` changes), use bind mounts for instant updates:

```bash
# Start with development overrides (bind mounts source code)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# After code changes, just restart (no rebuild needed!)
docker compose restart app

# View logs
docker compose logs -f app
```

**When to Rebuild:**

Only rebuild when `requirements.txt` changes:

```bash
# Rebuild (uses layer caching - fast if base image exists)
docker compose build app && docker compose up -d app
```

**IMPORTANT:** Never use `--no-cache` unless absolutely necessary - it bypasses all caching and re-downloads PyTorch (~2.5GB).

**Full Rebuild (rare):**

```bash
# Build all services
docker compose build

# Start all services
docker compose up -d

# View logs
docker compose logs -f app
```

### IDE Configuration

**VSCode Recommended Extensions:**
- Python
- Pylance
- Docker
- YAML

**VSCode settings.json:**
```json
{
    "python.defaultInterpreterPath": "./venv/bin/python",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": true,
    "python.formatting.provider": "black"
}
```

---

## Project Structure

### Core Modules

```
src/
├── acquisition/          # Paper discovery & download
│   ├── discovery.py     # Multi-API paper search
│   ├── downloader.py    # PDF download with retries
│   └── apis/            # API client implementations
│       ├── openalex.py
│       ├── semantic_scholar.py
│       ├── unpaywall.py
│       ├── arxiv.py
│       └── crossref.py
│
├── ingestion/           # PDF processing
│   ├── pdf_parser.py    # Text extraction
│   └── quality_scorer.py
│
├── indexing/            # Document indexing
│   ├── indexer.py       # Main indexing orchestrator
│   ├── chunker.py       # Document chunking
│   ├── bm25_tantivy.py  # Tantivy BM25 implementation
│   └── bm25_index.py    # Standard BM25 implementation
│
├── retrieval/           # Search & retrieval
│   ├── hybrid_search.py # BM25 + semantic fusion
│   ├── hyde.py          # Hypothetical document embeddings
│   ├── vector_store.py  # Qdrant operations
│   ├── reranker.py      # Cross-encoder reranking
│   └── sequential/      # Multi-round RAG
│       ├── search.py
│       └── processor.py
│
├── generation/          # LLM generation
│   ├── llm.py           # Ollama client
│   ├── prompts.py       # Prompt templates
│   └── citation.py      # Citation formatting
│
├── embedding/           # Vector embeddings
│   └── embedder.py      # Ollama embedding client
│
├── pipeline/            # Concurrent processing
│   ├── concurrent_pipeline.py  # Main pipeline orchestrator
│   └── bm25_worker.py   # Background BM25 indexing
│
└── storage/             # Database operations
    ├── paper_db.py      # Paper metadata CRUD
    └── cache.py         # Redis caching
```

### Service Modules

```
services/
├── auth/                # Authentication service
│   ├── main.py         # FastAPI endpoints
│   ├── models.py       # SQLAlchemy models
│   ├── auth.py         # JWT handling
│   ├── crypto.py       # Fernet encryption
│   └── Dockerfile
│
├── caddy/               # Reverse proxy
│   └── Caddyfile       # Routing configuration
│
└── cloudflared/         # HTTPS tunnel
    └── Dockerfile
```

### App Module

```
app/
├── main.py              # Streamlit entry point
├── components/          # UI components
│   ├── chat.py         # Chat interface
│   ├── sidebar.py      # Sidebar controls (includes knowledge source toggle)
│   ├── sidebar_config.py # Sidebar configuration dataclass
│   ├── quick_upload.py # Session-only document uploads
│   ├── rag_wrapper.py  # RAG pipeline wrappers
│   └── auth_ui.py      # Login/register forms
└── pages/               # Streamlit pages
    └── settings.py     # User settings
```

### Dashboard Module

```
dashboard/
├── backend/
│   ├── main.py         # FastAPI entry point
│   ├── auth.py         # Authentication utilities
│   └── routes/
│       ├── documents_routes.py  # User document CRUD API
│       ├── config_routes.py
│       ├── run_routes.py
│       └── ws_routes.py         # WebSocket events
└── frontend/
    └── src/
        ├── App.tsx
        ├── lib/api.ts           # API client with documents methods
        └── pages/
            ├── MyDocuments.tsx  # User document management UI
            ├── Dashboard.tsx
            ├── RunControls.tsx
            └── ConfigEditor.tsx
```

---

## Adding New Features

### Adding a New API Source

1. **Create API client** in `src/acquisition/apis/`:

```python
# src/acquisition/apis/new_api.py
from typing import List, Dict, Optional
import httpx

class NewAPIClient:
    """Client for NewAPI academic paper search."""

    BASE_URL = "https://api.newapi.org/v1"

    def __init__(self, api_key: Optional[str] = None, email: str = ""):
        self.api_key = api_key
        self.email = email
        self.client = httpx.Client(timeout=30)

    def search(
        self,
        query: str,
        max_results: int = 100,
        min_year: Optional[int] = None
    ) -> List[Dict]:
        """Search for papers matching query."""
        params = {
            "q": query,
            "limit": max_results,
        }
        if min_year:
            params["from_year"] = min_year

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = self.client.get(
            f"{self.BASE_URL}/search",
            params=params,
            headers=headers
        )
        response.raise_for_status()

        return self._parse_results(response.json())

    def _parse_results(self, data: Dict) -> List[Dict]:
        """Convert API response to standard paper format."""
        papers = []
        for item in data.get("results", []):
            papers.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "authors": item.get("authors", []),
                "abstract": item.get("abstract"),
                "year": item.get("year"),
                "doi": item.get("doi"),
                "pdf_url": item.get("pdf_url"),
                "source": "newapi"
            })
        return papers
```

2. **Register in discovery.py**:

```python
# src/acquisition/discovery.py
from src.acquisition.apis.new_api import NewAPIClient

class PaperDiscovery:
    def __init__(self, config: Dict):
        # ... existing clients ...
        if config["apis"]["newapi"]["enabled"]:
            self.newapi = NewAPIClient(
                api_key=config["apis"]["newapi"]["api_key"],
                email=config["emails"][0]
            )
```

3. **Add configuration**:

```yaml
# config/acquisition_config.yaml
acquisition:
  apis:
    newapi:
      enabled: true
      api_key: "${NEW_API_KEY}"
      requests_per_minute: 30
      timeout_seconds: 30
```

### Adding a New Retrieval Strategy

1. **Create retrieval module**:

```python
# src/retrieval/new_strategy.py
from typing import List, Optional
from src.retrieval.base import BaseRetriever, RetrievalResult

class NewStrategyRetriever(BaseRetriever):
    """New retrieval strategy implementation."""

    def __init__(self, config: Dict):
        self.config = config
        # Initialize components

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        user_id: Optional[str] = None,  # CRITICAL for multi-user
        **kwargs
    ) -> List[RetrievalResult]:
        """
        Retrieve relevant documents using new strategy.

        Args:
            query: Search query
            top_k: Number of results
            user_id: User ID for data isolation (REQUIRED)
        """
        # Implement retrieval logic
        # ALWAYS filter by user_id
        results = self._search(query, user_id=user_id)
        return results[:top_k]
```

2. **Integrate with hybrid search**:

```python
# src/retrieval/hybrid_search.py
from src.retrieval.new_strategy import NewStrategyRetriever

class HybridSearcher:
    def __init__(self, config: Dict):
        # ... existing initialization ...
        if config.get("use_new_strategy"):
            self.new_strategy = NewStrategyRetriever(config)

    def search(self, query: str, user_id: str, **kwargs):
        # Add new strategy to fusion
        if self.new_strategy:
            new_results = self.new_strategy.retrieve(
                query, user_id=user_id
            )
            # Fuse with existing results
```

### Adding a New UI Component

1. **Create component**:

```python
# app/components/new_feature.py
import streamlit as st

def render_new_feature(user_id: str):
    """Render new feature UI component."""
    st.subheader("New Feature")

    # Get user-specific data
    data = fetch_user_data(user_id)

    # Render UI
    st.write(data)

    # Handle interactions
    if st.button("Action"):
        perform_action(user_id)
```

2. **Get current user** - Use `get_current_user()` from `app/auth_helper.py`:

```python
from app.auth_helper import get_current_user

# Returns an AuthUser dataclass (NOT a dict)
current_user = get_current_user()

# AuthUser attributes:
#   - current_user.id           # User's unique ID (string)
#   - current_user.email        # User's email address
#   - current_user.display_name # Display name (may be None)
#   - current_user.role         # User role (viewer/operator/admin)

# CORRECT - Use attribute access
user_id = current_user.id if current_user else None

# WRONG - AuthUser is NOT a dict, this will fail:
# user_id = current_user.get("user_id")  # AttributeError!
# user_id = current_user["id"]           # TypeError!
```

3. **Integrate in main.py**:

```python
# app/main.py
from app.auth_helper import get_current_user
from app.components.new_feature import render_new_feature

# In the main rendering function
current_user = get_current_user()
if current_user and st.session_state.get("show_new_feature"):
    render_new_feature(user_id=current_user.id)
```

### Working with Knowledge Sources

When adding features that interact with retrieval, respect the knowledge source toggle:

```python
# app/components/sidebar_config.py
@dataclass
class SidebarConfig:
    knowledge_source: str = "both"  # "shared_only", "user_only", "both"
    # ... other fields

# In retrieval code, pass knowledge_source
results = hybrid_search.search(
    query=query,
    user_id=user_id,
    knowledge_source=config.knowledge_source  # Respects user's toggle
)
```

### Adding Quick Upload Support

To make a component work with Quick Uploads:

```python
# Always include quick uploads in context (they're always active)
from app.components.quick_upload import get_quick_upload_context

def build_context(query: str, config: SidebarConfig, user_id: str) -> str:
    context_parts = []

    # 1. Quick Uploads - ALWAYS included (highest priority)
    quick_context = get_quick_upload_context()
    if quick_context:
        context_parts.append(quick_context)

    # 2. Retrieved documents (filtered by knowledge_source)
    results = hybrid_search.search(
        query, user_id=user_id, knowledge_source=config.knowledge_source
    )
    for r in results:
        context_parts.append(r.text)

    return "\n\n---\n\n".join(context_parts)
```

---

## Extending the Pipeline

### Adding a New Processing Stage

1. **Create processor**:

```python
# src/processing/new_stage.py
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class NewStageProcessor:
    """New processing stage for the pipeline."""

    def __init__(self, config: Dict):
        self.config = config

    def process(self, papers: List[Dict]) -> List[Dict]:
        """Process papers through new stage."""
        results = []
        for paper in papers:
            try:
                processed = self._process_paper(paper)
                results.append(processed)
            except Exception as e:
                logger.error(f"Failed to process {paper['id']}: {e}")
        return results

    def _process_paper(self, paper: Dict) -> Dict:
        """Process a single paper."""
        # Implementation here
        return paper
```

2. **Add to pipeline orchestrator**:

```python
# scripts/run_pipeline.py
from src.processing.new_stage import NewStageProcessor

def run_full_pipeline(config):
    # ... existing stages ...

    # Add new stage
    if config.get("enable_new_stage"):
        processor = NewStageProcessor(config)
        papers = processor.process(papers)
```

### Adding a New Embedding Model

1. **Create embedder wrapper**:

```python
# src/embedding/new_embedder.py
from typing import List, Union
import numpy as np

class NewEmbedder:
    """Wrapper for new embedding model."""

    def __init__(self, model_name: str, device: str = "cuda"):
        self.model_name = model_name
        self.device = device
        self._load_model()

    def _load_model(self):
        """Load the embedding model."""
        # Model loading logic
        pass

    def embed(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 32
    ) -> np.ndarray:
        """Generate embeddings for texts."""
        if isinstance(texts, str):
            texts = [texts]

        embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = self._embed_batch(batch)
            embeddings.extend(batch_embeddings)

        return np.array(embeddings)

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts."""
        # Implementation
        pass
```

2. **Update configuration**:

```yaml
embedding:
  model_name: "new-embedding-model"
  model_type: "new"  # Triggers new embedder
```

---

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_retrieval.py

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test
pytest tests/test_retrieval.py::test_hybrid_search -v
```

### Writing Tests

```python
# tests/test_new_feature.py
import pytest
from src.retrieval.new_strategy import NewStrategyRetriever

@pytest.fixture
def retriever():
    """Create retriever with test config."""
    config = {
        "option1": "value1",
        "option2": "value2"
    }
    return NewStrategyRetriever(config)

def test_retrieve_returns_results(retriever):
    """Test that retrieve returns expected results."""
    results = retriever.retrieve(
        query="test query",
        user_id="test-user-id"
    )
    assert len(results) > 0
    assert all(r.score >= 0 for r in results)

def test_user_isolation(retriever):
    """Test that user_id filtering works."""
    # Create test data for different users
    # Verify user A cannot see user B's data
    pass

@pytest.mark.integration
def test_with_real_database(retriever):
    """Integration test with real database."""
    # Requires running services
    pass
```

### Test Configuration

```python
# tests/conftest.py
import pytest
import os

@pytest.fixture(scope="session")
def test_config():
    """Load test configuration."""
    return {
        "vector_store": {
            "host": os.getenv("TEST_QDRANT_HOST", "localhost"),
            "port": 6333,
            "collection_name": "test_collection"
        }
    }

@pytest.fixture
def mock_user_id():
    """Provide test user ID."""
    return "test-user-12345"
```

---

## Debugging

### Logging

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Use logging
logger.debug("Detailed debug info")
logger.info("General info")
logger.warning("Warning message")
logger.error("Error occurred", exc_info=True)
```

### Docker Debugging

```bash
# View container logs
docker compose logs -f app

# Enter container shell
docker exec -it sme_app bash

# Check container status
docker compose ps

# Inspect container
docker inspect sme_app

# Check resource usage
docker stats
```

### Qdrant Debugging

```bash
# Check collection info
curl http://localhost:6333/collections/sme_papers_v2

# Check point count
curl http://localhost:6333/collections/sme_papers_v2/points/count

# Search test
curl -X POST http://localhost:6333/collections/sme_papers_v2/points/search \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, ...],
    "limit": 5,
    "filter": {
      "must": [{"key": "user_id", "match": {"value": "test-user"}}]
    }
  }'
```

### Redis Debugging

```bash
# Connect to Redis
docker exec -it sme_redis redis-cli

# Check keys
KEYS *

# Check specific key
GET "embed:hash123"

# Clear cache
FLUSHALL
```

---

## Common Tasks

### Fixing Docker Mount Corruption

If you see errors like "not a directory: Are you trying to mount a directory onto a file?":

```bash
# Option 1: Let init-validator auto-repair (recommended)
docker-compose up -d  # init-validator runs automatically

# Option 2: Manual recovery script
./scripts/fix-mounts.sh

# Option 3: Manual fix
docker stop sme_caddy sme_tunnel
rm -rf services/caddy/Caddyfile  # If it's a directory
git checkout services/caddy/Caddyfile  # Restore from git
docker-compose up -d caddy cloudflared
```

### Rebuilding the BM25 Index

```bash
docker exec -it sme_app python scripts/rebuild_bm25.py
```

### Checking BM25 Indexing Status

```bash
# Check papers needing BM25 indexing
docker exec -it sme_app python -c "
from src.storage.paper_store import PaperStore
store = PaperStore('data/sme.db')
unindexed = store.get_unindexed_bm25_papers(limit=10)
print(f'Papers needing BM25 indexing: {len(unindexed)}')
"

# Check Tantivy index document count
docker exec -it sme_app python -c "
from src.indexing.bm25_index import create_bm25_index
bm25 = create_bm25_index('data/bm25_index_tantivy', use_tantivy=True)
searcher = bm25.tantivy_index.searcher()
print(f'Tantivy documents: {searcher.num_docs}')
"
```

### Understanding the BM25 Persistent Writer Pattern

The BM25Worker uses a **persistent writer pattern** to avoid `LockBusy` errors on Windows. On Windows, file locks are not released immediately even after `del writer` + `gc.collect()`.

**Pattern:**
```python
# BM25Worker acquires writer ONCE at start
def run(self):
    try:
        self._acquire_writer()  # Once
        while not shutdown:
            self._flush_batch(batch)  # Reuses self._writer
    finally:
        self._release_writer()  # Once at end

# Batches use the persistent writer
def _flush_batch(self, batch):
    for item in batch:
        self._writer.add_document(doc)
    self._writer.commit()  # Keeps writer open
```

**Why this matters:**
- Creating a new writer per batch causes `LockBusy` errors on Windows
- The persistent writer is held for the entire BM25Worker lifetime
- Only `commit()` is called between batches; writer stays open
- This is why BM25Worker must be started as a single thread

**Verifying BM25Worker is running:**
```bash
docker exec sme_app sh -c "grep 'BM25-WORKER.*Committed' /app/data/autonomous_update.log | tail -5"
# Should show: "[BM25-WORKER] Committed batch: 50 papers, XXXX chunks..."
```

### Migrating the Database

```python
# scripts/migrate_db.py
from sqlalchemy import create_engine, text
import os

def migrate():
    engine = create_engine(os.getenv("DATABASE_URL"))

    with engine.connect() as conn:
        # Add new column
        conn.execute(text("""
            ALTER TABLE papers
            ADD COLUMN IF NOT EXISTS new_field TEXT
        """))
        conn.commit()

if __name__ == "__main__":
    migrate()
```

### Adding a New Configuration Option

1. Add to config YAML
2. Update config loading code
3. Update documentation
4. Add environment variable if sensitive

### Updating Docker Images

```bash
# Pull latest base images
docker compose pull

# Rebuild all services
docker compose build --no-cache

# Restart with new images
docker compose up -d
```

### Creating a New Service

1. Create service directory: `services/new-service/`
2. Add Dockerfile
3. Add to docker-compose.yml
4. Update Caddyfile for routing (if needed)
5. Add health check endpoint

### Working with User Documents API

```python
# Testing document upload
import requests

token = "your_jwt_token"
headers = {"Authorization": f"Bearer {token}"}

# Upload document
with open("paper.pdf", "rb") as f:
    response = requests.post(
        "http://localhost:8400/api/documents/upload",
        files={"file": ("paper.pdf", f, "application/pdf")},
        headers=headers
    )
    doc_id = response.json()["document_id"]

# Trigger processing
response = requests.post(
    f"http://localhost:8400/api/documents/{doc_id}/process",
    headers=headers
)

# List documents
response = requests.get(
    "http://localhost:8400/api/documents",
    headers=headers
)
documents = response.json()["documents"]

# Delete document (cascading)
response = requests.delete(
    f"http://localhost:8400/api/documents/{doc_id}",
    headers=headers
)
```

### Checking User Document Processing Status

```bash
# Check processing queue
docker exec -it sme_dashboard_api python -c "
from routes.documents_routes import _get_paper_store
store = _get_paper_store()
for user_id in ['test-user']:
    pending = store.get_pending_user_papers(user_id)
    print(f'User {user_id}: {len(pending)} pending documents')
"
```

---

## Code Style Guidelines

### Python

- Use Black for formatting
- Use type hints
- Write docstrings for public functions
- Follow PEP 8

```python
def search(
    self,
    query: str,
    top_k: int = 10,
    user_id: Optional[str] = None
) -> List[RetrievalResult]:
    """
    Search for relevant documents.

    Args:
        query: Search query text
        top_k: Number of results to return
        user_id: User ID for data isolation

    Returns:
        List of retrieval results sorted by relevance

    Raises:
        ValueError: If query is empty
    """
    if not query.strip():
        raise ValueError("Query cannot be empty")
    # Implementation
```

### Critical: User Data Isolation

**ALWAYS include user_id parameter in:**
- All retrieval functions
- All database queries
- All cache keys
- **All delete operations** (prevents cross-user data deletion)
- **All existence checks** (prevents information disclosure)

```python
# CORRECT - Search with user isolation
def search(self, query: str, user_id: str) -> List[Result]:
    return self.db.query(
        "SELECT * FROM papers WHERE user_id = ?",
        (user_id,)
    )

# CORRECT - Delete with user isolation
def delete(self, doi: str, user_id: str) -> None:
    # Only deletes documents belonging to this user
    vector_store.delete(doi=doi, user_id=user_id)

# CORRECT - Check existing IDs with user isolation
def check_existing(self, ids: List[str], user_id: str) -> List[str]:
    # Only returns IDs belonging to this user
    return vector_store.check_existing_ids(ids=ids, user_id=user_id)

# WRONG - Security vulnerability! No user isolation
def search(self, query: str) -> List[Result]:
    return self.db.query("SELECT * FROM papers")

# WRONG - Allows cross-user deletion!
def delete(self, doi: str) -> None:
    vector_store.delete(doi=doi)  # Missing user_id!
```

**WARNING:** Do NOT use `src/retrieval/parallel_search.py` - it is deprecated
and lacks user_id support. Use `src/retrieval/sequential/search.py` instead.

### Streamlit Best Practices

**CRITICAL: Avoid Module-Level Execution**

Streamlit page modules should ONLY define functions, never execute them at module level. Module-level execution causes functions to run during import, leading to duplicate rendering and widget key conflicts.

```python
# WRONG - Module-level execution
def render_page():
    st.form("my_form")
    # ... page content

render_page()  # ← DO NOT DO THIS!

# CORRECT - Only define functions
def render_page():
    st.form("my_form")
    # ... page content

# Function is called explicitly by main.py or other entry points
```

**Why this matters:**
- When `main.py` imports a page module, ALL module-level code executes
- If a page renders itself at module level AND is called explicitly, it renders twice
- This causes `DuplicateWidgetID` errors and unexpected behavior
- Streamlit multipage apps should have a single entry point that controls page rendering

**Widget Keys:**
- Use unique, static keys for forms and widgets when possible
- Only use dynamic keys if the same widget needs multiple instances in one session
- Never rely on dynamic keys to "fix" duplicate rendering - fix the root cause instead

---

---

## Unified Authentication System

### Overview

SME uses a unified authentication system that allows users to share credentials between the Chat UI (Streamlit) and the Dashboard (React). Both UIs authenticate against the same Auth Service.

### Login Methods

Users can log in using any of these identifiers:

| Identifier Type | Example | Notes |
|----------------|---------|-------|
| Email | `ahmed.kamel@ubc.ca` | Direct email lookup |
| Username | `AhmedKamel` | Stored in User.username column |
| Dashboard username | `admin` | Maps to `{username}@dashboard.local` |

### Default Admin Credentials

```
Username: admin     Password: admin123
Username: AhmedKamel  Password: admin123  (for ahmed.kamel@ubc.ca)
```

### Architecture

```
┌─────────────┐     ┌─────────────┐
│   Chat UI   │     │  Dashboard  │
│ (Streamlit) │     │   (React)   │
└──────┬──────┘     └──────┬──────┘
       │                   │
       │  /api/auth/login  │  /api/auth/internal/login
       │                   │
       └─────────┬─────────┘
                 │
         ┌───────▼───────┐
         │ Auth Service  │
         │  (FastAPI)    │
         └───────┬───────┘
                 │
         ┌───────▼───────┐
         │   auth.db     │
         │   (SQLite)    │
         └───────────────┘
```

### Session Persistence (Chat UI)

The Chat UI now persists sessions across page refreshes using browser localStorage:

1. **On Login**: Refresh token is saved to localStorage via JavaScript injection
2. **On Page Load**: JavaScript checks localStorage and redirects with token in query params
3. **On Refresh**: `init_auth_state()` reads query params and refreshes the session
4. **On Logout**: localStorage tokens are cleared

```python
# How session restoration works in auth_helper.py
def init_auth_state():
    if "auth" not in st.session_state:
        st.session_state.auth = {...}
        _try_restore_from_storage()  # Checks query params for refresh token

def _try_restore_from_storage():
    params = st.query_params
    stored_refresh = params.get("_auth_refresh")
    if stored_refresh:
        st.query_params.clear()  # Clean URL
        st.session_state.auth["refresh_token"] = stored_refresh
        refresh_tokens()  # Restore session
```

### Adding a New User

```python
# Via Auth Service container
docker exec -it sme_auth python -c "
from models import get_engine, get_session_factory, User
from auth import hash_password

engine = get_engine('sqlite:///./data/auth.db')
SessionLocal = get_session_factory(engine)
db = SessionLocal()

user = User(
    email='newuser@example.com',
    username='NewUser',  # Optional: login alias
    password_hash=hash_password('SecurePassword123!'),
    display_name='New User',
    role='user',  # or 'admin'
    dashboard_role='viewer'  # admin, operator, or viewer
)
db.add(user)
db.commit()
db.close()
"
```

### Setting a Username for Existing User

```python
docker exec -it sme_auth python -c "
import sqlite3
conn = sqlite3.connect('./data/auth.db')
cursor = conn.cursor()
cursor.execute(\"UPDATE users SET username = 'MyUsername' WHERE email = 'user@example.com'\")
conn.commit()
conn.close()
"
```

### User Model Fields

| Field | Type | Description |
|-------|------|-------------|
| id | String(36) | UUID primary key |
| email | String(255) | Unique, required, indexed |
| username | String(100) | Unique, optional, indexed - login alias |
| password_hash | String(255) | bcrypt hash |
| display_name | String(100) | Display name (optional) |
| role | String(20) | Auth role: `user` or `admin` |
| dashboard_role | String(20) | Dashboard role: `admin`, `operator`, or `viewer` |
| is_active | String(5) | `"true"` or `"false"` |

### Auth Endpoints

**Public (Chat UI)**:
- `POST /api/auth/login` - Login with email/username + password
- `POST /api/auth/register` - Register new account
- `POST /api/auth/refresh` - Refresh access token
- `GET /api/auth/me` - Get current user info

**Internal (Dashboard → Auth Service)**:
- `POST /api/auth/internal/login` - Service-to-service login (no rate limiting)

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [API_REFERENCE.md](API_REFERENCE.md) - API documentation
- [DATA_FLOWS.md](DATA_FLOWS.md) - Data pipeline details
- [SECURITY.md](SECURITY.md) - Security model
