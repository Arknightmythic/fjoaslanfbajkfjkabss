# Synchrono Chatbot API Contract & Integration Guide

> **STATUS: CURRENT & VERIFIED**
>
> Kontrak ini adalah acuan resmi integrasi frontend/web portal ke API Synchrono Chatbot.
>
> **Version:** 2.1  
> **Last updated:** 27 Oktober 2026  
> **Active analytics database:** `syncrono_starrocks_v002`  
> **Protocol:** REST + Server-Sent Events (SSE)  
> **Local base URL (Docker Compose):** `http://127.0.0.1:8001`  
> **Container base URL:** `http://chatbot-api:8000`  
> **OpenAPI/Swagger:** `GET /docs`, `GET /redoc`, `GET /openapi.json`

---

## 0. Ringkasan Cepat

| Method | Path | Jenis | Kegunaan |
|---|---|---|---|
| `GET` | `/api/v1/health` | JSON | Health check |
| `POST` | `/chat` | SSE | Chat utama chatbot |
| `POST` | `/api/v1/knowledge/documents` | Multipart | Upload dokumen/FAQ secara asynchronous |
| `GET` | `/api/v1/knowledge/documents/{document_id}` | JSON | Status ingestion dokumen |
| `GET` | `/api/v1/knowledge/documents/{document_id}/chunks` | JSON | Daftar chunk hasil ingestion |
| `POST` | `/api/v1/knowledge/documents/{document_id}/retry` | JSON | Retry ingestion |
| `POST` | `/api/v1/ingest/file` | JSON | Ingest file dari path server, synchronous |
| `POST` | `/api/v1/ingest/text` | JSON | Ingest teks langsung, synchronous |
| `POST` | `/api/v1/ingest/clear-cache` | JSON | Bersihkan cache FAQ |
| `GET` | `/`, `/test-ui` | HTML | Halaman demo UI |
| `GET` | `/batch-synchronization/investigate` | HTML | Halaman investigasi demo |
| `GET` | `/batch-synchronization/preview` | HTML | Halaman preview demo |

**Catatan:** endpoint chat adalah `/chat`, **bukan** `/api/v1/chat`. Endpoint upload adalah `/api/v1/knowledge/documents`, bukan `/upload`.

---

## 1. Konvensi Umum

### 1.1 Format
- Request JSON memakai `Content-Type: application/json`, kecuali upload yang memakai `multipart/form-data`.
- Response JSON memakai UTF-8.
- ID (`user_id`, `thread_id`, `document_id`, `job_id`, `file_id`) berupa string.
- `user_id` dan `thread_id` maksimal **36 karakter**.
- Pertanyaan chat minimal **1 karakter**.
- Timestamp database mentah umumnya UTC. Field yang berakhiran `_wib` adalah ISO-8601 dengan offset `+07:00`.

### 1.2 Autentikasi
Saat ini **belum ada autentikasi**.
- Header `Authorization` tidak divalidasi.
- `user_id` hanya identifier aplikasi, bukan bukti identitas.
- CORS masih `allow_origins=["*"]`.
- Jangan mengekspos API ini ke internet tanpa gateway/auth.

### 1.3 Error JSON
Error non-streaming mengikuti format FastAPI:

```json
{
  "detail": "Knowledge document not found"
}
```

