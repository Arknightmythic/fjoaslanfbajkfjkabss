# FILE SYNCHRONIZATION & LINK ROUTING SKILL

## Purpose
This skill defines business logic for determining file upload synchronization status and applying correct link publication rules based on file quality grade and database columns.

## 1. Synchronization Status Evaluation Rules
Check `uploaded_files.matching_task_status` and `uploaded_files.reasoning_task_status`:

- **In Synchronization (In Progress):**
  - `matching_task_status` = 'PROCESSING' OR `reasoning_task_status` IN ('IDLE', 'PROCESSING')
  - **Action:** Inform the user that the file is still undergoing synchronization/processing. **DO NOT** provide any download, preview, or investigation links.

- **Synchronization Completed:**
  - BOTH `matching_task_status` AND `reasoning_task_status` are 'SUCCESS'.
  - **Action:** Proceed to publish the corresponding action link.

## 2. Link Publication Rules (Post-Synchronization)
When synchronization is complete, publish appropriate action links based on `uploaded_files.grade` and the actual non-null column:

- **Grade 'A':**
  - Provide **Preview Link (`preview_url`)**.
- **Non-Grade 'A' (Grade B, C, D, E, or F):**
  - Provide **Investigate Link (`investigate_url`)**.

## 3. Ground Truth: Use Stored Column Verbatim
- **MANDATORY RULE:** ALWAYS `SELECT` the `uploaded_files.preview_url` or `uploaded_files.investigate_url` column and return that **exact string value verbatim** as the link.
- **NEVER** construct, guess, shorten, or reconstruct the URL yourself (e.g. do not manually assemble `/batch-synchronization/investigate?file_id=...`). The stored column contains the exact token and parameter set expected by the frontend.
- If the relevant URL column is `NULL`, inform the user that the link is not yet available.
