# SME Research Assistant - User Guide

A multi-user research assistant that helps you explore academic literature using AI-powered search and generation.

---

## Table of Contents

1. [First-Time Setup](#first-time-setup)
2. [Starting the System](#starting-the-system)
3. [Creating an Account](#creating-an-account)
4. [Using the Chat Interface](#using-the-chat-interface)
5. [Quick Upload (Session Documents)](#quick-upload-session-documents)
6. [My Documents (Dashboard)](#my-documents-dashboard)
7. [Knowledge Source Selection](#knowledge-source-selection)
8. [Adding Papers to Your Library](#adding-papers-to-your-library)
9. [Using the Dashboard](#using-the-dashboard)
10. [Configuration Options](#configuration-options)
11. [Troubleshooting](#troubleshooting)

---

## First-Time Setup

### Prerequisites

- **Docker Desktop** with Docker Compose v2+
- **NVIDIA GPU** with CUDA support (RTX 3060+ recommended, 12GB+ VRAM ideal)
- **64GB RAM** recommended (32GB minimum)
- **100GB+ free disk space** for papers and vector database

### Step 1: Clone and Configure

```bash
# Navigate to the project directory
cd /path/to/SME

# Copy the environment template
cp .env.example .env
```

### Step 2: Generate Security Secrets

Edit `.env` and fill in the required values:

```bash
# Generate secure random secrets (run in terminal)
openssl rand -base64 32  # Use output for JWT_SECRET
openssl rand -base64 32  # Use output for MASTER_ENCRYPTION_KEY
```

### Step 3: Obtain API Credentials

The system requires API keys from academic data providers. Obtain these for free:

#### OpenAlex API
- **URL**: https://openalex.org/
- **Steps**:
  1. Visit https://openalex.org/
  2. API access is free - no registration required
  3. (Optional) Register for higher rate limits
  4. Add to `.env`: `OPENALEX_API_KEY=your_key_here`

#### Semantic Scholar API
- **URL**: https://www.semanticscholar.org/product/api
- **Steps**:
  1. Visit https://www.semanticscholar.org/product/api
  2. Sign up for a free account
  3. Generate API key from your account dashboard
  4. Add to `.env`: `SEMANTIC_SCHOLAR_API_KEY=your_key_here`

#### Email for API Identification
- **Add to `.env`**: `SME_EMAILS=your-email@example.com`
- Used by APIs to identify your application

Your `.env` file should look like:

```env
# ── Multi-User Authentication ──
JWT_SECRET=your_generated_jwt_secret_here
MASTER_ENCRYPTION_KEY=your_generated_encryption_key_here
ADMIN_EMAIL=admin@example.com          # Optional: Creates initial admin account
ADMIN_PASSWORD=SecurePassword123!      # Minimum 12 characters

# ── API Keys (Optional but recommended) ──
OPENALEX_API_KEY=your_openalex_key     # Get from https://openalex.org/
SEMANTIC_SCHOLAR_API_KEY=your_ss_key   # Get from https://semanticscholar.org/product/api
SME_EMAILS=your.email@example.com      # Used for API identification
```

### Step 3: Pull the Embedding Model

The system uses Ollama for embeddings. After first start, pull the required model:

```bash
# Start services first (see next section)
docker compose up -d

# Wait for Ollama to be ready, then pull the embedding model
docker exec -it sme_ollama ollama pull qwen3-embedding:8b

# Optionally, link your Ollama Cloud account for more models
docker exec -it sme_ollama ollama signin
```

---

## Starting the System

### Start All Services

```bash
# Start in detached mode
docker compose up -d

# View logs (optional)
docker compose logs -f
```

### Access Points

Once running, access the system at:

| Service | URL | Description |
|---------|-----|-------------|
| **Chat Interface** | http://localhost:8080/chat | Main research assistant UI |
| **Dashboard** | http://localhost:8080/dashboard | Paper management & monitoring |
| **Direct Streamlit** | http://localhost:8502 | Alternative chat access |

### Stop the System

```bash
docker compose down
```

### Remote Access (Optional)

The system includes Cloudflare Tunnel for free HTTPS remote access:

```bash
# View the generated tunnel URL
docker compose logs cloudflared | grep "trycloudflare.com"
```

Share the `https://xxx-yyy-zzz.trycloudflare.com` URL with your users.

---

## Creating an Account

### Registration

1. Navigate to http://localhost:8080/chat
2. Click the **"Sign Up"** tab
3. Enter your email and password (minimum 12 characters, must include letters and numbers)
4. Click **"Create Account"**

### Login

1. Navigate to http://localhost:8080/chat
2. Enter your email and password
3. Click **"Sign In"**

### Setting Up API Keys (Optional)

For enhanced paper discovery, add your API keys:

1. Click the **Settings** icon (⚙️) in the sidebar
2. Go to **"API Keys"** section
3. Add your OpenAlex and/or Semantic Scholar API keys
4. Click **"Save"**

---

## Using the Chat Interface

### Asking Research Questions

1. Type your research question in the search bar
2. Press Enter or click the arrow button
3. Wait for the AI to search your paper library and generate a response

**Example questions:**
- "What are the main findings on autonomous vehicle safety?"
- "Summarize recent research on traffic conflict analysis"
- "Compare methodologies for road safety assessment"

### Understanding the Response

Each response includes:

- **Main Answer**: AI-generated synthesis of relevant papers
- **In-text Citations**: References like [1], [2] linking to specific papers
- **References Section**: Full APA citations for all cited papers
- **Confidence Badge**: Indicates response quality (🟢 High, 🟡 Medium, 🔴 Low)

### Sidebar Options

| Option | Description |
|--------|-------------|
| **Quick Upload** | Upload temporary documents for this session |
| **Knowledge Base** | Choose data sources: Both, Shared KB Only, or My Documents Only |
| **Research Depth** | Low (fast), Medium (balanced), High (thorough) |
| **Model** | Select the LLM model for generation |
| **Sequential Mode** | Enable multi-round reasoning for complex questions |
| **Section Mode** | Generate structured responses with sections |
| **Paper Range** | Control how many papers to consider |
| **Citation Density** | Low, Medium, or High citation frequency |

### Follow-up Questions

After receiving a response, type follow-up questions in the chat input at the bottom. The system maintains conversation context.

---

## Quick Upload (Session Documents)

Quick Upload allows you to add temporary documents for immediate use in your chat session. Perfect for when you have a specific paper or document you want the AI to reference.

### How to Use

1. In the sidebar, find the **"Quick Upload"** section
2. Drag and drop a file, or click to browse
3. The document text is extracted and immediately available
4. Ask questions referencing your uploaded document

### Limits and Behavior

| Aspect | Value |
|--------|-------|
| **Max file size** | 10MB per file |
| **Max files** | 3 per session |
| **File types** | PDF, MD, TXT, DOCX |
| **Persistence** | Session only (cleared on page refresh) |
| **Priority** | Highest (always included in context) |

### Tips

- Quick Uploads are **always included** regardless of your Knowledge Source selection
- Great for asking questions about a specific paper you're reading
- Use the "X" button to remove individual files
- Refreshing the page clears all Quick Uploads

---

## My Documents (Dashboard)

My Documents allows you to upload documents permanently to your personal knowledge base. These documents go through the full embedding pipeline and become searchable.

### How to Use

1. Go to Dashboard → **My Documents** (http://localhost:8080/dashboard/documents)
2. Drag and drop files or click to browse
3. Files appear with status "Pending"
4. Click **"Process"** on individual files, or **"Process All"** for batch processing
5. Wait for status to change: Pending → Processing → Ready

### Document Statuses

| Status | Meaning |
|--------|---------|
| **Pending** | Uploaded, not yet processed |
| **Processing** | Currently being embedded (may take a few minutes) |
| **Ready** | Fully indexed and searchable |
| **Failed** | Processing error (click for details) |

### Limits

| Aspect | Value |
|--------|-------|
| **Max file size** | 50MB per file |
| **Max files** | Unlimited |
| **File types** | PDF, MD, DOCX |
| **Persistence** | Permanent (until deleted) |

### Deleting Documents

1. Click the trash icon next to any document
2. Confirm deletion
3. The document is removed from:
   - Vector database (Qdrant)
   - Keyword index (BM25)
   - Database record
   - Disk storage

You can also select multiple documents and click "Delete Selected" for batch deletion.

---

## Knowledge Source Selection

Control which documents are searched when you ask questions.

### Options

Located in the sidebar under **"Knowledge Base"**:

| Option | Description |
|--------|-------------|
| **Both (Recommended)** | Search your documents AND the shared knowledge base |
| **Shared KB Only** | Only search the shared knowledge base (papers from discovery pipeline) |
| **My Documents Only** | Only search your uploaded documents |

### Context Priority

When "Both" is selected, results are prioritized:

1. **Quick Uploads** - Always highest priority (shown first in context)
2. **My Documents** - Your uploaded and processed documents
3. **Shared KB** - Papers from the automatic discovery pipeline

### Note

Quick Uploads are **always included** regardless of your Knowledge Source selection. This ensures documents you explicitly upload to your chat session are always used.

---

## Adding Papers to Your Library

### Method 1: Automatic Discovery (Recommended)

The system can automatically discover and download papers based on your research keywords.

#### Configure Keywords

Edit `config/acquisition_config.yaml`:

```yaml
acquisition:
  keywords:
    - '"Road Safety" AND "Autonomous Vehicles"'
    - '"Traffic Conflict" AND "Computer Vision"'
    - 'your research topic here'
```

#### Run Discovery Pipeline

From the Dashboard (http://localhost:8080/dashboard):

1. Go to **"Pipeline"** section
2. Click **"Run Discovery"** to find new papers
3. Click **"Run Download"** to download PDFs
4. Click **"Run Processing"** to parse, chunk, and embed papers

Or via command line:

```bash
# Run the full pipeline (discovery → download → process)
docker exec -it sme_app python scripts/run_pipeline.py --full
```

### Method 2: Manual PDF Import

For papers you already have:

1. Place PDF files in the `DataBase/Papers/` directory
2. Run the ingestion script:

```bash
docker exec -it sme_app python scripts/ingest_papers.py --papers-dir /app/DataBase/Papers
```

### Method 3: Dashboard Upload

1. Go to http://localhost:8080/dashboard
2. Navigate to **"Papers"** section
3. Use the upload interface to add individual PDFs

### Checking Import Status

View your paper library status:

```bash
# Check database stats
docker exec -it sme_app python -c "
from src.storage.paper_db import PaperDB
db = PaperDB()
stats = db.get_stats()
print(f'Total papers: {stats[\"total\"]}')
print(f'Embedded: {stats[\"embedded\"]}')
print(f'Failed: {stats[\"failed\"]}')
"
```

---

## Using the Dashboard

Access the Dashboard at http://localhost:8080/dashboard

### My Documents

Upload and manage your personal document collection:

- **Upload**: Drag-drop or browse for PDF, MD, DOCX files (up to 50MB)
- **Process**: Click to embed documents into your searchable knowledge base
- **Status**: Track processing progress (Pending → Processing → Ready)
- **Delete**: Remove documents with full cleanup (vectors, index, files)

See [My Documents (Dashboard)](#my-documents-dashboard) for detailed instructions.

### Papers View

- View all papers in the shared library
- Filter by status (discovered, downloaded, embedded, failed)
- See paper metadata (title, authors, year, DOI)
- Monitor processing progress

### Pipeline Control

- **Discovery**: Search academic APIs for new papers
- **Download**: Fetch PDFs for discovered papers
- **Processing**: Parse, chunk, and embed papers

### System Monitoring

- GPU utilization and memory
- Qdrant vector database stats
- Pipeline health metrics

---

## Configuration Options

### Research Depth Presets

| Depth | Papers | Processing Time | Best For |
|-------|--------|-----------------|----------|
| **Low** | 3-5 | ~30 seconds | Quick lookups |
| **Medium** | 8-15 | ~1-2 minutes | General research |
| **High** | 20-35 | ~3-5 minutes | Comprehensive reviews |

### config/config.yaml

Key settings you might want to adjust:

```yaml
# Embedding model (must match Ollama model)
embedding:
  model_name: "qwen3-embedding:8b"

# Vector database collection
vector_store:
  collection_name: "sme_papers_v2"

# LLM settings
generation:
  model_name: "gpt-oss:120b-cloud"
  temperature: 0.1
  max_tokens: 2000
```

### config/acquisition_config.yaml

Paper discovery settings:

```yaml
acquisition:
  keywords:
    - 'your research keywords'

  filters:
    min_year: 2020
    open_access_only: true
```

---

## Troubleshooting

### System Won't Start

```bash
# Check service status
docker compose ps

# View logs for specific service
docker compose logs app
docker compose logs qdrant
docker compose logs ollama
```

### Embedding Model Not Found

```bash
# Pull the model manually
docker exec -it sme_ollama ollama pull qwen3-embedding:8b

# Verify it's available
docker exec -it sme_ollama ollama list
```

### Out of GPU Memory

Edit `docker-compose.yml` to reduce memory limits:

```yaml
qdrant:
  deploy:
    resources:
      limits:
        memory: 24G  # Reduce from 48G
```

### Search Returns No Results

1. Verify papers are embedded:
   ```bash
   docker exec -it sme_app python -c "
   from src.indexing import create_vector_store
   vs = create_vector_store()
   print(f'Vectors in store: {vs.count()}')
   "
   ```

2. Check BM25 index exists:
   ```bash
   ls -la data/bm25_index_tantivy/
   ```

3. Rebuild BM25 index if needed:
   ```bash
   docker exec -it sme_app python scripts/rebuild_bm25.py
   ```

### Login Issues

- Ensure `JWT_SECRET` is set in `.env`
- Check auth service is running: `docker compose logs auth`
- Clear browser cookies and try again

### Slow Performance

1. Ensure GPU is being used:
   ```bash
   docker exec -it sme_ollama nvidia-smi
   ```

2. Check Qdrant optimization status in Dashboard

3. Consider reducing `top_k_initial` in depth presets

---

## Multi-User Notes

- Each user's papers are isolated (user A cannot see user B's papers)
- Legacy papers (imported before multi-user) are visible to all users
- API keys are encrypted per-user with Fernet encryption
- Rate limiting protects against brute-force login attempts

---

## Getting Help

- **Issues**: https://github.com/anthropics/claude-code/issues
- **Logs**: `docker compose logs -f`
- **Configuration**: Check `config/config.yaml` and `config/acquisition_config.yaml`

---

*Last updated: March 2026*
