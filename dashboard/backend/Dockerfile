FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI (static binary) for docker exec commands
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz | \
    tar xz --strip-components=1 -C /usr/local/bin docker/docker && \
    apt-get remove -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Security: create non-root user and switch to it
RUN groupadd -r dashboard && useradd -r -g dashboard -d /app dashboard && \
    chown -R dashboard:dashboard /app
USER dashboard

EXPOSE 8400

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8400", "--workers", "1"]
