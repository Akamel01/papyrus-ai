# Cloudflare Tunnel - Setup & Maintenance Guide

## Overview

The SME system uses Cloudflare Tunnel (named tunnel) to expose the application at `papyrus-ai.net` without opening firewall ports.

---

## Current Setup (After Fix on 2026-03-30)

**Status**: ✅ Working

- **Tunnel ID**: `edf7796d-4ecc-4478-a538-0633a71b403e`
- **Tunnel Name**: `papyrus-tunnel`
- **Credentials File**: `config/cloudflared-credentials.json`
- **Config File**: `config/cloudflared-config.yml`
- **Docker Image**: `cloudflare/cloudflared:2024.12.2` (pinned, stable)
- **Connections**: 4 active (sea09, yvr02, sea09, yvr02)

---

## What Went Wrong (And How It's Fixed)

### The Problem

The `Endpoint` field in credentials was **EMPTY**, causing:
```json
{
  "AccountTag": "...",
  "TunnelSecret": "...",
  "TunnelID": "...",
  "Endpoint": ""  // ❌ INVALID - causes connection failure
}
```

When `Endpoint` is empty, cloudflared cannot:
1. Authenticate with Cloudflare's backend
2. Establish the tunnel connection
3. Route traffic from papyrus-ai.net

**Why it happens**: Cloudflare's tunnel creation sometimes omits the Endpoint field, requiring manual addition.

### The Solution (Implemented 2026-03-30)

1. **Regenerated tunnel credentials**:
   ```bash
   cloudflared tunnel delete papyrus-tunnel
   cloudflared tunnel create papyrus-tunnel
   ```

2. **Fixed the Endpoint field**:
   ```json
   {
     "AccountTag": "1bde08c94022d2f83395dafe200028fa",
     "TunnelSecret": "MnWtMeMjCXoMQ08v8mqhSIbN8VxzcvJDgEbaZSZD8xQ=",
     "TunnelID": "edf7796d-4ecc-4478-a538-0633a71b403e",
     "Endpoint": "https://tunnel.cloudflare.com"  // ✅ FIXED
   }
   ```

3. **Updated tunnel ID** in `config/cloudflared-config.yml`:
   ```yaml
   tunnel: edf7796d-4ecc-4478-a538-0633a71b403e
   ```

4. **Added automatic validation** in `docker-compose.yml`:
   - init-validator now checks all required fields
   - Validates Endpoint is a valid HTTPS URL
   - Prevents startup if credentials are invalid

---

## How to Prevent This in the Future

### 1. Automatic Validation (Already Implemented ✅)

The `init-validator` service in `docker-compose.yml` now:
- Validates credentials exist before cloudflared starts
- Checks all required fields are present
- Verifies Endpoint is a valid HTTPS URL
- **Fails startup** if validation fails (prevents silent tunnel failure)

**When it runs**: Every time you do `docker-compose up`

**Example output**:
```
init-validator    | ERROR: cloudflared-credentials.json field 'Endpoint' is empty
init-validator    | HINT: Run 'cloudflared tunnel create papyrus-tunnel' to regenerate
```

### 2. Manual Verification Script

A standalone script is available: `scripts/validate-cloudflare-credentials.sh`

**Usage**:
```bash
bash scripts/validate-cloudflare-credentials.sh config/cloudflared-credentials.json
```

**Output**:
```
[CLOUDFLARE-VALIDATOR] ✓ AccountTag: 1bde08c94022d2f83...
[CLOUDFLARE-VALIDATOR] ✓ TunnelSecret: MnWtMeMjCXoMQ08v8...
[CLOUDFLARE-VALIDATOR] ✓ TunnelID: edf7796d-4ecc-4478...
[CLOUDFLARE-VALIDATOR] ✓ Endpoint: https://tunnel.cloudflare.com
[CLOUDFLARE-VALIDATOR] ✅ All credentials validated successfully
```

### 3. Monitoring (Recommended)

Monitor the cloudflared logs regularly:

```bash
docker-compose logs cloudflared --tail 50 --follow
```

**Look for**:
- ✅ `"Registered tunnel connection"` - Normal, tunnel is healthy
- ❌ `"failed to lookup srv record"` - Endpoint issue
- ❌ `"failed to authenticate"` - Credential issue

---

## Regenerating Tunnel Credentials (If Needed)

**Only do this if the tunnel stops working.**

### Step 1: Stop the tunnel
```bash
docker-compose down cloudflared
sleep 5
```

### Step 2: Delete old tunnel
```bash
cloudflared tunnel list              # See the tunnel ID
cloudflared tunnel delete papyrus-tunnel
```

