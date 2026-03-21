# Multi-User Server Transformation Plan

**Date:** 2026-03-18
**Status:** PLANNING PHASE
**Mode:** Multi-Agent Simulation

---

# AGENT 1: SYSTEM ARCHITECT

## 1.1 Current State Assessment

### Verified Components (from codebase analysis)
| Component | Location | Port | Current State |
|-----------|----------|------|---------------|
| Chat UI (Streamlit) | `app/main.py` | 8502 | Single-user, hardcoded password |
| Dashboard UI | `dashboard/frontend/` | 3030 | JWT auth, single admin |
| Dashboard API | `dashboard/backend/` | Internal | FastAPI, role-based |
| Ollama | Docker container | Internal | v0.18.0, qwen3-embedding:8b |
| Qdrant | Docker container | Internal | v1.12.6, single collection |
| Redis | Docker container | Internal | Session cache (global) |
| Embedding Model | Ollama container | - | Remote via HTTP API |

### UNKNOWNS (Require Clarification)
| ID | Unknown | Options | Impact |
|----|---------|---------|--------|
| U1 | Network topology | Home network / Office / Cloud VM | Determines exposure strategy |
| U2 | Domain availability | Custom domain / IP-only / Subdomain | Affects TLS setup |
| U3 | Expected user count | 5 / 20 / 100+ concurrent | Affects scaling strategy |
| U4 | Budget constraints | Free / $50/mo / Enterprise | Affects infrastructure |
| U5 | User trust level | Internal team / External researchers / Public | Affects security posture |

## 1.2 Proposed Architecture

```
                                    INTERNET
                                        │
                                   [FIREWALL]
                                        │
                    ┌───────────────────┼───────────────────┐
                    │              REVERSE PROXY            │
                    │         (Caddy/Nginx + TLS)           │
                    │              Port 443                 │
                    └───────────────────┼───────────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           │                            │                            │
    ┌──────┴──────┐             ┌───────┴───────┐            ┌───────┴───────┐
    │  AUTH SVC   │             │   CHAT UI     │            │  DASHBOARD    │
    │  (new)      │             │  (Streamlit)  │            │   (existing)  │
    │  /api/auth  │             │  /chat        │            │  /dashboard   │
    └──────┬──────┘             └───────┬───────┘            └───────┬───────┘
           │                            │                            │
           └────────────────────────────┼────────────────────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    │           SHARED SERVICES             │
                    │  ┌─────────┐ ┌─────────┐ ┌─────────┐  │
                    │  │ Qdrant  │ │  Redis  │ │ Ollama  │  │
                    │  │(vectors)│ │(sessions)│ │(embed)  │  │
                    │  └─────────┘ └─────────┘ └─────────┘  │
                    └───────────────────────────────────────┘
```

## 1.3 Responsibility Split

### Server-Side (Host Machine)
| Responsibility | Justification |
|----------------|---------------|
| Embedding model (qwen3-embedding:8b) | GPU required, 4.7GB model, shared across users |
| Vector search (Qdrant) | Centralized index, metadata filtering per user |
| Session management (Redis) | Server-side sessions required for security |
| User authentication | Centralized credential validation |
| Paper storage (SQLite/PostgreSQL) | Shared database with user isolation |
| Audit logging | Compliance, debugging |

### User-Side (Browser/Client)
| Responsibility | Justification |
|----------------|---------------|
| Chat UI rendering | Streamlit handles in browser |
| Credential input | User enters API keys, email |
| Query composition | User types queries |
| Result viewing | Rendered in browser |

### Hybrid (User Choice)
| Component | Server Default | User Override Option |
|-----------|----------------|---------------------|
| LLM Generation | Server Ollama (gpt-oss:120b-cloud) | User's Ollama Cloud account |
| API Rate Limits | Server keys (shared pool) | User's own API keys |
| Model Selection | Server models | User-specified models |

---

# AGENT 2: BACKEND ENGINEER

## 2.1 Authentication System Design

### Current State (Problems)
```python
# app/main.py:100 - INSECURE
if password == "sme_research_2024":  # Hardcoded!
```

### Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTH SERVICE (NEW)                       │
│                    FastAPI Microservice                     │
├─────────────────────────────────────────────────────────────┤
│  Endpoints:                                                 │
│  POST /api/auth/register    → Create user account           │
│  POST /api/auth/login       → Issue JWT tokens              │
│  POST /api/auth/refresh     → Refresh access token          │
│  POST /api/auth/logout      → Invalidate session            │
│  GET  /api/auth/me          → Get current user info         │
│  PUT  /api/auth/me/keys     → Update API keys (encrypted)   │
│  GET  /api/auth/me/keys     → List API keys (masked)        │
├─────────────────────────────────────────────────────────────┤
│  Storage:                                                   │
│  - Users table (PostgreSQL or SQLite)                       │
│  - Sessions in Redis (TTL: 24h)                             │
│  - API keys encrypted with Fernet (per-user key)            │
└─────────────────────────────────────────────────────────────┘
```

## 2.2 Database Schema

```sql
-- users table
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    display_name    VARCHAR(100),
    role            VARCHAR(20) DEFAULT 'user',  -- user, admin
    created_at      TIMESTAMP DEFAULT NOW(),
    last_login      TIMESTAMP,
    is_active       BOOLEAN DEFAULT TRUE
);

-- user_api_keys table (encrypted storage)
CREATE TABLE user_api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    key_name        VARCHAR(50) NOT NULL,  -- openalex, semantic_scholar, etc.
    encrypted_value BYTEA NOT NULL,        -- Fernet encrypted
    created_at      TIMESTAMP DEFAULT NOW(),
    last_used       TIMESTAMP,
    UNIQUE(user_id, key_name)
);

