# ==============================================================================
# Synchrono AI Chatbot Service - Production Containerfile
# ==============================================================================
FROM python:3.12-slim-bookworm AS base

# Install system dependencies (curl for healthcheck, build-essential/libpq if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    HOST=0.0.0.0

# Set working directory
WORKDIR /app

# Install uv for fast, reliable dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /bin/uv

# Copy dependency files first to leverage Docker layer caching
COPY pyproject.toml uv.lock* /app/

# Install dependencies into system environment
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy project source code
COPY main.py /app/
COPY api/ /app/api/
COPY chatbot/ /app/chatbot/
COPY static/ /app/static/
COPY scripts/ /app/scripts/
COPY evals/ /app/evals/
COPY tests/ /app/tests/

# Create data directory for SQLite offline fallbacks
RUN mkdir -p /app/data && chmod -R 777 /app/data

# Security: Create non-root user
RUN groupadd -r synchrono && useradd -r -g synchrono -d /app -s /sbin/nologin synchrono && \
    chown -R synchrono:synchrono /app

# Switch to non-root user
USER synchrono

# Expose HTTP port
EXPOSE 8000

# Healthcheck to verify service availability
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Launch production server via Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
