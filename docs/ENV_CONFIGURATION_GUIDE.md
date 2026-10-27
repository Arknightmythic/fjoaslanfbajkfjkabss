# Synchrono AI Chatbot: Environment Configuration Guide (`.env`)

> **Target Audience:** Developers, DevOps Engineers, and System Integrators  
> **Purpose:** Detailed walkthrough for configuring LLM base URLs, API keys, database URIs, and local JSONL trace logging.

---

## 1. Quick Start

To configure your environment:
1. Make a copy of the example environment file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` in your editor.
3. Configure your **AI Model credentials** and local trace file settings as described in the sections below.

---

## 2. LLM Provider Configuration (Universal Adapter)

The Synchrono Chatbot uses LangChain's universal `init_chat_model()` factory. Because the core engine communicates using the standard **OpenAI-compatible `/v1` specification**, you can swap between cloud and local model providers simply by adjusting three variables:

```env
OPENAI_BASE_URL=<endpoint_url>
OPENAI_MODEL_NAME=<model_identifier>
OPENAI_API_KEY=<provider_api_key>
```

### Provider Reference & Examples

#### Option A: Ollama Cloud (Default & Recommended)
* **Website:** [https://ollama.com](https://ollama.com)
* **Characteristics:** Hosted enterprise-grade open models with high throughput and zero local hardware requirements.
* **Setup:**
  1. Create an account at [ollama.com](https://ollama.com).
  2. Navigate to your Account Settings to generate an API key.
  3. Configure `.env`:
     ```env
     OPENAI_BASE_URL=https://ollama.com/v1
     OPENAI_MODEL_NAME=gemma4:31b-cloud
     OPENAI_API_KEY=your_ollama_cloud_api_key
     ```

#### Option B: Local Ollama (Running on Your Own Machine)
* **Characteristics:** 100% offline, privacy-first, zero cloud inference cost.
* **Prerequisites:** Install [Ollama](https://ollama.com/download) and pull the model:
  ```bash
  ollama run gemma4:31b
  ```
* **Setup for Host Machine:**
  ```env
  OPENAI_BASE_URL=http://localhost:11434/v1
  OPENAI_MODEL_NAME=gemma4:31b
  OPENAI_API_KEY=ollama
  ```
* **Setup when Chatbot runs inside Docker Container:**
  *(On Windows or macOS, access the host's localhost via `host.docker.internal`)*
  ```env
  OPENAI_BASE_URL=http://host.docker.internal:11434/v1
  OPENAI_MODEL_NAME=gemma4:31b
  OPENAI_API_KEY=ollama
  ```

#### Option C: OpenRouter (Multi-Model Gateway)
* **Website:** [https://openrouter.ai](https://openrouter.ai)
* **Characteristics:** Access hundreds of models (Gemini, Claude, DeepSeek, Llama) with a single API key.
* **Setup:**
  ```env
  OPENAI_BASE_URL=https://openrouter.ai/api/v1
  OPENAI_MODEL_NAME=google/gemini-2.0-flash-001
  OPENAI_API_KEY=sk-or-v1-your_openrouter_api_key
  ```

#### Option D: Groq Cloud (Ultra-Fast Inference)
* **Website:** [https://console.groq.com](https://console.groq.com)
* **Characteristics:** LPUs deliver sub-second token generation times.
* **Setup:**
  ```env
  OPENAI_BASE_URL=https://api.groq.com/openai/v1
  OPENAI_MODEL_NAME=llama-3.3-70b-versatile
  OPENAI_API_KEY=gsk_your_groq_api_key
  ```

#### Option E: DeepSeek Cloud
* **Website:** [https://platform.deepseek.com](https://platform.deepseek.com)
* **Setup:**
  ```env
  OPENAI_BASE_URL=https://api.deepseek.com/v1
  OPENAI_MODEL_NAME=deepseek-chat
  OPENAI_API_KEY=sk-your_deepseek_api_key
  ```

#### Option F: Official OpenAI
* **Website:** [https://platform.openai.com](https://platform.openai.com)
* **Setup:**
  ```env
  OPENAI_BASE_URL=https://api.openai.com/v1
  OPENAI_MODEL_NAME=gpt-4o-mini
  OPENAI_API_KEY=sk-your_openai_api_key
  ```

---

## 3. PostgreSQL Conversation Storage Configuration

The chatbot uses PostgreSQL to persist user sessions, messages, and timestamps.

```env
POSTGRES_USER=synchrono
POSTGRES_PASSWORD=synchrono123
POSTGRES_DB=synchrono_chatbot
POSTGRES_PORT=5433
POSTGRES_HOST=localhost

