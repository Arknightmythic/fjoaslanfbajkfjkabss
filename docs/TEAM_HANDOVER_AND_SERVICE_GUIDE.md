# Synchrono AI Chatbot: Master Team Handover & Service Deployment Guide

> **Target Audience:** Incoming Engineering Teams, DevOps, Backend Leads, and AI Coding Agents  
> **Service Name:** `synchrono-chatbot`  
> **Status:** Production-Ready & Formally Evaluated  
> **Protocol:** REST API + Server-Sent Events (SSE) Streaming  

---

## 1. Executive Summary & Microservice Boundary

The **Synchrono AI Chatbot** is a decoupled, standalone analytical microservice. It acts as an automated data analyst, mismatch reasoning engine, and investigation link router for the Synchrono Identity-Matching platform.

### System Boundary & Architecture Context

```
+----------------------------------------------------------------------------------------------------+
|                                    Production Infrastructure                                       |
|                                                                                                    |
|    +-----------------------------+                     +---------------------------------------+   |
|    |    Synchrono Web Client     |                     |    Core Backend & Matching Engine     |   |
|    |   (React / Next.js / Vue)   |                     |     (Batch ETL / Pipeline Worker)     |   |
|    +--------------+--------------+                     +-------------------+-------------------+   |
|                   |                                                        |                       |
|                   | SSE Stream / REST                                      | Direct DB Ingestion   |
|                   v                                                        v                       |
|    +-------------------------------------------------------------------------------------------+   |
|    |                        Ingress / Reverse Proxy (Nginx / Traefik / ALB)                    |   |
|    |                        Domain: https://api-chatbot.synchrono.internal                     |   |
|    +----------------------------------------------+--------------------------------------------+   |
|                                                   |                                                |
|                                                   v                                                |
|    +-------------------------------------------------------------------------------------------+   |
|    |                        synchrono-chatbot Microservice (FastAPI :8000)                     |   |
|    |  - LangGraph Reasoning Agent Graph                                                        |   |
|    |  - PII Masking & Injection Guardrails                                                     |   |
|    |  - Strict Read-Only Query Executor                                                        |   |
|    +--------------------+---------------------------------+------------------------------------+   |
|                         |                                 |                                        |
|                         v                                 v                                        v
|    +-------------------------------+   +-------------------------------+   +-------------------+   |
|    |      synchrono-chatbot-db     |   |    Analytics DB (Read-Only)   |   |    Opik Cloud     |   |
|    |      (PostgreSQL :5433)       |   |  (PostgreSQL/StarRocks :5432) |   |   Observability   |   |
|    |  - conversations & messages   |   |  - uploaded_files, matches    |   |  - Trace & Tokens |   |
|    +-------------------------------+   +-------------------------------+   +-------------------+   |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Phase 1: Repository Setup & Environment Configuration (`.env`)

### Step 1.1: Clone the Repository
```bash
git clone <repository_url>
cd synchrono-chatbot
```

### Step 1.2: Generate Your `.env` File
Copy the provided `.env.example` template:
```bash
cp .env.example .env
```

### Step 1.3: Step-by-Step `.env` Configuration Breakdown

Open `.env` in your editor and configure the sections below:

#### Section A: Server & Network Binding
```env
PORT=8000
HOST=0.0.0.0
# Allowed origins for web browsers (JSON array string). In production, specify your web domain.
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173","https://app.synchrono.internal"]
```

#### Section B: AI Model Configuration (Universal OpenAI-Compatible Adapter)
The service utilizes LangChain's universal factory. You can switch between cloud and local providers without changing code:

* **Option 1: Ollama Cloud (Default & Recommended)**
  1. Register at [ollama.com](https://ollama.com).
  2. Navigate to **Account Settings** -> **API Keys** -> generate a key.
  3. Fill `.env`:
     ```env
     OPENAI_BASE_URL=https://ollama.com/v1
     OPENAI_MODEL_NAME=gemma4:31b-cloud
     OPENAI_API_KEY=your_ollama_cloud_api_key_here
     ```

* **Option 2: Local Ollama (Running on developer laptop)**
  ```env
  # For host execution:
  OPENAI_BASE_URL=http://localhost:11434/v1
  # For Docker on Windows/Mac:
  # OPENAI_BASE_URL=http://host.docker.internal:11434/v1
  OPENAI_MODEL_NAME=gemma4:31b
  OPENAI_API_KEY=ollama
  ```

* **Option 3: OpenRouter (Multi-Provider: Claude, Gemini, DeepSeek)**
  ```env
  OPENAI_BASE_URL=https://openrouter.ai/api/v1
  OPENAI_MODEL_NAME=google/gemini-2.0-flash-001
  OPENAI_API_KEY=sk-or-v1-your_openrouter_api_key
  ```

* **Option 4: Groq Cloud (Ultra-Fast LPUs)**
  ```env
  OPENAI_BASE_URL=https://api.groq.com/openai/v1
  OPENAI_MODEL_NAME=llama-3.3-70b-versatile
  OPENAI_API_KEY=gsk_your_groq_api_key
  ```

* **Option 5: Official OpenAI**
  ```env
  OPENAI_BASE_URL=https://api.openai.com/v1
  OPENAI_MODEL_NAME=gpt-4o-mini
  OPENAI_API_KEY=sk-your_openai_api_key
  ```

#### Section C: PostgreSQL Chatbot Conversation Database
Manages conversation sessions, user IDs, and message logs:
```env
POSTGRES_USER=synchrono
POSTGRES_PASSWORD=synchrono123
POSTGRES_DB=synchrono_chatbot
POSTGRES_PORT=5433
POSTGRES_HOST=localhost

