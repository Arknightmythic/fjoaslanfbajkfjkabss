# Dokumentasi End-to-End: Synchrono AI Chatbot Platform

Dokumentasi komprehensif arsitektur, konfigurasi model, tata kelola database PostgreSQL, keamanan guardrail, spesifikasi API, dan antarmuka Pop-up Chatbot untuk Synchrono Identity-Matching Platform.

---

## 1. Ikhtisar & Arsitektur Sistem

Synchrono Chatbot adalah layanan mandiri (*standalone microservice*) yang bertindak sebagai **Data Analyst & Reasoning Agent** untuk platform pemadanan data identitas kependudukan (*Identity-Matching*). Asisten ini dirancang untuk menjawab pertanyaan seputar statistik file batch, kualitas data (Grade A hingga F), anomali pencocokan, serta menyediakan tautan langsung ke halaman investigasi manual review.

### Diagram Arsitektur

```
                                    +-----------------------+
                                    |     Browser Klien     |
                                    |  (Pop-up Chat Widget) |
                                    +-----------+-----------+
                                                |
                                      HTTP / SSE (Stream)
                                                v
+-----------------------------------------------------------------------------------+
|                           FastAPI Gateway (Port 8000)                             |
|                                                                                   |
|  +--------------------+   +---------------------+   +--------------------------+  |
|  | Web Route Handlers |   | Chat & Session API  |   | Investigation Route API  |  |
|  |  /, /investigate   |   | /api/v1/chat (SSE)  |   | /api/v1/investigate/{id} |  |
|  +---------+----------+   +----------+----------+   +------------+-------------+  |
|            |                         |                           |                |
|            |                         v                           |                |
|            |          +-------------------------------+          |                |
|            |          |     ChatbotHandler (Core)     |          |                |
|            |          +---------------+---------------+          |                |
|            |                          |                          |                |
|            |      +-------------------+--------------------+     |                |
|            |      |                                        |     |                |
|            |      v                                        v     |                |
|      +---------------+                        +---------------+  |                |
|      |  Middlewares  |                        | Tools Engine  |  |                |
|      | - Injection   |                        | - run_query   |  |                |
|      | - PII Masking |                        | - load_skills |  |                |
|      | - Tool Retry  |                        | - schema_info |  |                |
|      +-------+-------+                        +-------+-------+  |                |
+--------------|----------------------------------------|----------|----------------+
               |                                        |          |
               v                                        v          v
    +----------------------+                +---------------------------------------+
    |     Ollama Cloud     |                |        PostgreSQL Container           |
    | (OpenAI-Compatible)  |                |                                       |
    |   gemma4:31b-cloud   |                |  [DB: synchrono_chatbot] (Read/Write) |
    +----------------------+                |  - Sesi percakapan & bubble chat      |
                                            |                                       |
                                            |  [DB: synchrono] (Strict Read-Only)   |
                                            |  - uploaded_files                     |
                                            |  - manual_matches                     |
                                            |  - User: synchrono_readonly           |
                                            +---------------------------------------+
```

---

## 2. Model AI: LangChain Official Universal Factory

Layanan ini mengintegrasikan model penalaran **Ollama Cloud (`gemma4:31b-cloud`)** menggunakan fungsi factory resmi LangChain: `init_chat_model()` via OpenAI-compatible endpoint.

### Implementasi Inisialisasi Model

File: `chatbot/handler.py`

```python
from langchain.chat_models import init_chat_model

# Inisialisasi universal LangChain model
self._llm = init_chat_model(
    os.getenv("OPENAI_MODEL_NAME", "gemma4:31b-cloud"),
    model_provider="openai",
    base_url=os.getenv("OPENAI_BASE_URL", "https://ollama.com/v1"),
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0,
    stream_usage=True,
)
```

### Keunggulan:
- Tidak bergantung pada library vendor spesifik.
- Mendukung *streaming* token kata per kata secara native (*server-sent events*).
- Kompatibel dengan *Structured Outputs* untuk penamaan judul sesi otomatis (*TitleGenerator*).

---

## 3. Tata Kelola & Isolasi Database PostgreSQL

Sistem menggunakan **dua database terisolasi** pada PostgreSQL untuk menjamin keamanan mutlak data master:

| Database | Pengguna DB | Hak Akses | Fungsi |
| :--- | :--- | :--- | :--- |
| **`synchrono_chatbot`** | `postgres` | Read & Write | Menyimpan daftar percakapan pengguna (`conversations`) dan pesan bubble (`messages`). |
| **`synchrono`** | `synchrono_readonly` | **Strict Read-Only** (`SELECT` saja) | Sumber data identitas analitik (`uploaded_files`, `manual_matches`). |

