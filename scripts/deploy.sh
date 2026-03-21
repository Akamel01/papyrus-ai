#!/bin/bash
# SME Research Assistant — Master Deployment Script
# Orchestrates the complete deployment process.
#
# This script:
# 1. Checks prerequisites (Docker, disk space, GPU)
# 2. Runs setup.sh if .env doesn't exist
# 3. Builds Docker images
# 4. Starts all services
# 5. Waits for health checks
# 6. Runs validation
# 7. Prints access URLs and next steps
#
# Usage: bash scripts/deploy.sh

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
BOLD='\033[1m'
NC='\033[0m' # No Color

# ── Helper Functions ──
info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; }
step()    { echo -e "\n${BOLD}── $1 ──${NC}"; }

# Cleanup function for graceful exit
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo ""
        error "Deployment failed with exit code $exit_code"
        echo ""
        echo "Troubleshooting tips:"
        echo "  1. Check Docker logs:  docker compose logs -f"
        echo "  2. Verify .env file:   cat .env"
        echo "  3. Run validation:     bash scripts/validate.sh"
        echo "  4. Check disk space:   df -h"
        echo ""
    fi
    exit $exit_code
}

trap cleanup EXIT

echo -e "${BOLD}==========================================="
echo "  SME Research Assistant — Deployment"
echo -e "===========================================${NC}"
echo ""

# ══════════════════════════════════════════════════════════════════════
# STEP 1: Prerequisites Check
# ══════════════════════════════════════════════════════════════════════
step "Checking Prerequisites"

# Check Docker
if ! command -v docker &> /dev/null; then
    error "Docker is not installed or not in PATH"
    echo "  Install Docker Desktop: https://docs.docker.com/get-docker/"
    exit 1
fi
success "Docker CLI found"

# Check Docker daemon
if ! docker info &> /dev/null 2>&1; then
    error "Docker daemon is not running"
    echo "  Start Docker Desktop or run: sudo systemctl start docker"
    exit 1
fi
success "Docker daemon is running"

# Check Docker Compose (V2)
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    success "Docker Compose V2 found"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
    warn "Using legacy docker-compose. Consider upgrading to Docker Compose V2"
else
    error "Docker Compose not found"
    echo "  Install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# Check disk space (require 50GB+)
REQUIRED_SPACE_GB=50
if command -v df &> /dev/null; then
    # Get available space in GB (works on Linux and macOS)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        AVAILABLE_GB=$(df -g . | awk 'NR==2 {print $4}')
    else
        AVAILABLE_GB=$(df -BG . 2>/dev/null | awk 'NR==2 {gsub(/G/,""); print $4}' || echo "unknown")
    fi

    if [ "$AVAILABLE_GB" != "unknown" ] && [ -n "$AVAILABLE_GB" ]; then
        if [ "$AVAILABLE_GB" -ge "$REQUIRED_SPACE_GB" ]; then
            success "Disk space: ${AVAILABLE_GB}GB available (${REQUIRED_SPACE_GB}GB required)"
        else
            warn "Low disk space: ${AVAILABLE_GB}GB available (${REQUIRED_SPACE_GB}GB recommended)"
            echo "  Consider freeing up space or using an external volume"
            read -p "Continue anyway? (y/N): " CONTINUE_LOW_SPACE
            if [ "$CONTINUE_LOW_SPACE" != "y" ] && [ "$CONTINUE_LOW_SPACE" != "Y" ]; then
                exit 1
            fi
        fi
    else
        info "Could not determine available disk space"
    fi
else
    info "df command not available - skipping disk space check"
fi

# Check GPU (optional)
GPU_AVAILABLE=false
if command -v nvidia-smi &> /dev/null; then
    if nvidia-smi &> /dev/null 2>&1; then
        GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
        if [ -n "$GPU_INFO" ]; then
            success "NVIDIA GPU detected: $GPU_INFO"
            GPU_AVAILABLE=true
        fi
    fi
fi

if [ "$GPU_AVAILABLE" = false ]; then
    warn "No NVIDIA GPU detected"
    echo "  GPU is optional but recommended for faster embedding/inference"
    echo "  The system will use CPU-based processing"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 2: Environment Setup
# ══════════════════════════════════════════════════════════════════════
step "Environment Configuration"

if [ ! -f ".env" ]; then
    warn ".env file not found"
    echo "  Running first-time setup..."
    echo ""

    if [ -f "${SCRIPT_DIR}/setup.sh" ]; then
        bash "${SCRIPT_DIR}/setup.sh"

        if [ ! -f ".env" ]; then
            error "setup.sh did not create .env file"
            exit 1
        fi
        success ".env file created by setup.sh"
    else
        error "setup.sh not found at ${SCRIPT_DIR}/setup.sh"
        exit 1
    fi