# Connection string for host execution:
POSTGRES_URI=postgresql://synchrono:synchrono123@localhost:5433/synchrono_chatbot
```
*(Host port 5433 prevents collisions with default PostgreSQL on port 5432. If PostgreSQL is offline, the service automatically falls back to local SQLite at `data/conversations_fallback.db`)*

> 💡 **Schema DDL Script:** A production DDL script with table definitions, foreign keys, cascade deletes, and composite indices is available at [`scripts/init_chatbot_db.sql`](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/scripts/init_chatbot_db.sql). In Docker Compose, it is automatically mounted to `/docker-entrypoint-initdb.d/` to pre-seed fresh containers on first launch.

#### Section D: Analytics Data Matching Database (`ANALYTICS_DB_URI`)
Points to the analytical database containing `uploaded_files`, `manual_matches`, and `institution` tables:
```env
# For Production / Staging (PostgreSQL or StarRocks):
ANALYTICS_DB_URI=postgresql://synchrono_readonly:readonly123@172.20.181.221:5432/synchrono

# For Local Development (Leave blank to enable automatic in-memory SQLite mock):
ANALYTICS_DB_URI=
```

#### Section E: Opik Cloud Tracing & Observability
Tracks latency, tool traces, token costs, and agent trajectories:
```env
USE_OPIK=true
OPIK_API_KEY=your_opik_api_key_here
OPIK_PROJECT_NAME=synchrono-chatbot
OPIK_WORKSPACE=your_opik_workspace_name
```
> **How to get Opik Key:**
> 1. Sign up at [https://www.comet.com/opik](https://www.comet.com/opik).
> 2. Open **Settings** -> **API Keys** -> click **Create API Key**.
> 3. Set `USE_OPIK=false` if you wish to run completely offline without sending telemetry.

---

## 3. Phase 2: Running the Service (3 Execution Modes)

### Mode 1: 1-Click Complete Docker Stack (Recommended for Testing & Staging)
Launches PostgreSQL and the containerized FastAPI chatbot with mutual health checks:

* **Windows PowerShell:**
  ```powershell
  .\start_all.ps1
  ```
* **Linux / macOS / Git Bash:**
  ```bash
  chmod +x *.sh
  ./start_all.sh
  ```
* **Or standard Docker Compose:**
  ```bash
  docker compose up -d --build
  ```

### Mode 2: Hybrid Local Development (Docker DB + Local Python Server)
Best for backend engineers developing features with hot-reloading:
```bash
# 1. Start database container
docker compose up -d postgres-chatbot

# 2. Run server with hot-reload
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Mode 3: Zero-Docker Pure Offline Mode
If Docker is unavailable, run directly on bare metal:
```bash
uv run uvicorn main:app --port 8000
```
*The engine auto-detects that PostgreSQL is offline and switches to SQLite fallback without throwing errors.*

---

## 4. Phase 3: Verification & Health Checks

Before exposing or deploying to production, execute these 3 verification steps:

### 1. Healthcheck Endpoint
```bash
curl -s http://localhost:8000/api/v1/health | jq .
```
Expected output:
```json
{
  "status": "healthy",
  "service": "synchrono-chatbot",
  "version": "1.0.0",
  "postgres_db": "localhost:5433/synchrono_chatbot",
  "analytics_db": "connected or in-memory mock",
  "model": "gemma4:31b-cloud"
}
```

### 2. Run Pytest Suite
```bash
uv run pytest tests/ -v
# Output: 7 passed
```

### 3. Run Trajectory Evaluation Harness (14 Scenarios)
```bash
uv run python evals/run_eval.py
# Output: 14 / 14 Passed (100% pass rate)
```

---

## 5. Phase 4: Production Service Deployment ("Dilempar by Service")

When the service is verified and ready to be handed over to production infrastructure, follow this deployment architecture.

### 5.1. Network & Reverse Proxy Architecture (Nginx)

Place the chatbot service behind your organization's reverse proxy (Nginx, Traefik, or AWS ALB). 

**CRITICAL SSE CONFIGURATION FOR NGINX:**
Server-Sent Events require turning off response buffering (`proxy_buffering off`) and disabling caching so tokens stream instantly to the client.

Example Nginx server block (`/etc/nginx/conf.d/synchrono-chatbot.conf`):