# Connection string used by host processes (e.g. uvicorn on host machine):
POSTGRES_URI=postgresql://synchrono:synchrono123@localhost:5433/synchrono_chatbot
```

### Important Notes:
1. **Port 5433:** Host port 5433 is used intentionally so that the chatbot database does not conflict with existing PostgreSQL servers running on default port 5432 (such as in local WSL or Docker).
2. **Containerized Execution:** When running via `docker compose up`, the chatbot API automatically connects to the database via internal container name `postgres-chatbot:5432`.
3. **Automatic Fallback:** If PostgreSQL is offline, the chatbot automatically writes conversation sessions to `data/conversations_fallback.db` (local SQLite), ensuring the server never crashes.

---

## 4. Analytics Data Matching Database (`ANALYTICS_DB_URI`)

This connection string points to the database containing identity matching tables (`uploaded_files`, `manual_matches`, `institution`).

```env
# Option A: Remote or WSL PostgreSQL database
ANALYTICS_DB_URI=postgresql://synchrono_readonly:sync_ro_pass@172.20.181.221:5432/synchrono

# Option B: StarRocks Engine
ANALYTICS_DB_URI=mysql+pymysql://root:@localhost:9030/synchrono

# Option C: Leave blank for automatic offline in-memory SQLite mock
ANALYTICS_DB_URI=
```

### In-Memory Resilience Feature:
If `ANALYTICS_DB_URI` is left blank or the remote database cannot be reached, the engine automatically initializes an internal SQLite in-memory database using SQLAlchemy `StaticPool`. This in-memory database comes preloaded with reference tables and mock records (including Budi Santoso and Budi Setiawan), allowing complete local testing without any external database dependencies.

---

## 5. Local JSONL Trace Logging

Chat and document-ingest lifecycle events are recorded locally as JSON Lines under the mounted `./data` directory. With `CHATBOT_TRACE_INCLUDE_CONTENT=true` (Opik-style), traces also capture the user question, final answer, LLM prompt/completion per call, and tool inputs/outputs. Payloads are truncated to `CHATBOT_TRACE_PAYLOAD_MAX_CHARS` and 16-digit NIK values are masked as `[NIK]`; credentials are never traced. Set `CHATBOT_TRACE_INCLUDE_CONTENT=false` to keep metadata only.

When a chat request completes, `CHATBOT_TRACE_WRITE_JSON=true` also writes a nested, human-readable trace document to `CHATBOT_TRACE_JSON_DIR/<trace_id>.json`. It contains the trace `input`/`output`, metadata, a `spans` tree (chain → tool/LLM calls with inputs, outputs, durations, status), and non-span lifecycle events. This is the local equivalent of an Opik trace page.

```env
CHATBOT_FILE_TRACE_ENABLED=true
CHATBOT_TRACE_FILE=/app/data/logs/chatbot-traces.jsonl
CHATBOT_TRACE_MAX_BYTES=10485760
CHATBOT_TRACE_BACKUP_COUNT=5
CHATBOT_TRACE_INCLUDE_CONTENT=true
CHATBOT_TRACE_PAYLOAD_MAX_CHARS=4000
CHATBOT_TRACE_WRITE_JSON=true
CHATBOT_TRACE_JSON_DIR=/app/data/logs/traces
```

Set `CHATBOT_FILE_TRACE_ENABLED=false` to disable local trace logging. Files rotate at the configured size and retain the configured number of backups. Inspect recent events on the host with:

```powershell
Get-Content .\data\logs\chatbot-traces.jsonl -Tail 50
```

---

## 6. Knowledge Ingestion Isolation (FAQ vs General Documents)

FAQ and non-FAQ documents use independent version pointers, PGVector collections, and SeaweedFS prefixes. Updating one source type never prunes or deactivates chunks from the other.

```env
# FAQ ingestion (existing behavior)
KNOWLEDGE_INGEST_PREFIX=faq-inbox/
PGVECTOR_COLLECTION_NAME=synchrono_faq_docs

