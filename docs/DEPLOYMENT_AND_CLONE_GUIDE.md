# Synchrono AI Chatbot: Repository Clone, Setup, and Deployment Guide

> **Target Audience:** Developers, DevOps Engineers, System Administrators, and AI Agents  
> **Status:** Production-Ready & Verified  
> **Supported Environments:** Docker, Docker Compose, Linux, macOS, Windows (PowerShell/WSL)  

---

## 1. Readiness & Self-Containment Confirmation

**Is this repository completely safe and ready for a fresh clone and execution?**

**YES.** The repository is completely self-contained and reproducible. Any developer or automated agent cloning this codebase can boot and operate the full stack immediately because of the following structural guarantees:

1. **Automatic Database Migrations:** Conversation and session tables (`conversations`, `messages`, indices) are dynamically created on initial boot. No manual SQL migrations or seed scripts are required.
2. **Dual-Mode Analytical Resilience:** The analytical database engine automatically detects whether an external database is reachable. If unreachable (e.g. developing offline or without a VPN connection), it transparently activates an internal SQLite in-memory database configured with `StaticPool`, pre-seeded with reference tables and realistic mock records.
3. **Multi-Platform Startup Scripts:** Complete one-click scripts are provided for both Unix/Linux/macOS (`.sh`) and Windows (`.ps1`).
4. **Port Conflict Protection:** PostgreSQL runs on host port **5433** to prevent collisions with pre-existing local PostgreSQL instances on port 5432.
5. **Universal LLM Adapter:** Built with LangChain `init_chat_model()`, supporting Ollama Cloud, local Ollama, OpenRouter, Groq, or OpenAI endpoints via environment variables.

---

## 2. Docker Compose Topology

The containerized setup uses a multi-tier Docker architecture connected over an internal bridge network (`synchrono_network`):

```
+-----------------------------------------------------------------------------------------+
|                                    Docker Host                                          |
|                                                                                         |
|      Port 8000                                            Port 5433                     |
|          |                                                    |                         |
|          v                                                    v                         |
|  +--------------------------------+               +----------------------------------+  |
|  |     synchrono-chatbot-api      |               |      synchrono-chatbot-db        |  |
|  |  (FastAPI + Python 3.12-slim)  |               |      (PostgreSQL 16-alpine)      |  |
|  |                                |               |                                  |  |
|  |  - Non-root user: synchrono    |  Internal     |  - Volume: synchrono_chatbot_data|  |
|  |  - Healthcheck: /api/v1/health |  Network      |  - Healthcheck: pg_isready       |  |
|  |  - Uvicorn Server              | <-----------> |  - Port: 5432 (Internal)         |  |
|  +--------------------------------+               +----------------------------------+  |
|                                                                                         |
+-----------------------------------------------------------------------------------------+
```

---

## 3. Deployment Modes

### Mode A: 1-Click Complete Docker Deployment (Recommended)

This mode launches both the PostgreSQL database container and the FastAPI chatbot service in isolated Docker containers.

#### Option 1: Using Automated Scripts
* **Windows (PowerShell):**
  ```powershell
  .\start_all.ps1
  ```
* **Linux / macOS / Git Bash:**
  ```bash
  chmod +x *.sh
  ./start_all.sh
  ```

#### Option 2: Using Standard Docker Compose Command
1. Clone the repository and enter the directory:
   ```bash
   git clone <repository_url>
   cd synchrono-chatbot
   ```
2. Create your environment configuration:
   ```bash
   cp .env.example .env
   ```
   *(Edit `.env` and set your `OPENAI_API_KEY` or LLM credentials)*
3. Build and launch containers in detached mode:
   ```bash
   docker compose up -d --build
   ```
4. Verify running services:
   ```bash
   docker compose ps
   ```
   *Both `synchrono-chatbot-db` and `synchrono-chatbot-api` should report `healthy`.*

#### Stopping the Stack:
* **Windows (PowerShell):** `.\stop_all.ps1`
* **Linux / macOS:** `./stop_all.sh`
* **Or via Docker Compose:** `docker compose down`

---

### Mode B: Hybrid Development (Docker PostgreSQL + Local Python)

Best for active backend development with hot-reload (`--reload`):

1. **Start the database container only:**
   * Windows: `.\start_db.ps1`
   * Linux/macOS: `./start_db.sh`
   * Or: `docker compose up -d postgres-chatbot`
2. **Install dependencies on host:**
   Using `uv` (recommended):
   ```bash
   uv sync
   ```
   Or using standard `pip`:
   ```bash
   python -m venv .venv
   # Windows:
   .\.venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate

   pip install -r pyproject.toml
   ```
3. **Launch the FastAPI development server:**
   ```bash
   uv run uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000
   ```
   *(Note: `main:app` is supported for backward compatibility)*

---

