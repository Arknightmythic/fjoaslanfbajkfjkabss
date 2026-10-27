# DATABASE SCHEMA & QUERY SAFETY SKILL

## Purpose
This skill provides authoritative context for the active StarRocks database `syncrono_starrocks_v002` and enforces SQL performance/safety guardrails.

## 1. Core Tables

### `syncrono_service_grading_jobs` (File grading jobs)
- One row per grading job. A file can have multiple jobs; use the latest `created_at` for the current result.
- Key columns: `job_id`, `file_id`, `filename`, `institution_name`, `status`, `stage`, `row_count`, `created_at`, `started_at`, `finished_at`, `error`, `grading_phase` (`BEFORE`/`AFTER`), `data_type` (`PNBP`/`NON_PNBP`).
- Safe to filter by `file_id`, `filename`, `institution_name`, or a recent `created_at` range.

### `syncrono_service_grading_results` (Grade per job/phase)
- Key columns: `job_id`, `file_id`, `phase` (`BEFORE`/`AFTER`), `grade_id`, `grade_letter`, `quality_score`, `row_count`, `rows_graded`, `rows_excluded`, `rows_modified`, `summary` (JSON), `created_at`.
- Final grade: join `r.job_id = j.job_id AND r.phase = j.grading_phase`.
- `summary` contains keys such as `grade`, `gradeLetter`, `qualityScore`, `rowCount`, `completeness`, `anomalyCount`, `trustedNikCount`, `canProceedToSync`.

### `syncrono_service_grade_bands` (Grade reference)
- `grade_id`, `grade_letter`, `score_min`, `score_max`, `severity_label`, `can_proceed`.
- Current bands: A 90–100, B 70–89, C 50–69, D 30–49, E 10–29, F 0–9.

### `syncrono_service_grade_criteria` (Completeness thresholds)
- Per-grade minimum completeness: `min_nik`, `min_nama`, `min_tempat_lahir`, `min_tanggal_lahir`, `min_jenis_kelamin`, `min_nama_ibu`, `min_nik_trusted`, and `nik_column` (`required`/`forbidden`).

### `syncrono_portal_matching_jobs` (Matching job summary)
- Key columns: `id` (job id), `file_id`, `master_file_id`, `status`, `current_stage`, `total_incoming`, `total_candidates`, `avg_candidates_per_row`, `pass1_count`, `pass2_count`, `scoring_count`, `auto_count`, `review_count`, `unmatch_count`, `conflict_count`, `last_error`, `failed_at`, `created_at`, `completed_at`.
- Not every grading `file_id` has a matching job; check before joining.

### `syncrono_portal_matching_results` (Per-record match result)
- Key columns: `id`, `job_id`, `id_incoming`, `master_nik`, `score`, `status` (`AUTO`/`UNMATCH`), `method` (`PASS1_NIK_NAMA`, `PASS2_NAMA_TGL_IBU`, `SCORING`), `rank_conflict`, `pattern_group`, `reasoning`, `incoming_snapshot` (JSON), `master_elements` (JSON), `review_decision`, `created_at`.
- `incoming_snapshot` keys: `nama`, `nik`, `tempat_lahir`, `tanggal_lahir`, `jenis_kelamin`, `nama_ibu`, `provinsi`.

### `syncrono_kl_records` (Per-row K/L identity data)
- Contains `file_id`, `row_id`, `nik`, `nama`, `tempat_lahir`, `tanggal_lahir`, `jenis_kelamin`, `nama_ibu`, `provinsi`, `kabupaten`, `kecamatan`, `kelurahan`, `status_hidup`, `nik_trusted`, `is_anomaly`, `anomaly_type`, `anomaly_notes`, `grading_job_id`, `created_at`.
- Contains PII. Always filter by `file_id` or a selective name/NIK clause and add `LIMIT`.

### `syncrono_kl_enriched` (Enriched per-row data)
- `file_id`, `row_no`, `nik_trusted`, `is_anomaly`, `anomaly_type`, `data` (JSON), `grading_job_id`, `created_at`.
- `data` contains identity and cleansing fields; use `get_json_string(data, '$.nama')` only when needed and mask PII.

### Async batch tables
- `syncrono_service_batches`: `job_id`, `kind`, `file_id`, `status`, `parts`, `total_rows`, `payload`, `profile`, `error`, `created_at`, `updated_at`.
- `syncrono_service_batch_parts`: `job_id`, `part_no`, `row_start`, `row_end`, `status`, `attempts`, `owner`, `retry_at`, `heartbeat_at`, `started_at`, `finished_at`, `counts`, `error`.

### Reference/config tables
- `syncrono_service_masters`: master registry metadata, not per-person master data.
- `syncrono_service_grade_rules`, `syncrono_service_matching_queries`, `syncrono_service_reasoning_patterns`, `syncrono_service_name_titles`, `syncrono_service_engine_config`, `syncrono_service_config_history`, `syncrono_service_config_versions`.

## 2. Join Rules
- `syncrono_service_grading_jobs.job_id` -> `syncrono_service_grading_results.job_id`
- `syncrono_service_grading_jobs.job_id` -> `syncrono_kl_records.grading_job_id`
- `syncrono_service_grading_jobs.file_id` -> `syncrono_kl_records.file_id`
- `syncrono_service_grading_jobs.file_id` -> `syncrono_portal_matching_jobs.file_id`
- `syncrono_portal_matching_jobs.id` -> `syncrono_portal_matching_results.job_id`
- `syncrono_service_grading_results.grade_id` -> `syncrono_service_grade_bands.grade_id`

## 3. JSON Syntax
Use StarRocks functions, not PostgreSQL operators:
- `get_json_string(incoming_snapshot, '$.nama')`
- `get_json_string(summary, '$.completeness')`
- `get_json_string(data, '$.anomaly_type')`

## 4. Typed Status Tools First
- For grading/matching status counts, failed jobs, file status, latest jobs, batch progress, and anomaly summaries, use the typed status tools before `run_query`.
- Use `get_failed_matching_jobs` or `get_file_status` when a matching job is `FAILED`; report `last_error` and `failed_at` when present.
- Never claim a column or reason is absent unless a typed tool or `get_table_detail` confirms it.

## 5. Mandatory LIMIT Guardrail
- Every `SELECT` must include an explicit `LIMIT` unless it is an aggregate query (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`) or a bounded grouped summary.
- Never run `SELECT *` on `syncrono_kl_records` or `syncrono_kl_enriched` without a selective filter and `LIMIT`.
- Never query legacy tables `uploaded_files`, `manual_matches`, `institution`, `ref_grades`, `ref_match_results`, `ref_sync_statuses`, or `grade_bands`; they do not exist in the active database.
