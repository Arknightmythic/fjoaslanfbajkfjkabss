# Synchrono AI Chatbot Service

Enterprise Data Analyst & Reasoning Agent microservice for the Synchrono Identity-Matching platform. Built with modern **LangChain & LangGraph**, served via **FastAPI**, backed by **PostgreSQL** conversation memory, and instrumented with **Opik Cloud** observability.

> 🧭 **New Team Member / Service Handover:** If you are onboarding to this codebase or deploying this microservice to staging/production, follow the step-by-step [Master Team Handover & Service Deployment Guide](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/docs/TEAM_HANDOVER_AND_SERVICE_GUIDE.md).

---

## 🌟 Core Features

1. **Standalone Microservice:** Completely decoupled from heavy data ingestion pipelines, providing high-throughput REST and SSE endpoints for web clients.
2. **Real-Time SSE Streaming:** Low-latency Server-Sent Events stream emitting live text tokens, tool execution statuses, and auto-generated conversation titles.
3. **Contextual Ambiguity Disambiguation:** Resolves underspecified queries (e.g., *"Tampilkan data Budi"*) by executing targeted database searches, presenting factual summaries with masked PII, and generating 2 to 4 contextual follow-up questions tailored specifically to the queried entity.
4. **Dual Database Architecture & Isolation:**
   - **`synchrono_chatbot`:** Dedicated PostgreSQL database managing conversational turns, session titles, and message history.
   - **`synchrono`:** Strict read-only analytical database restricted to `SELECT` permissions under `synchrono_readonly`. Includes an offline in-memory SQLite fallback with `StaticPool` to ensure connection stability during development.
5. **Multi-Layered Safety Guardrails:**
   - **`PromptInjectionGuardrail`:** Semantic inspection intercepting prompt injection, role subversion, and prompt leaking attempts.
   - **`PIIMiddleware`:** Automatic detection and masking of 16-digit Indonesian National Identity Numbers (NIK).
   - **`ToolRetryMiddleware`:** Automated self-correction for malformed SQL queries up to 2 retries.
6. **Anti-Slop Web UI:** Interactive testing interface at `http://localhost:8000/` featuring animated thinking states, dynamic tool progress indicators, and seamless transition to streaming markdown without black hollow box artifacts.
7. **7-Criteria Trajectory Evaluation Harness:** Comprehensive evaluation suite verifying intermediate tool calls, reasoning trajectories, factuality against ground-truth SQL, and multi-turn state retention across 14 benchmark scenarios.
8. **1-Click Full Docker Stack:** Multi-container `docker-compose.yml` including both PostgreSQL 16 on port 5433 and containerized FastAPI with automatic database healthcheck dependencies.

---

## 🛠️ Toolbelt Engine

The agent operates with 3 focused, purpose-built tools:

| Tool Name | Module | Description |
|:---|:---|:---|
| **`run_query`** | `chatbot/tools/db_query_executor.py` | Executes read-only SQL queries against analytics tables (`uploaded_files`, `manual_matches`, `institution`). Rejects destructive statements. |
| **`get_schemas`** | `chatbot/tools/schema_context.py` | Retrieves database table definitions, foreign key relationships, and column types via active schema reflection. |
| **`load_skills`** | `chatbot/tools/skill.py` | Dynamically loads domain business rules (e.g. data quality grading definitions Grade A–F, mismatch reasoning heuristics). |

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Python 3.12+** and **uv** (for host service execution)
- **Docker & Docker Compose** (for database containerization)

### 2. Configure Environment Variables
Preserve existing `.env` if already configured, or copy `.env.example` to `.env`:
```bash
# Preserve existing .env; copy template only if missing
cp -n .env.example .env
```
Key configuration parameters:
```env
# AI Model Configuration (Ollama Cloud / OpenAI Compatible)
OPENAI_MODEL_NAME=gemma4:31b-cloud
OPENAI_BASE_URL=https://ollama.com/v1
OPENAI_API_KEY=your_ollama_or_openai_api_key

# PostgreSQL Conversation & Chat History Storage (Internal DB, Port 5433)
INTERNAL_HOST=127.0.0.1
INTERNAL_PORT=5433
INTERNAL_USER=synchrono
INTERNAL_PASSWORD=change_me_local
INTERNAL_DATABASE=synchrono_chatbot

# Analytics Database (StarRocks Engine, Port 9030)
DB_HOST=127.0.0.1
DB_PORT=9030
DB_NAME=synchrono
DB_USER=synchrono_readonly
DB_PASSWORD=change_me_local

# Observability (Optional)
USE_OPIK=false
OPIK_API_KEY=your_opik_cloud_api_key_here
OPIK_PROJECT_NAME=synchrono-chatbot
```

---

### 3. Launching the Service

#### Option A: Lightweight Hybrid Development (Recommended)
Runs PostgreSQL in Docker and boots the FastAPI service locally on host:

1. **Sync dependencies:**
   ```bash
   uv sync --locked
   ```

2. **Start internal PostgreSQL container:**
   ```bash
   docker compose up -d postgres-chatbot
   ```

