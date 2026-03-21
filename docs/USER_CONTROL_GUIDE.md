# User Control Guide - Autonomous Paper Acquisition Pipeline

This guide documents all configurable parameters for the SME Research Assistant's autonomous embedding update pipeline. All settings are in `config/acquisition_config.yaml`.

---

## Quick Reference

| What You Want To Do | Config Section | Key Setting |
|---------------------|----------------|-------------|
| Change research topics | `acquisition.keywords` | Add/remove keywords |
| Adjust rate limits | `acquisition.apis.*` | `requests_per_minute` |
| Change download retries | `acquisition.download` | `max_retries` |
| Adjust VRAM usage | `embedding` | `max_seq_length`, `processing.embedding_batch_size` |
| Schedule runs | `scheduling` | `discovery_cron` |

---

## 1. Keywords & Search Terms

**Location:** `acquisition.keywords`

```yaml
keywords:
  - "Road Safety"
  - "Transportation"
  - "Bayesian"
```

**What it does:** Defines research topics. Each keyword is searched across all enabled APIs (OpenAlex, Semantic Scholar, arXiv). Searches include **title, abstract, and keywords** - not just titles.

**Tips:**
- Broader keywords = more papers (e.g., "Transportation" → 400K+ papers)
- Add specific terms for precision (e.g., "pedestrian collision prediction")

---

## 2. Email Configuration

**Location:** `acquisition.emails`

```yaml
emails:
  - "your-email@example.com"
  - "backup@example.com"
```

**What it does:** Emails for API "polite pool" access. Multiple emails allow rotation when rate-limited.

**Why it matters:** APIs give higher rate limits to registered emails. When one email hits limits, the system automatically rotates to the next.

---

## 3. API Settings

**Location:** `acquisition.apis.{openalex|semantic_scholar|arxiv|unpaywall}`

| Setting | Description | Default |
|---------|-------------|---------|
| `enabled` | Enable/disable this API | `true` |
| `requests_per_minute` | Rate limit | Varies by API |
| `timeout_seconds` | Request timeout | `30` |
| `max_retries` | Retry attempts | `3` |
| `api_key` | Optional API key (Semantic Scholar) | `null` |

**Example - Disable arXiv:**
```yaml
apis:
  arxiv:
    enabled: false
```

---

## 4. Search Filters

**Location:** `acquisition.filters`

| Setting | Description | Default |
|---------|-------------|---------|
| `min_year` | Minimum publication year | `2015` |
| `max_per_keyword` | Max papers per keyword per source | `10000` |
| `max_total` | Max total papers per run | `50000` |
| `publication_types` | Paper types to include | journal, conference, preprint |
| `open_access_only` | Only download open access | `true` |

**Note:** Set `open_access_only: false` to discover paywalled papers (you'll need to manually acquire PDFs).

---

## 5. Download Settings

**Location:** `acquisition.download`

| Setting | Description | Default |
|---------|-------------|---------|
| `max_retries` | Download retry attempts | `5` |
| `timeout_seconds` | Download timeout | `120` |
| `max_file_size_mb` | Skip files larger than this | `100` |
| `requests_per_minute` | Download rate limit | `60` |
| `skip_existing` | Don't re-download existing PDFs | `true` |
| `retry_failed` | Retry previously failed downloads | `true` |

---

## 6. Error Handling

**Location:** `acquisition.error_handling`

| Setting | Description | Default |
|---------|-------------|---------|
| `rotate_emails_on_429` | Auto-rotate on rate limit | `true` |
| `email_cooldown_seconds` | Wait time after email rate-limited | `300` (5 min) |
| `email_wait_timeout_seconds` | Max wait for available email | `600` (10 min) |
| `continue_on_error` | Continue on individual failures | `true` |
| `max_consecutive_failures` | Failures before pause | `50` |
| `pause_duration_seconds` | Pause duration | `300` |

---

## 7. Processing Settings

**Location:** `processing`

| Setting | Description | Default |
|---------|-------------|---------|
| `parsing_workers` | CPU threads for PDF parsing | `16` |
| `quality_threshold` | Min text quality (0-1) | `0.7` |
| `chunk_size` | Chunk size in tokens | `800` |
| `chunk_overlap` | Overlap between chunks | `150` |
| `embedding_batch_size` | Embedding batch size | `4` |
| `batch_buffer_multiplier` | Buffers before processing | `8` |
| `update_bm25` | Update BM25 index | `true` |
| `prefer_gpu` | Force GPU usage | `true` |

---

## 8. Embedding Settings

**Location:** `embedding`

| Setting | Description | Default |
|---------|-------------|---------|
| `max_seq_length` | Max tokens per chunk | `4096` |
| `normalize` | Normalize vectors | `true` |

**VRAM Optimization:**
- RTX 4070 Super (12GB): Use `4096`
- RTX 3090 (24GB): Can use `8192`
- Lower = less VRAM but may truncate long texts

---

## 9. Scheduling

**Location:** `scheduling`

| Setting | Description | Default |
|---------|-------------|---------|
| `enabled` | Enable scheduled runs | `true` |
| `discovery_cron` | Discovery schedule | `"0 2 * * 0"` (Sun 2AM) |
| `continuous_processing` | Process while work exists | `true` |
| `processing_check_interval` | Check interval (seconds) | `60` |
| `timezone` | Timezone for cron | `"America/Los_Angeles"` |

**Cron Examples:**
- `"0 2 * * 0"` = Every Sunday at 2 AM
- `"0 0 * * *"` = Every day at midnight
- `"0 */6 * * *"` = Every 6 hours

---

## 10. Logging

**Location:** `logging`

| Setting | Description | Default |
|---------|-------------|---------|
| `log_file` | Log file path | `"data/autonomous_update.log"` |
| `log_level` | Log verbosity | `"INFO"` |
| `console_output` | Also log to console | `true` |

**Log levels:** DEBUG, INFO, WARNING, ERROR

---

## Running the Pipeline

```bash
# Full pipeline
docker exec sme_app python scripts/autonomous_update.py

# Test mode (10 papers)
docker exec sme_app python scripts/autonomous_update.py --test

# Discovery only
docker exec sme_app python scripts/autonomous_update.py --discover-only

# Download only
docker exec sme_app python scripts/autonomous_update.py --download-only

# Embed only
docker exec sme_app python scripts/autonomous_update.py --embed-only

# Limit papers
docker exec sme_app python scripts/autonomous_update.py --limit 100
```

---

## Common Scenarios

### "I want faster downloads"
```yaml
download:
  requests_per_minute: 120
  max_retries: 3
```

### "I'm getting rate limited too often"
```yaml
error_handling:
  email_cooldown_seconds: 600  # Wait longer
  max_consecutive_failures: 100  # Be more patient
```

### "My GPU runs out of memory"
```yaml
processing:
  embedding_batch_size: 2  # Reduce batch size
embedding:
  max_seq_length: 2048  # Shorter sequences
```

### "I want more comprehensive search"
```yaml
filters:
  min_year: 2000
  open_access_only: false
  max_per_keyword: 50000
```
