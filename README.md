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
7. **7-Criteria Trajectory Evaluation Harness:** Comprehensive evaluation suite verifying intermediate tool calls, reasoning trajectories, factuality against ground-truth SQL, and multi-turn state retention across 14 benchmark scenarios (100% pass rate).
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
- **Docker & Docker Compose** (for containerized deployment)
- **Python 3.12+** and **uv** (if running locally on host)

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Key configuration parameters:
```env
# AI Model Configuration (Ollama Cloud / OpenAI Compatible)
OPENAI_MODEL_NAME=gemma4:31b-cloud
OPENAI_BASE_URL=https://ollama.com/v1
OPENAI_API_KEY=your_ollama_or_openai_api_key

# PostgreSQL Chatbot Storage (Container Port 5433)
POSTGRES_DB=synchrono_chatbot
POSTGRES_USER=synchrono
POSTGRES_PASSWORD=synchrono123
POSTGRES_PORT=5433
POSTGRES_HOST=localhost

# Analytics Database (Read-Only)
ANALYTICS_DB_URI=postgresql://synchrono_readonly:sync_ro_pass@localhost:5433/synchrono

# Observability (Optional)
USE_OPIK=true
OPIK_API_KEY=your_opik_api_key
OPIK_PROJECT_NAME=synchrono-chatbot
```

---

### 3. Launching the Service

#### Option A: 1-Click Docker Compose Full Stack (Recommended)
Launches both PostgreSQL database container and FastAPI service container with healthcheck verification:

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

*(To stop the entire stack, run `.\stop_all.ps1`, `./stop_all.sh`, or `docker compose down`)*

#### Option B: Hybrid Development (Docker DB + Local Python Server)
1. Start the PostgreSQL database container only:
   ```powershell
   .\start_db.ps1   # Windows
   ./start_db.sh    # Linux/macOS
   ```
2. Run the FastAPI development server with hot-reload:
   ```bash
   uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

#### Accessing the Service
Once started, the service is operational at:
* **Interactive Testing Web UI:** [http://localhost:8000/](http://localhost:8000/)
* **Swagger OpenAPI Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc Specification:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
* **Health Check API:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

## 🧪 Testing & Evaluation Harness

### 1. Unit & Integration Tests (Pytest)
Run the pytest test suite to verify database models, middleware sanitization, and endpoint routing:
```bash
uv run pytest tests/ -v
# Output: 7 passed
```

### 2. Trajectory-Level Evaluation Harness (LLM-as-a-Judge)
Evaluate the agent's intermediate tool calls, SQL accuracy, language compliance, PII safety, and contextual recommendations across all 14 test cases:
```bash
uv run python evals/run_eval.py
```

Evaluation output includes:
* Per-case pass/fail breakdown across 7 criteria.
* Hop count and intermediate tool inspection (`run_query`, `get_schemas`).
* Factuality verification against ground-truth SQL execution.
* Exported JSON summary at `evals/results.json`.

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
