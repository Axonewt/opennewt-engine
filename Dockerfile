# Python 3.12 slim image
FROM python:3.12-slim

LABEL maintainer="Axonewt <assassindavid2019@gmail.com>"
LABEL description="OpenNewt Engine - Regenerative Neural Infrastructure for Edge AI"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /app/data /app/logs

# Environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Ports
EXPOSE 8088

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8088/health')" || exit 1

# Start API server
CMD ["python", "api_server.py", "--host", "0.0.0.0", "--port", "8088"]