```nginx
upstream chatbot_backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name api-chatbot.synchrono.internal;

    ssl_certificate     /etc/ssl/certs/synchrono.crt;
    ssl_certificate_key /etc/ssl/private/synchrono.key;

    # Timeouts for long LLM reasoning queries
    proxy_read_timeout 180s;
    proxy_connect_timeout 10s;
    proxy_send_timeout 180s;

    location /api/v1/chat {
        proxy_pass http://chatbot_backend;
        proxy_http_version 1.1;

        # Mandatory SSE Headers
        proxy_set_header Connection '';
        proxy_set_header Cache-Control 'no-cache';
        proxy_set_header X-Accel-Buffering 'no';
        proxy_buffering off;
        chunked_transfer_encoding on;

        # Standard Proxy Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://chatbot_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

### 5.2. Systemd Service Deployment (Bare-Metal Production)

If running directly on a Linux virtual machine without Docker, configure a systemd daemon service:

Create `/etc/systemd/system/synchrono-chatbot.service`:

```ini
[Unit]
Description=Synchrono AI Chatbot Service
After=network.target postgresql.service

[Service]
Type=simple
User=synchrono
Group=synchrono
WorkingDirectory=/opt/synchrono-chatbot
EnvironmentFile=/opt/synchrono-chatbot/.env
ExecStart=/opt/synchrono-chatbot/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable synchrono-chatbot
sudo systemctl start synchrono-chatbot
sudo systemctl status synchrono-chatbot
```

---

### 5.3. Docker Production Deployment

For containerized cloud environments (AWS ECS, Kubernetes, or Docker Swarm):

1. **Build Container Image:**
   ```bash
   docker build -t synchrono-chatbot:1.0.0 .
   ```
2. **Kubernetes Pod Specification Example:**
   ```yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: synchrono-chatbot
     labels:
       app: synchrono-chatbot
   spec:
     replicas: 2
     selector:
       matchLabels:
         app: synchrono-chatbot
     template:
       metadata:
         labels:
           app: synchrono-chatbot
       spec:
         containers:
         - name: chatbot-api
           image: synchrono-chatbot:1.0.0
           ports:
           - containerPort: 8000
           envFrom:
           - configMapRef:
               name: chatbot-config
           - secretRef:
               name: chatbot-secrets
           livenessProbe:
             httpGet:
               path: /api/v1/health
               port: 8000
             initialDelaySeconds: 15
             periodSeconds: 10
           readinessProbe:
             httpGet:
               path: /api/v1/health
               port: 8000
             initialDelaySeconds: 5
             periodSeconds: 5
           resources:
             requests:
               memory: "512Mi"
               cpu: "500m"
             limits:
               memory: "2Gi"
               cpu: "2000m"
   ```

---

## 6. Phase 5: How Other Services Consume the Chatbot

### 6.1. Web Frontend Team Consumption
The frontend website connects to `POST /api/v1/chat` to stream responses. Ready-to-copy code is available in:
* **[Production Frontend Integration Guide](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/docs/FRONTEND_INTEGRATION_GUIDE.md)**
* Includes components and hooks for **React / Next.js**, **Vue 3 / Nuxt 3**, and **Vanilla JS**.

#### SSE Wire Format Summary:
* `{"step": "START"}`: Connection opened. Display thinking state.
* `{"step": "TITLE", "content": "..."}`: Conversation title generated.
* `{"step": "TOOL_CALL", "content": "..."}`: SQL analysis executing.
* `{"step": "AIMessageChunk", "content": "..."}`: Streaming markdown text token.
* `{"step": "END", "content": "..."}`: Stream complete. Render follow-up recommendation pills.
* `{"step": "ERROR", "content": "..."}`: Execution exception occurred.

### 6.2. Backend Core / ETL Service Consumption
Backend services can fetch investigation queue data directly:
* **Endpoint:** `GET /api/v1/investigate/{file_id}`
* **Returns:** Aggregated manual review records, mismatch reasons, and match scores for that batch file.

---

## 7. Master Handover Checklist

Ensure this checklist is completed before handing over the service:

- [ ] **Repository Cloned:** Codebase downloaded and verified.
- [ ] **`.env` Configured:** Valid AI API key, Base URL, and Database connection set.
- [ ] **Health Check Verified:** `GET /api/v1/health` returns `status: healthy`.
- [ ] **Pytest Passed:** Unit tests pass 7/7 (`uv run pytest tests/`).
- [ ] **Evaluation Passed:** Trajectory runner passes 14/14 (`uv run python evals/run_eval.py`).
- [ ] **Database Connection:** PostgreSQL port 5433 verified, or remote read-only analytics DB verified.
- [ ] **Proxy Buffering Disabled:** Nginx/ALB configured with `proxy_buffering off` for real-time SSE streaming.
- [ ] **CORS Origins Updated:** `CORS_ORIGINS` includes the production frontend origin domain.
- [ ] **Opik Observability Active:** Dashboard shows real-time traces and token usage.
