# SME Research Assistant (Papyrus AI)

**Intelligent Academic Literature Research Platform**

[![CI Pipeline](https://github.com/Akamel01/papyrus-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Akamel01/papyrus-ai/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## Overview

The SME Research Assistant (production name: **Papyrus AI**) is a self-hosted, multi-user RAG (Retrieval-Augmented Generation) system designed for academic literature research. It automatically discovers, downloads, and indexes research papers, then provides an AI-powered chat interface for querying the knowledge base with proper citations.

**Production URL:** https://papyrus-ai.net

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Hybrid Search** | Combines BM25 keyword search with semantic vector search for optimal retrieval |
| **HyDE Enhancement** | Hypothetical Document Embeddings for better semantic matching |
| **Cross-Encoder Reranking** | BGE reranker for high-precision final ranking |
| **Multi-User Support** | JWT-based authentication with per-user data isolation |
| **Paper Auto-Discovery** | Integrates with OpenAlex, Semantic Scholar, arXiv, CrossRef APIs |
| **Streaming Responses** | Real-time LLM response streaming with inline citations |
| **Admin Dashboard** | React-based monitoring dashboard for pipeline control and metrics |
| **Auto-Deploy CI/CD** | GitHub Actions with webhook-based auto-deployment |

---

## System Architecture

```
                           INTERNET
                              │
                    ┌─────────▼─────────┐
                    │ Cloudflare Tunnel │
                    │ (papyrus-ai.net)  │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Caddy Proxy     │
                    │   (Port 8080)     │
                    └─────────┬─────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Auth Service   │  │ Streamlit Chat  │  │    Dashboard    │
│  (JWT/bcrypt)   │  │   Interface     │  │  (React + API)  │
│     :8000       │  │     :8501       │  │ :3000 / :8400   │
└─────────────────┘  └────────┬────────┘  └─────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│     Qdrant      │  │     Ollama      │  │      Redis      │
│  (Vector DB)    │  │  (Embeddings)   │  │    (Cache)      │
│     :6333       │  │    :11434       │  │     :6379       │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Docker Services

| Service | Container | Purpose | Port |
|---------|-----------|---------|------|
| `caddy` | sme_caddy | Reverse proxy, routing | 8080 |
| `app` | sme_app | Streamlit chat interface | 8501 |
| `auth` | sme_auth | User authentication | 8000 |
| `dashboard-ui` | sme_dashboard_ui | React monitoring dashboard | 3000 |
| `dashboard-backend` | sme_dashboard_api | Dashboard REST API | 8400 |
| `qdrant` | sme_qdrant | Vector database | 6333 |
| `ollama` | sme_ollama | Embedding & LLM serving | 11434 |
| `redis` | sme_redis | Query/result caching | 6379 |
| `cloudflared` | sme_tunnel | HTTPS tunnel | - |
| `deploy-hook` | sme_deploy_hook | Auto-deploy webhook | 9000 |
| `gpu-exporter` | sme_gpu_exporter | GPU metrics | - |

---

## Quick Start

### Prerequisites

- **Docker Desktop** 4.0+ with Docker Compose v2
- **NVIDIA GPU** (optional, but recommended for embeddings)
- **64GB RAM** recommended (16GB minimum)
- **100GB disk space** for papers and indexes

### 1. Clone and Configure

```bash
git clone https://github.com/Akamel01/papyrus-ai.git
cd papyrus-ai

# Create environment file
cp .env.example .env

# Generate secrets
python -c "import secrets; print(secrets.token_urlsafe(32))"  # For JWT_SECRET
python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"  # For MASTER_ENCRYPTION_KEY
```

Edit `.env` and fill in the required values:
```env
JWT_SECRET=your_generated_jwt_secret
MASTER_ENCRYPTION_KEY=your_generated_encryption_key
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=YourSecurePassword123!
```

### 2. Start Services

```bash
docker compose up -d
```

### 3. Pull Embedding Model

```bash
docker exec -it sme_ollama ollama pull qwen3-embedding:8b
```

### 4. Access the Application

| Service | URL |
|---------|-----|
| Chat Interface | http://localhost:8080/chat |
| Dashboard | http://localhost:8080/dashboard |
| Production | https://papyrus-ai.net |

---

## Data Pipelines

### Paper Acquisition Pipeline

```
Discovery → Download → Parse → Chunk → Embed
   │           │         │        │        │
   ▼           ▼         ▼        ▼        ▼
 APIs      PDF files   Text    Tokens   Vectors
(OpenAlex, (DataBase/) (pymupdf) (800/chunk) (Qdrant)
 S2, arXiv)
```

**Stages:**
1. **Discovery**: Query academic APIs for papers matching keywords
2. **Download**: Retrieve PDFs via Unpaywall, S2, direct DOI
3. **Parse**: Extract text with pymupdf4llm, quality scoring
4. **Chunk**: Section-aware chunking (800 tokens, 150 overlap)
5. **Embed**: Generate 4096-dim vectors via qwen3-embedding:8b

### RAG Query Pipeline

```
User Query → HyDE → Hybrid Search → Rerank → Generate → Cite
                        │
           ┌────────────┴────────────┐
           │                         │
        BM25 (0.3)           Semantic (0.7)
       (Tantivy)               (Qdrant)
```

**Components:**
- **HyDE**: Generates hypothetical documents for better retrieval
- **Hybrid Search**: Fuses BM25 keyword and semantic vector scores
- **Reranking**: BGE-reranker-v2-m3 cross-encoder for precision
- **Generation**: LLM with streaming response and inline citations

---

## Configuration

### Main Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Environment variables, secrets |
| `config/acquisition_config.yaml` | Paper discovery keywords, API settings |
| `config/config.yaml` | System settings, model configuration |
| `config/depth_presets.yaml` | Research depth presets |
| `docker-compose.yml` | Service orchestration |
| `config/cloudflared-config.yml` | Cloudflare tunnel routing |

### Key Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `JWT_SECRET` | Yes | JWT signing key (32+ chars) |
| `MASTER_ENCRYPTION_KEY` | Yes | API key encryption (32 bytes base64) |
| `ADMIN_EMAIL` | No | Initial admin account email |
| `ADMIN_PASSWORD` | No | Initial admin password (12+ chars) |
| `OPENALEX_API_KEY` | No | OpenAlex API key for paper discovery |
| `SEMANTIC_SCHOLAR_API_KEY` | No | Semantic Scholar API key |
| `DEPLOY_WEBHOOK_SECRET` | No | GitHub webhook secret for auto-deploy |

---

## CI/CD Pipeline

The project uses GitHub Actions for continuous integration and deployment.

### CI Pipeline (`.github/workflows/ci.yml`)

```
Push/PR → Lint → Security → Tests → Build → Publish
              │        │        │       │        │
           Ruff    Trivy    pytest  Docker  GHCR
           Black   Bandit            Build  Push
```

**Jobs:**
1. **Code Quality**: Ruff linting, Black formatting
2. **Security Scan**: Trivy vulnerability scanner, Bandit
3. **Unit Tests**: pytest with coverage
4. **Integration Tests**: With Redis + Qdrant services
5. **Docker Build**: Multi-service parallel builds
6. **Publish**: Push to GitHub Container Registry

### Auto-Deploy Webhook

```
CI Success → workflow_run webhook → deploy-hook service
                                          │
                                    docker compose pull
                                    docker compose up -d
```

The `deploy-hook` service listens for GitHub webhook events and automatically deploys when CI passes.

**Webhook Configuration:**
- **URL**: `https://papyrus-ai.net/deploy-webhook/webhook`
- **Events**: Workflow runs
- **Secret**: HMAC-SHA256 signature verification

---

## Directory Structure

```
SME/
├── app/                          # Streamlit chat application
│   ├── main.py                   # Entry point
│   ├── components/               # UI components
│   └── pages/                    # Streamlit pages
│
├── config/                       # Configuration files
│   ├── acquisition_config.yaml   # Paper discovery settings
│   ├── cloudflared-config.yml    # Tunnel routing
│   └── config.yaml               # System settings
│
├── dashboard/                    # Admin dashboard
│   ├── backend/                  # FastAPI REST API
│   └── frontend/                 # React + Vite UI
│
├── documentation/                # Technical documentation
│   ├── ARCHITECTURE.md          # System architecture
│   ├── API_REFERENCE.md         # API documentation
│   ├── DATA_FLOWS.md            # Pipeline details
│   ├── DEPLOYMENT_GUIDE.md      # Setup instructions
│   ├── CI_CD_GUIDE.md           # CI/CD documentation
│   └── SECURITY.md              # Security model
│
├── services/                     # Microservices
│   ├── auth/                    # Authentication service
│   ├── caddy/                   # Reverse proxy config
│   └── deploy-hook/             # Auto-deploy webhook
│
├── src/                          # Core application code
│   ├── acquisition/             # Paper discovery & download
│   ├── embedding/               # Vector embeddings
│   ├── generation/              # LLM response generation
│   ├── indexing/                # Document processing
│   ├── ingestion/               # PDF parsing
│   ├── retrieval/               # Search & RAG
│   └── storage/                 # Database operations
│
├── tests/                        # Test suite
│   ├── unit/                    # Unit tests
│   └── integration/             # Integration tests
│
├── .github/workflows/            # CI/CD pipelines
├── docker-compose.yml            # Service orchestration
├── Dockerfile                    # Main app container
└── requirements.txt              # Python dependencies
```

---

## Security

### Authentication

- **JWT Tokens**: Access (15 min) + Refresh (7 days)
- **Password Hashing**: bcrypt with cost factor 12
- **Rate Limiting**: Configurable per-endpoint limits
- **Login Lockout**: 10 failed attempts → 15 min lockout

### Data Isolation

All queries are filtered by `user_id` to ensure users only see their own data:

```python
# Every search includes user_id filter
results = vector_store.search(
    query_vector,
    filters={"user_id": current_user.id}
)
```

### API Key Encryption

User API keys (OpenAlex, Semantic Scholar) are encrypted at rest using Fernet (AES-128-CBC).

---

## Monitoring

### Dashboard Features

- **Pipeline Control**: Start/stop acquisition pipeline
- **System Metrics**: CPU, RAM, GPU utilization
- **Vector Statistics**: Qdrant collection stats
- **Audit Logs**: User activity tracking
- **DLQ Management**: Failed paper retry/skip

### Health Endpoints

| Service | Endpoint | Expected Response |
|---------|----------|-------------------|
| Auth | `/api/auth/health` | `{"status":"healthy"}` |
| App | `/chat/_stcore/health` | 200 OK |
| Dashboard | `/api/health` | `{"status":"healthy"}` |
| Deploy Hook | `/deploy-webhook/health` | `{"status":"healthy"}` |

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| "Page does not exist" | Clear browser cache, check Streamlit baseUrlPath |
| Embedding model not found | Run `docker exec -it sme_ollama ollama pull qwen3-embedding:8b` |
| Database locked | Restart the app container: `docker compose restart app` |
| Out of memory | Reduce Qdrant memory limits in docker-compose.yml |
| Webhook not triggering | Check DEPLOY_WEBHOOK_SECRET matches GitHub |

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f app
docker compose logs -f deploy-hook
```

---

## Development

### Local Development Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/
```

### Running Linters

```bash
ruff check .
black --check .
```

### Building Docker Images

```bash
docker compose build --no-cache
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](documentation/ARCHITECTURE.md) | System architecture |
| [API_REFERENCE.md](documentation/API_REFERENCE.md) | API documentation |
| [DATA_FLOWS.md](documentation/DATA_FLOWS.md) | Pipeline details |
| [DEPLOYMENT_GUIDE.md](documentation/DEPLOYMENT_GUIDE.md) | Setup instructions |
| [CI_CD_GUIDE.md](documentation/CI_CD_GUIDE.md) | CI/CD documentation |
| [CONFIGURATION.md](documentation/CONFIGURATION.md) | Configuration reference |
| [SECURITY.md](documentation/SECURITY.md) | Security model |
| [TROUBLESHOOTING.md](documentation/TROUBLESHOOTING.md) | Common issues |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes and add tests
4. Run linting: `ruff check . && black --check .`
5. Commit with conventional commits: `git commit -m "feat: add my feature"`
6. Push and create a Pull Request

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Contact

- **Repository**: https://github.com/Akamel01/papyrus-ai
- **Issues**: https://github.com/Akamel01/papyrus-ai/issues
- **Production**: https://papyrus-ai.net