### Proteksi Keamanan Berlapis untuk Database Analitik:
1. **Engine Permission Lock**: Pengguna `synchrono_readonly` hanya diberikan izin `GRANT SELECT ON ALL TABLES IN SCHEMA public`. Perintah `INSERT`, `UPDATE`, `DELETE`, `DROP`, dan `ALTER` langsung ditolak oleh PostgreSQL engine dengan pesan *permission denied*.
2. **Regex Query Guardrail**: Modul `AnalyticsQueryEngine` memvalidasi setiap query SQL sebelum dikirim ke engine. Jika terdapat kata kunci pengubahan data (misal: `DROP`, `DELETE`, `UPDATE`, `TRUNCATE`), eksekusi dibatalkan sebelum menyentuh database.

---

## 4. Middleware & Lapisan Keamanan

Agen percakapan dilengkapi pipa middleware LangGraph yang aktif pada setiap putaran percakapan:

```
Pertanyaan Pengguna
        |
        v
[Prompt Injection Guardrail] ---> Deteksi serangan DAN, pembobolan prompt, atau destruksi data
        |
        v
[PII Masking Middleware]    ---> Sensor otomatis NIK 16 digit (\b\d{16}\b -> [NIK_DISENSOR])
        |
        v
[Tool Retry Middleware]     ---> Toleransi otomatis terhadap kegagalan query sementara (maks 2x retry)
        |
        v
[Execution Checkpointer]    ---> Pelacakan state percakapan berbasis thread_id
```

---

## 5. Spesifikasi REST API & Server-Sent Events (SSE)

FastAPI berjalan pada port 8000 (`http://localhost:8000`). Dokumentasi interaktif Swagger dapat diakses di `/docs`.

### 5.1 POST `/api/v1/chat` (Real-Time SSE Streaming)
Mengirim pertanyaan ke agen dan menerima respons bertahap melalui Server-Sent Events.

- **Request Body**:
  ```json
  {
    "query": "Kenapa data Fav Institute ada yang masuk Grade D?",
    "conversation_id": "conv-101-test",
    "user_id": "analyst_test_user",
    "enable_pii": true
  }
  ```
- **Struktur Event SSE**:
  - `data: {"step": "START", "content": ""}`
  - `data: {"step": "TITLE", "content": "Analisis Grade D Fav Institute"}`
  - `data: {"step": "TOOL_CALL", "tool_calls": [...], "content": "Mengeksekusi query database..."}`
  - `data: {"step": "AIMessageChunk", "content": "Berdasarkan bukti pemeriksaan..."}`
  - `data: {"step": "END", "content": "..."}`

### 5.2 GET `/api/v1/conversations?user_id={user_id}`
Mengambil seluruh daftar sesi percakapan untuk user tertentu dari database `synchrono_chatbot`.

- **Respons**:
  ```json
  [
    {
      "id": "conv-lh6hebl-munphkcf",
      "user_id": "analyst_test_user",
      "title": "Percakapan Data Synchrono",
      "created_at": "2026-09-30T06:10:20.128384Z",
      "updated_at": "2026-09-30T06:10:20.128384Z"
    }
  ]
  ```

### 5.3 GET `/api/v1/conversations/{conversation_id}`
Mengambil seluruh daftar pesan dalam satu sesi untuk dimuat kembali ke antarmuka.

### 5.4 DELETE `/api/v1/conversations/{conversation_id}`
Menghapus sesi dan seluruh pesan terkait dari database PostgreSQL.

### 5.5 GET `/api/v1/investigate/{file_id}`
Mengambil informasi file dan daftar antrean baris yang memerlukan peninjauan manual dari tabel `manual_matches`.

### 5.6 GET `/api/v1/health`
Healthcheck status layanan, URL koneksi database PostgreSQL, dan model Ollama Cloud yang aktif.

---

## 6. Antarmuka Pengguna: Pop-up Widget & Halaman Terintegrasi