Validation error `422`:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "question"],
      "msg": "String should have at least 1 character",
      "input": ""
    }
  ]
}
```

### 1.4 Routing Chat
Chatbot memilih jalur secara deterministik:

| Pertanyaan | Jalur | Memanggil LLM? | Memanggil DB? |
|---|---|---|---|
| FAQ platform stabil | FAQ | Untuk sintesis, atau cache hit | Tidak |
| Isi dokumen/panduan | Document | Untuk sintesis | Tidak |
| Status, file, NIK, nama, grade, anomali, K/L | Agent | Ya | Ya, `SELECT` ke v002 |
| Prosedur KTP/KK/KIA/IKD | Out of scope | Tidak | Tidak |
| Pertanyaan umum yang tidak terdeteksi live-data | Document retrieval | Jika ada chunk | Tidak |

Konsekuensinya, pertanyaan yang mirip FAQ bisa tidak menyentuh database. Untuk pertanyaan data live, gunakan kata seperti `berapa`, `status`, `file`, `batch`, `grade`, `NIK`, `matching`, atau `K/L`.

---

## 2. Health Check

### `GET /api/v1/health`

Response `200`:

```json
{
  "status": "healthy",
  "service": "synchrono-chatbot"
}
```

Endpoint ini hanya mengecek proses API, bukan koneksi StarRocks, Valkey, SeaweedFS, atau Celery.

---

## 3. Chat API

### 3.1 Endpoint

```http
POST /chat
Content-Type: application/json
Accept: text/event-stream
```

Response media type: `text/event-stream`.

### 3.2 Request

```json
{
  "user_id": "user-123",
  "thread_id": "thread-abc-123",
  "question": "Berapa jumlah file yang sudah selesai grading dan bagaimana distribusi grade-nya?",
  "enable_pii": true
}
```

| Field | Tipe | Wajib | Aturan | Deskripsi |
|---|---|---|---|---|
| `user_id` | string | Ya | 1–36 karakter | ID pengguna |
| `thread_id` | string | Ya | 1–36 karakter | ID percakapan; gunakan ID yang sama untuk melanjutkan konteks |
| `question` | string | Ya | min. 1 karakter | Pertanyaan pengguna |
| `enable_pii` | boolean | Tidak | default `true` | Masking NIK 16 digit pada input, tool result, dan output |

Tidak ada parameter `model_name`, `base_url`, atau `query` pada versi ini.

### 3.3 Perilaku Thread & Manajemen State Frontend
- **Inisiasi Thread:** Frontend membangkitkan `thread_id` unik (gunakan format UUID v4, misal `crypto.randomUUID()`).
- **Percakapan Multi-Turn (Lanjutan):** Untuk melanjutkan sesi obrolan (misal pertanyaan follow-up *"dari daftar tadi mana yang gagal?"*), kirim `thread_id` yang **sama persis**. Server otomatis memuat konteks obrolan sebelumnya via PostgreSQL LangGraph Checkpointer.
- **Auto Title:** Event `TITLE` hanya dikirimkan pada turn pertama (pertanyaan pembuka) untuk memberi label nama percakapan di UI.
- **Summarization Otomatis:** Server memiliki middleware peringkas otomatis jika percakapan melebihi 15 pesan, sehingga bot tetap ingat topik obrolan tanpa memperlambat waktu respon.
- **Penyimpanan State Sisi Klien:** Selama endpoint REST `/conversations` publik belum dibuka, frontend disarankan menyimpan daftar `thread_id` dan riwayat pesan aktif di state lokal (misal: `localStorage` atau React Context/Zustand).

### 3.4 Format SSE

Setiap event:

```text
data: {"step":"...","content":"..."}

