#!/bin/bash
# SME Research Assistant — Cloudflare Tunnel Setup
# Guided setup for exposing the SME Research Assistant via Cloudflare Tunnel.
#
# This script:
# 1. Checks for cloudflared CLI (guides installation if missing)
# 2. Guides user through Cloudflare login
# 3. Creates a tunnel named "sme-research"
# 4. Outputs the tunnel URL
# 5. Provides instructions for custom domain configuration
#
# Usage: bash scripts/setup-cloudflare.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root
cd "$PROJECT_ROOT"

# ── Color Definitions ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ── Helper Functions ──
info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; }
step()    { echo -e "\n${BOLD}${CYAN}Step $1:${NC} ${BOLD}$2${NC}"; }
prompt()  { echo -e "${YELLOW}>>>${NC} $1"; }

# ── Configuration ──
TUNNEL_NAME="papyrus-tunnel"
DOMAIN="papyrus-ai.net"

echo -e "${BOLD}==========================================="
echo "  SME Research Assistant"
echo "  Cloudflare Tunnel Setup"
echo -e "===========================================${NC}"
echo ""
echo "This script will configure secure access via Cloudflare Tunnel."
echo ""
echo -e "Default Configuration:"
echo -e "  Tunnel Name: ${CYAN}${TUNNEL_NAME}${NC}"
echo -e "  Domain:      ${CYAN}https://${DOMAIN}${NC}"
echo ""
echo "Requirements:"
echo "  - Cloudflare account with ${DOMAIN} added"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

# ══════════════════════════════════════════════════════════════════════
# STEP 1: Check for cloudflared CLI
# ══════════════════════════════════════════════════════════════════════
step "1" "Checking for cloudflared CLI"

if command -v cloudflared &> /dev/null; then
    CLOUDFLARED_VERSION=$(cloudflared --version 2>&1 | head -1)
    success "cloudflared is installed: $CLOUDFLARED_VERSION"
else
    warn "cloudflared CLI is not installed"
    echo ""
    echo "Installation instructions:"
    echo ""

    # Detect OS and provide appropriate instructions
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  macOS (Homebrew):"
        echo "    brew install cloudflared"
        echo ""
        echo "  macOS (Direct download):"
        echo "    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz | tar xz"
        echo "    sudo mv cloudflared /usr/local/bin/"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "  Debian/Ubuntu:"
        echo "    curl -L https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-archive-keyring.gpg"
        echo "    echo 'deb [signed-by=/usr/share/keyrings/cloudflare-archive-keyring.gpg] https://pkg.cloudflare.com/cloudflared focal main' | sudo tee /etc/apt/sources.list.d/cloudflared.list"
        echo "    sudo apt update && sudo apt install cloudflared"
        echo ""
        echo "  Arch Linux:"
        echo "    yay -S cloudflared"
        echo ""
        echo "  Direct binary (any Linux):"
        echo "    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared"
        echo "    chmod +x cloudflared && sudo mv cloudflared /usr/local/bin/"
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        echo "  Windows (winget):"
        echo "    winget install Cloudflare.cloudflared"
        echo ""
        echo "  Windows (Chocolatey):"
        echo "    choco install cloudflared"
        echo ""
        echo "  Windows (Direct download):"
        echo "    Download from: https://github.com/cloudflare/cloudflared/releases/latest"
        echo "    Choose: cloudflared-windows-amd64.exe"
        echo "    Rename to cloudflared.exe and add to PATH"
    else
        echo "  Visit: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
    fi

    echo ""
    error "Please install cloudflared and run this script again."
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 2: Cloudflare Login
# ══════════════════════════════════════════════════════════════════════
step "2" "Cloudflare Authentication"

# Check if already logged in
if cloudflared tunnel list &> /dev/null 2>&1; then
    success "Already authenticated with Cloudflare"
else
    echo ""
    echo "You need to authenticate with your Cloudflare account."
    echo "This will open a browser window for you to log in."
    echo ""
    prompt "Press Enter to open the Cloudflare login page..."
    read

    info "Opening browser for authentication..."
    if ! cloudflared tunnel login; then
        error "Cloudflare login failed"
        echo "  If the browser didn't open, visit the URL shown above manually"
        exit 1
    fi
    success "Successfully authenticated with Cloudflare"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 3: Create or Verify Tunnel
# ══════════════════════════════════════════════════════════════════════
step "3" "Creating Cloudflare Tunnel"

# Check if tunnel already exists
EXISTING_TUNNEL=$(cloudflared tunnel list --output json 2>/dev/null | grep -o "\"name\":\"${TUNNEL_NAME}\"" || true)

if [ -n "$EXISTING_TUNNEL" ]; then
    warn "Tunnel '${TUNNEL_NAME}' already exists"
    echo ""
    read -p "Use existing tunnel? (Y/n): " USE_EXISTING

    if [ "$USE_EXISTING" = "n" ] || [ "$USE_EXISTING" = "N" ]; then
        read -p "Enter a different tunnel name: " NEW_TUNNEL_NAME
        if [ -n "$NEW_TUNNEL_NAME" ]; then
            TUNNEL_NAME="$NEW_TUNNEL_NAME"
        else
            error "Tunnel name cannot be empty"
            exit 1
        fi
    else
        success "Using existing tunnel: ${TUNNEL_NAME}"
        TUNNEL_EXISTS=true
    fi
fi

if [ "$TUNNEL_EXISTS" != "true" ]; then
    info "Creating tunnel: ${TUNNEL_NAME}"
    if ! cloudflared tunnel create "$TUNNEL_NAME"; then
        error "Failed to create tunnel"
        exit 1
    fi
    success "Tunnel '${TUNNEL_NAME}' created"
