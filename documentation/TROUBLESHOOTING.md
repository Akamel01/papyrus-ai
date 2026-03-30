# SME Research Assistant - Troubleshooting Guide

**Version:** 1.0
**Last Updated:** March 2026

---

This guide helps you solve common issues with the SME Research Assistant. Each section covers a specific problem area with symptoms, causes, and step-by-step solutions.

---

## Table of Contents

1. [Docker Issues](#docker-issues)
2. [Service Startup Failures](#service-startup-failures)
3. [Authentication Issues](#authentication-issues)
4. [Cloudflare Tunnel Issues](#cloudflare-tunnel-issues)
5. [GPU and Ollama Issues](#gpu-and-ollama-issues)
6. [Retrieval and Search Issues](#retrieval-and-search-issues)
7. [Database Issues](#database-issues)
8. [Network Issues](#network-issues)
9. [Quick Diagnostic Commands](#quick-diagnostic-commands)

---

## Docker Issues

### Docker Engine 500 Errors (Windows)

**Symptoms:**
- All docker commands fail with: `request returned 500 Internal Server Error for API route and version http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/v1.51/...`
- Cannot run `docker compose logs`, `docker compose up`, or any docker command
- `docker compose up --build` fails with 500 errors for image pulls
- Docker Desktop appears to be running but is unresponsive

**Cause:**

The WSL2 Linux VM that powers Docker Desktop has crashed or become unresponsive, typically due to memory pressure. When Docker containers request more memory than WSL2's budget, the Linux kernel inside WSL2 OOM-kills the Docker daemon process, producing 500 errors on the Windows named pipe.

**Immediate Fix (Manual):**

1. Quit Docker Desktop completely (right-click tray icon → Quit)
2. Run in PowerShell: `wsl --shutdown`
3. Wait 5 seconds, then restart Docker Desktop
4. Wait 1-2 minutes for the engine to initialize
5. Run: `docker compose up -d`

**Permanent Fix (Prevention):**

1. Ensure `.wslconfig` exists at `C:\Users\<username>\.wslconfig` with memory limits:
   ```ini
   [wsl2]
   memory=52G
   swap=8G
   processors=12
   autoMemoryReclaim=gradual
   ```

2. Ensure all services in `docker-compose.yml` have `deploy.resources.limits.memory` set.

3. After creating `.wslconfig`, restart WSL2:
   ```powershell
   wsl --shutdown
   # Then restart Docker Desktop
   ```

**Automatic Recovery (Self-Healing Watchdog):**

The watchdog script monitors Docker engine health and auto-recovers on failure:

```powershell
# Start the watchdog
powershell -File scripts/docker-watchdog.ps1

# Or use the robust startup script (includes watchdog option)
powershell -File scripts/start-robust.ps1 -WithWatchdog
```

View watchdog logs: `Get-Content logs/docker-watchdog.log -Tail 20`

---

### Docker Daemon Not Running

**Symptoms:**
- Error message: "Cannot connect to the Docker daemon"
- Error message: "docker: command not found" or "Is the docker daemon running?"
- Docker commands fail immediately

**Solution:**

1. **Start Docker Desktop:**
   - **Windows:** Find Docker Desktop in the Start menu and click to open it
   - **Mac:** Find Docker in Applications and double-click to start it
   - Wait 1-2 minutes for Docker to fully initialize

2. **Verify Docker is running:**
   ```bash
   docker info
   ```

   If successful, you will see system information about Docker.

3. **If Docker still will not start:**
   - Restart your computer
   - Reinstall Docker Desktop from [docker.com](https://www.docker.com/products/docker-desktop)

---

### Out of Memory Errors

**Symptoms:**
- Containers restart repeatedly
- Error message: "OOM killed" in logs
- System becomes slow or unresponsive
- Error message: "Cannot allocate memory"

**Solution:**

1. **Check current memory usage:**
   ```bash
   docker stats --no-stream
   ```

2. **Increase Docker memory allocation:**
   - **Windows/Mac:** Open Docker Desktop, go to Settings (gear icon), then Resources
   - Increase Memory to at least 8GB (16GB recommended)
   - Click "Apply & Restart"

3. **Reduce application memory limits:**

   Edit `docker-compose.yml` and lower the Qdrant memory limit:
   ```yaml
   qdrant:
     deploy:
       resources:
         limits:
           memory: 24G  # Reduce from 48G
         reservations:
           memory: 4G   # Reduce from 8G
   ```

4. **Restart the services:**
   ```bash
   docker compose down
   docker compose up -d
   ```

---

### Disk Space Issues

**Symptoms:**
- Error message: "no space left on device"
- Docker build fails
- Containers fail to start
- Paper downloads fail

**Solution:**

1. **Check available disk space:**

   **Windows:**
   Open File Explorer and check the drive where Docker data is stored.

   **Mac/Linux:**
   ```bash
   df -h
   ```

2. **Clean up Docker resources:**
   ```bash
   # Remove stopped containers
   docker container prune -f

   # Remove unused images
   docker image prune -a -f

   # Remove unused volumes (be careful - this removes data!)
   docker volume prune -f

   # Remove all unused data
   docker system prune -a -f
   ```

3. **Check Docker data location:**
   - Docker Desktop stores data in a virtual disk
   - Windows: Usually in `C:\Users\<username>\AppData\Local\Docker`
   - Mac: Usually in `~/Library/Containers/com.docker.docker`

4. **Move Docker data to a larger drive (Advanced):**
   - Windows: Docker Desktop Settings > Resources > Disk image location
   - Mac: Docker Desktop Settings > Resources > Disk image location

---

## Service Startup Failures

### Health Check Failures

**Symptoms:**
- Container shows status "unhealthy"
- Service restarts repeatedly
- Error in logs: "health check failed"

**Solution:**

1. **Check which service is unhealthy:**
   ```bash
   docker compose ps
   ```

2. **View the service logs:**
   ```bash
   # Replace "service_name" with the actual service (app, qdrant, auth, etc.)
   docker compose logs --tail=50 service_name
   ```

3. **Common fixes by service:**

   **Redis unhealthy:**
   ```bash
   docker compose restart redis
   ```

   **Qdrant unhealthy:**
   ```bash
   # Check if port 6333 is in use
   docker compose logs qdrant

   # Restart Qdrant
   docker compose restart qdrant
   ```

   **Auth service unhealthy:**
   ```bash
   # Check for missing environment variables
   docker compose logs auth

   # Verify .env file has JWT_SECRET and MASTER_ENCRYPTION_KEY
   ```

   **Ollama unhealthy:**
   ```bash
   # Check GPU access
   docker compose logs ollama

   # Restart Ollama
   docker compose restart ollama
   ```

4. **If a service keeps failing, rebuild it:**
   ```bash
   docker compose down
   docker compose build --no-cache service_name
   docker compose up -d
   ```

---

### Port Conflicts

**Symptoms:**
- Error message: "port is already allocated"
- Error message: "address already in use"
- Service fails to start but others work

**Solution:**

1. **Find what is using the port:**

   **Windows (PowerShell):**
   ```powershell
   netstat -ano | findstr :8080
   netstat -ano | findstr :8502
   netstat -ano | findstr :3030
   ```

   **Mac/Linux:**
   ```bash
   lsof -i :8080
   lsof -i :8502
   lsof -i :3030
   ```

2. **Stop the conflicting application** or change the SME port in `docker-compose.yml`:
   ```yaml
   caddy:
     ports:
       - "9080:80"  # Changed from 8080 to 9080
   ```

3. **Restart services:**
   ```bash
   docker compose down
   docker compose up -d
   ```

4. **Access the system at the new port:** http://localhost:9080/chat

---

## Authentication Issues

### Cannot Log In

**Symptoms:**
- Login form shows error message
- Redirected back to login page after entering credentials
- Error message: "Invalid credentials"

**Solution:**

1. **Verify the auth service is running:**
   ```bash
   docker compose ps auth
   docker compose logs auth
   ```

2. **Check that environment variables are set:**
   ```bash
   # View the .env file
   cat .env
   ```

   Ensure these are set:
   - `JWT_SECRET` (must be at least 32 characters)
   - `MASTER_ENCRYPTION_KEY`

3. **If you forgot your password, reset the admin account:**

   Edit `.env` file to set new admin credentials:
   ```env
   ADMIN_EMAIL=admin@example.com
   ADMIN_PASSWORD=NewSecurePassword123!
   ```

   Then restart the auth service:
   ```bash
   docker compose restart auth
   ```

4. **Clear your browser cache and cookies:**
   - Open browser settings
   - Clear cookies for localhost
   - Try logging in again

5. **Try a different browser or incognito/private window**

---

### Duplicate Login Form Error

**Symptoms:**
- Error during page load: "There are multiple identical forms with `key='login_form'`"
- Error appears briefly during initialization then disappears
- Login still works but error is visible momentarily

**Cause:**
This was caused by module-level execution in `app/pages/auth.py` that rendered the login form when the module was imported, and again when explicitly called by the authentication check.

**Solution:**
This issue was fixed in the codebase by:
- Removing module-level execution from `app/pages/auth.py`
- Removing duplicate localStorage JavaScript
- Using static form keys instead of dynamic ones

If you encounter this error, ensure you're running the latest version:
```bash
git pull
docker compose restart app
```

---

### Session Timeouts

**Symptoms:**
- Logged out unexpectedly
- "Session expired" message
- Need to log in frequently

**Solution:**

1. **Check the session timeout setting in `config/config.yaml`:**
   ```yaml
   security:
     session_timeout: 3600  # 3600 seconds = 1 hour
   ```

2. **Increase the timeout value:**
   ```yaml
   security:
     session_timeout: 28800  # 8 hours
   ```

3. **Restart the application:**
   ```bash
   docker compose restart app
   ```

---

### Account Lockout

**Symptoms:**
- Cannot log in even with correct password
- Error message mentions lockout or too many attempts
- Account temporarily disabled

**Solution:**

1. **Wait for the lockout period to expire:**

   Default lockout is 15 minutes after 10 failed attempts.

2. **To reset lockout immediately, restart the auth service:**
   ```bash
   docker compose restart auth
   ```

3. **Adjust lockout settings in `.env`:**
   ```env
   LOGIN_LOCKOUT_ATTEMPTS=10
   LOGIN_LOCKOUT_MINUTES=15
   ```

---

## Cloudflare Tunnel Issues

### Tunnel Not Connecting

**Symptoms:**
- Cannot access the system remotely
- No trycloudflare.com URL in logs
- Error message: "failed to connect to origin"

**Solution:**

1. **Check the tunnel service status:**
   ```bash
   docker compose ps cloudflared
   docker compose logs cloudflared
   ```

2. **Verify the Caddy service is running:**
   ```bash
   docker compose ps caddy
   ```

3. **Restart the tunnel:**
   ```bash
   docker compose restart cloudflared
   ```

4. **Get the new tunnel URL:**
   ```bash
   docker compose logs cloudflared | grep "trycloudflare.com"
   ```

5. **If tunnel keeps failing, check your internet connection:**
   - The tunnel requires outbound internet access
   - Some corporate networks block Cloudflare tunnels

---

### DNS/Domain Issues

**Symptoms:**
- Custom domain not working
- "DNS resolution failed" errors
- Certificate errors in browser

**Solution:**

1. **For trycloudflare.com URLs (temporary tunnels):**
   - URLs change every time the container restarts
   - Get the new URL: `docker compose logs cloudflared | grep "trycloudflare.com"`

2. **For custom domains:**
   - Verify DNS records point to Cloudflare
   - Check Cloudflare dashboard for tunnel status
   - Ensure tunnel token in docker-compose.yml is correct

3. **SSL/Certificate issues:**
   - Clear browser cache
   - Try accessing in incognito mode
   - Cloudflare provides automatic HTTPS, no certificates needed on your end

---

### Tunnel URL Changes After Restart

**Symptoms:**
- Previous URL no longer works
- Users cannot access with saved bookmark

**Explanation:**

This is normal behavior for free Cloudflare Quick Tunnels. The URL changes each time the cloudflared container restarts.

**Solutions:**

1. **Get the new URL each time:**
   ```bash
   docker compose logs cloudflared | grep "trycloudflare.com"
   ```

2. **For a permanent URL, use a paid Cloudflare Tunnel with your own domain:**
   - Create a tunnel at [one.dash.cloudflare.com](https://one.dash.cloudflare.com)
   - Configure with your tunnel token (see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md))

---

## GPU and Ollama Issues

### Embedding Model Not Found

**Symptoms:**
- Error message: "model not found"
- Embeddings fail
- Search returns no results

**Solution:**

1. **Check if the model is installed:**
   ```bash
   docker exec -it sme_ollama ollama list
   ```

2. **Pull the required model:**
   ```bash
   docker exec -it sme_ollama ollama pull qwen3-embedding:8b
   ```

3. **Verify the model name in `config/config.yaml` matches:**
   ```yaml
   embedding:
     model_name: "qwen3-embedding:8b"
   ```

4. **If the download fails, check internet connectivity inside the container:**
   ```bash
   docker exec -it sme_ollama curl -I https://ollama.ai
   ```

---

### GPU Not Detected

**Symptoms:**
- Embeddings run slowly (CPU mode)
- Error message: "CUDA not available"
- nvidia-smi shows no GPUs

**Solution:**

1. **Verify NVIDIA drivers are installed:**
   ```bash
   nvidia-smi
   ```

   If this command fails, install NVIDIA drivers from [nvidia.com/drivers](https://www.nvidia.com/drivers)

2. **Install NVIDIA Container Toolkit:**

   **Windows:**
   - NVIDIA Container Toolkit is included with Docker Desktop
   - Ensure "Use the WSL 2 based engine" is enabled in Docker Desktop settings

   **Linux:**
   ```bash
   # Add NVIDIA repository
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

   # Install
   sudo apt-get update
   sudo apt-get install -y nvidia-container-toolkit

   # Restart Docker
   sudo systemctl restart docker
   ```

3. **Restart Docker Desktop** after driver installation

4. **Test GPU access in Docker:**
   ```bash
   docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
   ```

---

### GPU Out of Memory

**Symptoms:**
- Error message: "CUDA out of memory"
- Model loading fails
- System becomes unresponsive during queries

**Solution:**

1. **Check current GPU memory usage:**
   ```bash
   docker exec -it sme_ollama nvidia-smi
   ```

2. **Free up GPU memory by stopping other GPU applications**

3. **Use a smaller embedding model:**

   Edit `config/config.yaml`:
   ```yaml
   embedding:
     model_name: "nomic-embed-text"  # Smaller alternative
   ```

   Pull the new model:
   ```bash
   docker exec -it sme_ollama ollama pull nomic-embed-text
   ```

4. **Enable model quantization (already default in this system):**
   ```yaml
   embedding:
     quantization: "4bit"
   ```

5. **Restart services:**
   ```bash
   docker compose restart app ollama
   ```

---

### Ollama Service Crashes

**Symptoms:**
- Ollama container keeps restarting
- Embedding requests fail intermittently
- Logs show segmentation faults or crashes

**Solution:**

1. **Check Ollama logs:**
   ```bash
   docker compose logs --tail=100 ollama
   ```

2. **Clear Ollama cache and restart:**
   ```bash
   docker compose down
   docker volume rm sme_ollama_data
   docker compose up -d

   # Re-pull the model
   docker exec -it sme_ollama ollama pull qwen3-embedding:8b
   ```

3. **Reduce Ollama parallel requests:**

   Edit `docker-compose.yml` under the ollama service:
   ```yaml
   environment:
     - OLLAMA_NUM_PARALLEL=64  # Reduce from 128
   ```

---

## Retrieval and Search Issues

### HyDE knowledge_source TypeError

**Symptoms:**
- Error message: `QdrantVectorStore.search() got an unexpected keyword argument 'knowledge_source'`
- HyDE search fails when using knowledge source filtering
- Error appears in logs: "HyDE Generation Failed"

**Cause:**
This was caused by the HyDE retriever passing `knowledge_source` directly to the vector store instead of converting it to filter conditions.

**Solution:**
This issue was fixed in the codebase. The HyDE retriever now:
1. Accepts `knowledge_source` as a named parameter
2. Converts it to proper filter conditions before calling the vector store
3. Supports all three modes: `shared_only`, `user_only`, `both`

If you encounter this error, update to the latest version:
```bash
git pull
docker compose restart app
```

**Verification:**
```bash
# Check that HyDE accepts knowledge_source parameter
docker compose exec app python -c "
from src.retrieval.hyde import HyDERetriever
import inspect
sig = inspect.signature(HyDERetriever.search)
print('knowledge_source' in sig.parameters)
"
# Should print: True
```

---

## Database Issues

### Database Corruption

**Symptoms:**
- Error message: "database is locked"
- Error message: "database disk image is malformed"
- Application crashes when accessing data
- Papers or chat history missing

**Solution:**

1. **Stop all services:**
   ```bash
   docker compose down
   ```

2. **Check database integrity:**
   ```bash
   # Check the main database
   docker run --rm -v sme_db_data:/data alpine sqlite3 /data/sme.db "PRAGMA integrity_check;"

   # Check the auth database
   docker run --rm -v sme_db_data:/data alpine sqlite3 /data/auth.db "PRAGMA integrity_check;"
   ```

3. **If corruption is detected, restore from backup** (if available)

4. **If no backup exists, try to recover:**
   ```bash
   # Create a dump of recoverable data
   docker run --rm -v sme_db_data:/data alpine sh -c "
     sqlite3 /data/sme.db '.dump' > /data/sme_backup.sql
   "
   ```

5. **As a last resort, recreate the database:**
   ```bash
   # WARNING: This deletes all data!
   docker volume rm sme_db_data
   docker compose up -d
   ```

---

### Migration Errors

**Symptoms:**
- Error message about database migrations
- "Table already exists" or "Table not found" errors
- Application fails to start

**Solution:**

1. **Check migration status:**
   ```bash
   docker compose logs app | grep -i migration
   docker compose logs auth | grep -i migration
   ```

2. **Force re-run migrations:**
   ```bash
   docker compose exec app python -c "from src.database import run_migrations; run_migrations()"
   ```

3. **If migrations continue to fail, backup and recreate:**
   ```bash
   # Backup
   docker compose exec app cp /app/data/sme.db /app/data/sme.db.backup

   # Recreate
   docker compose down
   docker compose up -d
   ```

---

## Network Issues

### CORS Errors

**Symptoms:**
- Browser console shows "CORS" errors
- API calls fail from the frontend
- "Access-Control-Allow-Origin" errors

**Solution:**

1. **Check that you are using the correct URL:**
   - Use http://localhost:8080 (through Caddy) not direct service ports
   - The Caddy reverse proxy handles CORS headers

2. **If using a custom setup, add CORS origins:**

   Edit `docker-compose.yml` under dashboard-backend:
   ```yaml
   environment:
     - CORS_ORIGINS=http://localhost:8080,http://localhost:3030,https://your-domain.com
   ```

3. **Restart services:**
   ```bash
   docker compose restart dashboard-backend caddy
   ```

---

### Firewall Blocking Connections

**Symptoms:**
- Cannot access http://localhost:8080
- Connection refused or timeout
- Works on the server but not from other computers

**Solution:**

1. **Check if ports are open locally:**
   ```bash
   curl http://localhost:8080
   ```

2. **Windows Firewall:**
   - Open Windows Defender Firewall
   - Click "Allow an app through firewall"
   - Add Docker Desktop and allow private/public access
   - Or allow ports 8080, 8502, 3030 specifically

3. **Mac Firewall:**
   - System Preferences > Security & Privacy > Firewall
   - Allow Docker to accept incoming connections

4. **Linux (ufw):**
   ```bash
   sudo ufw allow 8080/tcp
   sudo ufw allow 8502/tcp
   sudo ufw allow 3030/tcp
   ```

---

### Services Cannot Communicate

**Symptoms:**
- Errors about connection refused between services
- "Name resolution failed" errors
- One service cannot reach another

**Solution:**

1. **Check Docker network:**
   ```bash
   docker network ls
   docker network inspect sme_default
   ```

2. **Verify all services are on the same network:**
   ```bash
   docker compose ps
   ```

3. **Restart the entire stack:**
   ```bash
   docker compose down
   docker compose up -d
   ```

4. **If network issues persist, recreate networks:**
   ```bash
   docker compose down
   docker network prune -f
   docker compose up -d
   ```

---

## Quick Diagnostic Commands

Use these commands to quickly diagnose issues:

### Check Overall System Status

```bash
# View all container statuses
docker compose ps

# View resource usage
docker stats --no-stream

# View all logs (last 50 lines)
docker compose logs --tail=50
```

### Check Specific Services

```bash
# Redis
docker compose logs redis
docker exec -it sme_redis redis-cli ping

# Qdrant
docker compose logs qdrant
curl http://localhost:6333/health

# Ollama
docker compose logs ollama
docker exec -it sme_ollama ollama list

# Auth Service
docker compose logs auth

# Main Application
docker compose logs app
```

### Check GPU

```bash
# Host GPU status
nvidia-smi

# GPU inside Ollama container
docker exec -it sme_ollama nvidia-smi
```

### Check Disk Space

```bash
# Docker disk usage
docker system df

# Host disk usage (Linux/Mac)
df -h

# Clean up Docker
docker system prune -a
```

### Check Network

```bash
# Test service connectivity
docker exec -it sme_app curl -s http://sme_qdrant:6333/health
docker exec -it sme_app curl -s http://sme_ollama:11434/api/tags
docker exec -it sme_app curl -s http://sme_redis:6379
```

### Restart Services

```bash
# Restart everything
docker compose restart

# Restart specific service
docker compose restart app
docker compose restart qdrant
docker compose restart ollama

# Full reset (keeps data)
docker compose down
docker compose up -d

# Nuclear option - reset everything including data
# WARNING: This deletes all your data!
docker compose down -v
docker compose up -d
```

---

## Getting Additional Help

If you cannot resolve an issue using this guide:

1. **Collect diagnostic information:**
   ```bash
   # Save all logs to a file
   docker compose logs > sme_logs.txt 2>&1

   # Save system info
   docker info > docker_info.txt
   docker compose ps > services_status.txt
   ```

2. **Check existing documentation:**
   - [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Setup instructions
   - [CONFIGURATION.md](CONFIGURATION.md) - Configuration options
   - [USER_GUIDE.md](../USER_GUIDE.md) - Usage guide

3. **Search for similar issues** in the project issue tracker

4. **Report a new issue** with:
   - Description of the problem
   - Steps to reproduce
   - Error messages (from logs)
   - Your system information (OS, Docker version, hardware)

---

## Related Documentation

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Step-by-step deployment
- [CONFIGURATION.md](CONFIGURATION.md) - Configuration reference
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [USER_GUIDE.md](../USER_GUIDE.md) - User guide
