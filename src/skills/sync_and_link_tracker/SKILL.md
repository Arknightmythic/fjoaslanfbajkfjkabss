# FILE SYNCHRONIZATION & LINK ROUTING SKILL

## Purpose
This skill defines how to report file processing/synchronization status in the active `syncrono_starrocks_v002` database.

## 1. Status Sources
Use the typed status tools first: `get_file_status`, `get_latest_grading_jobs`, `get_grading_status_summary`, `get_matching_status_summary`, `get_failed_matching_jobs`, and `get_batch_status_summary`. Use raw SQL only when no typed tool covers the question.

Use the latest grading job for the file:
- `syncrono_service_grading_jobs.file_id`, `job_id`, `status`, `stage`, `grading_phase`, `created_at`, `finished_at`, `error`.
- Async progress: `syncrono_service_batches.status`, `parts`, `total_rows`; per-part status in `syncrono_service_batch_parts`.

Use the matching job when one exists:
- `syncrono_portal_matching_jobs.file_id`, `id`, `status`, `current_stage`, `total_incoming`, `auto_count`, `review_count`, `unmatch_count`, `last_error`, `failed_at`, `completed_at`.
- Matching status values include `MATCHING`, `COMPLETED`, `FAILED`, and `CANCELLED`.

## 2. Interpretation
- **Still processing:** grading job is not `COMPLETED`, or a matching job exists with status `MATCHING`.
- **Completed:** grading job is `COMPLETED`; if a matching job exists, it is also `COMPLETED`.
- **Failed/cancelled:** report the grading or matching status and the stored `error` or `last_error` value.
- Do not claim synchronization succeeded merely because a file was uploaded; verify the job status first.
- Do not claim a failure reason is unavailable when `last_error` is populated; report it verbatim or summarize it.

## 3. Links
- The active schema does **not** contain `preview_url` or `investigate_url` columns.
- Never construct, guess, or fabricate a URL.
- If the user asks for a link, explain that the analytics database does not store the URL and provide the exact `file_id`/`job_id` so the user can open it in the portal.
