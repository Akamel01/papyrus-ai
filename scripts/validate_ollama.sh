#!/bin/bash
# SME Research Assistant — Ollama Validation
# Checks Ollama connectivity and authentication status.
#
# Usage: bash scripts/validate_ollama.sh

set -e

echo "==========================================="
echo "  Ollama Connectivity Check"
echo "==========================================="
echo ""

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker CLI not found"
    exit 1
fi

if ! docker info &> /dev/null 2>&1; then
    echo "[ERROR] Docker daemon not running"
    exit 1
fi

# Check if Ollama container is running
if ! docker ps --format '{{.Names}}' | grep -q "^sme_ollama$"; then
    echo "[ERROR] sme_ollama container is not running"
    echo ""
    echo "Start it with: docker compose up -d ollama"
    exit 1
fi

echo "[INFO] sme_ollama container is running"

# Check Ollama API connectivity
echo "[INFO] Testing Ollama API..."
if docker exec sme_ollama curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "[PASS] Ollama API is responding"
else
    echo "[FAIL] Ollama API not responding"
    echo ""
    echo "Check logs with: docker logs sme_ollama"
    exit 1
fi

# Check authentication status
echo "[INFO] Checking authentication..."
if docker exec sme_ollama ollama list >/dev/null 2>&1; then
    echo "[PASS] Ollama is authenticated"
    echo ""
    echo "Available models:"
    docker exec sme_ollama ollama list
else
    echo "[WARN] Ollama may not be authenticated"
    echo ""
    echo "To authenticate, run:"
    echo "  docker exec -it sme_ollama ollama signin"
    echo ""
    echo "This will open a browser to sign in to your Ollama account."
    exit 0
fi

echo ""
echo "==========================================="
echo "  Ollama is ready!"
echo "==========================================="
