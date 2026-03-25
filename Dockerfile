# syntax=docker/dockerfile:1
# SME Research Assistant - Application Dockerfile
#
# This Dockerfile extends from a pre-baked base image that includes
# CUDA, Python 3.11, and PyTorch. This avoids re-downloading PyTorch
# (~2.5GB) on every build, reducing build time from ~15-20 min to ~2-3 min.
#
# For local development without the base image, set:
#   --build-arg BASE_IMAGE=nvidia/cuda:12.1.1-runtime-ubuntu22.04
# Then uncomment the fallback sections below.

# Base image with CUDA + Python + PyTorch pre-installed
# Override with --build-arg BASE_IMAGE=... for custom base
ARG BASE_IMAGE=nvidia/cuda:12.1.1-runtime-ubuntu22.04
FROM ${BASE_IMAGE}

# Set environment variables (in case base image doesn't have them)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# ─── Fallback: Install deps if using raw CUDA image ───
# These layers are skipped if base image already has them (layer caching)
SHELL ["/bin/bash", "-c"]
RUN if ! command -v python3.11 &> /dev/null; then \
        apt-get update && apt-get install -y software-properties-common curl gpg-agent && \
        add-apt-repository -y ppa:deadsnakes/ppa && \
        apt-get update && apt-get install -y \
        python3.11 python3.11-venv python3.11-dev python3.11-distutils \
        gcc g++ poppler-utils tesseract-ocr libgl1 && \
        rm -rf /var/lib/apt/lists/* && \
        curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 && \
        ln -s /usr/bin/python3.11 /usr/local/bin/python && \
        ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
        python -m pip install --upgrade pip; \
    fi

# ─── Fallback: Install PyTorch if not in base image ───
RUN if ! python -c "import torch" 2>/dev/null; then \
        pip install torch --index-url https://download.pytorch.org/whl/cu121; \
    fi

# Reset shell to default
SHELL ["/bin/sh", "-c"]

# Set working directory
WORKDIR /app

# Install remaining Python dependencies
# Use cu121 index for PyTorch to ensure CUDA 12.1 compatibility (works with driver 576.x)
# Default PyPI torch resolves to cu130 which requires CUDA 13.0 / newer drivers
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --ignore-installed blinker --ignore-installed zipp \
    --extra-index-url https://download.pytorch.org/whl/cu121 \
    -r requirements.txt

# Copy source code
COPY src ./src
COPY app ./app
COPY config ./config
COPY scripts ./scripts

# Create directories for data (volumes will mount here)
RUN mkdir -p data DataBase/Papers

# Copy and set up entrypoint script
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose Streamlit port
EXPOSE 8501

# Healthcheck - using /chat prefix for baseUrlPath configuration
HEALTHCHECK CMD curl --fail http://localhost:8501/chat/_stcore/health || exit 1

# Use entrypoint for auto-resume capability
ENTRYPOINT ["/entrypoint.sh"]