```

Gunakan `fetch` + streaming reader, bukan `EventSource`, karena endpoint memakai `POST`.

### 3.5 Event yang Benar-Benar Dikirim

| `step` | Content | Kapan | Handling Frontend |
|---|---|---|---|
| `START` | `""` | Awal stream | Tampilkan indikator proses |
| `TITLE` | Judul | Turn pertama | Update judul; bisa datang sebelum atau sesudah `END` |
| `AIMessageChunk` dengan `tool_calls` | Biasanya `""` | Agent memanggil tool | Tampilkan status; **jangan** append ke jawaban |
| `ToolMessage` | Hasil tool/SQL | Setelah tool selesai | Tampilkan status generik; **jangan** append ke jawaban |
| `AIMessageChunk` tanpa `tool_calls` | Potongan jawaban | Jawaban model | **Append** ke jawaban |
| `END` | `""` | Jawaban selesai | Tutup status sukses |
| `ERROR` | Pesan fallback generik | Stream gagal | Tampilkan error; stream berakhir tanpa `END` |

**Penting:** implementasi saat ini **tidak mengirim** `step: "TOOL_CALL"`. Tool call muncul sebagai `step: "AIMessageChunk"` yang memiliki properti `tool_calls`.

Saat agen menganalisis data, ada 3 kategori tool yang bisa muncul di `tool_calls`:

1. **Semantic Layer (`query_metrics`)** — Tool utama untuk kueri analitik berbasis metrik, filter waktu dinamis, dan tren multidimensi:
```json
{
  "step": "AIMessageChunk",
  "content": "",
  "tool_calls": [
    {
      "name": "query_metrics",
      "args": {
        "metrics": ["completed_jobs", "failed_jobs"],
        "dimensions": ["day"],
        "time_range": "today"
      },
      "id": "call_123",
      "type": "tool_call"
    }
  ]
}
```

2. **Typed Operational Tools (7 Tools)** — Tool cepat untuk operasi spesifik:
   * `get_grading_status_summary`
   * `get_matching_status_summary`
   * `get_failed_matching_jobs`
   * `get_file_status`
   * `get_latest_grading_jobs`
   * `get_batch_status_summary`
   * `get_anomaly_summary`

Contoh:
```json
{
  "step": "AIMessageChunk",
  "content": "",
  "tool_calls": [
    {
      "name": "get_file_status",
      "args": {
        "identifier": "data_kemenkes_batch1.csv"
      },
      "id": "call_456",
      "type": "tool_call"
    }
  ]
}
```

3. **Fallback Raw Query (`run_query`)** — Kueri SQL mandiri jika pertanyaan sangat spesifik dan belum ada di katalog metrik:
```json
{
  "step": "AIMessageChunk",
  "content": "",
  "tool_calls": [
    {
      "name": "run_query",
      "args": {
        "query": "SELECT ... LIMIT 5"
      },
      "id": "call_789",
      "type": "tool_call"
    }
  ]
}
```

Hasil eksekusi tool muncul berikutnya sebagai `ToolMessage`:
```json
{
  "step": "ToolMessage",
  "content": "{\"period\": {\"preset\": \"today\"}, \"data\": [{\"completed_jobs\": 68}]}"
}
```

#### Panduan Label Status UI untuk Frontend
Agar pengalaman pengguna halus, frontend dapat menampilkan animasi indikator/badge status berdasarkan `tool_calls[0].name`:

| Nama Tool | Label Status UI yang Direkomendasikan |
|---|---|
| `query_metrics` | 📊 *Menganalisis metrik data...* |
| `get_grading_status_summary` | 📝 *Memeriksa ringkasan penilaian mutu berkas...* |
| `get_matching_status_summary` | 🔍 *Memeriksa ringkasan status pemadanan...* |
| `get_failed_matching_jobs` | ⚠️ *Mengecek kendala proses pemadanan...* |
| `get_file_status` | 📁 *Memeriksa riwayat berkas di database...* |
| `get_latest_grading_jobs` | ⏱️ *Mengambil data penilaian berkas terbaru...* |
| `get_batch_status_summary` | 📦 *Mengecek status sinkronisasi batch...* |
| `get_anomaly_summary` | 🚩 *Menganalisis anomali data K/L...* |
| `run_query` | 🔎 *Menjalankan kueri data...* |
| `get_table_names` / `get_table_detail` | 🗄️ *Membaca struktur tabel database...* |

### 3.6 Urutan Event

Jalur FAQ, dokumen, cache, dan out-of-scope umumnya:

```text
START
TITLE          (jika thread baru)
AIMessageChunk (jawaban)
END
```

Jalur agent umumnya:

```text
START
AIMessageChunk (tool_calls)
ToolMessage
AIMessageChunk (tool_calls)
ToolMessage
AIMessageChunk (jawaban)
END
TITLE          (jika thread baru)
```

Karena `TITLE` pada jalur agent dapat datang setelah `END`, frontend tidak boleh langsung menutup parser hanya karena melihat `END` jika masih membutuhkan judul. Cara paling aman: proses sampai koneksi selesai, atau beri jeda singkat setelah `END`.

### 3.7 Contoh cURL

```bash
curl -N -X POST "http://127.0.0.1:8001/chat" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "user_id": "user-123",
    "thread_id": "thread-abc-123",
    "question": "Tampilkan 5 job matching terbaru beserta status dan jumlah AUTO/UNMATCH.",
    "enable_pii": true
  }'
