# syntax=docker/dockerfile:1
# Use NVIDIA CUDA base image to ensure GPU runtime libraries are present
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies AND Python 3.11
RUN apt-get update && apt-get install -y software-properties-common curl gpg-agent && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3.11-distutils \
    gcc \
    g++ \
    poppler-utils \
    tesseract-ocr \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Set python3.11 as default python and install pip
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 && \
    ln -s /usr/bin/python3.11 /usr/local/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    python -m pip install --upgrade pip

# Set working directory
WORKDIR /app

# Install Python dependencies
# Step 1: CUDA-enabled PyTorch (separate layer for caching — only rebuilds if index changes)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch --index-url https://download.pytorch.org/whl/cu121

# Step 2: Remaining dependencies (torch requirement already satisfied, pip skips it)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --ignore-installed blinker --ignore-installed zipp -r requirements.txt

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
