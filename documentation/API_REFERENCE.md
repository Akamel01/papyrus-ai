# SME Research Assistant - API Reference

**Version:** 1.0
**Last Updated:** March 2026

---

## Table of Contents

1. [Auth Service API](#auth-service-api)
2. [Dashboard API](#dashboard-api)
3. [Documents API](#documents-api)
4. [Internal APIs](#internal-apis)
5. [WebSocket API](#websocket-api)
6. [Core Interfaces](#core-interfaces)

---

## Auth Service API

**Base URL:** `http://localhost:8080/api/auth` (via Caddy)
**Direct URL:** `http://localhost:8000/api/auth` (internal)

### Authentication Endpoints

#### Register User

```http
POST /api/auth/register
Content-Type: application/json
```

**Request:**
```json
{
    "email": "user@example.com",
    "password": "SecurePass123!",
    "display_name": "John Doe"  // optional
}
```

**Response (200):**
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 900
}
```

**Validation Rules:**
- Password: minimum 12 characters, must contain letters and numbers
- Email: valid email format, must be unique

**Rate Limit:** 10 registrations per minute per IP

---

#### Login

```http
POST /api/auth/login
Content-Type: application/json
```

**Request:**
```json
{
    "email": "user@example.com",
    "password": "SecurePass123!"
}
```

**Response (200):**
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 900
}
```

**Error Responses:**
- `401 Unauthorized`: Invalid email or password
- `403 Forbidden`: Account is disabled
- `429 Too Many Requests`: Account locked (10 failed attempts = 15 min lockout)

**Rate Limit:** 100 requests per minute per IP
**Login Lockout:** 10 failed attempts triggers 15-minute lockout

---

#### Refresh Token

```http
POST /api/auth/refresh
Content-Type: application/json
```

**Request:**
```json
{
    "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Response (200):**
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 900
}
```

**Rate Limit:** 30 refreshes per minute per IP

---

#### Logout

```http
POST /api/auth/logout
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
    "message": "Logged out successfully"
}
```

---

### User Management Endpoints

#### Get Current User

```http
GET /api/auth/me
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "display_name": "John Doe",
    "role": "user",
    "created_at": "2026-03-18T10:30:00Z"
}
```

---

#### Update Profile

```http
PUT /api/auth/me
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request:**
```json
{
    "display_name": "Jane Doe"
}
```

---

#### Change Password

```http
POST /api/auth/me/password
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request:**
```json
{
    "current_password": "OldSecurePass123!",
    "new_password": "NewSecurePass456!"
}
```

---

### API Key Management

#### List API Keys

```http
GET /api/auth/me/keys
Authorization: Bearer <access_token>
```

**Response (200):**
```json
[
    {
        "id": "key-uuid-1",
        "key_name": "openalex",
        "masked_value": "****abcd",
        "created_at": "2026-03-18T10:30:00Z",
        "last_used": "2026-03-19T14:20:00Z"
    },
    {
        "id": "key-uuid-2",
        "key_name": "semantic_scholar",
        "masked_value": "****efgh",
        "created_at": "2026-03-18T10:35:00Z",
        "last_used": null
    }
]
```

---

#### Add/Update API Key

```http
PUT /api/auth/me/keys
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request:**
```json
{
    "key_name": "openalex",
    "key_value": "your-actual-api-key"
}
```

**Allowed key_name values:**
- `openalex`
- `semantic_scholar`
- `ollama_cloud`

---

#### Delete API Key

```http
DELETE /api/auth/me/keys/{key_name}
Authorization: Bearer <access_token>
```

---

### User Preferences

#### Get Preferences

```http
GET /api/auth/me/preferences
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
    "preferred_model": "gpt-oss:120b-cloud",
    "research_depth": "comprehensive",
    "citation_style": "apa",
    "ollama_mode": "server"
}
```

---

#### Update Preferences

```http
PUT /api/auth/me/preferences
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request:**
```json
{
    "preferred_model": "gpt-oss:120b-cloud",
    "research_depth": "quick",
    "citation_style": "apa",
    "ollama_mode": "server"
}
```

---

## Dashboard API

**Base URL:** `http://localhost:8080/api` (via Caddy)
**Direct URL:** `http://localhost:8400/api` (internal)

### Configuration Routes (`/api/config`)

#### Get Configuration

```http
GET /api/config
Authorization: Bearer <access_token>
```

Returns the current `acquisition_config.yaml` as JSON.

---

#### Update Configuration

```http
PUT /api/config
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request:** Updated config object (partial or full)

---

### Pipeline Control (`/api/run`)

#### Get Pipeline Status

```http
GET /api/run/status
Authorization: Bearer <access_token>
```

**Response:**
```json
{
    "running": true,
    "mode": "discovery",
    "start_time": "2026-03-19T10:00:00Z",
    "papers_processed": 150,
    "errors": 2
}
```

---

#### Start Pipeline

```http
POST /api/run/start
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request:**
```json
{
    "mode": "full",  // "discovery", "download", "processing", "full"
    "dry_run": false
}
```

---

#### Stop Pipeline

```http
POST /api/run/stop
Authorization: Bearer <access_token>
```

---

### Database Routes (`/api/db`)

#### Get Paper Counts

```http
GET /api/db/counts
Authorization: Bearer <access_token>
```

**Response:**
```json
{
    "discovered": 5420,
    "downloaded": 3210,
    "parsed": 3100,
    "chunked": 3050,
    "embedded": 3000,
    "failed": 110
}
```

---

#### Get Papers List

```http
GET /api/db/papers?status=embedded&limit=50&offset=0
Authorization: Bearer <access_token>
```

---

#### Get Paper Details

```http
GET /api/db/papers/{paper_id}
Authorization: Bearer <access_token>
```

---

### Qdrant Routes (`/api/qdrant`)

#### Get Collection Info

```http
GET /api/qdrant/info
Authorization: Bearer <access_token>
```

**Response:**
```json
{
    "collection": "sme_papers_v2",
    "vectors_count": 245000,
    "indexed_vectors_count": 245000,
    "segments_count": 12,
    "status": "green",
    "disk_size_bytes": 2147483648
}
```

---

#### Trigger Optimization

```http
POST /api/qdrant/optimize
Authorization: Bearer <access_token>
```

---

### Metrics Routes (`/api/metrics`)

#### Get Current Metrics

```http
GET /api/metrics/current
Authorization: Bearer <access_token>
```

**Response:**
```json
{
    "gpu": {
        "util_pct": 45.2,
        "vram_used_mb": 8192,
        "vram_total_mb": 12288,
        "temperature": 65
    },
    "cpu_pct": 32.5,
    "ram_used_gb": 28.4,
    "ram_total_gb": 64.0,
    "disk_free_gb": 156.2
}
```

---

#### Get Historical Metrics

```http
GET /api/metrics/history?hours=24
Authorization: Bearer <access_token>
```

---

### Dead Letter Queue (`/api/dlq`)

#### Get Failed Items

```http
GET /api/dlq/items?limit=50
Authorization: Bearer <access_token>
```

---

#### Retry Failed Item

```http
POST /api/dlq/retry/{item_id}
Authorization: Bearer <access_token>
```

---

#### Clear DLQ

```http
DELETE /api/dlq/clear
Authorization: Bearer <access_token>
```

---

### Audit Routes (`/api/audit`)

#### Get Audit Log

```http
GET /api/audit/logs?limit=100&user_id=<optional>
Authorization: Bearer <access_token>
```

---

## Documents API

**Base URL:** `http://localhost:8080/api/documents` (via Caddy)
**Direct URL:** `http://localhost:8400/api/documents` (internal)

The Documents API enables users to upload, process, and manage their personal documents. Documents are isolated per user and go through the full embedding pipeline.

### Upload Document

```http
POST /api/documents/upload
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
```

**Request:**
- `file`: File upload (PDF, MD, DOCX, max 50MB)

**Response (200):**
```json
{
    "document_id": "user:uuid:manual:checksum",
    "filename": "paper.pdf",
    "status": "pending",
    "message": "Document uploaded successfully. Click 'Process' to embed."
}
```

**Error Responses:**
- `400 Bad Request`: Invalid file type or size exceeded
- `409 Conflict`: Document with same content already exists

---

### Process Document

```http
POST /api/documents/{document_id}/process
Authorization: Bearer <access_token>
```

**Processing Modes:**
- **Pipeline Mode**: When streaming pipeline is running, document is queued
- **On-Demand Mode**: When pipeline is NOT running, document is processed immediately in background

**Response (200) - Pipeline Mode:**
```json
{
    "document_id": "user:uuid:manual:checksum",
    "status": "processing",
    "message": "Document queued for processing via pipeline."
}
```

**Response (200) - On-Demand Mode:**
```json
{
    "document_id": "user:uuid:manual:checksum",
    "status": "processing",
    "message": "Document processing started (on-demand mode)."
}
```

**Error Responses:**
- `404 Not Found`: Document not found or not owned by user
- `400 Bad Request`: Document cannot be processed (already processing/ready)

---

### Process All Pending

```http
POST /api/documents/process-all
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
    "queued_count": 5,
    "message": "Queued 5 documents for processing."
}
```

---

### List Documents

```http
GET /api/documents
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
    "documents": [
        {
            "document_id": "user:uuid:manual:checksum",
            "filename": "paper.pdf",
            "title": "Paper Title",
            "status": "ready",
            "file_size": 2456789,
            "upload_date": "Mar 23, 2026",
            "error_message": null,
            "bm25_indexed": true
        }
    ],
    "total": 1,
    "counts": {
        "total": 10,
        "pending": 2,
        "processing": 1,
        "ready": 6,
        "failed": 1
    }
}
```

**Document Status Values:**
- `pending`: Uploaded, not yet processed
- `processing`: Currently being embedded
- `ready`: Fully indexed and searchable
- `failed`: Processing failed (see error_message)

---

### Get Document Status

```http
GET /api/documents/{document_id}/status
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
    "document_id": "user:uuid:manual:checksum",
    "title": "Paper Title",
    "status": "ready",
    "internal_status": "embedded"
}
```

---

### Delete Document

```http
DELETE /api/documents/{document_id}
Authorization: Bearer <access_token>
```

Performs cascading delete:
1. Qdrant (vector embeddings)
2. BM25 Tantivy (keyword index)
3. SQLite (paper record)
4. Disk (source file)

**Response (200):**
```json
{
    "deleted": true,
    "message": "Document deleted successfully."
}
```

---

### Batch Delete Documents

```http
DELETE /api/documents/batch
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request:**
```json
{
    "document_ids": ["doc1", "doc2", "doc3"]
}
```

**Response (200):**
```json
{
    "deleted_count": 3,
    "failed": []
}
```

---

## Internal APIs

These endpoints are for service-to-service communication and should not be exposed externally.

### Documents Internal

#### Notify Document Completion (Pipeline → Dashboard)

```http
POST /api/documents/internal/notify-completion
Content-Type: application/json
```

Called by the streaming pipeline when a document finishes embedding. Triggers WebSocket broadcast to all connected dashboard clients.

**Request:**
```json
{
    "document_id": "user:uuid:manual:checksum",
    "status": "ready",
    "bm25_indexed": true
}
```

**Response (200):**
```json
{
    "ok": true
}
```

**WebSocket Broadcast:**
```json
{
    "type": "document.status_change",
    "payload": {
        "document_id": "user:uuid:manual:checksum",
        "status": "ready",
        "bm25_indexed": true
    }
}
```

---

### Auth Service Internal

#### Internal Login (Service-to-Service)

```http
POST /api/auth/internal/login
Content-Type: application/json
```

**Request:**
```json
{
    "email": "user@example.com",
    "password": "SecurePass123!"
}
```

**Response (200):**
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 900,
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "dashboard_role": "operator"
}
```

**Notes:**
- No rate limiting (internal use only)
- Returns dashboard_role for role-based access control
- Used by Dashboard backend to authenticate against Auth Service

---

#### Validate Token

```http
GET /api/auth/internal/validate
Authorization: Bearer <access_token>
```

**Response:**
```json
{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "role": "user"
}
```

Used by other services to validate incoming requests.

---

#### Get Decrypted API Key

```http
GET /api/auth/internal/user/{user_id}/api-key/{key_name}
```

**Response:**
```json
{
    "key_value": "actual-decrypted-api-key"
}
```

**Security:** Must be protected by internal network. Not accessible externally.

---

## WebSocket API

**URL:** `ws://localhost:8080/ws` (via Caddy)
**Direct URL:** `ws://localhost:8400/ws`

### Connection

```javascript
const ws = new WebSocket('ws://localhost:8080/ws');
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(data.type, data.payload);
};
```

### Message Types

#### Metrics Update (Server → Client)

```json
{
    "type": "metrics.update",
    "payload": {
        "gpu": { "util_pct": 45.2, "vram_used_mb": 8192 },
        "cpu_pct": 32.5,
        "ram_used_gb": 28.4,
        "counts": {
            "discovered": 5420,
            "downloaded": 3210,
            "embedded": 3000
        }
    }
}
```

Sent every 1 second.

---

#### Pipeline Event (Server → Client)

```json
{
    "type": "pipeline.event",
    "payload": {
        "event": "paper_embedded",
        "paper_id": "10.1234/example",
        "title": "Paper Title"
    }
}
```

---

#### Error Event (Server → Client)

```json
{
    "type": "pipeline.error",
    "payload": {
        "error": "Download failed",
        "paper_id": "10.1234/example",
        "details": "Connection timeout"
    }
}
```

---

#### Pipeline State Change (Server → Client)

```json
{
    "type": "pipeline.state_change",
    "payload": {
        "running": true,
        "mode": "processing",
        "papers_processed": 150
    }
}
```

Sent when pipeline starts, stops, or changes mode. Enables real-time UI updates without polling.

---

#### Document Status Change (Server → Client)

```json
{
    "type": "document.status_change",
    "payload": {
        "document_id": "user:uuid:manual:checksum",
        "status": "ready",
        "bm25_indexed": true
    }
}
```

Sent when a user document's processing status changes. Includes `bm25_indexed` field indicating whether the document has been indexed for keyword search.

**Status Values:**
- `processing`: Document is being parsed, chunked, or embedded
- `ready`: Document is fully indexed (vector + BM25)
- `failed`: Processing failed

---

## Core Interfaces

### Retrieval Interface

Located in `src/retrieval/hybrid_search.py`:

```python
class HybridSearcher:
    def search(
        self,
        query: str,
        top_k: int = 10,
        user_id: Optional[str] = None,  # Required for multi-user isolation
        knowledge_source: str = "both",  # Knowledge source filter
        filters: Optional[Dict] = None,
        bm25_weight: float = 0.3,
        semantic_weight: float = 0.7
    ) -> List[RetrievalResult]:
        """
        Hybrid search combining BM25 and semantic retrieval.

        Args:
            query: Search query text
            top_k: Number of results to return
            user_id: User ID for data isolation (critical for multi-user)
            knowledge_source: "shared_only", "user_only", or "both"
            filters: Additional metadata filters
            bm25_weight: Weight for BM25 scores (0.0-1.0)
            semantic_weight: Weight for semantic scores (0.0-1.0)

        Returns:
            List of RetrievalResult objects with scores

        Knowledge Source Behavior:
            - "shared_only": Only search shared KB (user_id is NULL)
            - "user_only": Only search user's uploaded documents
            - "both": Search both user docs and shared KB
        """
```

---

### Vector Store Interface

Located in `src/retrieval/vector_store.py`:

```python
class QdrantVectorStore:
    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        user_id: Optional[str] = None,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Search vectors with user isolation.

        The user_id filter is automatically applied when provided.
        """

    def upsert(
        self,
        points: List[Dict],
        user_id: str  # Required for new documents
    ) -> None:
        """
        Insert or update vectors with user ownership.

        Each point must include user_id in payload for isolation.
        """
```

---

### BM25 Index Interface

Located in `src/indexing/bm25_tantivy.py`:

```python
class TantivyBM25Index:
    def search(
        self,
        query: str,
        top_k: int = 10,
        user_id: Optional[str] = None  # For filtering during hydration
    ) -> List[RetrievalResult]:
        """
        BM25 keyword search with user filtering.

        Note: Tantivy index is shared, filtering happens during
        Qdrant hydration phase.
        """
```

---

### Embedder Interface

Located in `src/embedding/embedder.py`:

```python
class OllamaEmbedder:
    def embed(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 64
    ) -> List[List[float]]:
        """
        Generate embeddings via Ollama.

        Args:
            texts: Single text or list of texts
            batch_size: Batch size for processing

        Returns:
            List of 4096-dimensional vectors
        """
```

---

### LLM Interface

Located in `src/generation/llm.py`:

```python
class OllamaClient:
    def generate(
        self,
        prompt: str,
        model: str = "gpt-oss:120b-cloud",
        temperature: float = 0.1,
        max_tokens: int = 2000,
        stream: bool = True
    ) -> Union[str, Generator[str, None, None]]:
        """
        Generate text response.

        Returns string if stream=False, generator if stream=True.
        """
```

---

## Error Responses

All APIs use consistent error response format:

```json
{
    "detail": "Error message describing what went wrong"
}
```

**Common HTTP Status Codes:**

| Code | Meaning |
|------|---------|
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Missing or invalid token |
| 403 | Forbidden - Account disabled or insufficient permissions |
| 404 | Not Found - Resource doesn't exist |
| 429 | Too Many Requests - Rate limit exceeded |
| 500 | Internal Server Error - Server-side error |

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [DATA_FLOWS.md](DATA_FLOWS.md) - Data pipeline details
- [SECURITY.md](SECURITY.md) - Security model