### Mode C: Zero-Docker Pure Offline Mode

If Docker is unavailable on the machine, the system can operate completely offline using local SQLite storage:

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Run the server directly:
   ```bash
   uv run uvicorn src.api.server:app --reload --port 8000
   ```
   *The system detects that PostgreSQL is offline, automatically initializes local SQLite files in `data/`, seeds in-memory analytical datasets, and serves traffic without error.*

---

## 4. Environment Variables Reference (`.env`)

| Variable Name | Default Value | Description |
|:---|:---|:---|
| `PORT` | `8000` | HTTP port exposed by FastAPI |
| `HOST` | `0.0.0.0` | Network binding interface |
| `CORS_ORIGINS` | `["*"]` | Allowed CORS origins for web client embedding |
| `OPENAI_MODEL_NAME` | `gemma4:31b-cloud` | LLM model identifier |
| `OPENAI_BASE_URL` | `https://ollama.com/v1` | OpenAI-compatible endpoint URL |
| `OPENAI_API_KEY` | *(Required)* | Authentication token or API key |
| `POSTGRES_USER` | `synchrono` | Database user for conversation store |
| `POSTGRES_PASSWORD` | `synchrono123` | Database password |
| `POSTGRES_DB` | `synchrono_chatbot` | Conversation database name |
| `POSTGRES_PORT` | `5433` | Host-side port mapping for PostgreSQL |
| `POSTGRES_URI` | `postgresql://synchrono:synchrono123@localhost:5433/synchrono_chatbot` | Connection URI for host-based runs |
| `ANALYTICS_DB_URI` | *(Optional)* | Connection URI to production matching database |
| `USE_OPIK` | `false` | Enable Opik Cloud observability tracing |
| `OPIK_API_KEY` | *(Optional)* | Opik Cloud API key |
| `OPIK_PROJECT_NAME` | `synchrono-chatbot` | Project namespace in Opik Cloud |

---

## 5. Verification & Smoke Testing

### 1. Healthcheck Endpoint
Verify that the service is operational and both database engines are connected:
```bash
curl -s http://localhost:8000/api/v1/health | jq .
```
Expected output:
```json
{
  "status": "healthy",
  "service": "synchrono-chatbot",
  "version": "1.0.0",
  "postgres_db": "synchrono-chatbot-db:5432/synchrono_chatbot",
  "analytics_db": "in-memory (mock SQLite) or PostgreSQL/StarRocks",
  "model": "gemma4:31b-cloud"
}
```

### 2. Interactive Web UI
Open your browser and navigate to:
* **Interactive UI:** [http://localhost:8000/](http://localhost:8000/)
* **API Documentation (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc Contract:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

### 3. Unit Test Suite Execution
Execute the automated test suite across all routers and middleware:
```bash
uv run pytest -v
```
* Default `testpaths = ["src/tests"]` and `addopts = "-m 'not eval'"` run offline/unit tests with isolated SQLite conversation storage and in-memory mock analytics. Opik telemetry is disabled during tests.

### 4. Trajectory-Level Live Evaluation Harness
Run the 14-scenario trajectory evaluation harness against a live LLM:
```bash
uv run pytest -m eval -v
```
*(Optional: `--junitxml=pytest-evals.xml` to export standard test results)*
* Evaluates intermediate tool calling, SQL generation, factuality, PII safety, and contextual recommendations across all 14 scenarios.
* Executes real model calls and consumes API quota. Opik is disabled in tests.

---

## 6. Production Hardening Features

* **Multi-Stage Lean Image:** Built on `python:3.12-slim-bookworm` with layer-cached dependencies installed via Astral `uv`.
* **Least-Privilege Security:** The container runs under a non-root system user (`synchrono:synchrono`, UID/GID created during build).
* **Graceful Degradation:** Resilient connection pools (`pool_pre_ping=True`, `pool_recycle=1800`) automatically recover from network blips.
* **Deterministic Evaluation:** Ground-truth SQL queries verify answer accuracy in regression tests without model hallucinations.

---

## 7. Troubleshooting & FAQ

### Issue 1: Port 5433 or 8000 is already in use
* Check for conflicting processes:
  * Windows: `netstat -ano | findstr :5433`
  * Linux/macOS: `lsof -i :5433`
* Customize the host port in `.env`:
  ```env
  POSTGRES_PORT=5434
  PORT=8080
  ```
  Then restart with `docker compose up -d`.

### Issue 2: Resetting the PostgreSQL database
To completely wipe persistent chat volumes and start fresh:
```bash
docker compose down -v
docker compose up -d
```

### Issue 3: Docker container cannot reach host database
If you need the containerized chatbot to query a database running on your host machine (outside Docker), set the host URI in `.env`:
```env
ANALYTICS_DB_URI=postgresql://postgres:postgres@host.docker.internal:5432/synchrono
```
