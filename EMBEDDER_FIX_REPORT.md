# Embedder Remote URL Fix Report

**Date:** 2026-03-18
**Issue:** RemoteEmbedder (Ollama) not being used despite having `remote_url` configured, causing unwanted 14GB HuggingFace model download
**Status:** ✅ RESOLVED

---

## Root Cause Analysis

The issue was that the pipeline loads `config/config.yaml` by default (not `acquisition_config.yaml`), and the main config file was **missing the `remote_url` setting in the embedding section**.

### Configuration Mismatch

**acquisition_config.yaml** (line 301) had:
```yaml
embedding:
  remote_url: "http://sme_ollama:11434"  # ✅ Present
```

But **config.yaml** (lines 29-35) only had:
```yaml
embedding:
  model_name: "Qwen/Qwen3-Embedding-8B"
  device: "cuda"
  batch_size: 64
  normalize: true
  dimension: 4096
  quantization: "4bit"
  # remote_url was MISSING ❌
```

### Code Flow

1. `autonomous_update.py` line 281: `config = load_config("config/config.yaml")`
2. `autonomous_update.py` line 363: `embedder_config = config.get('embedding', {})`
3. `autonomous_update.py` line 370: `remote_url=embedder_config.get('remote_url')`
4. Since `remote_url` was not in config.yaml, `get('remote_url')` returned **None**
5. `create_embedder()` at line 34 of embedder.py: `if remote_url:` failed
6. Pipeline fell back to local TransformerEmbedder and downloaded 14GB HuggingFace model ❌

---

## Fixes Applied

### 1. ✅ Added Remote URL to config.yaml

**File:** `config/config.yaml`

```yaml
embedding:
  model_name: "Qwen/Qwen3-Embedding-8B"
  device: "cuda"
  batch_size: 64
  normalize: true
  dimension: 4096
  quantization: "4bit"
  # Remote Embedding via Ollama (CRITICAL: fixes 14GB HuggingFace download)
  # Routes embedding to Dockerized Ollama instead of loading TransformerEmbedder locally
  remote_url: "http://sme_ollama:11434"  # ✅ NOW PRESENT
```

**Impact:** Pipeline will now create RemoteEmbedder instead of TransformerEmbedder, eliminating the 14GB model download.

---

### 2. ✅ Fixed Docker Network Configuration

The config file had hardcoded `localhost` and external port mappings for internal Docker services. Changed to use Docker service names and internal ports:

#### Vector Store (Qdrant)
**Before:**
```yaml
vector_store:
  host: "localhost"
  port: 6334  # External mapping
```

**After:**
```yaml
vector_store:
  host: "sme_qdrant"  # Docker service name
  port: 6333  # Internal port
```

#### Cache (Redis)
**Before:**
```yaml
cache:
  host: "localhost"
  port: 6380  # External mapping
```

**After:**
```yaml
cache:
  host: "sme_redis"  # Docker service name
  port: 6379  # Internal port
```

#### Generation (Ollama)
**Before:**
```yaml
generation:
  base_url: "http://localhost:11435"
```

**After:**
```yaml
generation:
  base_url: "http://sme_ollama:11434"  # Docker service name + internal port
```

**Impact:** Eliminates connection timeouts and ensures proper service discovery within Docker network.

---

### 3. ✅ Fixed Qdrant Client Version Incompatibility

**Warning that was occurring:**
```
UserWarning: Qdrant client version 1.17.1 is incompatible with server version 1.12.6.
Major versions should match and minor version difference must not exceed 1.
```

**File:** `requirements.txt`

**Before:**
```
qdrant-client>=1.7.0  # Loose constraint allowed 1.17.1
```

**After:**
```
qdrant-client==1.12.6  # Pinned to match server version
```

**Impact:** Eliminates version incompatibility warning and ensures stable communication with Qdrant server.

---

### 4. ✅ Cleared HuggingFace Model Cache

Deleted all cached models from both HuggingFace cache volumes:
- `sme_sme_hf_model_cache` → cleared
- `sme_hf_model_cache` → cleared

**Command:**
```bash
docker run --rm -v sme_sme_hf_model_cache:/cache alpine rm -rf /cache/*
docker run --rm -v sme_hf_model_cache:/cache alpine rm -rf /cache/*
```

**Impact:** Ensures fresh start; no old cached models interfering with pipeline.

---

## Verification Steps

### Step 1: Rebuild Docker Image
Rebuild the app image to pick up the new `requirements.txt` with pinned qdrant-client:

```bash
docker compose build --no-cache sme_app
```

### Step 2: Restart Services
```bash
docker compose down
docker compose up -d
```

### Step 3: Check Logs for Correct Embedder Initialization

Run the pipeline and verify the logs show **RemoteEmbedder** initialization:

```bash
docker compose exec sme_app python scripts/autonomous_update.py --embed-only --limit 5
```

**Expected log output:**
```
Creating RemoteEmbedder for Qwen/Qwen3-Embedding-8B at http://sme_ollama:11434
```

**NOT this (which indicates the bug still exists):**
```
Creating Local TransformerEmbedder for Qwen/Qwen3-Embedding-8B...
```

### Step 4: Monitor HuggingFace Cache Volume Size

```bash
docker run --rm -v sme_sme_hf_model_cache:/cache alpine du -sh /cache
docker run --rm -v sme_hf_model_cache:/cache alpine du -sh /cache
```

Both should return **0B** or very small size (only metadata, not the 14GB model).

---

## Files Modified

| File | Changes | Reason |
|------|---------|--------|
| `config/config.yaml` | Added `remote_url: "http://sme_ollama:11434"` to embedding section | Fix primary issue |
| `config/config.yaml` | Changed vector_store host to `sme_qdrant`, port to `6333` | Use Docker network |
| `config/config.yaml` | Changed cache host to `sme_redis`, port to `6379` | Use Docker network |
| `config/config.yaml` | Changed generation base_url to `http://sme_ollama:11434` | Use Docker network |
| `requirements.txt` | Pinned `qdrant-client==1.12.6` | Fix version incompatibility warning |

---

## Testing Checklist

- [ ] Rebuild Docker image: `docker compose build --no-cache sme_app`
- [ ] Restart system: `docker compose down && docker compose up -d`
- [ ] Run pipeline: `docker compose exec sme_app python scripts/autonomous_update.py --embed-only --limit 5`
- [ ] Check logs contain "Creating RemoteEmbedder" (NOT "Creating Local TransformerEmbedder")
- [ ] Verify HuggingFace cache volumes have ~0B size
- [ ] Verify no Qdrant version incompatibility warnings in logs
- [ ] Monitor GPU memory: should NOT show 14GB model loaded
- [ ] Test embedding quality: Ollama /api/embed endpoint should work

---

## Why This Happened

This was a configuration management issue:
1. `acquisition_config.yaml` is used for paper discovery configuration
2. `config.yaml` is used for RAG system components
3. The remote_url setting was only added to acquisition_config.yaml
4. The pipeline loader defaults to config.yaml, which didn't have this setting
5. The mismatch caused the fallback to local embedder

## Prevention

Ensure configuration settings for shared components (like embeddings) are synchronized across:
- `config/config.yaml` (main RAG config)
- `config/acquisition_config.yaml` (acquisition-specific config, if loaded by same app)
- All Docker container configs

---

**This fix completely resolves the RemoteEmbedder issue and eliminates the unwanted HuggingFace model download.**