fi

# Get tunnel ID
TUNNEL_ID=$(cloudflared tunnel list --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data:
    if t.get('name') == '${TUNNEL_NAME}':
        print(t.get('id', ''))
        break
" 2>/dev/null || echo "")

if [ -z "$TUNNEL_ID" ]; then
    # Fallback: try to get tunnel ID from list output
    TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}')
fi

if [ -n "$TUNNEL_ID" ]; then
    info "Tunnel ID: ${TUNNEL_ID}"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 4: Display Quick Tunnel URL
# ══════════════════════════════════════════════════════════════════════
step "4" "Tunnel Configuration"

echo ""
echo "Your tunnel has been created. You have two options for running it:"
echo ""
echo -e "${BOLD}Option A: Quick Tunnel (Temporary URL)${NC}"
echo "  Run this command to get an instant public URL:"
echo ""
echo -e "  ${CYAN}cloudflared tunnel --url http://localhost:8080${NC}"
echo ""
echo "  This will output a URL like: https://random-words.trycloudflare.com"
echo "  Note: URL changes each time you restart the tunnel"
echo ""

echo -e "${BOLD}Option B: Named Tunnel with Docker (Recommended for Production)${NC}"
echo "  The SME docker-compose.yml already includes a cloudflared service."
echo "  To use it with your named tunnel:"
echo ""
echo "  1. Copy your tunnel credentials file:"
echo "     cp ~/.cloudflared/${TUNNEL_ID}.json ./config/cloudflared-credentials.json"
echo ""
echo "  2. Update docker-compose.yml cloudflared service command:"
echo "     command: tunnel run --credentials-file /config/cloudflared-credentials.json ${TUNNEL_NAME}"
echo ""
echo "  3. Mount credentials in the service (add to volumes):"
echo "     - ./config/cloudflared-credentials.json:/config/cloudflared-credentials.json:ro"
echo ""

# ══════════════════════════════════════════════════════════════════════
# STEP 5: Custom Domain Configuration (Optional)
# ══════════════════════════════════════════════════════════════════════
step "5" "Custom Domain Configuration (Optional)"

echo ""
echo "If you have a domain managed by Cloudflare, you can route it to your tunnel."
echo ""
read -p "Configure a custom domain now? (y/N): " CONFIGURE_DOMAIN

if [ "$CONFIGURE_DOMAIN" = "y" ] || [ "$CONFIGURE_DOMAIN" = "Y" ]; then
    echo ""
    echo -e "Default domain: ${CYAN}${DOMAIN}${NC}"
    read -p "Use default domain ${DOMAIN}? (Y/n): " USE_DEFAULT_DOMAIN

    if [ "$USE_DEFAULT_DOMAIN" = "n" ] || [ "$USE_DEFAULT_DOMAIN" = "N" ]; then
        read -p "Enter your domain (e.g., sme.example.com): " CUSTOM_DOMAIN
    else
        CUSTOM_DOMAIN="$DOMAIN"
    fi

    if [ -n "$CUSTOM_DOMAIN" ]; then
        info "Creating DNS route: ${CUSTOM_DOMAIN} -> tunnel:${TUNNEL_NAME}"

        if cloudflared tunnel route dns "$TUNNEL_NAME" "$CUSTOM_DOMAIN"; then
            success "DNS route created successfully"
            echo ""
            echo -e "${GREEN}Your SME Research Assistant will be available at:${NC}"
            echo -e "  ${BOLD}https://${CUSTOM_DOMAIN}${NC}"
            echo ""
            echo "Note: DNS propagation may take a few minutes."
        else
            warn "Failed to create DNS route"
            echo ""
            echo "You can manually add a CNAME record in Cloudflare DNS:"
            echo "  Name:   ${CUSTOM_DOMAIN%%.*}"
            echo "  Target: ${TUNNEL_ID}.cfargotunnel.com"
            echo "  Proxy:  Enabled (orange cloud)"
        fi
    fi
else
    echo ""
    echo "To configure a custom domain later, run:"
    echo "  cloudflared tunnel route dns ${TUNNEL_NAME} your-subdomain.yourdomain.com"
    echo ""
    echo "Or manually add a CNAME record in Cloudflare DNS:"
    if [ -n "$TUNNEL_ID" ]; then
        echo "  Target: ${TUNNEL_ID}.cfargotunnel.com"
    else
        echo "  Target: <tunnel-id>.cfargotunnel.com"
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}==========================================="
echo "  Cloudflare Tunnel Setup Complete!"
echo -e "===========================================${NC}"
echo ""
echo -e "${BOLD}Quick Start:${NC}"
echo "  Start tunnel now:  cloudflared tunnel --url http://localhost:8080"
echo ""
echo -e "${BOLD}Tunnel Details:${NC}"
echo "  Name: ${TUNNEL_NAME}"
if [ -n "$TUNNEL_ID" ]; then
    echo "  ID:   ${TUNNEL_ID}"
fi
echo ""
echo -e "${BOLD}Useful Commands:${NC}"
echo "  List tunnels:      cloudflared tunnel list"
echo "  Delete tunnel:     cloudflared tunnel delete ${TUNNEL_NAME}"
echo "  Route to domain:   cloudflared tunnel route dns ${TUNNEL_NAME} subdomain.example.com"
echo ""
echo -e "${BOLD}Documentation:${NC}"
echo "  https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/"
echo ""
echo -e "${YELLOW}Security Note:${NC}"
echo "  When exposing to the internet, ensure your authentication is properly"
echo "  configured in .env and that you're using strong passwords."
echo ""