else
    success ".env file exists"

    # Check for required variables
    MISSING_VARS=()
    for VAR in JWT_SECRET; do
        if ! grep -q "^${VAR}=" .env 2>/dev/null; then
            MISSING_VARS+=("$VAR")
        fi
    done

    if [ ${#MISSING_VARS[@]} -gt 0 ]; then
        warn "Missing required variables in .env: ${MISSING_VARS[*]}"
        echo "  Consider re-running: bash scripts/setup.sh"
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 3: Build Docker Images
# ══════════════════════════════════════════════════════════════════════
step "Building Docker Images"

info "This may take several minutes on first run..."

if ! $COMPOSE_CMD build; then
    error "Docker build failed"
    echo "  Check the build output above for specific errors"
    echo "  Common issues:"
    echo "    - Network connectivity problems"
    echo "    - Missing Dockerfile"
    echo "    - Insufficient disk space"
    exit 1
fi
success "All Docker images built successfully"

# ══════════════════════════════════════════════════════════════════════
# STEP 4: Start Services
# ══════════════════════════════════════════════════════════════════════
step "Starting Services"

info "Starting all containers..."

if ! $COMPOSE_CMD up -d; then
    error "Failed to start containers"
    echo "  Check logs with: docker compose logs"
    exit 1
fi
success "Containers started"

# ══════════════════════════════════════════════════════════════════════
# STEP 5: Wait for Health Checks
# ══════════════════════════════════════════════════════════════════════
step "Waiting for Services to be Healthy"

TIMEOUT=120
INTERVAL=5
ELAPSED=0

# Core services to check
SERVICES=("sme_redis" "sme_qdrant" "sme_app" "sme_dashboard_api" "sme_dashboard_ui")

info "Waiting up to ${TIMEOUT}s for services to become healthy..."

while [ $ELAPSED -lt $TIMEOUT ]; do
    ALL_HEALTHY=true

    for SERVICE in "${SERVICES[@]}"; do
        # Check if container exists
        if ! docker ps -a --format '{{.Names}}' | grep -q "^${SERVICE}$"; then
            ALL_HEALTHY=false
            continue
        fi

        # Check if container is running
        if ! docker ps --format '{{.Names}}' | grep -q "^${SERVICE}$"; then
            ALL_HEALTHY=false
            continue
        fi

        # Check health status if available
        HEALTH=$(docker inspect --format='{{.State.Health.Status}}' "$SERVICE" 2>/dev/null || echo "none")
        if [ "$HEALTH" = "unhealthy" ]; then
            ALL_HEALTHY=false
        elif [ "$HEALTH" = "starting" ]; then
            ALL_HEALTHY=false
        fi
    done

    if [ "$ALL_HEALTHY" = true ]; then
        break
    fi

    # Show progress
    printf "\r  Elapsed: %3ds / %ds" $ELAPSED $TIMEOUT
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

echo "" # New line after progress

if [ $ELAPSED -ge $TIMEOUT ]; then
    warn "Health check timeout reached"
    echo "  Some services may still be starting up"
    echo "  Check status with: docker compose ps"
else
    success "All services are running (${ELAPSED}s)"
fi

# Show final container status
echo ""
info "Container status:"
$COMPOSE_CMD ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || $COMPOSE_CMD ps

# ══════════════════════════════════════════════════════════════════════
# STEP 6: Run Validation
# ══════════════════════════════════════════════════════════════════════
step "Running Validation"

if [ -f "${SCRIPT_DIR}/validate.sh" ]; then
    echo ""
    # Run validation but don't fail deployment if it has warnings
    if bash "${SCRIPT_DIR}/validate.sh"; then
        success "Validation passed"
    else
        warn "Validation completed with issues (see above)"
    fi
else
    warn "validate.sh not found - skipping validation"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 7: Success Summary
# ══════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}==========================================="
echo "  Deployment Complete!"
echo -e "===========================================${NC}"
echo ""
echo -e "${BOLD}Access Points:${NC}"
echo -e "  ${GREEN}Dashboard:${NC}     http://localhost:3030"
echo -e "  ${GREEN}Streamlit:${NC}     http://localhost:8502"
echo -e "  ${GREEN}API Gateway:${NC}   http://localhost:8080"
echo ""
echo -e "${BOLD}Useful Commands:${NC}"
echo "  View logs:        docker compose logs -f"
echo "  Stop services:    docker compose down"
echo "  Restart:          docker compose restart"
echo "  Check status:     docker compose ps"
echo ""
echo -e "${BOLD}Next Steps:${NC}"
echo "  1. Open http://localhost:3030 to access the dashboard"
echo "  2. Log in with the admin credentials from setup"

if [ "$GPU_AVAILABLE" = true ]; then
    echo "  3. Link Ollama account:  docker exec -it sme_ollama ollama signin"
fi

echo ""
echo -e "${BOLD}Optional: Enable Public Access${NC}"
echo "  Run: bash scripts/setup-cloudflare.sh"
echo ""