# General document ingestion
KNOWLEDGE_DOCUMENT_INGEST_PREFIX=document-inbox/
PGVECTOR_DOCUMENT_COLLECTION_NAME=synchrono_documents

# General document chat retrieval
DOCUMENT_RETRIEVAL_CANDIDATES=20
DOCUMENT_DIRECT_MIN_SCORE=0.0
```

Chat questions that explicitly ask for document content (for example `Jelaskan isi dokumen SOP terbaru`) are answered only from the active document snapshot. Retrieval uses the shared reranker (`RERANKER_MODEL`, falling back to `FAQ_RERANKER_MODEL`, default `BAAI/bge-reranker-base`). Non-live questions also try document retrieval before falling back to the analytics agent. Uploading a newer general document activates a new snapshot and prunes older document chunks, so only the latest active document snapshot is searchable.

Upload through `POST /api/v1/knowledge/documents` with a multipart `file` field and an optional `source_type` form field:

* `source_type=faq` (default) stores the file under `faq-inbox/` and versions it against the FAQ index state.
* `source_type=document` stores the file under `document-inbox/` and versions it against the document index state.

FAQ and document answers use separate semantic-cache indexes (`idx:query_cache` and `idx:query_cache_document`). Activating a new FAQ version clears only the FAQ cache; activating a new document version clears only the document cache. Document caching is enabled only while an active document version exists. Configure the document cache with `SEMANTIC_CACHE_DOCUMENT_INDEX` and `SEMANTIC_CACHE_DOCUMENT_KEY_PREFIX`; TTL and confidence thresholds are shared with the FAQ cache.

---

## 7. AI Database Schema Access Control (`ALLOWED_DB_SCHEMA`)

This variable restricts which tables and columns the AI reasoning agent is allowed to introspect via the `get_schemas` tool.

```env
ALLOWED_DB_SCHEMA=uploaded_files:*,manual_matches:*,institution:file_id,id_incoming,match_score,match_result,upload_date,ref_grades:*,ref_sync_statuses:*,ref_match_results:*,grade_bands:*
```

* **Wildcard (`*`):** Allows introspection of all columns in that table (e.g., `uploaded_files:*`).
* **Selective Columns:** Restricts the schema reflection to explicit columns only (e.g., `institution:file_id,id_incoming,match_score`).
* **Global Access:** Setting `ALLOWED_DB_SCHEMA=*` opens all tables in the database.

---

## 8. Verifying Your Configuration

Once your `.env` file is saved, verify that the configuration is working correctly:

### 1. Healthcheck Endpoint
Start the service and execute a GET request to the `/api/v1/health` endpoint:
```bash
curl -s http://localhost:8000/api/v1/health
```

Expected JSON response:
```json
{
  "status": "healthy",
  "service": "synchrono-chatbot",
  "version": "1.0.0",
  "postgres_db": "localhost:5433/synchrono_chatbot",
  "analytics_db": "in-memory (mock SQLite) or PostgreSQL/StarRocks",
  "model": "gemma4:31b-cloud"
}
```

### 2. Live Chat Test
Open [http://localhost:8000/](http://localhost:8000/) in your web browser and submit a test prompt:
> *"Tampilkan data Budi"*

Inspect `data/logs/chatbot-traces.jsonl` for request trace IDs, routes, model/tool lifecycle events, durations, completion/error events, and (when content capture is enabled) question/answer plus tool inputs/outputs. Raw credentials and unmasked NIKs are never written.
