# SME Research Assistant - Technical Documentation

**Version:** 1.0
**Last Updated:** March 2026

---

## Documentation Index

This folder contains comprehensive technical documentation for the SME Research Assistant system.

### Core Documents

| Document | Description | Audience |
|----------|-------------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, components, and technology stack | All developers |
| [API_REFERENCE.md](API_REFERENCE.md) | Complete API endpoints and interfaces | Backend developers |
| [DATA_FLOWS.md](DATA_FLOWS.md) | Data pipelines and processing flows | All developers |
| [CONFIGURATION.md](CONFIGURATION.md) | Configuration options reference | Operators, DevOps |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | How to extend and modify the system | Developers |
| [SECURITY.md](SECURITY.md) | Security model and audit checklist | Security, Auditors |

### Operations Documents

| Document | Description | Audience |
|----------|-------------|----------|
| [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) | Step-by-step deployment instructions | Operators, Non-technical users |
| [CI_CD_GUIDE.md](CI_CD_GUIDE.md) | CI/CD pipeline and auto-deploy setup | DevOps, Developers |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues and solutions | All users |
| [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) | Security incident procedures | Security, Operators |
| [../RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) | Pre-release verification checklist | Developers, QA |

### Performance Documents

| Document | Description | Audience |
|----------|-------------|----------|
| [QUERY_WORKFLOW.md](QUERY_WORKFLOW.md) | Query processing workflow (High depth + Section mode) | Developers, Performance Engineers |

### User Documentation

| Document | Description | Audience |
|----------|-------------|----------|
| [../USER_GUIDE.md](../USER_GUIDE.md) | End-user setup and usage guide | End users |

---

## Quick Links

### For New Developers

1. Start with [ARCHITECTURE.md](ARCHITECTURE.md) to understand the system structure
2. Read [DATA_FLOWS.md](DATA_FLOWS.md) to understand how data moves
3. Follow [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) to set up your environment

### For Adding Features

1. Check [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) for patterns and examples
2. Review [API_REFERENCE.md](API_REFERENCE.md) for existing interfaces
3. **Critical:** Read [SECURITY.md](SECURITY.md) for user isolation requirements

### For Operations/DevOps

1. Start with [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for setup instructions
2. Review [CONFIGURATION.md](CONFIGURATION.md) for all config options
3. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues
4. Read [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) for emergency procedures

### For Security Audits

1. Start with [SECURITY.md](SECURITY.md) - contains audit checklist
2. Review [DATA_FLOWS.md](DATA_FLOWS.md) for data isolation points
3. Check [API_REFERENCE.md](API_REFERENCE.md) for authentication flows
4. Review [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) for incident procedures

### For Performance Optimization

1. Read [QUERY_WORKFLOW.md](QUERY_WORKFLOW.md) for complete query pipeline analysis
2. Review LLM call inventory and token usage breakdown
3. Check optimization opportunities table (11 identified)
4. Monitor latency breakdown (reranking = 45% of time)

### For First-Time Deployment

1. Follow [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) step-by-step
2. Use `scripts/deploy.sh` for automated setup
3. Run `scripts/validate.sh` to verify installation
4. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) if issues arise

### For CI/CD Setup

1. Start with [CI_CD_GUIDE.md](CI_CD_GUIDE.md) for pipeline overview
2. Configure GitHub Actions secrets
3. Set up deploy-hook service for auto-deployment
4. Configure GitHub webhook for workflow_run events

---

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   SME Research Assistant                    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Paper Acquisition Pipeline              │   │
│  │  Discovery → Download → Parse → Chunk → Embed       │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Data Storage Layer                      │   │
│  │  Qdrant (vectors) │ Tantivy (BM25) │ SQLite (meta)  │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │               RAG Query Pipeline                     │   │
│  │  HyDE → Hybrid Search → Rerank → Generate → Cite    │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Multi-User Layer                        │   │
│  │  Auth (JWT) │ Data Isolation │ API Key Encryption   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Technologies

| Category | Technology | Purpose |
|----------|------------|---------|
| Orchestration | Docker Compose | Service management |
| Vector DB | Qdrant | Semantic search |
| BM25 Index | Tantivy | Keyword search |
| Embedding | qwen3-embedding:8b | 4096-dim vectors |
| LLM | gpt-oss:120b-cloud | Response generation |
| Auth | JWT + bcrypt | User authentication |
| Encryption | Fernet (AES-128) | API key storage |
| Cache | Redis | Query caching |
| Tunnel | Cloudflare | HTTPS access |
| CI/CD | GitHub Actions | Automated testing/deployment |
| Registry | GitHub Container Registry | Docker image storage |
| Auto-Deploy | Webhook + deploy-hook | CI-triggered deployment |

---

## Critical Security Notes

### User Data Isolation

**EVERY data access must include user_id filtering:**

```python
# CORRECT
results = search(query, user_id=current_user.id)

# WRONG - Security vulnerability!
results = search(query)
```

See [SECURITY.md](SECURITY.md) for complete audit checklist.

### Environment Secrets

Required secrets in `.env`:
- `JWT_SECRET` - JWT signing key (32+ chars)
- `MASTER_ENCRYPTION_KEY` - API key encryption (32 bytes base64)

Generate with: `openssl rand -base64 32`

---

## Contributing to Documentation

When updating documentation:

1. Update the relevant document
2. Update "Last Updated" date
3. Update this README if adding new documents
4. Ensure cross-references are correct

---

## Document Maintenance

| Document | Owner | Update Frequency |
|----------|-------|------------------|
| ARCHITECTURE.md | Lead Developer | On major changes |
| API_REFERENCE.md | Backend Team | On API changes |
| DATA_FLOWS.md | All Developers | On pipeline changes |
| CONFIGURATION.md | DevOps | On config changes |
| DEVELOPMENT_GUIDE.md | Lead Developer | Quarterly |
| SECURITY.md | Security Team | On security changes |
| DEPLOYMENT_GUIDE.md | DevOps | On deployment changes |
| TROUBLESHOOTING.md | All Teams | As issues discovered |
| INCIDENT_RESPONSE.md | Security Team | Annually or after incidents |
