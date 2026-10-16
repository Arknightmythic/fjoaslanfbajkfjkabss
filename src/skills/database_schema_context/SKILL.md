# DATABASE SCHEMA & QUERY SAFETY SKILL

## Purpose
This skill provides authoritative domain context for database tables and enforces strict performance guardrails for SQL query generation.

## 1. Core Tables Overview

### `uploaded_files` (Upload Batch Tracker)
- **Purpose:** Stores metadata for each uploaded file batch (one row per file).
- **Safety:** Small table. Safe to query frequently.
- **Key Columns:**
  - `file_id`: Unique file identifier.
  - `original_filename`: Name of the uploaded file. Note: multiple uploads may share the same filename. When listing files per institution, group by `original_filename` and include `COUNT(*)` as `jumlah`.
  - `institution_name`: Name of the submitting institution (e.g. 'Fav Institute', 'Dukcapil', etc.).
  - `upload_timestamp`: Timestamp when file was uploaded. Useful for 1-year summary queries (`upload_timestamp >= NOW() - INTERVAL 1 YEAR`).
  - `row_count`: Number of records contained in the file.
  - `grade`: Numeric grade code (1=A, 2=B, 3=C, 4=D, 5=E, 6=F). Join with `ref_grades.grade_id` for readable letter code.
  - `matching_task_status`: Status of identity matching (`IDLE`, `PROCESSING`, `SUCCESS`, `FAILED`).
  - `reasoning_task_status`: Status of reasoning generator (`IDLE`, `PROCESSING`, `SUCCESS`, `FAILED`).
  - `preview_url`: Verbatim direct link for Grade A / completed preview.
  - `investigate_url`: Verbatim direct link for Non-Grade A / manual review investigation.
- **Join Requirement:** Always join `ref_grades`, `ref_sync_statuses`, and `ref_process` for readable labels.

### `master` (National Population Master Registry)
- **Purpose:** Source-of-truth identity registry containing full national population data (~1 billion rows).
- **CRITICAL SAFETY RULE:** NEVER execute a query against `master` without a selective `WHERE` clause (e.g., `WHERE nik = '...'` or `WHERE id = '...'`) OR a strict `LIMIT` clause (e.g., `LIMIT 5`).
- Full table scans degrade system performance severely.
- Prefer joining via `nik_master` from `institution` table.

### `manual_matches` (Mismatch Review Queue)
- **Purpose:** Holds records requiring manual review and details WHY automatic matching failed.
- **Key Columns:** `file_id`, `id_incoming`, `nama_incoming`, `tempat_lahir_incoming`, `tanggal_lahir_incoming`, `reason`, `pattern_name`, `reasoning_status`.

### `institution` (Incoming Data & Match Results)
- **Purpose:** Synchronized incoming records paired with potential matches from `master`.
- **Safety:** Always filter by `file_id` or `id_incoming`. Avoid scanning full table.
- **Human Readable Labels:** Join `institution i JOIN ref_match_results r ON i.match_result = r.id`.

### Reference Lookup Tables
- `ref_grades`: Grade codes to quality labels ('A' through 'F', where 'F' = custom mapping).
- `ref_match_results`: `AUTO_MATCH`, `AUTO_UNMATCH`, `MANUAL_REVIEW`, `MANUAL_MATCH`, `MANUAL_UNMATCH`.
- `ref_process`: `UPLOADED`, `GRADED`.
- `ref_sync_statuses`: `In Progress`, `Awaiting Action`, `Completed`.

## 2. Mandatory LIMIT Guardrail
- **STRICT REQUIREMENT:** Every `SELECT` query MUST include an explicit `LIMIT` clause (e.g., `LIMIT 20` or `LIMIT 50`), unless it is performing an explicit aggregate function (`COUNT(*)`, `SUM()`, `AVG()`, etc.).
- **NEVER** execute unbounded queries like `SELECT * FROM uploaded_files` without a `LIMIT`.