```

Contoh output:

```text
data: {"step":"START","content":""}

data: {"step":"AIMessageChunk","content":"","tool_calls":[{"name":"run_query","args":{"query":"SELECT ... LIMIT 5"},"id":"call_1","type":"tool_call"}]}

data: {"step":"ToolMessage","content":"id\tstatus\t..."}

data: {"step":"AIMessageChunk","content":"Berikut 5 job matching terbaru..."}

data: {"step":"END","content":""}
```

### 3.8 Error dan Terminasi
- Error koneksi/eksekusi stream: `ERROR` dengan `GENERIC_FALLBACK_MESSAGE`, tanpa `END`.
- Model mengembalikan jawaban kosong: fallback teks dikirim sebagai `AIMessageChunk`, lalu `END`.
- Klien disconnect: server berhenti menghasilkan stream; tidak ada event penutup.
- Tidak ada heartbeat/keepalive eksplisit. Proxy dengan idle timeout pendek perlu dikonfigurasi.
- Stream yang berhenti tanpa `END` atau `ERROR` harus dianggap gagal oleh frontend.

### 3.9 PII
- `enable_pii=true` (default) memasking NIK 16 digit, misalnya `*************123`.
- Masking berlaku pada pertanyaan, hasil tool, dan output streaming.
- Masking saat ini **hanya** mendeteksi 16 digit NIK. Nama, tanggal lahir, dan elemen demografis lain tidak otomatis dimasking.
- `enable_pii=false` mematikan masking; hanya gunakan untuk debugging internal.

### 3.10 Batasan Chat
- Tidak ada link portal dari database; tidak ada `preview_url`/`investigate_url`.
- Tidak ada keputusan review manual (`review_decision` masih kosong).
- Tidak bisa mengubah/memicu grading atau matching.
- Tidak memproses seluruh baris lewat LLM; hanya agregasi dan sampel.
- Data analytics aktif hanya `syncrono_starrocks_v002`.

---

## 4. Knowledge Document Upload API

Digunakan untuk menambah FAQ atau dokumen umum secara **asynchronous** dan **versioned**. Ini jalur yang direkomendasikan untuk produksi.

### 4.1 Lifecycle

```text
uploading -> queued -> processing -> completed
                                \-> failed
                                \-> superseded (jika versi lebih lama selesai belakangan)
```

Status yang mungkin:
- `uploading`
- `queued`
- `processing`
- `completed`
- `failed`
- `superseded`

Versi baru tidak langsung aktif. Setelah ingestion selesai:
- Jika `version_number > active_version`, versi baru menjadi aktif dan chunk lama dipangkas.
- Jika `version_number < active_version`, dokumen menjadi `superseded` dan chunk versi tersebut dihapus.
- Cache FAQ atau cache dokumen dibersihkan saat versi baru aktif.

### 4.2 Upload

```http
POST /api/v1/knowledge/documents
Content-Type: multipart/form-data
```

Form fields:

| Field | Tipe | Wajib | Default | Deskripsi |
|---|---|---|---|---|
| `file` | file | Ya | — | `.md`, `.txt`, atau `.pdf` berbasis teks |
| `source_type` | string | Tidak | `faq` | `faq` atau `document` |

Batas ukuran default: **25 MB** (`KNOWLEDGE_MAX_UPLOAD_BYTES`).

Contoh:

```bash
curl -X POST "http://127.0.0.1:8001/api/v1/knowledge/documents" \
  -F "file=@./sop-pemadanan.pdf;type=application/pdf" \
  -F "source_type=document"
