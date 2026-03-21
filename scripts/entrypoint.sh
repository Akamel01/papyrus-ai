#!/bin/bash
# SME Research Assistant - Docker Entrypoint
# 
# Handles auto-resume of interrupted pipeline runs on container startup.

set -e

DATA_DIR="/app/data"
STATE_FILE="$DATA_DIR/pipeline_state.json"
LOG_FILE="$DATA_DIR/autonomous_update.log"

echo "==================================================="
echo "SME Research Assistant - Starting..."
echo "==================================================="

# Auto-resume logic disabled by user request.
# Pipeline must be started manually using 'docker exec'.

echo ""
echo "🚀 Starting Streamlit UI..."
echo "==================================================="

# Start Pipeline API in the background
echo "Starting Pipeline Controller API on :8000..."
uvicorn scripts.pipeline_api:app --host 0.0.0.0 --port 8000 &

# Start Streamlit as the main process
echo "Starting Streamlit on :8501..."
exec streamlit run app/main.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.baseUrlPath=/chat \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
