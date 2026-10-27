FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    HOST=0.0.0.0

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /bin/uv
COPY pyproject.toml uv.lock* /app/
RUN uv sync --no-cache

COPY main.py alembic.ini /app/
COPY migration/ /app/migration/
COPY src/ /app/src/
COPY static/ /app/static/
COPY scripts/ /app/scripts/

RUN mkdir -p /app/data && chmod -R 777 /app/data
RUN groupadd -r synchrono && useradd -r -g synchrono -d /app -s /sbin/nologin synchrono && \
    chown -R synchrono:synchrono /app

USER synchrono

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["/app/.venv/bin/uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
