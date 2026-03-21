# SME Research Assistant - Deployment Guide

**Version:** 1.0
**Last Updated:** March 2026

---

This guide provides step-by-step instructions for deploying the SME Research Assistant. Written for users who may not have extensive technical experience, each section walks you through the process with clear explanations and commands you can copy and paste.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (5 Steps)](#quick-start-5-steps)
3. [Manual Setup](#manual-setup)
4. [Remote Access Options](#remote-access-options)
5. [Post-Deployment Verification](#post-deployment-verification)
6. [Common Configuration Options](#common-configuration-options)
7. [Updating and Maintenance](#updating-and-maintenance)

---

## Prerequisites

Before you begin, ensure your system meets these requirements:

### Required Software

| Software | Minimum Version | Download Link |
|----------|-----------------|---------------|
| Docker Desktop | 4.0+ | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop) |

**How to check if Docker is installed:**

Open a terminal (Command Prompt on Windows, Terminal on Mac/Linux) and run:

```bash
docker --version
```

You should see output like: `Docker version 24.0.0`

### Hardware Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **Disk Space** | 50 GB free | 100+ GB free |
| **RAM** | 16 GB | 64 GB |
| **GPU** | Optional | NVIDIA RTX 3060+ (12GB+ VRAM) |

**Important Notes:**
- The system works without a GPU but will be significantly slower
- Disk space is needed for: Docker images (~10GB), papers (~20GB+), and vector database (~20GB+)
- More RAM allows for faster searches across larger paper libraries

### Checking Your System Resources

**Windows:**
1. Press `Ctrl + Shift + Esc` to open Task Manager
2. Click the "Performance" tab
3. View Memory (RAM) and check your available disk space in File Explorer

**Mac:**
1. Click the Apple menu and select "About This Mac"
2. View Memory and Storage information

**Linux:**
```bash
# Check RAM
free -h

# Check disk space
df -h
```

---

## Quick Start (5 Steps)

If you want to get up and running quickly, follow these five steps:

### Step 1: Open Terminal and Navigate to Project

Open your terminal application and navigate to the SME Research Assistant folder:

```bash
cd /path/to/SME
```

Replace `/path/to/SME` with the actual path where your project is located (for example, `cd C:\gpt\SME` on Windows or `cd ~/projects/SME` on Mac/Linux).

### Step 2: Create Environment File

Copy the example environment file to create your own configuration:

**Mac/Linux:**
```bash
cp .env.example .env
```

**Windows (Command Prompt):**
```cmd
copy .env.example .env
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

### Step 3: Generate Security Secrets

You need to create two secret keys. Run these commands and copy the output:

**Mac/Linux:**
```bash
openssl rand -base64 32
```

Run this command twice - once for JWT_SECRET and once for MASTER_ENCRYPTION_KEY.

**Windows (if OpenSSL is not available):**

Use an online generator or Python:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 4: Edit the Environment File

Open the `.env` file in a text editor and fill in these required values:

```env
JWT_SECRET=paste_your_first_generated_secret_here
MASTER_ENCRYPTION_KEY=paste_your_second_generated_secret_here
ADMIN_EMAIL=admin@yourcompany.com
ADMIN_PASSWORD=YourSecurePassword123!
```

**Password Requirements:**
- Minimum 12 characters
- Must include letters and numbers

Save and close the file.

### Step 5: Start the System

Run Docker Compose to start all services:

```bash
docker compose up -d
```

This command will:
1. Download all necessary Docker images (first time only, may take 10-15 minutes)
2. Create the required containers
3. Start all services in the background

Wait 2-3 minutes for all services to initialize, then access the system at:
- **Chat Interface:** http://localhost:8080/chat
- **Dashboard:** http://localhost:8080/dashboard

---

## Manual Setup

If you prefer more control or the Quick Start did not work, follow these detailed steps.

### Step 1: Verify Docker is Running

Ensure Docker Desktop is running. You should see the Docker icon in your system tray (Windows) or menu bar (Mac).

Test Docker is working:

```bash
docker info
```

If you see an error like "Cannot connect to the Docker daemon," start Docker Desktop and wait for it to fully load.

### Step 2: Clone or Download the Project

If you have not already downloaded the project:

**Using Git:**
```bash
git clone https://github.com/your-org/SME.git
cd SME
```

**Manual Download:**
1. Download the project ZIP file
2. Extract it to a folder on your computer
3. Open terminal and navigate to that folder

### Step 3: Create and Configure Environment File

Create your environment file:

**Mac/Linux:**
```bash
cp .env.example .env
```

**Windows:**
```cmd
copy .env.example .env
```

Open `.env` in a text editor (Notepad, VS Code, etc.) and configure:

```env
# ── REQUIRED: Multi-User Authentication ──
JWT_SECRET=your_32_character_secret_key_here
MASTER_ENCRYPTION_KEY=your_32_byte_base64_key_here

# ── OPTIONAL: Initial Admin Account ──
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=SecurePassword123!

# ── OPTIONAL: API Keys for Paper Discovery ──
OPENALEX_API_KEY=your_openalex_key
SEMANTIC_SCHOLAR_API_KEY=your_semantic_scholar_key
SME_EMAILS=your.email@example.com
```

### Step 4: Build and Start Services

Build the Docker images (first time only):

```bash
docker compose build
```

This may take 10-20 minutes depending on your internet speed.

Start all services:

```bash
docker compose up -d
```

### Step 5: Pull the Embedding Model

After services start, you need to download the AI embedding model:

```bash
docker exec -it sme_ollama ollama pull qwen3-embedding:8b
```

This downloads approximately 4-5 GB and may take several minutes.

### Step 6: Verify All Services are Running

Check that all containers are healthy:

```bash
docker compose ps
```

You should see all services with status "Up" or "healthy":

```
NAME                STATUS
sme_redis           Up (healthy)
sme_qdrant          Up (healthy)
sme_ollama          Up (healthy)
sme_app             Up
sme_auth            Up (healthy)
sme_caddy           Up
sme_dashboard_api   Up
sme_dashboard_ui    Up
sme_tunnel          Up
```

---

## Remote Access Options

The SME Research Assistant offers three ways to access the system:

### Option 1: Local Access Only (Default)

Access the system only from the computer running Docker:

| Service | URL |
|---------|-----|
| Chat Interface | http://localhost:8080/chat |
| Dashboard | http://localhost:8080/dashboard |
| Direct Streamlit | http://localhost:8502 |

**Pros:** Most secure, no additional configuration needed
**Cons:** Cannot access from other devices

### Option 2: Cloudflare Tunnel (Free, Recommended for Remote Access)

The system includes automatic Cloudflare Tunnel support, providing free HTTPS access from anywhere.

**How to get your tunnel URL:**

```bash
docker compose logs cloudflared | grep "trycloudflare.com"
```

Look for a URL like: `https://random-words-here.trycloudflare.com`

**Important Notes:**
- The URL changes each time you restart the cloudflared container
- The tunnel provides automatic HTTPS encryption
- Share this URL with authorized users only

**To restart and get a new URL:**
```bash
docker compose restart cloudflared
docker compose logs cloudflared | grep "trycloudflare.com"
```

### Option 3: Custom Domain - papyrus-ai.net (Production)

The SME Research Assistant is configured for production deployment at **https://papyrus-ai.net**.

#### Setup Instructions

**Step 1: Install cloudflared CLI**

**Windows:**
```cmd
winget install Cloudflare.cloudflared
```

**Mac:**
```bash
brew install cloudflared
```

**Linux:**
```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared && sudo mv cloudflared /usr/local/bin/
```

**Step 2: Authenticate with Cloudflare**

```bash
cloudflared tunnel login
```

This opens a browser to authenticate with your Cloudflare account.

**Step 3: Create the Named Tunnel**

```bash
cloudflared tunnel create papyrus-tunnel
```

This creates the tunnel and outputs a credentials file path like:
`~/.cloudflared/<TUNNEL_ID>.json`

**Step 4: Copy Credentials to Project**

```bash
# Find your tunnel ID
cloudflared tunnel list

# Copy credentials file (replace <TUNNEL_ID> with actual ID)
cp ~/.cloudflared/<TUNNEL_ID>.json ./config/cloudflared-credentials.json
```

**Step 5: Route DNS to Tunnel**

```bash
cloudflared tunnel route dns papyrus-tunnel papyrus-ai.net
```

This creates a CNAME record in Cloudflare DNS pointing to your tunnel.

**Step 6: Start the System**

```bash
docker compose up -d
```

The system will now be accessible at **https://papyrus-ai.net**

#### Configuration Files

The following files are pre-configured for papyrus-ai.net:

| File | Configuration |
|------|---------------|
| `docker-compose.yml` | cloudflared service uses named tunnel mode |
| `scripts/setup-cloudflare.sh` | Default tunnel name: `papyrus-tunnel` |
| CORS settings | `https://papyrus-ai.net` whitelisted |

#### Verifying the Setup

```bash
# Check tunnel is running
docker compose logs cloudflared

# Should show: Connection registered

# Test the URL
curl -I https://papyrus-ai.net
```

**Production URLs:**
| Service | URL |
|---------|-----|
| Chat Interface | https://papyrus-ai.net/chat |
| Dashboard | https://papyrus-ai.net/dashboard |

**Pros:** Permanent URL, professional appearance, automatic HTTPS, DDoS protection
**Cons:** Requires domain ownership and initial Cloudflare configuration

---

## Post-Deployment Verification

After deployment, verify everything is working correctly:

### 1. Check All Services are Running

```bash
docker compose ps
```

All services should show "Up" status.

### 2. Check Service Health

```bash
docker compose logs --tail=20 auth
docker compose logs --tail=20 app
docker compose logs --tail=20 qdrant
```

Look for any error messages. Healthy services show normal startup logs without ERROR lines.

### 3. Access the Web Interface

1. Open your browser
2. Navigate to http://localhost:8080/chat
3. You should see the login page

### 4. Create an Account

1. Click "Sign Up" tab
2. Enter your email and a password (minimum 12 characters)
3. Click "Create Account"
4. You should be logged in and see the chat interface

### 5. Test a Query

1. In the chat interface, type a simple question like: "What is road safety?"
2. Press Enter
3. You should receive a response (even if no papers are loaded, the system should respond)

### 6. Check the Dashboard

1. Navigate to http://localhost:8080/dashboard
2. You should see the monitoring interface
3. Verify GPU stats are displaying (if you have an NVIDIA GPU)

### 7. Verify Embedding Model

```bash
docker exec -it sme_ollama ollama list
```

You should see `qwen3-embedding:8b` in the list.

---

## Common Configuration Options

### Changing Memory Limits

If you have limited RAM, edit `docker-compose.yml`:

```yaml
qdrant:
  deploy:
    resources:
      limits:
        memory: 24G  # Reduce from 48G for systems with less RAM
      reservations:
        memory: 4G   # Reduce from 8G
```

Restart after changes:
```bash
docker compose down
docker compose up -d
```

### Changing the LLM Model

Edit `config/config.yaml`:

```yaml
generation:
  model_name: "your-model-name:tag"
```

Then pull the model:
```bash
docker exec -it sme_ollama ollama pull your-model-name:tag
```

### Adjusting Search Depth

Edit `config/config.yaml`:

```yaml
retrieval:
  top_k_initial: 50     # Papers to consider initially
  top_k_rerank: 20      # Papers to rerank
  top_k_final: 10       # Papers in final results
```

### Adding Research Keywords

Edit `config/acquisition_config.yaml`:

```yaml
acquisition:
  keywords:
    - '"Your Research Topic" AND "Specific Terms"'
    - '"Another Topic"'
```

### Changing Port Numbers

Edit `docker-compose.yml` to change external ports:

```yaml
caddy:
  ports:
    - "8080:80"  # Change 8080 to your preferred port

app:
  ports:
    - "8502:8501"  # Change 8502 to your preferred port
```

---

## Updating and Maintenance

### Updating the System

When updates are available:

1. Stop the running services:
```bash
docker compose down
```

2. Get the latest code (if using Git):
```bash
git pull origin main
```

3. Rebuild the images:
```bash
docker compose build --no-cache
```

4. Start the updated services:
```bash
docker compose up -d
```

### Backing Up Data

Important data to back up:

| Location | Contents |
|----------|----------|
| `data/` | Database files, chat history |
| `config/` | Your configuration files |
| `.env` | Your environment variables |
| `DataBase/Papers/` | Downloaded PDF files |

**Create a backup:**

**Mac/Linux:**
```bash
tar -czvf sme_backup_$(date +%Y%m%d).tar.gz data/ config/ .env DataBase/Papers/
```

**Windows PowerShell:**
```powershell
Compress-Archive -Path data, config, .env, DataBase\Papers -DestinationPath "sme_backup_$(Get-Date -Format 'yyyyMMdd').zip"
```

### Viewing Logs

View logs for all services:
```bash
docker compose logs -f
```

View logs for a specific service:
```bash
docker compose logs -f app
docker compose logs -f qdrant
docker compose logs -f ollama
```

### Restarting Services

Restart all services:
```bash
docker compose restart
```

Restart a specific service:
```bash
docker compose restart app
docker compose restart qdrant
```

### Cleaning Up Disk Space

Remove old Docker images and cache:
```bash
docker system prune -a
```

**Warning:** This removes all unused images. Only run when you have a working system and want to reclaim disk space.

### Checking System Health

View resource usage:
```bash
docker stats
```

This shows real-time CPU and memory usage for each container.

### Stopping Everything

To completely stop and remove all containers:
```bash
docker compose down
```

To stop and also remove data volumes (WARNING: This deletes your data!):
```bash
docker compose down -v
```

---

## Next Steps

After successful deployment:

1. **Add Papers:** Follow the [User Guide](../USER_GUIDE.md) to add papers to your library
2. **Configure Keywords:** Set up research keywords for automatic paper discovery
3. **Invite Users:** Share the access URL with your team members
4. **Review Troubleshooting:** If you encounter issues, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## Related Documentation

- [USER_GUIDE.md](../USER_GUIDE.md) - How to use the system
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues and solutions
- [CONFIGURATION.md](CONFIGURATION.md) - Detailed configuration reference
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture overview
