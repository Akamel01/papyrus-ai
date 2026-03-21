# SME Research Assistant - Configuration Reference

**Version:** 1.0
**Last Updated:** March 2026

---

## Table of Contents

1. [Environment Variables](#environment-variables)
2. [Main Configuration (config.yaml)](#main-configuration-configyaml)
3. [Acquisition Configuration](#acquisition-configuration)
4. [Prompt Templates](#prompt-templates)
5. [Docker Configuration](#docker-configuration)

---

## Environment Variables

**File:** `.env` (copy from `.env.example`)

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `JWT_SECRET` | JWT signing key (32+ chars) | `openssl rand -base64 32` |
| `MASTER_ENCRYPTION_KEY` | API key encryption (32 bytes base64) | `openssl rand -base64 32` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ADMIN_EMAIL` | Initial admin account email | - |
| `ADMIN_PASSWORD` | Initial admin password (min 12 chars) | - |
| `OPENALEX_API_KEY` | OpenAlex API key | - |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar API key | - |
| `SME_EMAILS` | Email for API identification | - |

### Rate Limiting Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `RATE_LIMIT_PER_MINUTE` | General API rate limit | `100` |
| `LOGIN_LOCKOUT_ATTEMPTS` | Failed logins before lockout | `10` |
| `LOGIN_LOCKOUT_MINUTES` | Lockout duration | `15` |

### Service URLs (Docker Internal)

| Variable | Description | Default |
|----------|-------------|---------|
| `QDRANT_URL` | Qdrant vector database | `http://sme_qdrant:6333` |
| `OLLAMA_URL` | Ollama embedding/LLM | `http://sme_ollama:11434` |

---

## Main Configuration (config.yaml)

**File:** `config/config.yaml`

### System Settings

```yaml
system:
  project_name: "SME Research Assistant"
  data_dir: "./data"           # Runtime data directory
  papers_dir: "./DataBase/Papers"  # PDF storage
  log_level: "INFO"            # DEBUG, INFO, WARNING, ERROR
```

### Hardware Profile

```yaml
hardware:
  gpu_vram_gb: 12              # GPU VRAM (RTX 4070 Super)
  system_ram_gb: 64            # System RAM
```

### Ingestion Settings

```yaml
ingestion:
  pdf_parser: "pymupdf4llm"    # Primary parser
  fallback_parser: "pymupdf"   # Fallback for problematic PDFs
  batch_size: 100              # Papers per batch
  max_workers: 4               # Parallel workers (adjust based on CPU)
  quality_threshold: 0.7       # Minimum parse quality (0.0-1.0)
  checkpoint_interval: 50      # Save progress every N papers
```

### Chunking Settings

```yaml
chunking:
  chunk_size: 800              # Target chunk size in tokens
  chunk_overlap: 150           # Overlap between chunks
  strategy: "hierarchical"     # doc -> section -> paragraph
  min_chunk_size: 100          # Minimum chunk size
  tokenizer: "cl100k_base"     # Tokenizer for counting
```

**Chunking Strategies:**
- `hierarchical`: Respects document structure (recommended)
- `fixed`: Fixed-size chunks regardless of structure
- `semantic`: Splits on semantic boundaries

### Embedding Settings

```yaml
embedding:
  model_name: "qwen3-embedding:8b"  # Ollama model tag
  device: "cuda"               # cuda or cpu
  batch_size: 64               # Texts per embedding batch
  normalize: true              # Normalize vectors (recommended)
  dimension: 4096              # Vector dimensions
  quantization: "4bit"         # Required for 12GB VRAM
  remote_url: "http://sme_ollama:11434"  # Ollama API URL
```

### Vector Store Settings

```yaml
vector_store:
  type: "qdrant"
  host: "sme_qdrant"           # Docker service name
  port: 6333
  collection_name: "sme_papers_v2"
  on_disk_payload: true        # Store payloads on disk
  timeout: 300                 # Request timeout (seconds)

  hnsw:
    m: 32                      # HNSW graph connectivity
    ef_construct: 128          # Construction-time search depth
    ef_search: 400             # Query-time search depth

  quantization:
    type: "int8"               # Scalar quantization type
    quantile: 0.99             # Quantile for range
    always_ram: true           # Keep quantized vectors in RAM
    oversampling: 2.0          # Oversampling factor
    rescore: true              # Rescore with original vectors
```

**HNSW Tuning Guide:**

| Parameter | Impact | Recommendation |
|-----------|--------|----------------|
| `m` | Memory vs accuracy | 16-64 (32 balanced) |
| `ef_construct` | Build time vs index quality | 100-200 |
| `ef_search` | Query speed vs accuracy | 100-500 |

### BM25 Settings

```yaml
bm25:
  index_path: "./data/bm25_index_tantivy"
  tokenizer: "word"            # word or char
  remove_stopwords: true       # Remove common words
```

### Retrieval Settings

```yaml
retrieval:
  top_k_initial: 50            # Initial candidates from each source
  top_k_rerank: 20             # Candidates to rerank
  top_k_final: 10              # Final results returned

  bm25_weight: 0.3             # Weight for BM25 scores
  semantic_weight: 0.7         # Weight for semantic scores

  use_reranker: true           # Enable cross-encoder reranking
  reranker_model: "BAAI/bge-reranker-v2-m3"
  reranker_device: "cuda"
  reranker_batch_size: 128
  reranker_max_length: 512
  reranker_dtype: "fp16"

  mmr_diversity: 0.7           # Maximal marginal relevance diversity
```

**Weight Tuning:**
- Higher `bm25_weight`: Better exact keyword matching
- Higher `semantic_weight`: Better conceptual matching
- Sum should equal 1.0

### Generation Settings

```yaml
generation:
  llm_provider: "ollama"
  model_name: "gpt-oss:120b-cloud"  # Model name in Ollama
  base_url: "http://sme_ollama:11434"
  temperature: 0.1             # Lower = more focused
  max_tokens: 2000             # Maximum response tokens
  stream: true                 # Stream responses
  timeout: 240                 # Generation timeout (seconds)
  num_ctx: 65536               # Context window size
  max_context_length: 60000    # Max input context
```

**Temperature Guide:**
- `0.0-0.3`: Factual, consistent responses (recommended for research)
- `0.3-0.7`: Balanced creativity
- `0.7-1.0`: More creative/varied

### Chat Settings

```yaml
chat:
  context_messages: 10         # Conversation history length
  persist_history: true        # Save chat history
  history_db: "./data/chat_history.db"
```

### Cache Settings

```yaml
cache:
  enabled: true
  type: "redis"
  host: "sme_redis"
  port: 6379
  ttl_query_embedding: 86400   # 24 hours
  ttl_search_results: 3600     # 1 hour
  ttl_responses: 1800          # 30 minutes
```

### Security Settings

```yaml
security:
  auth_enabled: true
  session_timeout: 3600        # Session timeout (seconds)
  max_query_length: 2000       # Maximum query characters
  audit_logging: true          # Log all queries
```

### Monitoring Settings

```yaml
monitoring:
  log_queries: true            # Log all queries
  collect_feedback: true       # Collect user feedback
  metrics_retention_days: 90   # Keep metrics for N days
  health_check_interval: 60    # Health check frequency (seconds)
```

### Resilience Settings

```yaml
resilience:
  retry_attempts: 3            # Retry failed operations
  retry_backoff_multiplier: 2  # Exponential backoff
  retry_max_wait: 30           # Max wait between retries
  circuit_breaker_threshold: 5 # Failures before circuit opens
  circuit_breaker_timeout: 60  # Circuit open duration
```

---

## Acquisition Configuration

**File:** `config/acquisition_config.yaml`

### Keywords Configuration

```yaml
acquisition:
  use_sqlite: false            # Use SQLite for 100K+ papers

  keywords:
    # Exact phrase only
    - '"Road Safety" AND "Autonomous Vehicles"'

    # Phrase with location filter
    - '"Cost of Crash" AND (\"BC\" OR \"British Columbia\")'

    # Two required phrases
    - '"Road Safety" AND "Extreme Value Theory"'
```

**Keyword Syntax:**
- `"exact phrase"`: Exact phrase matching
- `AND`: Both terms required
- `OR`: Either term matches
- `NOT`: Exclude term
- Parentheses for grouping

### API Configuration

```yaml
acquisition:
  emails:
    - "${SME_EMAILS}"          # From environment variable

  apis:
    openalex:
      enabled: true
      api_key: "${OPENALEX_API_KEY}"
      search_fields: ["title", "abstract", "keywords"]
      requests_per_minute: 60
      timeout_seconds: 30
      max_retries: 3
      results_per_page: 100

    semantic_scholar:
      enabled: true
      api_key: "${SEMANTIC_SCHOLAR_API_KEY}"
      requests_per_minute: 50
      timeout_seconds: 30
      max_retries: 3

    unpaywall:
      enabled: true
      requests_per_minute: 60
      timeout_seconds: 30

    arxiv:
      enabled: true
      requests_per_minute: 20
      timeout_seconds: 30

    crossref:
      enabled: true
      requests_per_minute: 50
      timeout_seconds: 30
```

### Search Filters

```yaml
acquisition:
  filters:
    min_year: 2020             # Oldest publication year
    max_year: "present"        # Newest (or specific year)
    max_per_keyword: 1000000   # Max results per keyword
    max_total: 10000000        # Max total papers
    discovery_batch_size: 50   # Papers per DB commit

    publication_types:
      journal_article: true
      conference_paper: true
      preprint: false
      book: false
      book_chapter: false
      review: true
      report: false
      dataset: false
      editorial: false
      thesis: false
      clinical_trial: false
      letter: false
      standard: false

    open_access_only: true     # Only free PDFs
```

### Download Settings

```yaml
acquisition:
  download:
    max_retries: 5             # Retry attempts per paper
    timeout_seconds: 120       # Download timeout
    max_file_size_mb: 100      # Max PDF size
    requests_per_minute: 60    # Rate limit
    skip_existing: true        # Skip already downloaded
    retry_failed: true         # Retry previously failed
    poll_batch_size: 20        # Papers per poll cycle
    max_workers: 4             # Concurrent downloads
```

### Error Handling

```yaml
acquisition:
  error_handling:
    rotate_emails_on_429: true
    email_cooldown_seconds: 300
    email_wait_timeout_seconds: 600
    continue_on_error: true
    max_consecutive_failures: 50
    pause_duration_seconds: 300

    pdf_fallback_chain:
      - "unpaywall"
      - "semantic_scholar"
      - "arxiv"
      - "direct_doi"
```

### State Management

```yaml
acquisition:
  state:
    state_file: "data/pipeline_state.json"
    updated_papers_dir: "DataBase/UpdatedPapers"
    interim_chunks_dir: "data/interim_chunks"
    failed_downloads_file: "data/failed_downloads.json"
    discovery_cache_file: "data/discovery_cache.json"
```

### Processing Pipeline

```yaml
processing:
  parsing_workers: 16          # CPU workers for parsing
  quality_threshold: 0.7       # Min parse quality
  chunk_size: 800              # Chunk size (tokens)
  chunk_overlap: 150           # Overlap (tokens)
  chunk_batch_size: 10         # Papers per PKL file
  embed_source_batch_size: 100 # Papers per embed poll
  update_bm25: true            # Update BM25 index
  save_interim_chunks: true    # Save chunk PKL files
  prefer_gpu: true             # Use GPU when possible
```

### Scheduling

```yaml
scheduling:
  enabled: true
  discovery_cron: "0 2 * * 0"  # Sunday 2 AM
  continuous_processing: true
  processing_check_interval: 60
  timezone: "America/Los_Angeles"
```

### Monitoring

```yaml
monitoring:
  enabled: true
  metrics_file: "data/pipeline_metrics.json"
  history_file: "data/pipeline_history.jsonl"
  heartbeat_interval_seconds: 30

  alerts:
    stuck_threshold_seconds: 300
    failure_rate_threshold: 0.20
    disk_free_threshold_gb: 10
    gpu_memory_threshold_percent: 90
    low_throughput_threshold: 0.5
```

---

## Prompt Templates

**File:** `config/prompts.yaml`

### System Prompt

The system prompt defines the AI persona:

```yaml
system_prompt: |
  You are a distinguished Research Scientist and Professor...

  YOUR PERSONA:
  - You value methodological rigor, empirical evidence...

  KNOWLEDGE SOURCE:
  Your knowledge comes ONLY from the provided context excerpts.

  CRITICAL RULES:
  1. EVERY factual claim MUST cite its source using APA format
  2. If information is NOT in the context, say so explicitly
  ...
```

### Citation Enforcement

```yaml
citation_enforcement: |
  CITATION DENSITY REQUIREMENTS:

  1. Every paragraph MUST contain at least one numbered citation [1], [2], etc.
  2. Use the source numbers from the context
  ...

  FORBIDDEN PATTERNS:
  ❌ "Studies show that..." (no citation)

  REQUIRED PATTERNS:
  ✅ "TTC is defined as... [1, 3]"
```

### Equation Formatting

```yaml
equation_format: |
  EQUATION AND SYMBOL FORMATTING:

  1. INLINE EQUATIONS: Use $...$ for inline math
     Examples: $TTC = D / V_{rel}$

  2. BLOCK EQUATIONS: Use $$...$$ for standalone equations
     Example: $$TTC = \frac{D}{V_{rel}}$$

  3. COMMON SYMBOLS:
     Greek letters: $\alpha$, $\beta$, $\gamma$
     Subscripts: $V_{rel}$, $T_{c}$
     ...
```

### Response Structure

```yaml
response_format: |
  Structure your response as a scholarly synthesis:

  1. **Direct Answer**: Concise thesis statement
  2. **Critical Analysis**: Deep examination with citations
  3. **Limitations & Gaps**: What the literature does/doesn't address
  4. **Conclusion**: Summary with confidence assessment
  5. **References**: List of cited works in APA format
```

---

## Docker Configuration

**File:** `docker-compose.yml`

### Service Resource Limits

| Service | Memory Limit | CPU Limit | GPU |
|---------|--------------|-----------|-----|
| qdrant | 48GB | - | No |
| ollama | - | - | Yes (1) |
| app | - | - | Yes (1) |
| dashboard-backend | 2GB | 2 cores | No |
| dashboard-ui | 512MB | 1 core | No |
| redis | - | - | No |

### Volume Mounts

| Volume | Purpose |
|--------|---------|
| `redis_data` | Redis persistence |
| `ollama_data` | Ollama model cache |
| `qdrant-data` | Vector database storage |
| `sme_db_data` | SQLite databases |
| `sme_hf_model_cache` | HuggingFace model cache |
| `caddy_data` | Caddy certificates |
| `caddy_config` | Caddy configuration |

### Port Mappings

| External | Internal | Service |
|----------|----------|---------|
| 8080 | 80 | Caddy (main entry) |
| 8502 | 8501 | Streamlit (direct) |
| 3030 | 3000 | Dashboard UI (direct) |

### Environment Variables in Docker

Services receive environment variables from:
1. `.env` file via `env_file` directive
2. Explicit `environment` block in compose file

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [API_REFERENCE.md](API_REFERENCE.md) - API documentation
- [DATA_FLOWS.md](DATA_FLOWS.md) - Data pipeline details
- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) - Extension guide