### Step 3: Create new tunnel
```bash
cloudflared tunnel create papyrus-tunnel
```

Output will show:
```
Tunnel credentials written to C:\Users\<user>\.cloudflared\<tunnel-id>.json
Created tunnel papyrus-tunnel with id <tunnel-id>
```

### Step 4: Copy credentials and fix Endpoint
```bash
# Copy the new credentials file
cp ~/.cloudflared/<tunnel-id>.json config/cloudflared-credentials.json

# Edit it and add the Endpoint field:
# "Endpoint": "https://tunnel.cloudflare.com"
```

### Step 5: Update config
Edit `config/cloudflared-config.yml` and update the tunnel ID:
```yaml
tunnel: <new-tunnel-id>
```

### Step 6: Restart
```bash
docker-compose up -d cloudflared
docker-compose logs cloudflared --tail 20
```

---

## Key Files

| File | Purpose | Notes |
|------|---------|-------|
| `config/cloudflared-credentials.json` | Tunnel credentials | ⚠️ KEEP SECRET - In .gitignore |
| `config/cloudflared-config.yml` | Tunnel routing config | Defines which domains → services |
| `scripts/validate-cloudflare-credentials.sh` | Validation script | Standalone validation |
| `docker-compose.yml` | Service definitions | Contains auto-validation logic |

---

## Validation Checklist

Before assuming the tunnel is working:

1. **Docker running**:
   ```bash
   docker ps | grep sme_tunnel
   # Should show: sme_tunnel ... "Up X minutes"
   ```

2. **Service is healthy**:
   ```bash
   docker-compose logs cloudflared --tail 20 | grep "Registered tunnel"
   # Should show: "Registered tunnel connection" (4 times)
   ```

3. **Credentials valid**:
   ```bash
   bash scripts/validate-cloudflare-credentials.sh config/cloudflared-credentials.json
   # Should exit with code 0 (success)
   ```

4. **DNS resolving**:
   ```bash
   nslookup papyrus-ai.net
   # Should return an IP address
   ```

5. **HTTP accessible**:
   ```bash
   curl -I https://papyrus-ai.net/chat
   # Should return 200 or 302 (redirect)
   ```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Container won't start | Invalid credentials JSON | Validate with script |
| Container starts but no connections | Missing/empty Endpoint | Regenerate tunnel |
| Connections drop after 5 min | Stale tunnel session | `docker-compose restart cloudflared` |
| DNS not resolving | Tunnel deleted on Cloudflare | Create new tunnel |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Cloudflare Edge (papyrus-ai.net)                        │
│ - 4 redundant connection points (sea09, yvr02, etc)     │
│ - TLS termination                                       │
│ - DDoS protection                                       │
└──────────────────────────┬──────────────────────────────┘
                           │ QUIC tunnel (secure)
                           │
┌──────────────────────────┴──────────────────────────────┐
│ Docker: cloudflared service (sme_tunnel)                │
│ - Credentials: config/cloudflared-credentials.json     │
│ - Routes: config/cloudflared-config.yml                │
│ - Image: cloudflare/cloudflared:2024.12.2 (pinned)    │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP/1.1
                           │
┌──────────────────────────┴──────────────────────────────┐
│ Docker: Caddy reverse proxy (sme_caddy)                 │
│ - Port: 80 (internal only)                              │
│ - Handles SSL termination for apps                      │
└──────────────────────────┬──────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────┴─────┐   ┌─────┴─────┐   ┌─────┴─────┐
    │ Streamlit │   │ Dashboard │   │Deploy Hook│
    │ (sme_app) │   │(sme_dash*) │   │  (sme_dh) │
    └───────────┘   └───────────┘   └───────────┘
```

---

## Environment Variables

No special env vars needed for cloudflared. Credentials are read from:
- `config/cloudflared-credentials.json` (volume mount)
- `config/cloudflared-config.yml` (volume mount)

---

## Security Notes

⚠️ **IMPORTANT**:
- **Never** commit `config/cloudflared-credentials.json` to git
- **Never** share your tunnel credentials
- **Never** put credentials in `.env` files
- **Always** use the `.gitignore` exclusion (already in place)
- **Rotate** credentials if they've been exposed
- **Use** the automatic validation to catch issues early

---

## References

- [Cloudflare Tunnel Docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
- [Named Tunnel Setup](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/tunnel-guide/named/)
- [Cloudflared Configuration](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/configuration/configuration-files/ingress-configuration/)
- Local guides: [CLOUDFLARE_TUNNEL_FIX.md](CLOUDFLARE_TUNNEL_FIX.md)

---

**Last Updated**: 2026-03-30
**Status**: ✅ Fixed and Validated
**Next Review**: Check logs monthly