```

Response `202 Accepted`:

```json
{
  "document_id": "8fb9b0e4-2e7d-4a8b-9a1b-6f4f3c2d1a77",
  "task_id": "b1c2d3e4-5678-4abc-9def-1234567890ab",
  "filename": "sop-pemadanan.pdf",
  "source_type": "document",
  "version_number": 6,
  "status": "queued"
}
```

`task_id` adalah ID task Celery, bukan `document_id`.

### 4.3 Status Dokumen

```http
GET /api/v1/knowledge/documents/{document_id}
```

Response `200`:

```json
{
  "document_id": "8fb9b0e4-2e7d-4a8b-9a1b-6f4f3c2d1a77",
  "filename": "sop-pemadanan.pdf",
  "source_type": "document",
  "version_number": 6,
  "status": "completed",
  "file_size": 482113,
  "chunk_count": 12,
  "retry_count": 0,
  "error": null,
  "created_at": "2026-10-26T03:50:12",
  "updated_at": "2026-10-26T03:50:44",
  "completed_at": "2026-10-26T03:50:44",
  "created_at_wib": "2026-10-26T10:50:12+07:00",
  "updated_at_wib": "2026-10-26T10:50:44+07:00",
  "completed_at_wib": "2026-10-26T10:50:44+07:00",
  "ingested_at_wib": "2026-10-26T10:50:44+07:00"
}
```

`error` berisi pesan ringkas jika status `failed`.

### 4.4 Daftar Chunk

```http
GET /api/v1/knowledge/documents/{document_id}/chunks
```

Response `200`:

```json
{
  "document_id": "8fb9b0e4-2e7d-4a8b-9a1b-6f4f3c2d1a77",
  "source_type": "document",
  "version_number": 6,
  "status": "completed",
  "chunk_count": 2,
  "chunks": [
    {
      "chunk": 1,
      "document_id": "8fb9b0e4-2e7d-4a8b-9a1b-6f4f3c2d1a77",
      "document_version": 6,
      "source": "sop-pemadanan.pdf",
      "ingested_at_wib": "2026-10-26T10:50:44+07:00",
      "chunk_hash": "f4c1...",
      "preview": "Potongan awal chunk maksimal 240 karakter..."
    }
  ]
}
```

Catatan:
- `preview` hanya 240 karakter pertama, bukan isi penuh.
- Tidak ada pagination.
- `ingested_at_wib` bisa `null` untuk data lama yang belum memiliki metadata WIB.
- `chunk` adalah nomor urut chunk (mulai 1).

### 4.5 Retry Ingestion

```http
POST /api/v1/knowledge/documents/{document_id}/retry
```

Response `202`:

```json
{
  "document_id": "8fb9b0e4-2e7d-4a8b-9a1b-6f4f3c2d1a77",
  "task_id": "new-celery-task-id",
  "source_type": "document",
  "version_number": 6,
  "status": "queued"
}
```

Hanya boleh untuk status `failed` atau `uploaded`. Status lain menghasilkan `409`.

### 4.6 Error Upload/Status/Retry

| Status | Penyebab |
|---|---|
| `400` | Filename invalid, dokumen kosong, `source_type` tidak dikenal |
| `404` | `document_id` tidak ditemukan |
| `413` | Melebihi batas ukuran |
| `415` | Ekstensi bukan `.md`, `.txt`, `.pdf` |
| `422` | Field multipart tidak valid |
| `409` | Retry pada status yang tidak diizinkan |
| `502` | Gagal menyimpan objek ke SeaweedFS |
| `503` | Queue Celery tidak tersedia |

Contoh:

```json
{
  "detail": "Only .md, .txt, and text-based .pdf documents are supported"
}
```

### 4.7 Catatan Penting
- Tidak ada endpoint untuk list semua dokumen.
- Tidak ada endpoint delete dokumen.
- PDF scan/gambar tanpa teks akan gagal karena belum ada OCR.
- Upload bersifat asynchronous; jangan menganggap response `202` berarti dokumen sudah aktif.
- `source_type=faq` mengisi collection FAQ; `source_type=document` mengisi collection dokumen umum.

---

## 5. Direct Ingest API

Endpoint ini adalah jalur lama/synchronous. Berguna untuk operasi internal, bukan untuk upload dari browser.

### 5.1 Ingest File dari Path Server

```http
POST /api/v1/ingest/file
Content-Type: application/json
```

```json
{
  "file_path": "/app/data/faq.md"
}
```

`file_path` dibaca dari filesystem server, bukan diupload. Path dapat absolut atau relatif.

Response sukses `200`:

```json
{
  "file": "faq.md",
  "status": "success",
  "new_chunks": 17,
  "cache_cleared": true
}
```

Kemungkinan response:

```json
{
  "file": "faq.md",
  "status": "skipped",
  "reason": "file_hash_match",
  "new_chunks": 0,
  "cache_cleared": false
}
```

```json
{
  "file": "faq.md",
  "status": "no_new_chunks",
  "new_chunks": 0,
  "cache_cleared": false
}
```

Error:
- `404` jika path tidak ditemukan.
- `500` untuk error ingestion.

### 5.2 Ingest Teks

```http
POST /api/v1/ingest/text
Content-Type: application/json
```

```json
{
  "content": "# FAQ\n\nPertanyaan: ...\n<answer>...</answer>",
  "doc_name": "faq-tambahan.md"
}
```

Aturan:
- `content` minimal 5 karakter.
- `doc_name` default `document.md`.

Response mengikuti bentuk yang sama dengan ingest file (`success`, `skipped`, atau `no_new_chunks`).

### 5.3 Clear Cache FAQ

```http
POST /api/v1/ingest/clear-cache
```

Response:

```json
{
  "status": "success",
  "message": "Semantic cache cleared successfully",
  "cleared_items": 12
}
```

Catatan:
- Endpoint ini membersihkan cache FAQ.
- Cache dokumen umum memiliki scope terpisah dan tidak dibersihkan oleh endpoint ini.

### 5.4 Batasan Direct Ingest
- Synchronous; request bisa lama.
- Tidak memiliki `document_id`, `version_number`, atau status tracking.
- `/ingest/file` dan `/ingest/text` selalu memakai collection FAQ default.
- `/ingest/file` bisa membaca file apa pun yang dapat diakses proses API; batasi akses endpoint ini.
- Untuk produksi, gunakan `/api/v1/knowledge/documents`.

---

## 6. Halaman UI dan OpenAPI

| Method | Path | Keterangan |
|---|---|---|
| `GET` | `/` | Halaman demo chat |
| `GET` | `/test-ui` | Alias halaman demo |
| `GET` | `/batch-synchronization/investigate` | Halaman investigasi statis |
| `GET` | `/batch-synchronization/preview` | Halaman preview statis |
| `GET` | `/static/*` | Aset statis |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc |
| `GET` | `/openapi.json` | OpenAPI schema |

Halaman UI bukan bagian dari kontrak API dan dapat berubah tanpa versioning.

---

## 7. Kontrak Data yang Dipakai Agent

Agent hanya melakukan `SELECT` ke StarRocks `syncrono_starrocks_v002`:

| Kebutuhan | Tabel utama |
|---|---|
| Status grading | `syncrono_service_grading_jobs` |
| Hasil grade | `syncrono_service_grading_results` |
| Band dan kriteria grade | `syncrono_service_grade_bands`, `syncrono_service_grade_criteria` |
| Status matching | `syncrono_portal_matching_jobs` |
| Hasil mismatch | `syncrono_portal_matching_results` |
| Data per baris/K/L | `syncrono_kl_records`, `syncrono_kl_enriched` |
| Progress batch | `syncrono_service_batches`, `syncrono_service_batch_parts` |
| Metadata master | `syncrono_service_masters` |

Aturan:
- Hanya `SELECT`; DML/DDL, multi-statement, `SELECT INTO`, dan locking diblokir.
- `run_query` wajib memakai `LIMIT` untuk query non-agregat.
- Join status proses utama: `file_id` antara grading job dan matching job.
- Final grade: `grading_results.job_id = grading_jobs.job_id` dan `grading_results.phase = grading_jobs.grading_phase`.
- JSON memakai `get_json_string(column, '$.key')`, bukan `->>`.
- Tidak ada URL portal di database.

---

## 8. Security dan Limitasi Produksi

1. **Tanpa auth:** semua endpoint dapat dipanggil siapa pun yang menjangkau API.
2. **CORS terbuka:** `allow_origins=["*"]`; batasi sebelum produksi.
3. **Allowlist tabel belum ada:** tool SQL dapat membaca seluruh tabel yang terlihat, termasuk tabel konfigurasi/API key. Ini harus dikunci.
4. **PII masking terbatas:** hanya NIK 16 digit; nama dan tanggal lahir tidak otomatis disamarkan.
5. **Upload path traversal:** direct ingest membaca path server; jangan diekspos ke pengguna umum.
6. **Tanpa rate limit:** belum ada pembatasan request per user/IP.
7. **Tanpa heartbeat SSE:** proxy harus mengizinkan stream yang relatif lama.
8. **Model cloud:** `gemma4:31b-cloud` perlu diverifikasi agar sesuai klaim pemrosesan internal.
9. **Data demo:** sebagian besar data v002 masih data uji; ringkasan K/L dan tren belum representatif.

---

---

## 8. Format Data Audit & Observabilitas (Internal DB)

Bagi tim QA, Data Analyst, atau Developer yang memantau rekam jejak bot di database PostgreSQL internal (`synchrono_chatbot` pada port 5433):

* **Tabel `answer_audits`:**
  * `id`: UUID string.
  * `user_id`: ID pengguna.
  * `thread_id`: ID percakapan.
  * `route`: Jalur eksekusi bot (`agent`, `faq_synthesized`, `document_synthesized`, `faq_cache`, `document_cache`, `out_of_scope`).
  * `question`: Teks pertanyaan pengguna.
  * `answer`: Teks jawaban bot.
  * `confidence_score`: Nilai 0.0–1.0 (hanya terisi pada RAG FAQ/Dokumen, `NULL` pada rute `agent`/database).
  * `retrieval_score`: Nilai raw reranker score (bernilai `NULL` pada rute `agent`).
  * `created_at_wib`: Timestamp WIB dengan format **`YYYY-MM-DD HH:MM:SS.fff`** (contoh: `2026-10-26 17:53:49.357`).
  * `created_at`: `timestamp with time zone` UTC bawaan database.

---

## 9. Contoh Kode Integrasi Frontend (TypeScript / React)

Berikut adalah fungsi client siap pakai (*drop-in helper*) untuk membaca stream SSE dari `POST /chat` menggunakan `fetch` dan `ReadableStream` bawaan browser:

```typescript
// types/chat.ts
export interface ChatEvent {
  step: 'START' | 'TITLE' | 'AIMessageChunk' | 'ToolMessage' | 'END' | 'ERROR';
  content: string;
  tool_calls?: Array<{
    name: string;
    args: Record<string, unknown>;
    id: string;
    type: 'tool_call';
  }>;
}

export interface SendMessageOptions {
  baseUrl?: string;
  userId: string;
  threadId: string;
  question: string;
  enablePii?: boolean;
  onStart?: () => void;
  onTitle?: (title: string) => void;
  onChunk?: (textChunk: string) => void;
  onToolStatus?: (toolName: string, label: string) => void;
  onEnd?: () => void;
  onError?: (errorMessage: string) => void;
}

const TOOL_LABELS: Record<string, string> = {
  query_metrics: 'Menganalisis metrik data...',
  get_grading_status_summary: 'Memeriksa ringkasan penilaian berkas...',
  get_matching_status_summary: 'Memeriksa ringkasan status pemadanan...',
  get_failed_matching_jobs: 'Mengecek kendala proses pemadanan...',
  get_file_status: 'Memeriksa riwayat berkas...',
  get_latest_grading_jobs: 'Mengambil data penilaian terbaru...',
  get_batch_status_summary: 'Mengecek status sinkronisasi batch...',
  get_anomaly_summary: 'Menganalisis anomali data K/L...',
  run_query: 'Menjalankan kueri data...',
};

export async function sendChatMessage({
  baseUrl = 'http://127.0.0.1:8001',
  userId,
  threadId,
  question,
  enablePii = true,
  onStart,
  onTitle,
  onChunk,
  onToolStatus,
  onEnd,
  onError,
}: SendMessageOptions): Promise<void> {
  try {
    const response = await fetch(`${baseUrl}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({
        user_id: userId,
        thread_id: threadId,
        question: question,
        enable_pii: enablePii,
      }),
    });

    if (!response.ok || !response.body) {
      throw new Error(`HTTP Error ${response.status}: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const block of lines) {
        const line = block.trim();
        if (!line.startsWith('data: ')) continue;

        const jsonStr = line.replace(/^data:\s*/, '');
        try {
          const event: ChatEvent = JSON.parse(jsonStr);

          switch (event.step) {
            case 'START':
              onStart?.();
              break;
            case 'TITLE':
              onTitle?.(event.content);
              break;
            case 'AIMessageChunk':
              if (event.tool_calls && event.tool_calls.length > 0) {
                const toolName = event.tool_calls[0].name;
                const label = TOOL_LABELS[toolName] || 'Sedang memproses data...';
                onToolStatus?.(toolName, label);
              } else if (event.content) {
                onChunk?.(event.content);
              }
              break;
            case 'ToolMessage':
              // Progress tool selesai
              break;
            case 'END':
              onEnd?.();
              break;
            case 'ERROR':
              onError?.(event.content || 'Terjadi kesalahan sistem.');
              break;
          }
        } catch (e) {
          console.warn('Gagal mem-parse blok SSE:', jsonStr, e);
        }
      }
    }
  } catch (err: any) {
    onError?.(err?.message || 'Gagal terhubung ke server chatbot.');
  }
}
```

---

## 10. Checklist Integrasi Frontend

- [ ] Gunakan `POST /chat`, bukan `/api/v1/chat`.
- [ ] Gunakan field `question`, bukan `query`.
- [ ] Gunakan `thread_id`, bukan `conversation_id`.
- [ ] Baca SSE dengan `fetch` + parser, bukan `EventSource`.
- [ ] Append hanya `AIMessageChunk` tanpa `tool_calls`.
- [ ] Tangani `AIMessageChunk` dengan `tool_calls` sebagai status proses (tampilkan badge/loader ramah pengguna).
- [ ] Tangani `ToolMessage` sebagai status proses, bukan teks jawaban.
- [ ] Jangan bergantung pada event `TOOL_CALL`; event itu tidak dikirim.
- [ ] Tangani `TITLE` sebelum maupun sesudah `END`.
- [ ] Anggap stream tanpa `END`/`ERROR` sebagai gagal.
- [ ] Setelah upload `202`, polling `GET /api/v1/knowledge/documents/{id}` sampai `completed`/`failed`.
- [ ] Jangan menampilkan link portal yang tidak ada di database.
- [ ] Jangan mengirim NIK penuh jika `enable_pii=true`.

---

## 11. Perubahan dari Kontrak Lama

| Lama | Sekarang |
|---|---|
| `POST /api/v1/chat` | `POST /chat` |
| `query` | `question` |
| `conversation_id` | `thread_id` |
| `TOOL_CALL` | `AIMessageChunk` dengan `tool_calls` + `ToolMessage` |
| `END.content` berisi jawaban | `END.content` selalu kosong |
| `Authorization` wajib | Belum ada auth |
| `model_name`/`base_url` | Tidak didukung |
| Analytics lama `synchrono` | `syncrono_starrocks_v002` |
