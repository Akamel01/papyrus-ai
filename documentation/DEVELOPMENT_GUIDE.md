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

# Start infrastructure services only
docker compose up -d redis qdrant ollama

# Run the app locally (outside Docker)
streamlit run app/main.py
```

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
│   ├── sidebar.py      # Sidebar controls
│   └── auth_ui.py      # Login/register forms
└── pages/               # Streamlit pages
    └── settings.py     # User settings
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

2. **Integrate in main.py**:

```python
# app/main.py
from app.components.new_feature import render_new_feature

# In the main rendering function
if st.session_state.get("show_new_feature"):
    render_new_feature(user_id=current_user["user_id"])
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

### Verifying Tantivy Writer Lock

If you see "LockBusy" errors, verify the writer is being released:

```bash
docker exec -it sme_app python -c "
from src.indexing.bm25_index import create_bm25_index
import gc

bm25 = create_bm25_index('data/bm25_index_tantivy', use_tantivy=True)

# Acquire and release writer
writer = bm25.tantivy_index.writer(heap_size=64*1024*1024)
del writer
gc.collect()
bm25.tantivy_index.reload()

# Should succeed - lock released
writer2 = bm25.tantivy_index.writer(heap_size=64*1024*1024)
print('Lock released correctly!')
del writer2
gc.collect()
"
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

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [API_REFERENCE.md](API_REFERENCE.md) - API documentation
- [DATA_FLOWS.md](DATA_FLOWS.md) - Data pipeline details
- [SECURITY.md](SECURITY.md) - Security model
