# SME Research Assistant - Security Documentation

**Version:** 1.0
**Last Updated:** March 2026

---

## Table of Contents

1. [Security Overview](#security-overview)
2. [Authentication System](#authentication-system)
3. [Data Isolation Model](#data-isolation-model)
4. [Encryption](#encryption)
5. [Rate Limiting & Brute Force Protection](#rate-limiting--brute-force-protection)
6. [Network Security](#network-security)
7. [Security Audit Checklist](#security-audit-checklist)
8. [Vulnerability Considerations](#vulnerability-considerations)

---

## Security Overview

The SME Research Assistant implements a multi-layered security model:

```
┌─────────────────────────────────────────────────────────────────┐
│                      SECURITY LAYERS                            │
│                                                                 │
│  Layer 1: Network (Cloudflare + Caddy)                         │
│  ├── TLS termination at Cloudflare                             │
│  ├── DDoS protection                                           │
│  └── Internal services not exposed                             │
│                                                                 │
│  Layer 2: Authentication (JWT + bcrypt)                        │
│  ├── Access tokens (15 min)                                    │
│  ├── Refresh tokens (7 days)                                   │
│  └── Rate limiting per IP                                      │
│                                                                 │
│  Layer 3: Data Isolation (user_id filtering)                   │
│  ├── Qdrant filter: {"user_id": "xxx"}                         │
│  ├── BM25 hydration filter                                     │
│  └── Database queries filtered                                 │
│                                                                 │
│  Layer 4: Encryption (Fernet)                                  │
│  └── API keys encrypted at rest                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Authentication System

### Password Security

**Implementation:** `services/auth/auth.py`

| Aspect | Implementation |
|--------|----------------|
| Algorithm | bcrypt |
| Work Factor | 12 |
| Storage | Hashed only (never plaintext) |
| Minimum Length | 12 characters |
| Requirements | Must contain letters AND numbers |

```python
# Password validation rules
def validate_password(password: str) -> bool:
    if len(password) < 12:
        return False
    if not re.search(r"[A-Za-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    return True
```

### JWT Token Security

**Implementation:** `services/auth/auth.py`

| Token Type | Expiry | Purpose |
|------------|--------|---------|
| Access Token | 15 minutes | API authentication |
| Refresh Token | 7 days | Token renewal |

**Token Structure:**
```json
{
    "sub": "user-uuid",
    "email": "user@example.com",
    "role": "user",
    "type": "access",
    "exp": 1711008000,
    "iat": 1711007100
}
```

**Security Measures:**
- Tokens signed with `JWT_SECRET` (HS256)
- Token type validated (`access` vs `refresh`)
- Sessions stored in database with hashed refresh token
- Logout invalidates all user sessions

### Session Management

**Database:** `data/auth.db` - `sessions` table

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    refresh_token_hash TEXT NOT NULL,  -- bcrypt hash
    expires_at TIMESTAMP NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Session Operations:**
- Login: Creates new session, stores hashed refresh token
- Refresh: Validates refresh token, creates new session
- Logout: Deletes all user sessions

---

## Data Isolation Model

### Multi-User Isolation

Every data access path filters by `user_id` to ensure users can only see their own data.

### Critical Code Paths

| Component | File | Method | Isolation Point |
|-----------|------|--------|-----------------|
| Main App | `app/main.py:1166-1172` | `handle_query()` | Extracts user_id from session |
| Hybrid Search | `src/retrieval/hybrid_search.py:125` | `search()` | Passes user_id to BM25 |
| Vector Store | `src/indexing/vector_store.py` | `search()` | Qdrant filter condition |
| Vector Store | `src/indexing/vector_store.py` | `delete()` | user_id filter on delete |
| Vector Store | `src/indexing/vector_store.py` | `check_existing_ids()` | user_id filter on ID check |
| BM25 Tantivy | `src/indexing/bm25_tantivy.py:180-272` | `search()` | Filter during hydration |
| BM25 Standard | `src/indexing/bm25_index.py:130-199` | `search()` | Filter during scoring |
| HyDE Search | `src/retrieval/hyde.py:66-116` | `search()` | Injects user_id filter |
| Sequential | `src/retrieval/sequential/search.py:147` | Various | Propagates to all calls |

### Deprecated/Unsafe Code Paths

| Component | File | Status | Reason |
|-----------|------|--------|--------|
| Parallel Search | `src/retrieval/parallel_search.py` | **DEPRECATED** | No user_id support - do NOT use |

### Isolation Implementation

**Qdrant Filter:**
```python
# src/retrieval/vector_store.py
from qdrant_client.models import Filter, FieldCondition, MatchValue

def search(self, query_vector, top_k, user_id=None, **kwargs):
    filter_conditions = []

    if user_id:
        filter_conditions.append(
            FieldCondition(
                key="user_id",
                match=MatchValue(value=user_id)
            )
        )

    results = self.client.search(
        collection_name=self.collection_name,
        query_vector=query_vector,
        limit=top_k,
        query_filter=Filter(must=filter_conditions) if filter_conditions else None
    )
```

**BM25 Filter (Tantivy):**
```python
# src/indexing/bm25_tantivy.py
def search(self, query, top_k, user_id=None):
    # Fetch extra results to account for filtering
    fetch_k = top_k * 3 if user_id else top_k

    # Get BM25 scores from Tantivy
    bm25_results = self._tantivy_search(query, fetch_k)

    # Hydrate from Qdrant and filter
    for chunk_id in bm25_results:
        point = self.qdrant_client.retrieve(chunk_id)
        point_user_id = point.payload.get("user_id")

        # CRITICAL: Filter by user_id
        if user_id and point_user_id is not None:
            if point_user_id != user_id:
                continue  # Skip - belongs to different user

        # Legacy data (user_id = NULL) is visible to all
        results.append(point)
```

### Legacy Data Handling

Papers imported before multi-user mode have `user_id = NULL`:
- These papers are visible to ALL users (shared corpus)
- This is intentional for backwards compatibility
- New papers are always assigned to the uploading user

```python
# Legacy data check
if point_user_id is not None and point_user_id != user_id:
    continue  # Skip (different user)
# If point_user_id is None, include it (legacy shared data)
```

### Knowledge Source Filtering

The system supports three knowledge source modes controlled via the Chat UI sidebar:

| Mode | Behavior | Qdrant Filter |
|------|----------|---------------|
| `shared_only` | Only shared KB | `IsNull(user_id)` |
| `user_only` | Only user's docs | `Match(user_id, value)` |
| `both` | User docs + shared | `Should([Match(user_id), IsNull(user_id)])` |

**Implementation (Qdrant):**
```python
# src/indexing/vector_store.py
if knowledge_source == "shared_only":
    conditions.append(IsNullCondition(is_null=PayloadField(key="user_id")))
elif knowledge_source == "user_only":
    conditions.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))
elif knowledge_source == "both":
    # OR condition: user's docs OR shared docs
    filter = Filter(should=[
        FieldCondition(key="user_id", match=MatchValue(value=user_id)),
        IsNullCondition(is_null=PayloadField(key="user_id"))
    ])
```

**Quick Uploads (Session Documents):**
- Always included regardless of knowledge source toggle
- Stored in Streamlit session state only
- Not persisted or indexed
- Highest priority in context

### Document Cascade Delete

When a user deletes a document, cleanup happens in strict order:

1. **Qdrant** - Delete vector embeddings with user_id filter
2. **BM25 Tantivy** - Delete keyword index entries
3. **SQLite** - Delete paper record with ownership check
4. **Disk** - Delete source file from `/data/user_documents/{user_id}/`

```python
# Ownership verification before delete
paper = paper_store.get_user_paper(document_id, user_id)
if not paper:
    raise HTTPException(404, "Document not found or not owned by you.")
```

---

## Encryption

### API Key Encryption

**Implementation:** `services/auth/crypto.py`

| Aspect | Implementation |
|--------|----------------|
| Algorithm | Fernet (AES-128-CBC + HMAC-SHA256) |
| Key Derivation | MASTER_KEY + user_id → per-user key |
| Storage | Encrypted BLOB in SQLite |

```python
# Key derivation
def derive_user_key(user_id: str) -> bytes:
    """Derive per-user encryption key from master key."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=user_id.encode(),
        iterations=100000
    )
    return base64.urlsafe_b64encode(
        kdf.derive(MASTER_ENCRYPTION_KEY.encode())
    )

# Encryption
def encrypt_api_key(user_id: str, plaintext: str) -> bytes:
    key = derive_user_key(user_id)
    f = Fernet(key)
    return f.encrypt(plaintext.encode())

# Decryption
def decrypt_api_key(user_id: str, ciphertext: bytes) -> str:
    key = derive_user_key(user_id)
    f = Fernet(key)
    return f.decrypt(ciphertext).decode()
```

### Key Display

API keys are never shown in full:
```python
def mask_api_key(key: str) -> str:
    """Show only last 4 characters."""
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]
```

---

## Rate Limiting & Brute Force Protection

### Implementation

**File:** `services/auth/main.py` (lines 20-98)

### Rate Limits

| Endpoint | Limit | Window |
|----------|-------|--------|
| `/api/auth/register` | 10 requests | 1 minute |
| `/api/auth/login` | 100 requests | 1 minute |
| `/api/auth/refresh` | 30 requests | 1 minute |
| Dashboard API | 200 requests | 1 minute |

### Login Lockout

| Setting | Value | Environment Variable |
|---------|-------|---------------------|
| Failed Attempts | 10 | `LOGIN_LOCKOUT_ATTEMPTS` |
| Lockout Duration | 15 minutes | `LOGIN_LOCKOUT_MINUTES` |

```python
class RateLimiter:
    def record_failed_login(self, ip: str) -> bool:
        """Record failed login. Returns True if now locked out."""
        current_count = self.failed_logins.get(ip, (0, 0))[0]
        new_count = current_count + 1

        if new_count >= LOGIN_LOCKOUT_ATTEMPTS:
            lockout_until = time.time() + (LOGIN_LOCKOUT_MINUTES * 60)
            self.failed_logins[ip] = (new_count, lockout_until)
            return True

        self.failed_logins[ip] = (new_count, 0)
        return False

    def clear_failed_logins(self, ip: str):
        """Clear on successful login."""
        if ip in self.failed_logins:
            del self.failed_logins[ip]
```

---

## Network Security

### Architecture

```
Internet ──► Cloudflare (TLS) ──► Caddy ──► Services
                  │
                  └── DDoS Protection
                  └── WAF Rules
                  └── Rate Limiting
```

### Service Exposure

| Service | External Port | Internal Port | Exposed |
|---------|---------------|---------------|---------|
| Caddy | 8080 | 80 | Yes (reverse proxy) |
| Streamlit | 8502 | 8501 | Optional (direct access) |
| Auth | - | 8000 | No (internal only) |
| Qdrant | - | 6333 | No (internal only) |
| Ollama | - | 11434 | No (internal only) |
| Redis | - | 6379 | No (internal only) |

### Cloudflare Tunnel

- Auto-generated TLS certificates
- No port forwarding required
- DDoS protection included
- IP addresses hidden

```bash
# Get tunnel URL
docker compose logs cloudflared | grep "trycloudflare.com"
```

---

## Security Audit Checklist

### Authentication

- [ ] JWT_SECRET is at least 32 characters
- [ ] JWT_SECRET is randomly generated
- [ ] MASTER_ENCRYPTION_KEY is at least 32 bytes
- [ ] Passwords require 12+ characters
- [ ] Passwords require letters AND numbers
- [ ] Failed login lockout is working
- [ ] Rate limiting is active
- [ ] Sessions are invalidated on logout

### Data Isolation

- [ ] All Qdrant searches include user_id filter
- [ ] BM25 searches filter by user_id during hydration
- [ ] HyDE search passes user_id to vector search
- [ ] Sequential search propagates user_id
- [ ] Database queries filter by user_id
- [ ] Cache keys include user_id prefix
- [ ] Test: User A cannot see User B's papers

### Knowledge Source Isolation

- [ ] `shared_only` mode only returns user_id=NULL documents
- [ ] `user_only` mode only returns matching user_id documents
- [ ] `both` mode correctly combines with OR logic
- [ ] Document delete verifies ownership before cascade
- [ ] Quick uploads stay in session only (not persisted)
- [ ] My Documents API validates user ownership on all operations

### Encryption

- [ ] API keys are encrypted at rest
- [ ] Master key is in environment only (not in code)
- [ ] API keys are masked in UI (show last 4 chars)
- [ ] No plaintext secrets in logs

### Network

- [ ] Internal services not exposed to internet
- [ ] Cloudflare tunnel working (HTTPS)
- [ ] CORS origins are restricted in production
- [ ] Security headers configured

### Code Review Points

```python
# AUDIT: Check for these patterns

# GOOD - User isolation present
results = search(query, user_id=user_id)

# BAD - Missing user isolation (SECURITY VULNERABILITY)
results = search(query)

# GOOD - Sensitive data masked
logger.info(f"User logged in: {email}")

# BAD - Sensitive data exposed
logger.info(f"User logged in with password: {password}")

# GOOD - Parameterized query
cursor.execute("SELECT * FROM papers WHERE user_id = ?", (user_id,))

# BAD - SQL injection vulnerability
cursor.execute(f"SELECT * FROM papers WHERE user_id = '{user_id}'")
```

---

## Vulnerability Considerations

### Known Limitations

1. **In-Memory Rate Limiting**
   - Rate limits reset on service restart
   - Not shared across multiple instances
   - Consider Redis-based rate limiting for production

2. **Legacy Data Visibility**
   - Papers with `user_id = NULL` are visible to all users
   - This is intentional but should be documented
   - Consider migration script to assign ownership

3. **Internal API Endpoint**
   - `/api/auth/internal/user/{user_id}/api-key/{key_name}` returns decrypted keys
   - Protected only by internal network
   - Consider adding internal service authentication

### Security Improvements (Future)

1. **CSRF Protection**
   - Add CSRF tokens for state-changing operations
   - Implement SameSite cookies

2. **Security Headers**
   - Add Content-Security-Policy
   - Add X-Frame-Options
   - Add X-Content-Type-Options

3. **Audit Logging**
   - Log all authentication events
   - Log data access patterns
   - Implement alerting for suspicious activity

4. **Key Rotation**
   - Implement JWT_SECRET rotation
   - Implement MASTER_ENCRYPTION_KEY rotation
   - Version encrypted API keys

---

## Incident Response

### Suspected Breach

1. **Immediate Actions:**
   ```bash
   # Stop external access
   docker compose stop cloudflared

   # Check auth logs
   docker compose logs auth | grep -i "fail\|error\|401\|429"

   # Check active sessions
   sqlite3 data/auth.db "SELECT * FROM sessions;"
   ```

2. **Investigation:**
   ```bash
   # Check login attempts
   docker compose logs auth | grep "login"

   # Check for unusual patterns
   docker compose logs caddy | grep -E "POST /api/auth"
   ```

3. **Remediation:**
   ```bash
   # Invalidate all sessions
   sqlite3 data/auth.db "DELETE FROM sessions;"

   # Rotate secrets (requires service restart)
   # Update .env with new JWT_SECRET and MASTER_ENCRYPTION_KEY
   docker compose down
   docker compose up -d
   ```

### Key Compromise

If JWT_SECRET is compromised:
1. Generate new secret
2. Update `.env`
3. Restart auth service
4. All users will need to re-authenticate

If MASTER_ENCRYPTION_KEY is compromised:
1. Generate new key
2. Re-encrypt all API keys (requires migration script)
3. Update `.env`
4. Restart services

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [API_REFERENCE.md](API_REFERENCE.md) - API documentation
- [CONFIGURATION.md](CONFIGURATION.md) - Configuration reference
- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) - Development guidelines
