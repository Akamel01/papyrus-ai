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
API_PID=$!

# Wait for Pipeline API to be ready
echo "Waiting for Pipeline API to initialize..."
for i in {1..30}; do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        echo "Pipeline API ready (took ${i}s)"
        break
    fi
    sleep 1
done

# Verify API process is still running
if ! kill -0 $API_PID 2>/dev/null; then
    echo "ERROR: Pipeline API failed to start"
    exit 1
fi

# Start Streamlit as the main process
echo "Starting Streamlit on :8501..."
exec streamlit run app/main.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.baseUrlPath=/chat \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
