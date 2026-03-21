# SME Research Assistant - Incident Response Guide

**Version:** 1.0
**Last Updated:** March 2026

---

## Table of Contents

1. [Incident Classification](#incident-classification)
2. [Detection Methods](#detection-methods)
3. [Immediate Response Steps](#immediate-response-steps)
4. [Containment Procedures](#containment-procedures)
5. [Investigation Procedures](#investigation-procedures)
6. [Recovery Procedures](#recovery-procedures)
7. [Post-Incident Actions](#post-incident-actions)
8. [Contact Information Template](#contact-information-template)

---

## Incident Classification

### Severity Levels

| Severity | Response Time | Description |
|----------|---------------|-------------|
| **Critical** | Immediate (< 15 min) | Active data breach, complete system compromise, or ransomware |
| **High** | < 1 hour | Suspected credential compromise, cross-user data access, active attack |
| **Medium** | < 4 hours | Brute force attempts, service disruption, suspicious activity |
| **Low** | < 24 hours | Minor policy violations, failed attack attempts, single user issues |

### Severity Level Examples

#### Critical Severity
- Confirmed unauthorized access to user data
- MASTER_ENCRYPTION_KEY or JWT_SECRET exposed publicly
- Evidence of data exfiltration (API keys, user credentials)
- Ransomware or destructive malware detected
- Complete loss of authentication system integrity
- Production database corruption affecting multiple users

#### High Severity
- Multiple failed login attempts from same IP across different accounts
- Successful login from unusual geographic location
- User reports seeing another user's papers or data
- JWT token forgery attempts detected
- Unauthorized API key usage
- Auth service crash with potential memory dump exposure

#### Medium Severity
- Sustained brute force attack (> 100 attempts in 10 minutes)
- Single service disruption (Qdrant, Ollama, Redis unavailable)
- Unusual query patterns suggesting data enumeration
- Failed authentication rate > 50% over 1 hour
- Disk space exhaustion affecting logging
- Certificate expiration warnings

#### Low Severity
- Individual account lockout due to failed passwords
- Single failed login from known user
- Minor service restart required
- Log rotation issues
- Configuration drift detected
- Non-critical dependency update available

---

## Detection Methods

### Automated Alerts

#### Authentication Monitoring

| Alert | Trigger Condition | Severity |
|-------|-------------------|----------|
| Login Lockout | 10 failed attempts in 15 minutes | Medium |
| Multi-Account Brute Force | Same IP, 5+ different accounts failed | High |
| JWT Validation Failure Spike | > 50 invalid tokens in 5 minutes | High |
| Session Anomaly | Refresh token used after logout | Critical |
| Concurrent Sessions | Same user, different IPs, same time | Medium |

#### Data Access Monitoring

| Alert | Trigger Condition | Severity |
|-------|-------------------|----------|
| Cross-User Query | Query results contain multiple user_ids | Critical |
| Mass Data Export | > 1000 chunks retrieved in 1 minute | High |
| API Key Decryption Spike | > 10 decryptions per minute per user | Medium |
| Vector Search Without Filter | Qdrant query missing user_id filter | Critical |

#### System Health Monitoring

| Alert | Trigger Condition | Severity |
|-------|-------------------|----------|
| Service Down | Container health check failed 3x | Medium |
| Disk Full | < 10GB free on data volume | High |
| Memory Exhaustion | > 90% RAM usage sustained 5 min | Medium |
| Database Locked | SQLite lock timeout > 30 seconds | Medium |

### Manual Indicators (Log Analysis)

#### Auth Service Logs (`docker compose logs auth`)

```bash
# Signs of brute force attack
docker compose logs auth 2>&1 | grep -E "login.*failed|401|429" | head -50

# Signs of successful compromise
docker compose logs auth 2>&1 | grep -E "login.*success" | awk '{print $NF}' | sort | uniq -c | sort -rn

# JWT validation failures (potential token forgery)
docker compose logs auth 2>&1 | grep -i "invalid.*token\|expired\|signature"

# Account lockouts
docker compose logs auth 2>&1 | grep -i "lockout\|locked\|blocked"
```

#### Caddy Logs (`docker compose logs caddy`)

```bash
# Unusual endpoints being probed
docker compose logs caddy 2>&1 | grep -E "404|403" | awk '{print $7}' | sort | uniq -c | sort -rn | head -20

# High volume from single IP
docker compose logs caddy 2>&1 | awk '{print $1}' | sort | uniq -c | sort -rn | head -10

# Suspicious User-Agents
docker compose logs caddy 2>&1 | grep -iE "curl|wget|python|scanner|nikto|sqlmap"
```

#### Application Logs (`docker compose logs app`)

```bash
# Search operations without user isolation
docker compose logs app 2>&1 | grep -i "search" | grep -v "user_id"

# Error patterns
docker compose logs app 2>&1 | grep -iE "error|exception|traceback" | tail -50

# Unusual query patterns
docker compose logs app 2>&1 | grep "query:" | awk -F'query:' '{print $2}' | sort | uniq -c | sort -rn
```

### User Reports

#### Common User-Reported Indicators

| User Report | Potential Incident | Initial Action |
|-------------|-------------------|----------------|
| "I see papers that aren't mine" | Cross-user data access | Critical - Escalate immediately |
| "I can't log in but didn't change password" | Account compromise | High - Check session logs |
| "My API keys are being rejected" | Key rotation/compromise | Medium - Verify key status |
| "System is very slow" | DoS attack or resource exhaustion | Medium - Check system metrics |
| "I got logged out unexpectedly" | Session invalidation or attack | Medium - Review auth logs |
| "Error messages showing weird data" | Data corruption or injection | High - Preserve error context |

---

## Immediate Response Steps

### Suspected Credential Compromise

**Severity:** High to Critical

**Indicators:**
- User reports unauthorized activity
- Login from unusual location/device
- Multiple sessions for single user
- Password change without user initiation

**Immediate Actions:**

```bash
# 1. Identify the affected user
sqlite3 data/auth.db "SELECT id, email, last_login FROM users WHERE email = 'affected@example.com';"

# 2. Invalidate all sessions for the user
USER_ID="<user-uuid-from-step-1>"
sqlite3 data/auth.db "DELETE FROM sessions WHERE user_id = '$USER_ID';"

# 3. Check recent session activity
sqlite3 data/auth.db "SELECT * FROM sessions WHERE user_id = '$USER_ID' ORDER BY created_at DESC LIMIT 20;"

# 4. Review login history (from auth logs)
docker compose logs auth 2>&1 | grep "$USER_ID\|affected@example.com" | tail -100

# 5. Check for API key access
sqlite3 data/auth.db "SELECT key_name, created_at FROM user_api_keys WHERE user_id = '$USER_ID';"

# 6. If compromise confirmed, force password reset flag (if implemented)
# Otherwise, contact user directly to reset password
```

**Escalation Criteria:**
- Multiple users affected
- Evidence of data access
- API keys were retrieved by attacker

---

### Cross-User Data Access Attempt

**Severity:** Critical

**Indicators:**
- User sees another user's papers
- Query returns data with mismatched user_id
- Logs show queries without user_id filter

**Immediate Actions:**

```bash
# 1. IMMEDIATELY stop external access
docker compose stop cloudflared

# 2. Identify scope of the issue
# Check if vector store queries are properly filtered
docker compose logs app 2>&1 | grep -E "search.*user_id" | tail -50

# 3. Check Qdrant for improper data exposure
# Connect to Qdrant and verify filter conditions are being applied
curl -s "http://localhost:6333/collections/sme_papers_v2" | python -m json.tool

# 4. Review recent search operations
docker compose logs app 2>&1 | grep -i "hybrid.*search\|vector.*search" | tail -100

# 5. Check BM25 hydration logs for filter issues
docker compose logs app 2>&1 | grep -i "bm25\|tantivy" | grep -v "user_id" | tail -50

# 6. Identify affected time window
docker compose logs --since="1h" app 2>&1 | grep "search" | head -1
docker compose logs app 2>&1 | grep "search" | tail -1

# 7. Preserve evidence before any fixes
mkdir -p /tmp/incident_$(date +%Y%m%d_%H%M%S)
docker compose logs app > /tmp/incident_$(date +%Y%m%d_%H%M%S)/app.log 2>&1
docker compose logs auth > /tmp/incident_$(date +%Y%m%d_%H%M%S)/auth.log 2>&1
cp data/auth.db /tmp/incident_$(date +%Y%m%d_%H%M%S)/
cp data/sme.db /tmp/incident_$(date +%Y%m%d_%H%M%S)/
```

**Do Not:**
- Restart services before preserving logs
- Modify code without understanding root cause
- Restore external access until issue is resolved

---

### Brute Force Attack Detected

**Severity:** Medium to High

**Indicators:**
- Multiple failed login attempts from same IP
- Account lockout rate spike
- 429 (rate limit) responses increasing

**Immediate Actions:**

```bash
# 1. Identify attacking IPs
docker compose logs auth 2>&1 | grep -i "failed\|401" | awk '{print $1}' | sort | uniq -c | sort -rn | head -20

# 2. Check current lockout status (in-memory, check logs)
docker compose logs auth 2>&1 | grep -i "lockout" | tail -20

# 3. Verify rate limiting is active
docker compose logs auth 2>&1 | grep "429" | wc -l

# 4. If attack is overwhelming, consider blocking at Cloudflare
# Access Cloudflare dashboard or use API to add firewall rule

# 5. Check if any accounts were compromised during attack
docker compose logs auth 2>&1 | grep -i "login.*success" | grep "<attacking-ip>"

# 6. If using Caddy, you can add temporary IP blocking
# Edit Caddyfile to add:
# @blocked {
#     remote_ip <attacking-ip>
# }
# respond @blocked 403

# 7. Monitor attack progress
watch -n 5 'docker compose logs --tail=20 auth 2>&1 | grep -i "failed\|success\|lockout"'
```

**Escalation Criteria:**
- Attack bypasses rate limiting
- Successful logins detected during attack
- Multiple source IPs (distributed attack)

---

### Service Disruption

**Severity:** Medium

**Indicators:**
- Users cannot access the application
- Health checks failing
- Containers restarting repeatedly

**Immediate Actions:**

```bash
# 1. Check overall service status
docker compose ps

# 2. Check for crashed services
docker compose ps | grep -E "Exit|Restarting"

# 3. Check system resources
df -h          # Disk space
free -m        # Memory
docker stats --no-stream   # Container resource usage

# 4. Check individual service logs
docker compose logs --tail=100 caddy    # Reverse proxy
docker compose logs --tail=100 auth     # Authentication
docker compose logs --tail=100 app      # Main application
docker compose logs --tail=100 qdrant   # Vector database
docker compose logs --tail=100 ollama   # LLM/Embedding
docker compose logs --tail=100 redis    # Cache

# 5. Check for OOM kills
dmesg | grep -i "out of memory\|oom" | tail -20

# 6. Check Docker events
docker events --since="1h" --until="now" 2>&1 | grep -E "die|kill|oom"

# 7. Attempt service recovery
docker compose up -d <service-name>

# 8. If database issues, check SQLite integrity
sqlite3 data/auth.db "PRAGMA integrity_check;"
sqlite3 data/sme.db "PRAGMA integrity_check;"

# 9. If Qdrant issues, check collection status
curl -s "http://localhost:6333/collections/sme_papers_v2" | python -m json.tool
```

---

### Malware/Suspicious Activity

**Severity:** High to Critical

**Indicators:**
- Unexpected processes running
- Unusual network connections
- File modifications in unexpected locations
- Cryptocurrency mining (high CPU, no apparent cause)

**Immediate Actions:**

```bash
# 1. IMMEDIATELY isolate the system
docker compose stop cloudflared

# 2. Do NOT restart or stop other containers yet (preserve state)

# 3. Check for unusual processes inside containers
docker compose exec app ps aux
docker compose exec auth ps aux

# 4. Check network connections
docker compose exec app netstat -tulpn 2>/dev/null || docker compose exec app ss -tulpn
docker compose exec auth netstat -tulpn 2>/dev/null || docker compose exec auth ss -tulpn

# 5. Check for recently modified files
docker compose exec app find /app -mtime -1 -type f -ls
docker compose exec auth find /app -mtime -1 -type f -ls

# 6. Check container file systems for anomalies
docker diff sme_app
docker diff sme_auth

# 7. Preserve container state
docker commit sme_app sme_app_forensic_$(date +%Y%m%d_%H%M%S)
docker commit sme_auth sme_auth_forensic_$(date +%Y%m%d_%H%M%S)

# 8. Export container filesystems for analysis
docker export sme_app > /tmp/sme_app_export_$(date +%Y%m%d_%H%M%S).tar
docker export sme_auth > /tmp/sme_auth_export_$(date +%Y%m%d_%H%M%S).tar

# 9. Check host system
ps aux | grep -v "^\[" | sort -k3 -rn | head -20  # High CPU processes
lsof -i -P -n | grep ESTABLISHED  # Network connections
```

**Critical:**
- Do not attempt to "clean" the system until forensic capture is complete
- Assume all credentials are compromised
- Plan for complete rebuild from known-good images

---

## Containment Procedures

### Isolate Affected Accounts

```bash
# 1. List potentially affected users (adjust time window as needed)
sqlite3 data/auth.db "SELECT id, email, last_login FROM users WHERE last_login > datetime('now', '-24 hours');"

# 2. Invalidate all sessions for specific user
sqlite3 data/auth.db "DELETE FROM sessions WHERE user_id = '<user-id>';"

# 3. Invalidate ALL sessions system-wide (nuclear option)
sqlite3 data/auth.db "DELETE FROM sessions;"

# 4. Lock specific user account (prevent new logins)
# Option A: Change password hash to invalid value (reversible)
sqlite3 data/auth.db "UPDATE users SET password_hash = 'LOCKED_' || password_hash WHERE id = '<user-id>';"

# Option B: Track locked users (create table if not exists)
sqlite3 data/auth.db "CREATE TABLE IF NOT EXISTS locked_users (user_id TEXT PRIMARY KEY, locked_at TIMESTAMP, reason TEXT);"
sqlite3 data/auth.db "INSERT INTO locked_users VALUES ('<user-id>', datetime('now'), 'Security incident');"

# 5. Disable specific user's API keys
sqlite3 data/auth.db "DELETE FROM user_api_keys WHERE user_id = '<user-id>';"
```

### Stop External Access (Cloudflare Tunnel)

```bash
# 1. Stop the Cloudflare tunnel (recommended - graceful)
docker compose stop cloudflared

# 2. Verify tunnel is stopped
docker compose ps cloudflared

# 3. If tunnel won't stop, force kill
docker compose kill cloudflared

# 4. For complete isolation, also stop Caddy
docker compose stop caddy

# 5. Verify no external access is possible
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
# Should fail or return error

# 6. If using direct port exposure, check and block
docker compose ps | grep -E "0.0.0.0|:::"
# Consider firewall rules if needed

# 7. To restore access later (after incident resolution):
docker compose start caddy
docker compose start cloudflared
```

### Preserve Evidence

```bash
# Create incident directory with timestamp
INCIDENT_DIR="/tmp/incident_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$INCIDENT_DIR"

# 1. Preserve all service logs
docker compose logs > "$INCIDENT_DIR/all_services.log" 2>&1
docker compose logs auth > "$INCIDENT_DIR/auth.log" 2>&1
docker compose logs app > "$INCIDENT_DIR/app.log" 2>&1
docker compose logs caddy > "$INCIDENT_DIR/caddy.log" 2>&1
docker compose logs qdrant > "$INCIDENT_DIR/qdrant.log" 2>&1

# 2. Preserve database state
cp data/auth.db "$INCIDENT_DIR/auth.db"
cp data/sme.db "$INCIDENT_DIR/sme.db"
cp data/chat_history.db "$INCIDENT_DIR/chat_history.db" 2>/dev/null

# 3. Preserve configuration (without secrets)
cp docker-compose.yml "$INCIDENT_DIR/"
cp config/config.yaml "$INCIDENT_DIR/"
# DO NOT copy .env file

# 4. Capture container state
docker compose ps > "$INCIDENT_DIR/container_status.txt"
docker stats --no-stream > "$INCIDENT_DIR/resource_usage.txt"

# 5. Capture Docker events
docker events --since="24h" --until="now" > "$INCIDENT_DIR/docker_events.log" 2>&1

# 6. Capture system state
df -h > "$INCIDENT_DIR/disk_usage.txt"
free -m > "$INCIDENT_DIR/memory_usage.txt"
uptime > "$INCIDENT_DIR/system_uptime.txt"

# 7. Create evidence manifest
cat > "$INCIDENT_DIR/MANIFEST.txt" << EOF
Incident Evidence Collection
============================
Timestamp: $(date -Iseconds)
Collected by: $(whoami)
Hostname: $(hostname)

Files Collected:
$(ls -la "$INCIDENT_DIR")

Collection completed: $(date -Iseconds)
EOF

# 8. Create tarball for secure storage
tar -czf "${INCIDENT_DIR}.tar.gz" -C /tmp "$(basename $INCIDENT_DIR)"
echo "Evidence preserved at: ${INCIDENT_DIR}.tar.gz"

# 9. Calculate checksums
sha256sum "${INCIDENT_DIR}.tar.gz" > "${INCIDENT_DIR}.tar.gz.sha256"
```

---

## Investigation Procedures

### Log Collection Commands

```bash
# Comprehensive log collection script
INVESTIGATION_DIR="./investigation_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$INVESTIGATION_DIR/logs"

# Collect logs with timestamps for specific time range
START_TIME="2026-03-20T00:00:00"
END_TIME="2026-03-21T00:00:00"

# Auth service - authentication events
docker compose logs --since="$START_TIME" --until="$END_TIME" auth > "$INVESTIGATION_DIR/logs/auth_timeframe.log" 2>&1

# Parse login attempts
grep -E "login|register|refresh|logout" "$INVESTIGATION_DIR/logs/auth_timeframe.log" > "$INVESTIGATION_DIR/logs/auth_events.log"

# Extract unique IPs with activity counts
awk '{print $1}' "$INVESTIGATION_DIR/logs/auth_timeframe.log" | sort | uniq -c | sort -rn > "$INVESTIGATION_DIR/logs/ip_activity.txt"

# App service - user queries and data access
docker compose logs --since="$START_TIME" --until="$END_TIME" app > "$INVESTIGATION_DIR/logs/app_timeframe.log" 2>&1

# Caddy - all HTTP requests
docker compose logs --since="$START_TIME" --until="$END_TIME" caddy > "$INVESTIGATION_DIR/logs/caddy_timeframe.log" 2>&1

# Extract request patterns
awk '{print $6, $7}' "$INVESTIGATION_DIR/logs/caddy_timeframe.log" | sort | uniq -c | sort -rn > "$INVESTIGATION_DIR/logs/request_patterns.txt"
```

### Database Queries to Run

```bash
# Authentication Database Queries
sqlite3 data/auth.db << 'EOF'
.mode column
.headers on

-- Recent user registrations
SELECT id, email, created_at, last_login
FROM users
ORDER BY created_at DESC
LIMIT 20;

-- Active sessions in last 24 hours
SELECT s.id, u.email, s.ip_address, s.user_agent, s.created_at, s.expires_at
FROM sessions s
JOIN users u ON s.user_id = u.id
WHERE s.created_at > datetime('now', '-24 hours')
ORDER BY s.created_at DESC;

-- Sessions per user (detect session anomalies)
SELECT u.email, COUNT(s.id) as session_count
FROM users u
LEFT JOIN sessions s ON u.id = s.user_id
WHERE s.created_at > datetime('now', '-7 days')
GROUP BY u.id
HAVING session_count > 5
ORDER BY session_count DESC;

-- API keys by user
SELECT u.email, ak.key_name, ak.created_at
FROM user_api_keys ak
JOIN users u ON ak.user_id = u.id
ORDER BY ak.created_at DESC;

-- Users with admin privileges
SELECT id, email, is_admin, created_at
FROM users
WHERE is_admin = 1;

-- Check for locked accounts (if using lock table)
SELECT lu.user_id, u.email, lu.locked_at, lu.reason
FROM locked_users lu
JOIN users u ON lu.user_id = u.id;
EOF

# Paper Database Queries
sqlite3 data/sme.db << 'EOF'
.mode column
.headers on

-- Recent paper additions by user
SELECT user_id, COUNT(*) as paper_count, MAX(created_at) as latest
FROM papers
WHERE created_at > datetime('now', '-7 days')
GROUP BY user_id
ORDER BY paper_count DESC;

-- Papers without user_id (legacy data check)
SELECT COUNT(*) as legacy_papers
FROM papers
WHERE user_id IS NULL;

-- Recent processing activity
SELECT ps.paper_id, p.user_id, ps.parse_status, ps.embed_status, ps.processed_at
FROM processing_status ps
JOIN papers p ON ps.paper_id = p.id
ORDER BY ps.processed_at DESC
LIMIT 50;

-- Check for any cross-user paper access patterns
-- (This would show if papers were modified by wrong users)
SELECT p.id, p.title, p.user_id, p.updated_at
FROM papers p
WHERE p.updated_at != p.created_at
ORDER BY p.updated_at DESC
LIMIT 20;
EOF
```

### Timeline Reconstruction

```bash
# Create unified timeline from multiple sources
TIMELINE_FILE="./investigation_timeline.txt"

echo "=== INCIDENT TIMELINE ===" > "$TIMELINE_FILE"
echo "Generated: $(date -Iseconds)" >> "$TIMELINE_FILE"
echo "" >> "$TIMELINE_FILE"

# 1. Database events (user creation, logins)
echo "=== USER ACTIVITY ===" >> "$TIMELINE_FILE"
sqlite3 data/auth.db "SELECT 'USER_CREATED', email, created_at FROM users UNION ALL SELECT 'USER_LOGIN', email, last_login FROM users WHERE last_login IS NOT NULL ORDER BY 3 DESC LIMIT 100;" >> "$TIMELINE_FILE"

# 2. Session events
echo "" >> "$TIMELINE_FILE"
echo "=== SESSION ACTIVITY ===" >> "$TIMELINE_FILE"
sqlite3 data/auth.db "SELECT 'SESSION', user_id, ip_address, created_at FROM sessions ORDER BY created_at DESC LIMIT 100;" >> "$TIMELINE_FILE"

# 3. Auth service events (from logs)
echo "" >> "$TIMELINE_FILE"
echo "=== AUTH EVENTS (from logs) ===" >> "$TIMELINE_FILE"
docker compose logs auth 2>&1 | grep -E "login|logout|register|refresh|error|fail" | tail -100 >> "$TIMELINE_FILE"

# 4. Application events
echo "" >> "$TIMELINE_FILE"
echo "=== APPLICATION EVENTS ===" >> "$TIMELINE_FILE"
docker compose logs app 2>&1 | grep -E "search|query|error|user_id" | tail -100 >> "$TIMELINE_FILE"

# 5. HTTP access patterns
echo "" >> "$TIMELINE_FILE"
echo "=== HTTP REQUESTS ===" >> "$TIMELINE_FILE"
docker compose logs caddy 2>&1 | grep -E "POST|PUT|DELETE" | tail -100 >> "$TIMELINE_FILE"

# 6. Docker events
echo "" >> "$TIMELINE_FILE"
echo "=== DOCKER EVENTS ===" >> "$TIMELINE_FILE"
docker events --since="24h" --until="now" 2>&1 | tail -50 >> "$TIMELINE_FILE"

echo "" >> "$TIMELINE_FILE"
echo "=== END TIMELINE ===" >> "$TIMELINE_FILE"

# Sort by timestamp if possible
# Note: Manual review will be needed due to varying timestamp formats
```

### Qdrant Vector Store Investigation

```bash
# Check collection health
curl -s "http://localhost:6333/collections/sme_papers_v2" | python -m json.tool

# Get collection statistics
curl -s "http://localhost:6333/collections/sme_papers_v2/points/count" | python -m json.tool

# Sample points to verify user_id field exists
curl -s -X POST "http://localhost:6333/collections/sme_papers_v2/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{"limit": 10, "with_payload": true}' | python -m json.tool

# Check for points without user_id (legacy data)
curl -s -X POST "http://localhost:6333/collections/sme_papers_v2/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must_not": [
        {"key": "user_id", "match": {"any": []}}
      ]
    },
    "limit": 10,
    "with_payload": {"include": ["user_id", "paper_id", "title"]}
  }' | python -m json.tool

# Count points per user
curl -s -X POST "http://localhost:6333/collections/sme_papers_v2/points/count" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {"key": "user_id", "match": {"value": "<specific-user-id>"}}
      ]
    }
  }' | python -m json.tool
```

---

## Recovery Procedures

### Secret Rotation - JWT_SECRET

**When to rotate:** Suspected token forgery, key exposure, or as part of incident recovery.

```bash
# 1. Generate new JWT_SECRET
NEW_JWT_SECRET=$(openssl rand -base64 32)
echo "New JWT_SECRET: $NEW_JWT_SECRET"

# 2. Update .env file
# IMPORTANT: Keep backup of old secret for potential audit
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)

# Edit .env and replace JWT_SECRET value
# JWT_SECRET=<new-value>

# 3. Invalidate all existing sessions (required - old tokens won't validate)
sqlite3 data/auth.db "DELETE FROM sessions;"
echo "All sessions invalidated"

# 4. Restart auth service to pick up new secret
docker compose restart auth

# 5. Verify auth service is running with new secret
docker compose logs --tail=20 auth

# 6. Test authentication
# All users will need to log in again
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpassword"}'

# 7. Notify users
echo "ACTION REQUIRED: All users must log in again due to security update"
```

### Secret Rotation - MASTER_ENCRYPTION_KEY

**When to rotate:** Key exposure, suspected API key theft, or compliance requirement.

**WARNING:** This is a more complex operation as all encrypted API keys must be re-encrypted.

```bash
# 1. Generate new MASTER_ENCRYPTION_KEY
NEW_MASTER_KEY=$(openssl rand -base64 32)
echo "New MASTER_ENCRYPTION_KEY: $NEW_MASTER_KEY"

# 2. CRITICAL: Export all API keys BEFORE rotation (they will be unrecoverable otherwise)
# This requires custom script to decrypt with OLD key

cat > /tmp/export_keys.py << 'EOF'
import sqlite3
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

OLD_MASTER_KEY = os.environ.get('MASTER_ENCRYPTION_KEY')

def derive_user_key(user_id: str, master_key: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=user_id.encode(),
        iterations=100000
    )
    return base64.urlsafe_b64encode(kdf.derive(master_key.encode()))

def decrypt_api_key(user_id: str, ciphertext: bytes) -> str:
    key = derive_user_key(user_id, OLD_MASTER_KEY)
    f = Fernet(key)
    return f.decrypt(ciphertext).decode()

# Export all keys
conn = sqlite3.connect('data/auth.db')
cursor = conn.cursor()
cursor.execute("""
    SELECT ak.user_id, ak.key_name, ak.encrypted_value, u.email
    FROM user_api_keys ak
    JOIN users u ON ak.user_id = u.id
""")

print("# Exported API Keys (SENSITIVE - DELETE AFTER USE)")
for row in cursor.fetchall():
    user_id, key_name, encrypted_value, email = row
    try:
        decrypted = decrypt_api_key(user_id, encrypted_value)
        print(f"{email}|{key_name}|{decrypted}")
    except Exception as e:
        print(f"# ERROR: {email}|{key_name}: {e}")

conn.close()
EOF

# Run export with current key
python /tmp/export_keys.py > /tmp/exported_keys.txt
echo "Keys exported to /tmp/exported_keys.txt"
echo "IMPORTANT: Secure and delete this file after re-encryption"

# 3. Update .env with new master key
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
# Edit .env and replace MASTER_ENCRYPTION_KEY

# 4. Delete all encrypted keys (they're now unusable)
sqlite3 data/auth.db "DELETE FROM user_api_keys;"

# 5. Restart services
docker compose restart auth

# 6. Re-encrypt and restore keys
cat > /tmp/import_keys.py << 'EOF'
import sqlite3
import os
import uuid
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

NEW_MASTER_KEY = os.environ.get('MASTER_ENCRYPTION_KEY')

def derive_user_key(user_id: str, master_key: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=user_id.encode(),
        iterations=100000
    )
    return base64.urlsafe_b64encode(kdf.derive(master_key.encode()))

def encrypt_api_key(user_id: str, plaintext: str) -> bytes:
    key = derive_user_key(user_id, NEW_MASTER_KEY)
    f = Fernet(key)
    return f.encrypt(plaintext.encode())

conn = sqlite3.connect('data/auth.db')
cursor = conn.cursor()

# Get user_id by email
def get_user_id(email):
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    return row[0] if row else None

with open('/tmp/exported_keys.txt', 'r') as f:
    for line in f:
        if line.startswith('#'):
            continue
        parts = line.strip().split('|')
        if len(parts) != 3:
            continue
        email, key_name, plaintext = parts
        user_id = get_user_id(email)
        if user_id:
            encrypted = encrypt_api_key(user_id, plaintext)
            cursor.execute("""
                INSERT INTO user_api_keys (id, user_id, key_name, encrypted_value, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (str(uuid.uuid4()), user_id, key_name, encrypted))
            print(f"Restored: {email} - {key_name}")

conn.commit()
conn.close()
EOF

# Source new .env and run import
source .env
python /tmp/import_keys.py

# 7. CRITICAL: Securely delete exported keys
shred -u /tmp/exported_keys.txt 2>/dev/null || rm -f /tmp/exported_keys.txt
rm -f /tmp/export_keys.py /tmp/import_keys.py

# 8. Verify keys are working
echo "Test API key retrieval through auth service"
```

### Password Reset for Affected Users

```bash
# 1. Generate password reset tokens (if implemented) or set temporary passwords

# Option A: Direct password reset (requires user notification)
cat > /tmp/reset_password.py << 'EOF'
import sqlite3
import bcrypt
import secrets
import string

def generate_temp_password(length=16):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

# Get user email from argument
import sys
if len(sys.argv) < 2:
    print("Usage: python reset_password.py <email>")
    sys.exit(1)

email = sys.argv[1]
temp_password = generate_temp_password()
password_hash = hash_password(temp_password)

conn = sqlite3.connect('data/auth.db')
cursor = conn.cursor()
cursor.execute("UPDATE users SET password_hash = ? WHERE email = ?", (password_hash, email))

if cursor.rowcount > 0:
    conn.commit()
    print(f"Password reset for: {email}")
    print(f"Temporary password: {temp_password}")
    print("IMPORTANT: User must change password on first login")
else:
    print(f"User not found: {email}")

conn.close()
EOF

# Reset password for specific user
python /tmp/reset_password.py "affected@example.com"

# 2. Invalidate existing sessions for reset users
sqlite3 data/auth.db "DELETE FROM sessions WHERE user_id = (SELECT id FROM users WHERE email = 'affected@example.com');"

# 3. Clean up
rm -f /tmp/reset_password.py
```

### Service Restoration

```bash
# 1. Verify all services are configured correctly
docker compose config --quiet && echo "Configuration valid"

# 2. Start services in dependency order
docker compose up -d qdrant redis ollama
sleep 10

# Verify backend services are healthy
curl -s http://localhost:6333/health && echo "Qdrant OK"
curl -s http://localhost:11434/api/tags && echo "Ollama OK"

# 3. Start application services
docker compose up -d auth
sleep 5
curl -s http://localhost:8000/health && echo "Auth OK"

docker compose up -d app dashboard-backend dashboard-ui
sleep 5

# 4. Start reverse proxy
docker compose up -d caddy

# 5. Verify all services
docker compose ps

# 6. Test basic functionality
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ && echo " - Caddy routing OK"

# 7. Restore external access (only after verification)
docker compose up -d cloudflared

# 8. Monitor for issues
docker compose logs -f --tail=50
```

### Data Integrity Verification

```bash
# 1. SQLite database integrity
echo "=== Database Integrity Checks ==="
sqlite3 data/auth.db "PRAGMA integrity_check;"
sqlite3 data/sme.db "PRAGMA integrity_check;"
sqlite3 data/chat_history.db "PRAGMA integrity_check;" 2>/dev/null || echo "chat_history.db not found or empty"

# 2. Check foreign key consistency
sqlite3 data/auth.db << 'EOF'
-- Sessions with valid users
SELECT COUNT(*) as orphan_sessions FROM sessions WHERE user_id NOT IN (SELECT id FROM users);

-- API keys with valid users
SELECT COUNT(*) as orphan_keys FROM user_api_keys WHERE user_id NOT IN (SELECT id FROM users);
EOF

sqlite3 data/sme.db << 'EOF'
-- Processing status with valid papers
SELECT COUNT(*) as orphan_status FROM processing_status WHERE paper_id NOT IN (SELECT id FROM papers);
EOF

# 3. Qdrant collection health
echo ""
echo "=== Qdrant Health ==="
curl -s "http://localhost:6333/health" | python -m json.tool
curl -s "http://localhost:6333/collections/sme_papers_v2" | python -m json.tool | grep -E "status|points_count|indexed_vectors_count"

# 4. Verify BM25 index exists and is accessible
echo ""
echo "=== BM25 Index Check ==="
if [ -d "data/bm25_index_tantivy" ]; then
    ls -la data/bm25_index_tantivy/
    echo "BM25 index directory exists"
else
    echo "WARNING: BM25 index directory not found"
fi

# 5. Cross-reference paper counts
echo ""
echo "=== Paper Count Verification ==="
SQLITE_COUNT=$(sqlite3 data/sme.db "SELECT COUNT(*) FROM papers WHERE status = 'embedded';")
echo "Papers marked as embedded in SQLite: $SQLITE_COUNT"

QDRANT_COUNT=$(curl -s "http://localhost:6333/collections/sme_papers_v2/points/count" | python -c "import json,sys; print(json.load(sys.stdin).get('result', {}).get('count', 'ERROR'))")
echo "Points in Qdrant: $QDRANT_COUNT"

# 6. Verify user data isolation
echo ""
echo "=== User Data Isolation Check ==="
sqlite3 data/sme.db << 'EOF'
SELECT user_id, COUNT(*) as paper_count
FROM papers
WHERE user_id IS NOT NULL
GROUP BY user_id;
EOF

# 7. Check for data anomalies
echo ""
echo "=== Anomaly Detection ==="
sqlite3 data/auth.db << 'EOF'
-- Users with suspicious activity patterns
SELECT email,
       (SELECT COUNT(*) FROM sessions WHERE user_id = users.id) as session_count,
       last_login
FROM users
WHERE (SELECT COUNT(*) FROM sessions WHERE user_id = users.id) > 10;
EOF
```

---

## Post-Incident Actions

### Documentation Requirements

Every incident must be documented with the following information:

```markdown
# Incident Report Template

## Incident Overview
- **Incident ID:** INC-YYYY-MM-DD-XXX
- **Date/Time Detected:**
- **Date/Time Resolved:**
- **Severity Level:** Critical/High/Medium/Low
- **Incident Type:** (e.g., Credential Compromise, Data Access Violation, etc.)

## Summary
[Brief description of what happened]

## Timeline
| Time | Event | Action Taken |
|------|-------|--------------|
| HH:MM | Detection | ... |
| HH:MM | Containment | ... |
| HH:MM | Investigation | ... |
| HH:MM | Recovery | ... |
| HH:MM | Resolution | ... |

## Impact Assessment
- **Users Affected:** [number/list]
- **Data Exposed:** [description]
- **Services Disrupted:** [list]
- **Duration of Impact:** [time period]

## Root Cause
[Detailed technical explanation]

## Evidence Collected
- [ ] Logs preserved
- [ ] Database snapshots taken
- [ ] Container states captured
- [ ] Screenshots/recordings

## Response Actions
1. [Action taken]
2. [Action taken]
...

## Recovery Steps
1. [Step performed]
2. [Step performed]
...

## Lessons Learned
- [What worked well]
- [What could be improved]

## Follow-up Actions
| Action | Owner | Due Date | Status |
|--------|-------|----------|--------|
| ... | ... | ... | ... |

## Approvals
- **Incident Handler:** [Name]
- **Reviewed By:** [Name]
- **Date:** [Date]
```

### Root Cause Analysis

```bash
# RCA Investigation Checklist

# 1. Collect all evidence artifacts
ls -la /tmp/incident_*/

# 2. Generate timeline report
cat /tmp/incident_*/MANIFEST.txt

# 3. Code review for vulnerability
# Check recent commits if using version control
git log --oneline -20

# 4. Configuration review
# Compare current config with known-good baseline
diff -u config/config.yaml.baseline config/config.yaml

# 5. Dependency vulnerability scan
pip audit 2>/dev/null || pip-audit
npm audit 2>/dev/null

# 6. Identify contributing factors checklist:
echo "RCA Contributing Factors Checklist:"
echo "[ ] Software vulnerability (CVE)"
echo "[ ] Configuration error"
echo "[ ] Missing security control"
echo "[ ] Human error"
echo "[ ] Social engineering"
echo "[ ] Third-party compromise"
echo "[ ] Insufficient monitoring"
echo "[ ] Process failure"
```

### Security Improvements

After each incident, evaluate and implement appropriate improvements:

#### Short-term (Immediate to 1 week)
- [ ] Rotate compromised credentials
- [ ] Patch identified vulnerabilities
- [ ] Add missing log entries
- [ ] Update firewall rules
- [ ] Enhance monitoring alerts

#### Medium-term (1-4 weeks)
- [ ] Implement additional authentication controls
- [ ] Add rate limiting to new endpoints
- [ ] Enhance audit logging
- [ ] Conduct security training
- [ ] Update incident response procedures

#### Long-term (1-3 months)
- [ ] Architecture security review
- [ ] Penetration testing
- [ ] Security automation (SIEM, SOAR)
- [ ] Disaster recovery testing
- [ ] Third-party security audit

### Alert and Monitoring Updates

```yaml
# Add to monitoring configuration after incident

new_alerts:
  - name: "Similar Incident Detection"
    description: "Alert based on patterns from incident"
    trigger: "..."
    severity: "high"

  - name: "Enhanced Logging"
    endpoints:
      - "/api/auth/*"
      - "/api/search/*"
    log_level: "debug"
    retention: "30d"
```

---

## Contact Information Template

### Internal Contacts

| Role | Name | Email | Phone | Escalation Level |
|------|------|-------|-------|------------------|
| System Administrator | [Name] | [email] | [phone] | 1 (Primary) |
| Security Lead | [Name] | [email] | [phone] | 2 |
| Development Lead | [Name] | [email] | [phone] | 2 |
| Operations Manager | [Name] | [email] | [phone] | 3 |
| Executive Sponsor | [Name] | [email] | [phone] | 4 (Critical only) |

### External Contacts

| Service | Contact | When to Contact |
|---------|---------|-----------------|
| Cloudflare Support | support.cloudflare.com | DDoS, Tunnel issues |
| Cloud Provider | [support URL] | Infrastructure issues |
| Legal Counsel | [email] | Data breach notification |
| Law Enforcement | [local contact] | Criminal activity |
| Cyber Insurance | [contact] | Coverage notification |

### Escalation Path

```
Level 1: System Administrator
    │
    ├── (High Severity - 1 hour no response)
    ▼
Level 2: Security Lead + Development Lead
    │
    ├── (Critical Severity OR 2 hours no response)
    ▼
Level 3: Operations Manager
    │
    ├── (Data breach confirmed OR 4 hours no resolution)
    ▼
Level 4: Executive Sponsor
```

### Communication Templates

#### Initial Notification (Internal)

```
Subject: [SEVERITY] Security Incident - INC-YYYY-MM-DD-XXX

Incident Type: [type]
Severity: [Critical/High/Medium/Low]
Status: [Active/Contained/Resolved]
Detected: [timestamp]

Summary:
[Brief description]

Current Impact:
- Users affected: [number]
- Services impacted: [list]

Current Actions:
- [action being taken]

Next Update: [time]

Incident Handler: [name]
```

#### User Notification (If Required)

```
Subject: Security Notice - Action Required

Dear [User],

We detected unusual activity on your account on [date]. As a precautionary measure, we have:

- Reset your session (you will need to log in again)
- [Other actions taken]

Recommended Actions:
1. Change your password at your earliest convenience
2. Review your recent account activity
3. Contact us if you notice anything suspicious

If you did not initiate this activity, please contact us immediately at [email].

We take security seriously and apologize for any inconvenience.

[Signature]
```

#### Post-Incident Summary (Stakeholders)

```
Subject: Incident Resolved - INC-YYYY-MM-DD-XXX Summary

Incident Type: [type]
Severity: [level]
Duration: [start] to [end]

Summary:
[What happened]

Impact:
- [impact details]

Root Cause:
[Brief explanation]

Resolution:
[What was done]

Preventive Measures:
- [measure 1]
- [measure 2]

Detailed report available upon request.

[Signature]
```

---

## Quick Reference Card

### Emergency Commands

```bash
# STOP ALL EXTERNAL ACCESS
docker compose stop cloudflared caddy

# INVALIDATE ALL SESSIONS
sqlite3 data/auth.db "DELETE FROM sessions;"

# PRESERVE EVIDENCE
docker compose logs > /tmp/incident_logs_$(date +%Y%m%d_%H%M%S).log 2>&1
cp data/*.db /tmp/

# CHECK SERVICE STATUS
docker compose ps

# RESTART SINGLE SERVICE
docker compose restart <service>

# FULL RESTART (after resolution)
docker compose down && docker compose up -d
```

### Severity Quick Guide

| Indicator | Severity | Response Time |
|-----------|----------|---------------|
| Data breach confirmed | Critical | Immediate |
| User reports seeing other's data | Critical | < 15 min |
| Successful unauthorized login | High | < 1 hour |
| Brute force attack active | Medium | < 4 hours |
| Single failed login | Low | Next business day |

---

## Related Documentation

- [SECURITY.md](SECURITY.md) - Security architecture and controls
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [CONFIGURATION.md](CONFIGURATION.md) - Configuration reference
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - General troubleshooting
