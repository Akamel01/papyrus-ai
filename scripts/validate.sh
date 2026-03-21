#!/bin/bash
# SME Research Assistant — Installation Validator
# Checks that all components are properly configured and running.
#
# Usage: bash scripts/validate.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "==========================================="
echo "  SME Research Assistant — Validation"
echo "==========================================="
echo ""

ERRORS=0
WARNINGS=0

# Helper functions
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; ERRORS=$((ERRORS + 1)); }
warn() { echo "  [WARN] $1"; WARNINGS=$((WARNINGS + 1)); }
info() { echo "  [INFO] $1"; }

# ── File System Checks ──
echo "── File System ──"

[ -f .env ] && pass ".env exists" || fail ".env missing (run scripts/setup.sh)"
[ -f .env.example ] && pass ".env.example exists" || warn ".env.example missing"
[ -f .dockerignore ] && pass ".dockerignore exists" || warn ".dockerignore missing"
[ -f docker-compose.yml ] && pass "docker-compose.yml exists" || fail "docker-compose.yml missing"

# Check .env permissions (Unix only)
if [ -f .env ] && [[ "$OSTYPE" != "msys" ]] && [[ "$OSTYPE" != "win32" ]]; then
    PERMS=$(stat -c "%a" .env 2>/dev/null || stat -f "%Lp" .env 2>/dev/null || echo "unknown")
    if [ "$PERMS" = "600" ]; then
        pass ".env permissions are 600 (secure)"
    elif [ "$PERMS" != "unknown" ]; then
        warn ".env permissions are $PERMS (should be 600)"
    fi
fi

# Check .gitignore includes .env
if [ -f .gitignore ]; then
    grep -q "^\.env$" .gitignore && pass ".env in .gitignore" || warn ".env not in .gitignore"
fi

echo ""

# ── Secrets Validation ──
echo "── Secrets Check ──"

# Check for leaked secrets in config files
if grep -rq "jxig8xd8dUs3wujBKJyMn3" config/ 2>/dev/null; then
    fail "OpenAlex API key found in config files (should be in .env)"
else
    pass "No OpenAlex key in config files"
fi

if grep -rq "9cFSf1mS9z1hn2JqZa7298ujHJEN34Uk7HXz0CEu" config/ 2>/dev/null; then
    fail "Semantic Scholar API key found in config files (should be in .env)"
else
    pass "No Semantic Scholar key in config files"
fi

if grep -rq "@mail.ubc.ca\|@cu.edu.eg" config/ 2>/dev/null; then
    fail "Personal emails found in config files (should be in .env)"
else
    pass "No personal emails in config files"
fi

# Check for placeholder values in .env
if [ -f .env ]; then
    if grep -q "CHANGE_ME\|changeme\|your_.*_here" .env 2>/dev/null; then
        warn "Placeholder values found in .env - please update"
    else
        pass "No placeholder values in .env"
    fi
fi

echo ""

# ── Docker Compose Validation ──
echo "── Docker Compose ──"

# Check for :latest tags
if grep -q ":latest" docker-compose.yml; then
    warn "Unpinned :latest tags found in docker-compose.yml"
else
    pass "All images have pinned versions"
fi

# Check for source bind mount
if grep -q "^\s*-\s*\.:/app" docker-compose.yml; then
    warn "Development bind mount (.:/app) still present"
else
    pass "No development bind mount"
fi

# Check for exposed infrastructure ports
EXPOSED_INFRA=0
grep -A2 "container_name: sme_redis" docker-compose.yml | grep -q "ports:" && EXPOSED_INFRA=1
grep -A2 "container_name: sme_qdrant" docker-compose.yml | grep -q "ports:" && EXPOSED_INFRA=1
grep -A2 "container_name: sme_ollama" docker-compose.yml | grep -q "ports:" && EXPOSED_INFRA=1

if [ $EXPOSED_INFRA -eq 1 ]; then
    warn "Infrastructure ports may be exposed (Redis/Qdrant/Ollama)"
else
    pass "Infrastructure ports are internal-only"
fi

echo ""

# ── Docker Status (if available) ──
echo "── Docker Services ──"

if ! command -v docker &> /dev/null; then
    info "Docker CLI not found - skipping container checks"
elif ! docker info &> /dev/null 2>&1; then
    info "Docker daemon not running - skipping container checks"
else
    # Check if containers are running
    for container in sme_app sme_redis sme_qdrant sme_ollama sme_dashboard_api sme_dashboard_ui; do
        if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
            STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "no-healthcheck")
            if [ "$STATUS" = "healthy" ]; then
                pass "$container is running (healthy)"
            elif [ "$STATUS" = "no-healthcheck" ]; then
                pass "$container is running"
            else
                warn "$container is running but unhealthy ($STATUS)"
            fi
        else
            info "$container is not running"
        fi
    done

    echo ""

    # Service connectivity tests
    echo "── Service Connectivity ──"

    if docker ps --format '{{.Names}}' | grep -q "^sme_redis$"; then
        if docker exec sme_redis redis-cli ping 2>/dev/null | grep -q PONG; then
            pass "Redis responding to ping"
        else
            fail "Redis not responding"
        fi
    fi

    if docker ps --format '{{.Names}}' | grep -q "^sme_app$"; then
        if docker exec sme_app curl -sf http://localhost:8501/_stcore/health >/dev/null 2>&1; then
            pass "Streamlit health check passed"
        else
            warn "Streamlit health check failed (may still be starting)"
        fi
    fi

    if docker ps --format '{{.Names}}' | grep -q "^sme_ollama$"; then
        if docker exec sme_ollama ollama list >/dev/null 2>&1; then
            pass "Ollama is accessible"
        else
            warn "Ollama not responding (may need 'ollama signin')"
        fi
    fi
fi

echo ""

# ── Python Syntax Check ──
echo "── Python Syntax ──"

if command -v python &> /dev/null || command -v python3 &> /dev/null; then
    PYTHON_CMD=$(command -v python3 || command -v python)

    if [ -f src/utils/env_resolver.py ]; then
        if $PYTHON_CMD -m py_compile src/utils/env_resolver.py 2>/dev/null; then
            pass "env_resolver.py syntax valid"
        else
            fail "env_resolver.py has syntax errors"
        fi
    fi

    if [ -f src/utils/helpers.py ]; then
        if $PYTHON_CMD -m py_compile src/utils/helpers.py 2>/dev/null; then
            pass "helpers.py syntax valid"
        else
            fail "helpers.py has syntax errors"
        fi
    fi
else
    info "Python not found - skipping syntax checks"
fi

echo ""

# ── Summary ──
echo "==========================================="
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo "  All checks passed!"
    echo "==========================================="
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo "  Passed with $WARNINGS warning(s)"
    echo "==========================================="
    exit 0
else
    echo "  $ERRORS error(s), $WARNINGS warning(s)"
    echo "  Please fix errors before proceeding."
    echo "==========================================="
    exit 1
fi