3. **Run FastAPI development server with hot-reload:**
   * **Linux / macOS / Git Bash:**
     ```bash
     USE_OPIK=false uv run uvicorn src.api.server:app --reload --host 127.0.0.1 --port 8000
     ```
   * **Windows PowerShell:**
     ```powershell
     $env:USE_OPIK="false"; uv run uvicorn src.api.server:app --reload --host 127.0.0.1 --port 8000
     ```

*(Note: FastAPI and the Web UI can boot without StarRocks; analytics tools require a configured, reachable StarRocks instance).*

#### Option B: Full Stack Docker Compose (Optional)
> ⚠️ **Prerequisite**: Host system requires **>= 4 GiB free RAM** to run the complete stack (StarRocks combined Frontend/Backend engines).

Launches PostgreSQL, StarRocks, StarRocks initializer, and FastAPI service containers with healthcheck verification:

* **Linux / macOS / Git Bash:**
  ```bash
  chmod +x scripts/start_all.sh
  ./scripts/start_all.sh
  ```
* **Windows PowerShell:**
  ```powershell
  .\scripts\start_all.ps1
  ```
* **Or standard Docker Compose:**
  ```bash
  docker compose --profile analytics --profile app up -d --build
  ```

*(To stop the entire stack, run `docker compose --profile analytics --profile app down`)*

#### Accessing the Service
Once started, the service is operational at:
* **Interactive Testing Web UI:** [http://localhost:8000/](http://localhost:8000/)
* **Swagger OpenAPI Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc Specification:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
* **Health Check API:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

## 🧪 Testing & Evaluation Harness

All automated tests and evaluation suites are located in `src/tests/` and run via pytest.

### 1. Unit & Offline Tests (Default)
Run the default test suite to verify database models, middleware sanitization, endpoint routing, and offline evaluation checks:
```bash
uv run pytest -v
```
* Default `testpaths = ["src/tests"]` and `addopts = "-m 'not eval'"` automatically exclude live model evaluations.
* Tests run isolated against a temporary SQLite conversation store and seeded in-memory analytical datasets. Opik telemetry is disabled during test runs.
* Canned demo responses and mocks are test-only fixtures for offline verification; runtime requires an active LLM endpoint and never emits synthetic fallback answers when model calls fail.

### 2. Live Model Evaluation (Deterministic Scoring)
Evaluate the agent's intermediate tool calls, SQL accuracy, language compliance, PII safety, and contextual recommendations across all 14 benchmark scenarios against a live model:
```bash
uv run pytest -m eval -v
```
*(Optional: add `--junitxml=pytest-evals.xml` to generate standard JUnit XML test reports)*

Evaluation details:
* Uses live LLM inferences (consumes API quota; Opik disabled during tests).
* Verifies per-scenario behavior across 7 evaluation criteria (Task Success, Tool-Use Correctness, Cross-Table Lookup, Language Compliance, PII Safety, Factuality, Contextual Recommendations).
* Tests intermediate tool inspection (`run_query`, `get_schemas`), hop counts, and factuality against ground-truth SQL.

---

## 📚 Technical Documentation & Integration Guides

Detailed technical specifications are organized in dedicated documents:

* **[Master Team Handover & Service Deployment Guide](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/docs/TEAM_HANDOVER_AND_SERVICE_GUIDE.md):**  
  The primary handbook for new engineers and DevOps. Covers setup, step-by-step `.env` configuration, Docker commands, and production service deployment ("dilempar by service") behind reverse proxies (Nginx/ALB) and Kubernetes.

* **[Environment Configuration Guide](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/docs/ENV_CONFIGURATION_GUIDE.md):**  
  Step-by-step walkthrough for configuring AI model providers (Ollama Cloud, Local Ollama, OpenRouter, Groq, OpenAI), database URIs, Opik Cloud observability, and schema access control.

* **[Clone, Setup & Deployment Guide](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/docs/DEPLOYMENT_AND_CLONE_GUIDE.md):**  
  Complete clone-and-run verification guide covering full Docker Compose deployment, hybrid development, offline SQLite execution, environment configurations, and production troubleshooting.

* **[Deep Architecture, Guardrails & Evaluation System](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/docs/ARCHITECTURE_AND_EVALS.md):**  
  In-depth architectural breakdown covering LangGraph state graphs, memory checkpointer hydration, PII masking, StaticPool SQLite fallback, ambiguity disambiguation protocols, and the 7-criteria evaluation rubric.

* **[Production Frontend Integration Guide](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/docs/FRONTEND_INTEGRATION_GUIDE.md):**  
  Complete, copy-pasteable implementation guide designed for frontend engineers and AI agents. Includes SSE wire format specifications, UI state transitions (resolving empty black boxes), recommendation pill parsing, and ready-to-use component templates for **React / Next.js**, **Vue 3 / Nuxt**, and **Vanilla JS Web Components**.

* **[API Contract & Specifications](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/API_CONTRACT.md):**  
  Formal REST and SSE schema contracts, header definitions, and error handling codes.
