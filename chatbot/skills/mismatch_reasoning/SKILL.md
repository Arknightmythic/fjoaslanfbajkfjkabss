# MISMATCH REASONING & IDENTITY RESOLUTION SKILL

## Purpose
This skill guides the agent in investigating, explaining, and presenting reasoning for records that failed automatic matching or require manual review.

## 1. Schema Inspection Requirement
Before querying mismatch details or reason fields:
- Call `get_table_detail` on table `manual_matches` to inspect its exact schema and sample rows.
- Do not assume column names for mismatch reasons.

## 2. Match Result Reference Statuses
Map `institution.match_result` via `ref_match_results`:
- `AUTO_MATCH`: System automatically matched identity to national registry (`master`).
- `AUTO_UNMATCH`: System determined no confident match exists.
- `MANUAL_REVIEW`: Records flagged for human judgment due to borderline confidence or field discrepancies.
- `MANUAL_MATCH`: Human judge confirmed a valid match.
- `MANUAL_UNMATCH`: Human judge confirmed records do not match.

## 3. Comparison Protocol
When explaining why a record is `UNMATCH` or in `MANUAL_REVIEW`:
1. Retrieve record discrepancy reasons from `manual_matches` or candidate data from `master`.
2. Present side-by-side field comparison (e.g. spelling variation, DOB discrepancy).
3. Recommend concrete corrective action in Bahasa Indonesia.