-- user_preferences table
CREATE TABLE user_preferences (
    user_id         UUID PRIMARY KEY REFERENCES users(id),
    preferred_model VARCHAR(100) DEFAULT 'gpt-oss:120b-cloud',
    research_depth  VARCHAR(20) DEFAULT 'comprehensive',
    citation_style  VARCHAR(20) DEFAULT 'apa',
    ollama_mode     VARCHAR(20) DEFAULT 'server',  -- server, cloud, hybrid
    ollama_cloud_id VARCHAR(100),  -- if using personal Ollama Cloud
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- sessions table (or use Redis)
CREATE TABLE sessions (
    id              UUID PRIMARY KEY,
    user_id         UUID REFERENCES users(id),
    access_token    TEXT NOT NULL,
    refresh_token   TEXT NOT NULL,
    expires_at      TIMESTAMP NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    ip_address      INET,
    user_agent      TEXT
);

-- audit_log table
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id),
    action          VARCHAR(100) NOT NULL,
    resource        VARCHAR(100),
    details         JSONB,
    ip_address      INET,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

## 2.3 Credential Storage Strategy

### API Key Encryption Flow
```
User Input: "sk-abc123..." (plaintext)
          │
          ▼
┌─────────────────────────────────┐
│  1. Generate user_secret_key    │
│     (derived from user_id +     │
│      master_secret)             │
└─────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│  2. Encrypt with Fernet         │
│     encrypted = Fernet(key)     │
│                 .encrypt(value) │
└─────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│  3. Store in user_api_keys      │
│     (only encrypted bytes)      │
└─────────────────────────────────┘
```

### Decryption (At Runtime)
```python
def get_user_api_key(user_id: str, key_name: str) -> str:
    """Decrypt API key for use in API calls."""
    row = db.query(
        "SELECT encrypted_value FROM user_api_keys "
        "WHERE user_id = ? AND key_name = ?",
        (user_id, key_name)
    )
    if not row:
        return None

    user_secret = derive_user_key(user_id, MASTER_SECRET)
    fernet = Fernet(user_secret)
    return fernet.decrypt(row.encrypted_value).decode()
```

## 2.4 Session Management

### JWT Token Structure
```json
{
  "sub": "user-uuid-here",
  "email": "user@example.com",
  "role": "user",
  "iat": 1710720000,
  "exp": 1710720900,  // 15 min access token
  "jti": "unique-token-id"
}
```

### Session Lifecycle
```
1. Login Request
   └─> Validate credentials
   └─> Generate access_token (15 min) + refresh_token (7 days)
   └─> Store session in Redis: session:{jti} -> user_id
   └─> Return tokens to client

2. API Request
   └─> Extract Bearer token from header
   └─> Validate JWT signature
   └─> Check session exists in Redis
   └─> Attach user context to request

3. Token Refresh
   └─> Validate refresh_token
   └─> Rotate tokens (new access + refresh)
   └─> Invalidate old tokens

4. Logout
   └─> Delete session from Redis
   └─> Blacklist tokens until expiry
```

---

# AGENT 3: DEVOPS ENGINEER

## 3.1 Remote Access Strategy Options

### OPTION A: Cloudflare Tunnel (Simple, Free)

**Architecture:**
```
User Browser ──► Cloudflare Edge ──► Cloudflare Tunnel ──► Local Machine
                  (TLS handled)        (cloudflared)         (Docker)
```

**Pros:**
- Free tier available
- No port forwarding needed
- Automatic TLS certificates
- DDoS protection included
- Works behind NAT/firewall

**Cons:**
- Dependent on Cloudflare
- Slight latency (~50-100ms added)
- Requires Cloudflare account

**Setup Complexity:** LOW (1-2 hours)

**Steps:**
1. Create Cloudflare account
2. Add domain or use `*.trycloudflare.com`
3. Install cloudflared in Docker
4. Configure tunnel routes

---

### OPTION B: Reverse Proxy + Dynamic DNS (Self-Hosted)

**Architecture:**
```
User Browser ──► Dynamic DNS ──► Router (Port Forward) ──► Caddy/Nginx ──► Docker
                (duckdns.org)     (443 → server)           (TLS certs)
```

**Pros:**
- Full control
- No third-party dependency
- Lower latency
- Custom domain support

