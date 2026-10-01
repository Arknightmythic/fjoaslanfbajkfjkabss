-- ====================================================================
-- SYNCHRONO DATABASE CONSTRAINTS & CONSTRAINT BUSINESS CONTEXT
-- Defines native PostgreSQL Constraints (PK, FK, UNIQUE, CHECK) and
-- attaches semantic business explanations via native COMMENT ON CONSTRAINT.
-- ====================================================================

-- 1. Remove any legacy or temporary relationship tables
DROP TABLE IF EXISTS schema_relations CASCADE;

-- --------------------------------------------------------------------
-- 2. MASTER REGISTRY CONSTRAINTS
-- --------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_master_nik') THEN
        ALTER TABLE master ADD CONSTRAINT uq_master_nik UNIQUE (nik);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_master_nik_length') THEN
        ALTER TABLE master ADD CONSTRAINT chk_master_nik_length CHECK (LENGTH(nik) = 16);
    END IF;
END $$;

COMMENT ON CONSTRAINT master_pkey ON master IS 'Primary key identifying each citizen demographic record in national master registry.';
COMMENT ON CONSTRAINT uq_master_nik ON master IS 'Enforces unique 16-digit National Identity Number (NIK) across the entire population registry.';
COMMENT ON CONSTRAINT chk_master_nik_length ON master IS 'Validates that official National Identity Numbers (NIK) strictly conform to 16 digits.';

-- --------------------------------------------------------------------
-- 3. UPLOADED_FILES BATCH TRACKER CONSTRAINTS
-- --------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_uploaded_files_row_count') THEN
        ALTER TABLE uploaded_files ADD CONSTRAINT chk_uploaded_files_row_count CHECK (row_count >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_uploaded_files_grade') THEN
        ALTER TABLE uploaded_files ADD CONSTRAINT chk_uploaded_files_grade CHECK (grade BETWEEN 1 AND 6);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_uploaded_files_matching_status') THEN
        ALTER TABLE uploaded_files ADD CONSTRAINT chk_uploaded_files_matching_status CHECK (matching_task_status IN ('IDLE', 'PROCESSING', 'SUCCESS', 'FAILED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_uploaded_files_reasoning_status') THEN
        ALTER TABLE uploaded_files ADD CONSTRAINT chk_uploaded_files_reasoning_status CHECK (reasoning_task_status IN ('IDLE', 'PROCESSING', 'SUCCESS', 'FAILED'));
    END IF;
END $$;

COMMENT ON CONSTRAINT uploaded_files_pkey ON uploaded_files IS 'Primary key uniquely identifying each batch upload of citizen identity data.';
COMMENT ON CONSTRAINT uploaded_files_grade_fkey ON uploaded_files IS 'Foreign key mapping numeric data quality grade (1 to 6) to letter representation in ref_grades.';
COMMENT ON CONSTRAINT uploaded_files_processing_status_fkey ON uploaded_files IS 'Foreign key tracking pipeline processing milestone in ref_process (1=UPLOADED, 2=GRADED).';
COMMENT ON CONSTRAINT uploaded_files_sync_status_fkey ON uploaded_files IS 'Foreign key tracking synchronization lifecycle in ref_sync_statuses (1=In Progress, 2=Awaiting Action, 3=Completed).';
COMMENT ON CONSTRAINT chk_uploaded_files_row_count ON uploaded_files IS 'Ensures total record count per file batch is non-negative.';
COMMENT ON CONSTRAINT chk_uploaded_files_grade ON uploaded_files IS 'Restricts data quality grade within valid range: 1 (Grade A) through 6 (Grade F).';
COMMENT ON CONSTRAINT chk_uploaded_files_matching_status ON uploaded_files IS 'Restricts matching execution state to valid lifecycle stages: IDLE, PROCESSING, SUCCESS, FAILED.';
COMMENT ON CONSTRAINT chk_uploaded_files_reasoning_status ON uploaded_files IS 'Restricts reasoning execution state to valid lifecycle stages: IDLE, PROCESSING, SUCCESS, FAILED.';

-- --------------------------------------------------------------------
-- 4. INSTITUTION INCOMING RECORDS CONSTRAINTS
-- --------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_institution_match_score') THEN
        ALTER TABLE institution ADD CONSTRAINT chk_institution_match_score CHECK (match_score >= 0.0 AND match_score <= 100.0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_institution_match_result') THEN
        ALTER TABLE institution ADD CONSTRAINT chk_institution_match_result CHECK (match_result BETWEEN 1 AND 5);
    END IF;
END $$;

COMMENT ON CONSTRAINT institution_pkey ON institution IS 'Composite primary key identifying each incoming record within its batch (file_id, id_incoming).';
COMMENT ON CONSTRAINT institution_match_result_fkey ON institution IS 'Foreign key classifying identity matching outcome in ref_match_results (1=AUTO_MATCH, 2=MANUAL_REVIEW, 3=AUTO_UNMATCH, 4=MANUAL_MATCH, 5=MANUAL_UNMATCH).';
COMMENT ON CONSTRAINT chk_institution_match_score ON institution IS 'Validates probabilistic identity matching confidence score stays between 0.00 and 100.00.';
COMMENT ON CONSTRAINT chk_institution_match_result ON institution IS 'Restricts identity match result classification code to valid range 1 through 5.';

-- --------------------------------------------------------------------
-- 5. MANUAL_MATCHES REVIEW QUEUE CONSTRAINTS
-- --------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_manual_matches_reasoning_status') THEN
        ALTER TABLE manual_matches ADD CONSTRAINT chk_manual_matches_reasoning_status CHECK (reasoning_status IN ('COMPLETED', 'MANUAL_REVIEW', 'PENDING', 'PROCESSING', 'FAILED'));
    END IF;
END $$;

COMMENT ON CONSTRAINT manual_matches_pkey ON manual_matches IS 'Composite primary key identifying each discrepancy or manual review record (file_id, id_incoming).';
COMMENT ON CONSTRAINT chk_manual_matches_reasoning_status ON manual_matches IS 'Restricts review status to valid states: COMPLETED, MANUAL_REVIEW, PENDING, PROCESSING, FAILED.';

-- --------------------------------------------------------------------
-- 6. GRADE_BANDS & REFERENCE TABLES CONSTRAINTS
-- --------------------------------------------------------------------
COMMENT ON CONSTRAINT grade_bands_pkey ON grade_bands IS 'Primary key for quality grade band completeness thresholds.';
COMMENT ON CONSTRAINT grade_bands_grade_id_fkey ON grade_bands IS 'Foreign key linking grade threshold configuration to ref_grades.';
COMMENT ON CONSTRAINT ref_grades_pkey ON ref_grades IS 'Primary key for reference table of quality grade letter codes.';
COMMENT ON CONSTRAINT ref_sync_statuses_pkey ON ref_sync_statuses IS 'Primary key for reference table of synchronization lifecycle statuses.';
COMMENT ON CONSTRAINT ref_match_results_pkey ON ref_match_results IS 'Primary key for reference table of match outcome classifications.';
COMMENT ON CONSTRAINT ref_process_pkey ON ref_process IS 'Primary key for reference table of pipeline processing stages.';
