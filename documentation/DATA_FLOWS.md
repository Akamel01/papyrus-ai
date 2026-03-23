# SME Research Assistant - Data Flows

**Version:** 1.0
**Last Updated:** March 2026

---

## Table of Contents

1. [Overview](#overview)
2. [Paper Acquisition Pipeline](#paper-acquisition-pipeline)
3. [RAG Query Pipeline](#rag-query-pipeline)
4. [Authentication Flow](#authentication-flow)
5. [User Data Isolation](#user-data-isolation)
6. [Caching Strategy](#caching-strategy)

---

## Overview

The SME Research Assistant has two primary data flows:

1. **Acquisition Pipeline** (Batch): Discovers, downloads, parses, and embeds academic papers
2. **Query Pipeline** (Real-time): Processes user questions through hybrid search and LLM generation

Both pipelines respect multi-user data isolation through `user_id` filtering.

---

## Paper Acquisition Pipeline

### Pipeline Stages

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Discovery  │───►│  Download   │───►│   Parse     │───►│   Chunk     │───►│   Embed     │
│  (APIs)     │    │   (PDFs)    │    │ (PyMuPDF)   │    │ (Tokenize)  │    │ (Qdrant)    │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
      │                  │                  │                  │                  │
      ▼                  ▼                  ▼                  ▼                  ▼
   sme.db            PDFs dir           Text files        PKL chunks        Qdrant + BM25
  (metadata)                                                                  (vectors)
```

### Stage 1: Discovery

**Module:** `src/acquisition/discovery.py`
**Config:** `config/acquisition_config.yaml` → `acquisition.keywords`

**Data Flow:**
```
Keywords (config) ──► API Clients ──► Paper Metadata ──► SQLite (sme.db)
                          │
                     ┌────┴────┐
                     │         │
              OpenAlex    Semantic Scholar
```

**Process:**
1. Load keywords from `acquisition_config.yaml`
2. Query enabled APIs (OpenAlex, Semantic Scholar, arXiv, CrossRef)
3. Deduplicate by DOI
4. Apply filters (year range, publication type, open access)
5. Insert into `papers` table with `status='discovered'`

**Database Record:**
```sql
INSERT INTO papers (id, title, authors, abstract, year, doi, source, status, user_id)
VALUES (uuid, 'Paper Title', '["Author1"]', 'Abstract...', 2024, '10.1234/...',
        'openalex', 'discovered', 'user-uuid');
```

### Stage 2: Download

**Module:** `src/acquisition/downloader.py`
**Output:** `DataBase/UpdatedPapers/{paper_id}.pdf`

**Data Flow:**
```
Papers (status=discovered) ──► PDF URL Resolution ──► Download ──► Disk
                                      │
                            ┌─────────┼─────────┐
                            │         │         │
                       Unpaywall   S2 API    Direct DOI
```

**PDF Resolution Chain:**
1. Unpaywall (open access links)
2. Semantic Scholar (if available)
3. arXiv (for preprints)
4. Direct DOI resolution

**Process:**
1. Query papers with `status='discovered'`
2. Resolve PDF URL using fallback chain
3. Download with retry logic (max 5 retries)
4. Save to `DataBase/UpdatedPapers/{safe_filename}.pdf`
5. Update `status='downloaded'`, set `pdf_path`

### Stage 3: Parse

**Module:** `src/ingestion/pdf_parser.py`
**Library:** pymupdf4llm (primary), pymupdf (fallback)

**Data Flow:**
```
PDFs ──► Text Extraction ──► Quality Scoring ──► Clean Text
              │                    │
              │              Score < 0.7? ──► Try fallback parser
              │                    │
              ▼                    ▼
        Markdown output      Status update
```

**Quality Metrics:**
- Text density (chars per page)
- OCR artifact detection
- Encoding issues
- Table/figure density

**Process:**
1. Load PDF with pymupdf4llm
2. Extract text preserving structure (headings, paragraphs)
3. Calculate quality score
4. If score < 0.7, retry with fallback parser
5. Update `status='parsed'` or `status='failed'`

### Stage 4: Chunk

**Module:** `src/indexing/chunker.py`
**Strategy:** Hierarchical (document → section → paragraph)

**Data Flow:**
```
Parsed Text ──► Section Detection ──► Token Counting ──► Overlap Split ──► Chunks
                     │                      │
                Section headers        cl100k_base
                detected              tokenizer
```

**Chunk Configuration:**
```yaml
chunking:
  chunk_size: 800       # tokens
  chunk_overlap: 150    # tokens
  min_chunk_size: 100   # tokens
  tokenizer: "cl100k_base"
```

**Process:**
1. Detect section boundaries (Introduction, Methods, etc.)
2. Split sections into paragraphs
3. Tokenize using cl100k_base
4. Split into chunks with overlap
5. Save to PKL files: `data/interim_chunks/{paper_id}.pkl`

**Chunk Structure:**
```python
{
    "chunk_id": "paper_id_chunk_0",
    "text": "Chunk content...",
    "paper_id": "10.1234/example",
    "chunk_index": 0,
    "section": "Introduction",
    "metadata": {
        "title": "Paper Title",
        "authors": ["Author 1"],
        "year": 2024,
        "user_id": "user-uuid"  # CRITICAL for isolation
    }
}
```

### Stage 5: Embed (with BM25 Streaming)

**Module:** `src/pipeline/concurrent_pipeline.py`, `src/pipeline/bm25_worker.py`
**Model:** qwen3-embedding:8b (via Ollama)
**Vector Dimension:** 4096

**Data Flow:**
```
┌─────────────────────────────────────────────────────────────────────────┐
│                    CONCURRENT EMBEDDING + BM25 PIPELINE                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Chunks ──► EmbedWorker ──► Qdrant Upsert                               │
│                 │                │                                       │
│            Ollama API      sme_papers_v2                                │
│                                  │                                       │
│                          on_success callback                            │
│                                  │                                       │
│                                  ▼                                       │
│                            bm25_queue ◄─────── Resume Thread            │
│                                  │             (background)              │
│                                  ▼                                       │
│                            BM25Worker                                   │
│                                  │                                       │
│                     ┌────────────┴────────────┐                         │
│                     ▼                         ▼                         │
│              Tantivy Index             SQLite (bm25_indexed=1)          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Process:**
1. Load chunks from PKL files
2. Batch embed via Ollama (batch_size=64)
3. Upsert to Qdrant with full payload including `user_id`
4. On successful Qdrant upsert, queue item to `bm25_queue`
5. BM25Worker (separate thread) consumes queue and indexes to Tantivy
6. Mark `bm25_indexed=1` in SQLite after successful Tantivy commit
7. Update `status='embedded'`

**BM25 Streaming Benefits:**
- Embedding pipeline never blocked by BM25 indexing
- GPU stays busy processing new papers
- Resume thread handles backlog in background at startup
- Batch commits to Tantivy (50 papers or 5s timeout) for efficiency

**Qdrant Point:**
```json
{
    "id": "uuid-hash-of-chunk-id",
    "vector": [0.123, -0.456, ...],  // 4096 dims
    "payload": {
        "chunk_id": "paper_id_chunk_0",
        "text": "Chunk content...",
        "paper_id": "10.1234/example",
        "title": "Paper Title",
        "authors": ["Author 1"],
        "year": 2024,
        "section": "Introduction",
        "user_id": "user-uuid"  // CRITICAL
    }
}
```

**BM25IndexItem (Queue Data Transfer):**
```python
@dataclass
class BM25IndexItem:
    paper_unique_id: str      # e.g., "doi:10.1234/example"
    chunk_ids: List[str]      # ["chunk_0", "chunk_1", ...]
    texts: List[str]          # Chunk contents for BM25 indexing
```

**BM25 Resume at Startup:**

On container restart, any papers with `status='embedded'` but `bm25_indexed=0` are automatically queued:

```sql
-- Papers needing BM25 indexing
SELECT unique_id FROM papers
WHERE status = 'embedded' AND bm25_indexed = 0;
```

The resume thread runs in the background, allowing the main pipeline to start immediately processing new papers.

---

## RAG Query Pipeline

### Pipeline Overview

```
User Query
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RETRIEVAL PHASE                               │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐      │
│  │  HyDE   │───►│ Embed   │───►│ Search  │───►│ Rerank  │      │
│  │(optional)│   │ Query   │    │ Hybrid  │    │  BGE    │      │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘      │
└───────────────────────────────────│─────────────────────────────┘
                                    │
                                    ▼
                              Top-K Chunks
                                    │
    ┌───────────────────────────────┴───────────────────────────┐
    │                    GENERATION PHASE                        │
    │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    │
    │  │   Build     │───►│   LLM       │───►│  Format     │    │
    │  │   Prompt    │    │  Generate   │    │  Citations  │    │
    │  └─────────────┘    └─────────────┘    └─────────────┘    │
    └───────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                          Final Response with Citations
```

### Detailed Flow

#### Step 1: Query Enhancement (HyDE)

**Module:** `src/retrieval/hyde.py`
**Purpose:** Generate hypothetical document to improve retrieval

```
User Query ──► LLM (fast model) ──► Hypothetical Answer ──► Embed ──► Vector Search
```

**When Used:**
- Complex questions
- Abstract concepts
- When initial retrieval quality is low

**HyDE Prompt:**
```
Write a paragraph that would appear in an academic paper that answers:
"{user_query}"
Be specific and use technical terminology.
```

#### Step 2: Hybrid Search

**Module:** `src/retrieval/hybrid_search.py`
**Weights:** BM25 (0.3) + Semantic (0.7)

```
Query
  │
  ├──► BM25 Search (Tantivy) ──► Keyword Scores
  │                                    │
  │                                    ▼
  └──► Semantic Search (Qdrant) ──► Vector Scores ──► Fusion ──► Combined Scores
```

**Fusion Formula:**
```python
combined_score = (bm25_weight * bm25_score) + (semantic_weight * semantic_score)
```

**User Filtering:**
```python
# Both searches filter by user_id
bm25_results = bm25_index.search(query, top_k=50, user_id=user_id)
semantic_results = vector_store.search(
    query_vector,
    top_k=50,
    filters={"user_id": user_id}
)
```

#### Step 3: Reranking

**Module:** `src/retrieval/reranker.py`
**Model:** BAAI/bge-reranker-v2-m3

```
Candidate Chunks (50) ──► Cross-Encoder ──► Reranked Scores ──► Top-K (10-20)
```

**Reranker Input:**
```
[CLS] {query} [SEP] {chunk_text} [SEP]
```

**Configuration:**
```yaml
retrieval:
  reranker_model: "BAAI/bge-reranker-v2-m3"
  reranker_batch_size: 128
  reranker_max_length: 512
```

#### Step 4: Context Building

**Module:** `src/generation/prompts.py`

```
Reranked Chunks ──► Deduplicate ──► Format Context ──► Build Prompt
                        │
                   Group by paper
                   to avoid redundancy
```

**Context Format:**
```
[1] Title: Paper Title (Author, 2024)
    Section: Introduction
    Content: This study examines...

[2] Title: Another Paper (Author2, 2023)
    Section: Methods
    Content: We employed a novel approach...
```

#### Step 5: LLM Generation

**Module:** `src/generation/llm.py`
**Model:** gpt-oss:120b-cloud (via Ollama)

```
System Prompt + Context + Query ──► LLM ──► Streamed Response
```

**System Prompt:**
```
You are a research assistant helping with academic literature review.
Use the provided context to answer the question.
Cite sources using [1], [2] notation.
If information is not in the context, say so.
Be concise and accurate.
```

#### Step 6: Citation Formatting

**Module:** `src/generation/citation.py`

```
Response + Chunk Metadata ──► APA Formatter ──► References Section
```

**Output Format:**
```
Main answer text with inline citations [1][2]...

---
**References:**
[1] Author, A., & Author, B. (2024). Paper Title. *Journal Name*, 10(2), 123-145.
[2] Author, C. (2023). Another Paper. In *Conference Proceedings* (pp. 45-52).
```

---

## Authentication Flow

### Login Flow

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│ Browser │───►│  Caddy  │───►│  Auth   │───►│ SQLite  │
│         │◄───│         │◄───│ Service │◄───│ auth.db │
└─────────┘    └─────────┘    └─────────┘    └─────────┘
     │              │              │
     │   POST /api/auth/login      │
     │              │              │
     │              │    verify    │
     │              │   password   │
     │              │       ▼      │
     │              │   bcrypt     │
     │              │    check     │
     │              │       │      │
     │              │◄──────┘      │
     │   JWT Tokens │              │
     │◄─────────────┘              │
```

### Token Lifecycle

```
Login ──► Access Token (15 min) + Refresh Token (7 days)
              │
              │ API Request
              ▼
        Token Valid? ──► Yes ──► Process Request
              │
              No (expired)
              │
              ▼
        Use Refresh Token ──► New Token Pair
```

### Session Storage

```sql
-- Sessions table tracks active refresh tokens
sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    refresh_token_hash TEXT,  -- bcrypt hash
    expires_at TIMESTAMP,
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMP
)
```

---

## User Data Isolation

### Critical Paths

All data access paths must include `user_id` filtering:

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER DATA ISOLATION                          │
│                                                                 │
│  Streamlit ──► Extract user_id from JWT                        │
│      │                                                          │
│      ├──► HybridSearcher.search(query, user_id=user_id)        │
│      │         │                                                │
│      │         ├──► VectorStore.search(filters={"user_id": x}) │
│      │         └──► BM25Index.search(user_id=x)                │
│      │                                                          │
│      └──► SequentialProcessor.process(user_id=user_id)         │
│                │                                                │
│                └──► All downstream searches filtered            │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation Points

| Component | File | Method | user_id Parameter |
|-----------|------|--------|-------------------|
| Main App | `app/main.py` | `handle_query()` | Extracted from session |
| Hybrid Search | `src/retrieval/hybrid_search.py` | `search()` | Required param |
| Vector Store | `src/retrieval/vector_store.py` | `search()` | Filter condition |
| BM25 Tantivy | `src/indexing/bm25_tantivy.py` | `search()` | Filter during hydration |
| BM25 Standard | `src/indexing/bm25_index.py` | `search()` | Filter during scoring |
| HyDE | `src/retrieval/hyde.py` | `search()` | Passed to vector search |
| Sequential | `src/retrieval/sequential/search.py` | `search()` | Propagated to all calls |

### Legacy Data Handling

Papers imported before multi-user mode have `user_id = NULL`:

```python
# These papers are visible to ALL users (shared corpus)
if point_user_id is not None and point_user_id != user_id:
    continue  # Skip (belongs to different user)
# Papers with user_id = NULL are NOT skipped (legacy shared)
```

---

## Caching Strategy

### Redis Cache Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                      CACHE LAYERS                               │
│                                                                 │
│  Layer 1: Query Embedding Cache (24h TTL)                      │
│  Key: embed:{hash(query_text)}                                 │
│  Value: [0.123, -0.456, ...] (4096 floats)                     │
│                                                                 │
│  Layer 2: Search Results Cache (1h TTL)                        │
│  Key: search:{user_id}:{hash(query)}:{params_hash}             │
│  Value: [RetrievalResult, ...]                                 │
│                                                                 │
│  Layer 3: Response Cache (30min TTL)                           │
│  Key: response:{user_id}:{hash(query)}:{model}                 │
│  Value: "Generated response text..."                           │
└─────────────────────────────────────────────────────────────────┘
```

### Cache Configuration

```yaml
cache:
  enabled: true
  type: "redis"
  host: "sme_redis"
  port: 6379
  ttl_query_embedding: 86400   # 24 hours
  ttl_search_results: 3600      # 1 hour
  ttl_responses: 1800           # 30 minutes
```

### Cache Invalidation

- **On Paper Update:** Clear all search result caches
- **On Index Rebuild:** Clear all caches
- **On User Preference Change:** Clear user-specific response caches

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [API_REFERENCE.md](API_REFERENCE.md) - API endpoints
- [CONFIGURATION.md](CONFIGURATION.md) - Configuration options
- [SECURITY.md](SECURITY.md) - Security model