**Cons:**
- Requires port forwarding
- Exposed to internet directly
- Must manage TLS certs (Let's Encrypt)
- Dynamic IP requires DDNS

**Setup Complexity:** MEDIUM (4-8 hours)

**Steps:**
1. Configure router port forwarding (443 → server)
2. Setup DuckDNS or similar DDNS
3. Install Caddy with automatic HTTPS
4. Configure firewall rules

---

### OPTION C: Tailscale (Zero-Trust VPN)

**Architecture:**
```
User Browser ──► Tailscale Client ──► WireGuard VPN ──► Local Machine
                 (on user device)      (encrypted)       (Docker)
```

**Pros:**
- Zero-trust security model
- No port forwarding
- Works everywhere
- Encrypted tunnel

**Cons:**
- Users must install Tailscale client
- Learning curve for naive users
- Free tier limited to 100 devices

**Setup Complexity:** MEDIUM (2-4 hours)

**Steps:**
1. Create Tailscale account
2. Install Tailscale on server
3. Share invite link with users
4. Users install Tailscale + join network

---

### RECOMMENDATION

| Scenario | Recommended Option |
|----------|-------------------|
| Quick demo / testing | Option A (Cloudflare Tunnel) |
| Production with domain | Option B (Caddy + Dynamic DNS) |
| Internal team only | Option C (Tailscale) |
| Enterprise / compliance | Option B + Cloudflare proxy |

## 3.2 Docker Compose Extension

### New Services Required

```yaml
# docker-compose.multi-user.yml (extends existing)

services:
  # New: Reverse Proxy
  caddy:
    image: caddy:2.9-alpine
    container_name: sme_caddy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./config/Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - auth
      - app
      - dashboard-ui
    restart: unless-stopped

  # New: Auth Service
  auth:
    build: ./services/auth
    container_name: sme_auth
    environment:
      - DATABASE_URL=postgresql://sme:password@postgres:5432/sme
      - REDIS_URL=redis://redis:6379
      - JWT_SECRET=${JWT_SECRET}
      - MASTER_ENCRYPTION_KEY=${MASTER_ENCRYPTION_KEY}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  # New: PostgreSQL (replaces SQLite for multi-user)
  postgres:
    image: postgres:16-alpine
    container_name: sme_postgres
    environment:
      - POSTGRES_USER=sme
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=sme
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  caddy_data:
  caddy_config:
  postgres_data:
```

## 3.3 Caddyfile Configuration

```caddyfile
{
    email admin@yourdomain.com
}

yourdomain.com {
    # Auth API
    handle /api/auth/* {
        reverse_proxy auth:8000
    }

    # Chat UI (Streamlit)
    handle /chat* {
        reverse_proxy app:8501
    }

    # Dashboard UI
    handle /dashboard* {
        reverse_proxy dashboard-ui:3000
    }

    # Dashboard API
    handle /api/dashboard/* {
        reverse_proxy dashboard-backend:8400
    }

    # Default: redirect to chat
    handle {
        redir /chat permanent
    }

    # Security headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
    }
}
```

---

# AGENT 4: FRONTEND / UX ENGINEER

## 4.1 User Onboarding Flow

### Screen 1: Landing Page
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                    SME Research Assistant                   │
│                                                             │
│        AI-Powered Research Paper Discovery & Chat           │
│                                                             │
│              ┌────────────────────────┐                     │
│              │      Get Started       │                     │
│              └────────────────────────┘                     │
│                                                             │
│              Already have an account? [Sign In]             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Screen 2: Registration
```
┌─────────────────────────────────────────────────────────────┐
│                    Create Your Account                      │
│                                                             │
│  Email Address *                                            │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ you@university.edu                                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  Password *                                                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ••••••••••••                                        │    │
│  └─────────────────────────────────────────────────────┘    │
│  ✓ At least 12 characters  ✓ Contains number               │
│                                                             │
│  Display Name (optional)                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Dr. Smith                                           │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│              ┌────────────────────────┐                     │
│              │    Create Account      │                     │
│              └────────────────────────┘                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Screen 3: API Key Setup (Post-Registration)
```
┌─────────────────────────────────────────────────────────────┐
│                   Connect Your API Keys                     │
│                                                             │
│  These keys enable full paper discovery. You can add        │
│  them now or later from Settings.                           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  OpenAlex API Key                            [?]    │    │
│  │  ┌─────────────────────────────────────────────┐    │    │
│  │  │ oa_xxxxxxxxxxxxxxxxx                       │    │    │
│  │  └─────────────────────────────────────────────┘    │    │
│  │  [Get free key at openalex.org]                     │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Semantic Scholar API Key (optional)         [?]    │    │
│  │  ┌─────────────────────────────────────────────┐    │    │
│  │  │                                            │    │    │
│  │  └─────────────────────────────────────────────┘    │    │
│  │  [Request at semanticscholar.org/api]               │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────┐  ┌────────────────────────┐        │
│  │    Skip for Now     │  │  Save & Continue       │        │
│  └─────────────────────┘  └────────────────────────┘        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Screen 4: Compute Preferences
```
┌─────────────────────────────────────────────────────────────┐
│                   Choose Your Setup                         │
│                                                             │
│  How would you like to run AI models?                       │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  ● Use Server Models (Recommended)                  │    │
│  │    Fast, no setup required. Uses shared GPU.        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  ○ Use Ollama Cloud (Personal Account)              │    │
│  │    Requires Ollama account. Your usage, your quota. │    │
│  │    ┌───────────────────────────────────────────┐    │    │
│  │    │ [Sign in with Ollama]                     │    │    │
│  │    └───────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  ○ Use Local Ollama (Advanced)                      │    │
│  │    Run models on your own machine.                  │    │
│  │    ┌───────────────────────────────────────────┐    │    │
│  │    │ http://localhost:11434                    │    │    │
│  │    └───────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│              ┌────────────────────────┐                     │
│              │    Start Researching   │                     │
│              └────────────────────────┘                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 4.2 Error Handling for Naive Users

### API Key Validation Messages
```
┌─────────────────────────────────────────────────────────────┐
│  ⚠️  OpenAlex API Key Invalid                               │
│                                                             │
│  The key you entered doesn't seem to be valid.              │
│                                                             │
│  Common issues:                                             │
│  • Key should start with "oa_"                              │
│  • Key should be 24 characters long                         │
│  • Check for extra spaces                                   │
│                                                             │
│  [Get a free key] · [Try Again] · [Skip]                    │
└─────────────────────────────────────────────────────────────┘
```

### Connection Issues
```
┌─────────────────────────────────────────────────────────────┐
│  🔌 Connection Issue                                        │
│                                                             │
│  We couldn't connect to Semantic Scholar.                   │
│                                                             │
│  This might mean:                                           │
│  • Their service is temporarily down                        │
│  • Your API key has expired                                 │
│  • Rate limit exceeded (try again in 1 minute)              │
│                                                             │
│  [Check API Status] · [Use OpenAlex Only] · [Retry]         │
└─────────────────────────────────────────────────────────────┘
```

## 4.3 Settings Page (Post-Onboarding)

```
┌─────────────────────────────────────────────────────────────┐
│  Settings                                          [Logout] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Profile                                                    │
│  ├── Email: you@university.edu                              │
│  ├── Display Name: Dr. Smith                     [Edit]     │
│  └── Password: ••••••••••                [Change Password]  │
│                                                             │
│  API Keys                                                   │
│  ├── OpenAlex: oa_xxxx...xxxx               ✓   [Update]    │
│  ├── Semantic Scholar: Not configured           [Add Key]   │
│  └── Ollama Cloud: Connected                    [Disconnect]│
│                                                             │
│  Research Preferences                                       │
│  ├── Default Depth: [Comprehensive ▼]                       │
│  ├── Citation Style: [APA ▼]                                │
│  └── Model: [gpt-oss:120b-cloud ▼]                          │
│                                                             │
│  Compute Settings                                           │
│  ├── Embedding: Server (shared)                ℹ️            │
│  └── LLM Generation: [Server ▼] / Ollama Cloud / Local      │
│                                                             │
│  Data & Privacy                                             │
│  ├── Export My Data                          [Download]     │
│  └── Delete Account                          [Delete...]    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

# AGENT 5: SECURITY ENGINEER

## 5.1 Threat Model

### Threats & Mitigations

| Threat | Severity | Likelihood | Mitigation |
|--------|----------|------------|------------|
| **T1: Credential Theft** | HIGH | MEDIUM | Fernet encryption for API keys, bcrypt for passwords, HTTPS only |
| **T2: Session Hijacking** | HIGH | LOW | Short-lived JWTs (15 min), HttpOnly cookies, session binding to IP |
| **T3: Brute Force Login** | MEDIUM | HIGH | Rate limiting (5 attempts/min), account lockout after 10 failures |
| **T4: API Key Leakage** | HIGH | MEDIUM | Keys never logged, masked in UI, encrypted at rest |
| **T5: Cross-User Data Access** | CRITICAL | LOW | Mandatory user_id filters in Qdrant, SQL queries |
| **T6: Unauthorized Admin Access** | CRITICAL | LOW | Role-based access, admin actions require re-auth |
| **T7: DDoS Attack** | MEDIUM | MEDIUM | Cloudflare proxy, rate limiting per IP |
| **T8: MITM Attack** | HIGH | LOW | TLS 1.3 only, HSTS headers |
| **T9: XSS/CSRF** | MEDIUM | MEDIUM | CSP headers, CSRF tokens, sanitized inputs |
| **T10: SQL Injection** | HIGH | LOW | Parameterized queries, ORM usage |

## 5.2 Security Controls

### Authentication Controls
```
✓ Password minimum: 12 characters
✓ Password complexity: letter + number + special char
✓ Password hashing: bcrypt (work factor 12)
✓ Failed login lockout: 10 attempts → 15 min lockout
✓ Session timeout: 24 hours inactive
✓ Force re-auth for sensitive actions
```

### Network Controls
```
✓ TLS 1.3 minimum
✓ HSTS with 1-year max-age
✓ No direct database port exposure
✓ Internal Docker network for services
✓ Firewall: only 80, 443 exposed
```

### Data Controls
```
✓ API keys encrypted with Fernet (AES-128)
✓ User data isolated by user_id filter
✓ Audit log for all state changes
✓ Backups encrypted at rest
✓ GDPR: data export + deletion available
```

## 5.3 API Key Security Implementation

```python
# services/auth/crypto.py

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import base64
import os

MASTER_KEY = os.environ["MASTER_ENCRYPTION_KEY"]  # 32 bytes, base64

def derive_user_key(user_id: str) -> bytes:
    """Derive per-user encryption key from master key + user_id."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=user_id.encode(),  # User ID as salt
        iterations=100000,
    )
    key = kdf.derive(base64.b64decode(MASTER_KEY))
    return base64.urlsafe_b64encode(key)

def encrypt_api_key(user_id: str, plaintext: str) -> bytes:
    """Encrypt API key for storage."""
    fernet = Fernet(derive_user_key(user_id))
    return fernet.encrypt(plaintext.encode())

def decrypt_api_key(user_id: str, ciphertext: bytes) -> str:
    """Decrypt API key for use."""
    fernet = Fernet(derive_user_key(user_id))
    return fernet.decrypt(ciphertext).decode()
```

---

# SECTION 1 — SYSTEM OVERVIEW

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER DEVICES                                │
│    (Browser: Chrome, Firefox, Safari, Edge)                         │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTPS (TLS 1.3)
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      REVERSE PROXY (Caddy)                          │
│   - TLS termination                                                 │
│   - Rate limiting                                                   │
│   - Request routing                                                 │
│   - Security headers                                                │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│  AUTH SERVICE │       │   CHAT UI     │       │  DASHBOARD    │
│   (FastAPI)   │       │  (Streamlit)  │       │ (React + API) │
│               │       │               │       │               │
│ /api/auth/*   │       │ /chat         │       │ /dashboard    │
└───────┬───────┘       └───────┬───────┘       └───────┬───────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│   PostgreSQL  │       │    Redis      │       │    Qdrant     │
│   (users,     │       │  (sessions,   │       │  (vectors,    │
│    keys,      │       │   cache)      │       │   per-user    │
│    audit)     │       │               │       │   filtering)  │
└───────────────┘       └───────────────┘       └───────────────┘
                                │
                                ▼
                        ┌───────────────┐
                        │    Ollama     │
                        │  (embedding   │
                        │   + LLM)      │
                        │  GPU-backed   │
                        └───────────────┘
```

## Server vs User Responsibilities

| Layer | Server Responsibility | User Responsibility |
|-------|----------------------|---------------------|
| **Authentication** | Validate credentials, issue tokens | Provide email + password |
| **API Keys** | Encrypt, store, use for API calls | Provide valid API keys |
| **Embedding** | Run qwen3-embedding:8b (GPU) | None (handled by server) |
| **LLM Generation** | Default: server Ollama | Optional: personal Ollama |
| **Vector Search** | Query Qdrant with user filter | None (handled by server) |
| **Session** | Manage in Redis | Store token in browser |
| **UI Rendering** | Serve Streamlit/React | Render in browser |

---

# SECTION 2 — COMPONENT BREAKDOWN

## Component: Auth Service (NEW)

| Attribute | Value |
|-----------|-------|
| **Purpose** | User registration, login, API key management |
| **Technology** | FastAPI + SQLAlchemy + Pydantic |
| **Inputs** | HTTP requests (credentials, API keys) |
| **Outputs** | JWT tokens, user profile data |
| **Dependencies** | PostgreSQL, Redis |
| **Port** | 8000 (internal) |
| **UNKNOWNS** | OAuth2 providers (Google, GitHub) - future enhancement |

## Component: Streamlit Chat UI (MODIFIED)

| Attribute | Value |
|-----------|-------|
| **Purpose** | Research chat interface |
| **Technology** | Streamlit 1.x |
| **Inputs** | User queries, session token |
| **Outputs** | Research results, citations |
| **Dependencies** | Auth service (token validation), Qdrant, Ollama |
| **Port** | 8501 (internal) |
| **Changes Needed** | Replace hardcoded password with JWT auth |

## Component: Dashboard (MODIFIED)

| Attribute | Value |
|-----------|-------|
| **Purpose** | Admin panel, settings, metrics |
| **Technology** | React frontend + FastAPI backend |
| **Inputs** | Admin credentials, config changes |
| **Outputs** | System metrics, audit logs |
| **Dependencies** | Auth service, PostgreSQL |
| **Port** | 3000 (frontend), 8400 (backend) |
| **Changes Needed** | Integrate with centralized auth |

## Component: Qdrant (MODIFIED)

| Attribute | Value |
|-----------|-------|
| **Purpose** | Vector similarity search |
| **Technology** | Qdrant v1.12.6 |
| **Inputs** | Query vectors, user_id filter |
| **Outputs** | Relevant document chunks |
| **Dependencies** | None |
| **Port** | 6333 (internal) |
| **Changes Needed** | Add user_id to all point payloads |

## Component: Ollama (UNCHANGED)

| Attribute | Value |
|-----------|-------|
| **Purpose** | Embedding generation, LLM inference |
| **Technology** | Ollama v0.18.0 |
| **Inputs** | Text chunks (embed), prompts (generate) |
| **Outputs** | Vectors (4096-dim), generated text |
| **Dependencies** | NVIDIA GPU |
| **Port** | 11434 (internal) |
| **Changes Needed** | None (shared across users) |

---

# SECTION 3 — MULTI-USER DESIGN

## User Isolation Strategy

### Data Isolation
```
Every data point tagged with user_id:

┌─────────────────────────────────────────────────┐
│  Qdrant Point Payload                           │
├─────────────────────────────────────────────────┤
│  {                                              │
│    "user_id": "uuid-123",      ← REQUIRED       │
│    "paper_id": "doi:10.1234",                   │
│    "chunk_text": "...",                         │
│    "metadata": { ... }                          │
│  }                                              │
└─────────────────────────────────────────────────┘

All queries MUST include:
  filter=FieldCondition(key="user_id", match=user_id)
```

### Session Isolation
```
Redis key structure:

session:{session_id}     → { user_id, created_at, ip }
user:{user_id}:config    → { preferences, model_choice }
cache:{user_id}:query:{hash} → { cached_result }
```

### Resource Isolation
```
Per-user limits (enforced in middleware):

- API calls: 1000/hour
- Papers indexed: 10,000 max
- Storage: 5GB max
- Concurrent requests: 5 max
```

## Credential Storage

```
┌─────────────────────────────────────────────────────────────┐
│                     PostgreSQL                              │
├─────────────────────────────────────────────────────────────┤
│  users                                                      │
│  ├── id (UUID, PK)                                          │
│  ├── email (unique, indexed)                                │
│  ├── password_hash (bcrypt)                                 │
│  └── created_at                                             │
│                                                             │
│  user_api_keys                                              │
│  ├── id (UUID, PK)                                          │
│  ├── user_id (FK → users)                                   │
│  ├── key_name ("openalex", "semantic_scholar")              │
│  ├── encrypted_value (Fernet encrypted bytes)               │
│  └── last_used                                              │
└─────────────────────────────────────────────────────────────┘

Encryption:
- Master key stored in environment variable
- Per-user key derived via PBKDF2(master_key, user_id)
- API keys encrypted with Fernet (AES-128-CBC + HMAC)
```

## Session Lifecycle

```
1. REGISTRATION
   └─> User submits email + password
   └─> Server validates, hashes password
   └─> Creates user record
   └─> Sends verification email (UNKNOWN: email service)

2. LOGIN
   └─> User submits email + password
   └─> Server validates credentials
   └─> Generates JWT access token (15 min) + refresh token (7 days)
   └─> Stores session in Redis
   └─> Returns tokens to client

3. AUTHENTICATED REQUEST
   └─> Client sends Authorization: Bearer <token>
   └─> Middleware validates JWT signature
   └─> Checks session exists in Redis
   └─> Attaches user_id to request context
   └─> Request proceeds to handler

4. TOKEN REFRESH
   └─> Client detects access token expired
   └─> Sends refresh token to /api/auth/refresh
   └─> Server validates refresh token
   └─> Issues new token pair
   └─> Invalidates old tokens

5. LOGOUT
   └─> Client calls /api/auth/logout
   └─> Server deletes session from Redis
   └─> Adds tokens to blacklist
```

---

# SECTION 4 — REMOTE ACCESS STRATEGY

## Option A: Cloudflare Tunnel (Recommended for Quick Start)

```
Setup Time: 1-2 hours
Cost: Free (basic) / $5/mo (custom domain)
Security: High (Cloudflare handles DDoS, TLS)
```

**Architecture:**
```
User → Cloudflare Edge → cloudflared → Docker Services
```

**Pros:**
- No port forwarding required
- Works behind any NAT/firewall
- Automatic TLS certificates
- Built-in DDoS protection
- Access control via Cloudflare Zero Trust

**Cons:**
- Adds 50-100ms latency
- Requires Cloudflare account
- Data passes through Cloudflare

**Setup Steps:**
1. Create Cloudflare account
2. Install cloudflared in Docker
3. Create tunnel: `cloudflared tunnel create sme`
4. Configure routes in Caddyfile
5. Start tunnel

---

## Option B: Caddy + Dynamic DNS (Recommended for Production)

```
Setup Time: 4-8 hours
Cost: Free (DuckDNS) / $10/year (custom domain)
Security: High (with proper firewall)
```

**Architecture:**
```
User → DNS → Router (Port Forward) → Caddy → Docker Services
```

**Pros:**
- Full control over infrastructure
- Lower latency (direct connection)
- No third-party data handling
- Custom domain support

**Cons:**
- Requires router port forwarding
- Exposed to internet directly
- Must manage firewall rules
- Dynamic IP requires DDNS

**Setup Steps:**
1. Get domain or setup DuckDNS
2. Configure router port forwarding (80, 443)
3. Install Caddy with automatic HTTPS
4. Configure firewall (ufw/iptables)
5. Test TLS certificate issuance

---

## Option C: Tailscale (Recommended for Internal Teams)

```
Setup Time: 2-4 hours
Cost: Free (up to 100 devices)
Security: Very High (zero-trust VPN)
```

**Architecture:**
```
User (Tailscale client) → WireGuard VPN → Server (Tailscale)
```

**Pros:**
- Zero-trust security model
- No port forwarding needed
- Works from anywhere
- End-to-end encryption

**Cons:**
- Users must install Tailscale client
- Not browser-only (requires app)
- Free tier limited to 100 devices

**Setup Steps:**
1. Create Tailscale account
2. Install Tailscale on server
3. Generate invite link
4. Users install Tailscale + join network
5. Access via Tailscale IP

---

# SECTION 5 — USER ONBOARDING FLOW

## Step-by-Step Flow

```
STEP 1: First Visit
────────────────────
User navigates to: https://sme.yourdomain.com
→ Sees landing page with "Get Started" button
→ Clicks "Get Started"

STEP 2: Registration
────────────────────
→ Enters email address
→ Creates password (min 12 chars, complexity required)
→ Optionally enters display name
→ Clicks "Create Account"
→ [UNKNOWN: Email verification required? Skip for MVP]

STEP 3: API Key Setup
────────────────────
→ Sees API key configuration screen
→ Option A: Enters OpenAlex key (with inline help)
→ Option B: Clicks "Skip for Now"
→ Keys validated in real-time (format check + test API call)

STEP 4: Compute Preference
────────────────────
→ Sees compute options:
   • Server Models (default, recommended)
   • Ollama Cloud (requires account)
   • Local Ollama (advanced users)
→ Selects preference
→ If Ollama Cloud: redirected to OAuth flow

STEP 5: Welcome Tutorial
────────────────────
→ Brief interactive tour:
   • "This is where you type queries"
   • "This is where results appear"
   • "Click here to adjust settings"
→ Optional: dismiss immediately

STEP 6: Ready to Use
────────────────────
→ Redirected to /chat
→ Session established
→ Can start querying immediately
```

## Error Recovery Paths

```
SCENARIO: Invalid API Key
────────────────────────
→ User enters malformed key
→ Real-time validation shows error
→ Inline help: "Keys should start with 'oa_'"
→ Link to "Get a free key"
→ Option to skip and add later

SCENARIO: Forgot Password
────────────────────────
→ Click "Forgot Password" on login
→ Enter email address
→ [UNKNOWN: Email service for password reset]
→ Receive reset link
→ Set new password

SCENARIO: Session Expired
────────────────────────
→ API returns 401 Unauthorized
→ Frontend detects expired token
→ Attempts silent refresh
→ If refresh fails: redirect to login
→ Show "Session expired, please sign in again"
```

---

# SECTION 6 — HYBRID OLLAMA STRATEGY

## What Runs Where

```
┌─────────────────────────────────────────────────────────────┐
│                        SERVER                               │
├─────────────────────────────────────────────────────────────┤
│  ALWAYS on server:                                          │
│  • Embedding Model (qwen3-embedding:8b)                     │
│    → Requires GPU                                           │
│    → 4.7GB model, not practical to replicate               │
│    → Shared across all users                                │
│                                                             │
│  DEFAULT on server (can be overridden):                     │
│  • LLM Generation (gpt-oss:120b-cloud)                      │
│    → Uses Ollama Cloud via server's account                │
│    → Rate limited per user                                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     USER CHOICE                             │
├─────────────────────────────────────────────────────────────┤
│  Option 1: Use Server LLM (default)                         │
│  • User queries → Server Ollama → Response                  │
│  • Pros: Simple, no setup                                   │
│  • Cons: Shared quota, potential wait times                 │
│                                                             │
│  Option 2: Use Ollama Cloud (personal account)              │
│  • User links Ollama Cloud account via OAuth                │
│  • User's queries → User's Ollama Cloud → Response          │
│  • Pros: Personal quota, faster (dedicated)                 │
│  • Cons: Requires Ollama account + payment                  │
│                                                             │
│  Option 3: Use Local Ollama (advanced)                      │
│  • User runs Ollama on their machine                        │
│  • User configures: http://localhost:11434                  │
│  • Server sends prompts to user's local Ollama              │
│  • CHALLENGE: Server can't reach user's localhost           │
│  • SOLUTION: WebSocket bridge or user-side proxy            │
└─────────────────────────────────────────────────────────────┘
```

## Ollama Cloud Integration Flow

```
STEP 1: User selects "Use Ollama Cloud"
────────────────────────────────────────
→ User clicks "Connect Ollama Cloud" button
→ Redirected to: https://ollama.com/oauth/authorize?...

STEP 2: OAuth Authorization
────────────────────────────
→ User logs into Ollama account
→ Grants permission to SME app
→ Ollama redirects back with authorization code

STEP 3: Token Exchange
──────────────────────
→ Server exchanges code for access_token
→ Stores encrypted token in user_api_keys
→ Token used for Ollama API calls on user's behalf

STEP 4: Usage
─────────────
→ When user queries, server:
   1. Generates embedding (server Ollama - always)
   2. Retrieves relevant chunks (Qdrant)
   3. Calls LLM via user's Ollama Cloud token
   4. Returns response to user
```

## Local Ollama Challenge & Solution

**Problem:** Server cannot reach user's localhost

**Solution Options:**

```
OPTION A: WebSocket Bridge (Recommended)
────────────────────────────────────────
User's Browser          Server              User's Local Ollama
     │                    │                        │
     │ ──WebSocket────►   │                        │
     │                    │ ──"generate prompt"──► │
     │                    │                        │
     │ ◄──WebSocket────   │ ◄──"response"───────── │
     │                    │                        │

Implementation:
- User opens browser with WebSocket to server
- Server sends generation requests via WebSocket
- User's browser forwards to localhost:11434
- Results flow back via WebSocket

Pros: Works through any firewall
Cons: Requires browser to stay open

OPTION B: Tailscale Funnel
────────────────────────────
User's Machine (Tailscale) ←→ Server (Tailscale)

- User exposes localhost:11434 via Tailscale Funnel
- Server accesses user's Ollama via Tailscale IP
- Secure, encrypted, no browser required

Pros: Works in background
Cons: User must install Tailscale
```

---

# SECTION 7 — SECURITY MODEL

## Threat Matrix

| ID | Threat | Severity | Mitigation |
|----|--------|----------|------------|
| T1 | Brute force login | MEDIUM | Rate limit: 5 attempts/min, lockout after 10 |
| T2 | Session hijacking | HIGH | HttpOnly cookies, session binding to IP |
| T3 | API key theft | HIGH | Fernet encryption, masked in UI |
| T4 | Cross-user data leak | CRITICAL | Mandatory user_id filter on ALL queries |
| T5 | MITM attack | HIGH | TLS 1.3 only, HSTS |
| T6 | DDoS | MEDIUM | Cloudflare / rate limiting |
| T7 | SQL injection | HIGH | Parameterized queries, ORM |
| T8 | XSS | MEDIUM | CSP headers, input sanitization |
| T9 | Privilege escalation | CRITICAL | Role-based access, re-auth for admin |
| T10 | Insecure defaults | MEDIUM | Secure by default configuration |

## Security Controls by Layer

### Network Layer
```
✓ TLS 1.3 minimum (no TLS 1.2)
✓ HSTS with includeSubDomains
✓ Only ports 80, 443 exposed
✓ Internal services on Docker network
✓ No direct database access from internet
```

### Application Layer
```
✓ JWT tokens with 15-min expiry
✓ Refresh token rotation
✓ Session stored in Redis (not client)
✓ CSRF tokens for state-changing operations
✓ Input validation on all endpoints
```

### Data Layer
```
✓ Passwords hashed with bcrypt (work factor 12)
✓ API keys encrypted with Fernet
✓ Database at rest encryption [UNKNOWN: depends on PostgreSQL setup]
✓ Audit log for all sensitive operations
✓ User data isolated by user_id
```

### Operational Security
```
✓ No secrets in code (use environment variables)
✓ Secret rotation capability
✓ Audit logging enabled
✓ Backup encryption
✓ Incident response plan [UNKNOWN: to be defined]
```

---

# SECTION 8 — STEP-BY-STEP IMPLEMENTATION PLAN

## Phase 1: Foundation (Week 1)

### Step 1.1: Database Setup
```
□ Create PostgreSQL Docker service
□ Define schema (users, user_api_keys, sessions, audit_log)
□ Run migrations
□ Verify connectivity
```

### Step 1.2: Auth Service Scaffolding
```
□ Create services/auth/ directory
□ Setup FastAPI project structure
□ Implement database models (SQLAlchemy)
□ Add Dockerfile for auth service
```

### Step 1.3: Core Auth Endpoints
```
□ POST /api/auth/register
□ POST /api/auth/login
□ POST /api/auth/refresh
□ POST /api/auth/logout
□ GET /api/auth/me
```

### Step 1.4: API Key Management
```
□ Implement Fernet encryption module
□ PUT /api/auth/me/keys (store encrypted)
□ GET /api/auth/me/keys (return masked)
□ Test encryption/decryption roundtrip
```

## Phase 2: UI Integration (Week 2)

### Step 2.1: Streamlit Auth Integration
```
□ Remove hardcoded password from app/main.py
□ Add login page component
□ Implement JWT token handling
□ Store token in session_state
□ Add token refresh logic
```

### Step 2.2: Dashboard Auth Integration
```
□ Update dashboard frontend to use central auth
□ Remove duplicate auth from dashboard backend
□ Add unified login flow
```

### Step 2.3: Onboarding UI
```
□ Create registration page
□ Create API key setup page
□ Create compute preference page
□ Add form validation
□ Add error handling UI
```

## Phase 3: Data Isolation (Week 3)

### Step 3.1: Qdrant User Filtering
```
□ Add user_id to all Qdrant point payloads
□ Update search functions to require user_id filter
□ Test isolation (user A cannot see user B's data)
```

### Step 3.2: Database User Scoping
```
□ Add user_id columns to papers, chunks tables
□ Update all queries to include user_id WHERE clause
□ Create database migration script
```

### Step 3.3: Cache Isolation
```
□ Change Redis key structure: cache:{user_id}:...
□ Update cache read/write functions
□ Test cache isolation
```

## Phase 4: Infrastructure (Week 4)

### Step 4.1: Reverse Proxy Setup
```
□ Add Caddy service to docker-compose
□ Configure Caddyfile with routes
□ Setup TLS (Let's Encrypt or self-signed for dev)
□ Test routing
```

### Step 4.2: Remote Access Configuration
```
□ Choose access strategy (Cloudflare / Caddy / Tailscale)
□ Configure firewall rules
□ Setup dynamic DNS (if needed)
□ Test external access
```

### Step 4.3: Security Hardening
```
□ Add rate limiting middleware
□ Configure security headers
□ Setup audit logging
□ Test security controls
```

## Phase 5: Testing & Documentation (Week 5)

### Step 5.1: Integration Testing
```
□ Test full registration flow
□ Test login → query → logout flow
□ Test API key management
□ Test session expiry and refresh
```

### Step 5.2: Security Testing
```
□ Test brute force protection
□ Test cross-user data isolation
□ Test token expiry
□ Test encryption/decryption
```

### Step 5.3: Documentation
```
□ Update README with multi-user setup
□ Create user onboarding guide
□ Create admin guide
□ Document API endpoints
```

---

# SECTION 9 — OPEN QUESTIONS / UNKNOWNS

## Critical Unknowns (Blocking)

| ID | Question | Options | Recommendation |
|----|----------|---------|----------------|
| **U1** | What is the network topology? | Home network / Office / Cloud VM | Determines port forwarding feasibility |
| **U2** | Do you have a domain name? | Yes (custom) / No (use IP) / Want to buy | Affects TLS setup |
| **U3** | Expected concurrent users? | 5 / 20 / 100+ | Determines if scaling needed |
| **U4** | Is email verification required? | Yes / No | Need email service if yes |

## Important Unknowns (Non-Blocking)

| ID | Question | Options | Default if Unspecified |
|----|----------|---------|------------------------|
| **U5** | OAuth providers for login? | None / Google / GitHub | None (email+password only) |
| **U6** | User trust level? | Internal team / External researchers | External (maximum security) |
| **U7** | Budget for infrastructure? | $0 / $50/mo / Enterprise | $0 (free tier only) |
| **U8** | Data retention policy? | 30 days / 1 year / Forever | Forever (user's data) |
| **U9** | GDPR compliance required? | Yes / No | Yes (assume EU users) |

## Technical Questions to Resolve

1. **Email Service**: What service for password reset emails?
   - Options: SendGrid, AWS SES, Mailgun, self-hosted
   - Can skip for MVP (no password reset)

2. **Ollama Cloud OAuth**: Is OAuth integration available?
   - Need to verify Ollama's OAuth documentation
   - Fallback: manual API key entry

3. **Local Ollama Bridge**: Which approach?
   - WebSocket bridge (more complex, works everywhere)
   - Tailscale Funnel (simpler, requires client install)

4. **Database Choice**: PostgreSQL or SQLite?
   - PostgreSQL: Better for concurrent access
   - SQLite: Simpler, already in use
   - Recommendation: PostgreSQL for multi-user

---

# SYNTHESIS: RECOMMENDED APPROACH

## Quick Start Path (1 week)

For immediate deployment with minimal changes:

1. **Auth**: Simple email+password with JWT (no OAuth)
2. **Access**: Cloudflare Tunnel (free, no port forwarding)
3. **Isolation**: User ID metadata filtering in Qdrant
4. **Ollama**: Server-only (no user Ollama integration yet)
5. **Database**: SQLite with user_id columns added

## Production Path (4 weeks)

For robust, scalable deployment:

1. **Auth**: Full auth service with API key encryption
2. **Access**: Caddy reverse proxy with custom domain
3. **Isolation**: Complete data isolation + per-user caching
4. **Ollama**: Server + Ollama Cloud OAuth integration
5. **Database**: PostgreSQL with proper migrations

## Decision Required

Before implementation, please clarify:

1. Which deployment timeline? (Quick Start / Production)
2. Network situation? (Home / Office / Cloud)
3. Domain availability? (Yes / No / Need to purchase)
4. Expected user count? (5 / 20 / 100+)
5. Email service? (None for MVP / SendGrid / Other)

---

**Plan Status:** COMPLETE - Awaiting clarification on unknowns before implementation.