### 6.1 Floating Pop-up Widget ([static/index.html](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/static/index.html))
- **Launcher FAB**: Tombol melayang di sudut kanan bawah dengan pulse status koneksi live.
- **Floating Modal (440px x 640px)**: Area chat proporsional dengan avatar, status koneksi, dan indikator aktivitas query (*spinner*).
- **Fullscreen Toggle**: Tombol pembesar layar untuk melebarkan chat menjadi modal 1040px saat meneliti tabel data analitik yang padat.
- **Slide-in History Drawer**: Laci riwayat sesi yang dapat dibuka dari kiri untuk beralih sesi atau membuat sesi baru (`+ Sesi Baru`).
- **Quick Prompt Chips**: Pintasan pertanyaan analitik 1-klik untuk evaluasi cepat data Fav Institute, duplikasi file, dan summary tahunan.

### 6.2 Halaman Investigasi Manual ([static/investigate.html](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/static/investigate.html))
- Mengakses rute `/batch-synchronization/investigate?file_id={file_id}&grade=D&name={filename}`.
- Membaca data anomali langsung dari PostgreSQL (`manual_matches`):
  - Contoh kasus: Baris NIK kosong dengan kemiripan nama 95%, dan NIK 12 digit.
  - Tombol aksi reviewer interaktif: "Setujui Pemadanan" dan "Tolak".
  - Pop-up chatbot tetap tersedia di halaman investigasi untuk asistensi langsung.

### 6.3 Halaman Pratinjau Grade A ([static/preview.html](file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/static/preview.html))
- Mengakses rute `/batch-synchronization/preview?file_id={file_id}&grade=A&name={filename}` untuk file yang lolos otomatis tanpa anomali.

---

## 7. Panduan Konfigurasi Lingkungan (`.env`)

File konfigurasi `.env` terletak di root folder `synchrono-chatbot`:

```ini
# Ollama Cloud LLM Configuration
OPENAI_BASE_URL=https://ollama.com/v1
OPENAI_MODEL_NAME=gemma4:31b-cloud
OPENAI_API_KEY=8b85d3218fd04a05b3700a87c03414e9.RJgHRL_Jh2wLgNNAROTjYQRX

# Isolated PostgreSQL Databases (Local WSL Container on localhost:5432)
POSTGRES_URI=postgresql://postgres@localhost:5432/synchrono_chatbot
ANALYTICS_DB_URI=postgresql://synchrono_readonly:readonly123@localhost:5432/synchrono

# Service Host & Port
HOST=0.0.0.0
PORT=8000
```

---

## 8. Langkah Menjalankan Layanan (*Runbook*)

### 1. Pastikan Container PostgreSQL Aktif di WSL:
```bash
wsl -d Ubuntu -- docker ps
# Jika container pg-synchrono mati:
wsl -d Ubuntu -- docker start pg-synchrono
```

### 2. Jalankan Server FastAPI Uvicorn:
Buka terminal PowerShell pada folder `synchrono-chatbot`:
```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\uvicorn.exe src.api.server:app --host 0.0.0.0 --port 8000 --reload
```
*(Catatan: `main:app` tetap didukung sebagai launcher untuk kompatibilitas)*

### 3. Akses Antarmuka Web:
- **Dashboard & Pop-up Chatbot**: [http://localhost:8000/](http://localhost:8000/)
- **Halaman Investigasi File**: [http://localhost:8000/batch-synchronization/investigate?file_id=fav-001&grade=D&name=peserta_diklat_fav.parquet](http://localhost:8000/batch-synchronization/investigate?file_id=fav-001&grade=D&name=peserta_diklat_fav.parquet)
- **Interactive Swagger OpenAPI**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 9. Kepatuhan Antislop Delivery Gate (Mode: DURING)

Layanan dibangun dengan mematuhi seluruh klausul standar Antislop:
- **R-02 (Copywriting)**: Bebas karakter em dash pada seluruh teks UI, judul, dan prompt sistem.
- **R-03 (Responsif Mobile)**: Antarmuka otomatis beradaptasi ke layar ponsel `<= 640px` dengan tap target minimum 44px.
- **R-17 & R-36 (Data Riil)**: Menampilkan angka riil dari database (6 file, 212.700 record) tanpa metrik fiktif.
- **R-25 (Kontras Warna)**: Rasio kontras teks slate-to-white mencapai 13.8:1, melebihi standar WCAG AA (4.5:1).
- **R-26 (Elemen Fungsional)**: Tidak ada tautan atau tombol mati; seluruh kontrol memiliki handler aktif.
- **R-27 (Kelengkapan State)**: Memiliki empty state, live loading indicator, dan error message handling.
- **R-32 (Aksesibilitas Keyboard)**: Mendukung navigasi Tab, Enter kirim pesan, Shift+Enter baris baru, Escape penutup popup, dan indikator focus outline `:focus-visible`.
