# MISMATCH REASONING & IDENTITY RESOLUTION SKILL

## Purpose
This skill guides the agent in investigating and explaining records that were automatically matched or left unmatched in the active StarRocks database.

## 1. Schema Inspection Requirement
Before querying mismatch details:
- Call `get_table_detail` on `syncrono_portal_matching_results`.
- Call `get_table_detail` on `syncrono_kl_records` when row-level anomaly context is needed.
- Do not assume legacy table or column names.

## 2. Match Status and Method
`syncrono_portal_matching_results.status`:
- `AUTO`: the system found a confident match. `method` explains how: `PASS1_NIK_NAMA`, `PASS2_NAMA_TGL_IBU`, or `SCORING`.
- `UNMATCH`: no confident match was found.
- `review_decision`: populated when a human reviewer records a decision; it may be `NULL`.

There is no separate `ref_match_results` or `manual_matches` table in this database.

## 3. Investigation Protocol
When explaining a record:
1. Query `syncrono_portal_matching_results` by `job_id`, `id_incoming`, or `master_nik` with a strict `LIMIT`.
2. Read `reasoning`, `status`, `method`, `score`, `rank_conflict`, and `pattern_group`.
3. Use `incoming_snapshot` for the incoming identity fields and `master_elements` for comparison evidence when present.
4. For anomaly context, join `syncrono_kl_records` by `file_id`/`grading_job_id` and read `is_anomaly`, `anomaly_type`, and `anomaly_notes`.
5. Present a concise side-by-side explanation of the likely cause: NIK mismatch/invalid, name variation, birth-date difference, missing element, or low score.
6. Recommend a concrete review action in Bahasa Indonesia.

## 4. Privacy
- Never output an unmasked 16-digit NIK.
- Do not dump `incoming_snapshot`, `data`, or raw personal records in full; select only the fields needed for the explanation.
