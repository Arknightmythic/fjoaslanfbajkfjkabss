-- ====================================================================
-- SYNCHRONO DATABASE SCHEMA DESCRIPTIONS, DATA DICTIONARY & RELATIONSHIPS
-- Provides comprehensive business context and column/table relationships
-- in English directly stored within PostgreSQL native catalogs and tables.
-- ====================================================================

-- --------------------------------------------------------------------
-- 1. TABLE: schema_relations (Table & Column Business Relationships)
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_relations (
    relation_id SERIAL PRIMARY KEY,
    source_table VARCHAR(64) NOT NULL,
    source_column VARCHAR(64) NOT NULL,
    target_table VARCHAR(64) NOT NULL,
    target_column VARCHAR(64) NOT NULL,
    relation_type VARCHAR(32) NOT NULL,
    join_sql_example TEXT NOT NULL,
    business_context TEXT NOT NULL
);

TRUNCATE TABLE schema_relations;

INSERT INTO schema_relations (source_table, source_column, target_table, target_column, relation_type, join_sql_example, business_context)
VALUES
(
    'uploaded_files', 'file_id', 'manual_matches', 'file_id', 'ONE_TO_MANY',
    'uploaded_files u JOIN manual_matches m ON u.file_id = m.file_id',
    'One uploaded batch file can contain multiple identity records that failed automatic matching or require human manual review.'
),
(
    'uploaded_files', 'file_id', 'institution', 'file_id', 'ONE_TO_MANY',
    'uploaded_files u JOIN institution i ON u.file_id = i.file_id',
    'One uploaded batch file contains thousands of individual incoming citizen records evaluated against the national master registry.'
),
(
    'uploaded_files', 'grade', 'ref_grades', 'grade_id', 'MANY_TO_ONE',
    'uploaded_files u JOIN ref_grades r ON u.grade = r.grade_id',
    'Translates numeric data quality grades (1 to 6) into human-readable letter codes (Grade A through Grade F).'
),
(
    'uploaded_files', 'sync_status', 'ref_sync_statuses', 'sync_status_id', 'MANY_TO_ONE',
    'uploaded_files u JOIN ref_sync_statuses s ON u.sync_status = s.sync_status_id',
    'Maps the lifecycle synchronization state: 1=In Progress, 2=Awaiting Action, 3=Completed.'
),
(
    'uploaded_files', 'processing_status', 'ref_process', 'process_id', 'MANY_TO_ONE',
    'uploaded_files u JOIN ref_process p ON u.processing_status = p.process_id',
    'Tracks the pipeline ingestion milestone: 1=UPLOADED, 2=GRADED.'
),
(
    'uploaded_files', 'grade', 'grade_bands', 'grade_id', 'MANY_TO_ONE',
    'uploaded_files u JOIN grade_bands g ON u.grade = g.grade_id',
    'Determines quality thresholds, severity labels, and procedural eligibility for automated synchronization.'
),
(
    'institution', 'match_result', 'ref_match_results', 'match_result_id', 'MANY_TO_ONE',
    'institution i JOIN ref_match_results r ON i.match_result = r.match_result_id',
    'Classifies identity matching outcomes: 1=AUTO_MATCH, 2=MANUAL_REVIEW, 3=AUTO_UNMATCH, 4=MANUAL_MATCH, 5=MANUAL_UNMATCH.'
),
(
    'institution', 'id_incoming', 'manual_matches', 'id_incoming', 'ONE_TO_ONE',
    'institution i JOIN manual_matches m ON i.file_id = m.file_id AND i.id_incoming = m.id_incoming',
    'Conditional linkage: when an incoming record is flagged with match_result=2 (MANUAL_REVIEW), the discrepancy reason is recorded in manual_matches.'
),
(
    'manual_matches', 'pattern_name', 'reasoning_patterns', 'pattern_name', 'MANY_TO_ONE',
    'manual_matches m JOIN reasoning_patterns p ON m.pattern_name = p.pattern_name',
    'References the cached explanation template and diagnostic signature explaining why records diverged from master registry.'
),
(
    'institution', 'nik_master', 'master', 'nik', 'MANY_TO_ONE',
    'institution i JOIN master m ON i.nik_master = m.nik',
    'Links matched incoming records with the official candidate citizen demographics in the national population master registry.'
);

-- --------------------------------------------------------------------
-- 2. TABLE: uploaded_files (Batch Upload Tracker)
-- --------------------------------------------------------------------
COMMENT ON TABLE uploaded_files IS 'Metadata and lifecycle status for each batch file uploaded to Synchrono for population identity matching.';

COMMENT ON COLUMN uploaded_files.file_id IS 'Unique batch upload identifier (e.g. fav-001, telkom-001). Foreign key connecting to manual_matches and institution.';
COMMENT ON COLUMN uploaded_files.original_filename IS 'Original filename of the submitted dataset (e.g. peserta_diklat_fav.parquet). Multiple batches may share the same filename.';
COMMENT ON COLUMN uploaded_files.institution_name IS 'Name of the submitting institution or agency (e.g. Fav Institute, PT Telekomunikasi Selular, BPJS Kesehatan).';
COMMENT ON COLUMN uploaded_files.parquet_path IS 'S3 or object storage URI where the curated parquet file is stored.';
COMMENT ON COLUMN uploaded_files.upload_timestamp IS 'Timestamp when the file was uploaded. Primary filter for historical time ranges (e.g. past 1 year).';
COMMENT ON COLUMN uploaded_files.row_count IS 'Total number of identity records contained within the uploaded batch file.';
COMMENT ON COLUMN uploaded_files.grade IS 'Numeric data quality grade (1=A, 2=B, 3=C, 4=D, 5=E, 6=F). Joined with ref_grades.grade_id for readable letter grade.';
COMMENT ON COLUMN uploaded_files.processing_status IS 'Pipeline processing milestone (1=UPLOADED, 2=GRADED). Joined with ref_process.process_id.';
COMMENT ON COLUMN uploaded_files.sync_status IS 'Synchronization lifecycle status (1=In Progress, 2=Awaiting Action, 3=Completed). Joined with ref_sync_statuses.';
COMMENT ON COLUMN uploaded_files.is_sync IS 'Boolean flag indicating whether the synchronization process is active.';
COMMENT ON COLUMN uploaded_files.matching_task_status IS 'Execution state of the identity matching worker task (IDLE, PROCESSING, SUCCESS, FAILED).';
COMMENT ON COLUMN uploaded_files.matching_time_ms IS 'Total wall-clock duration of the matching task execution in milliseconds.';
COMMENT ON COLUMN uploaded_files.is_custom_ready IS 'Boolean flag indicating whether custom column mapping is ready for processing.';
COMMENT ON COLUMN uploaded_files.preview_url IS 'Verbatim URL link to preview matched records (strictly applicable for Grade A datasets).';
COMMENT ON COLUMN uploaded_files.investigate_url IS 'Verbatim URL link to investigate mismatched records (applicable for Non-Grade A datasets).';
COMMENT ON COLUMN uploaded_files.reasoning_task_status IS 'Execution state of the reasoning analysis worker task (IDLE, PROCESSING, SUCCESS, FAILED).';

-- --------------------------------------------------------------------
-- 3. TABLE: manual_matches (Mismatch Diagnostic & Review Queue)
-- --------------------------------------------------------------------
COMMENT ON TABLE manual_matches IS 'Detailed records that failed automated identity matching or were flagged for human manual review with discrepancy diagnostics.';

COMMENT ON COLUMN manual_matches.file_id IS 'Batch dataset identifier (e.g. fav-001, qa/grade_b_warm, qa/edge_cases_matrix). Associates record with batch.';
COMMENT ON COLUMN manual_matches.id_incoming IS 'Unique row identifier from the submitting institution (e.g. inc_00098, fav-row-101).';
COMMENT ON COLUMN manual_matches.nama_incoming IS 'Full name of the individual as submitted by the incoming institution.';
COMMENT ON COLUMN manual_matches.tempat_lahir_incoming IS 'Place of birth as submitted by the incoming institution.';
COMMENT ON COLUMN manual_matches.tanggal_lahir_incoming IS 'Date of birth as submitted by the incoming institution (YYYY-MM-DD format).';
COMMENT ON COLUMN manual_matches.jenis_kelamin_incoming IS 'Gender as submitted by the incoming institution (LAKI-LAKI or PEREMPUAN).';
COMMENT ON COLUMN manual_matches.nama_ibu_incoming IS 'Biological mother name as submitted by the incoming institution.';
COMMENT ON COLUMN manual_matches.reason IS 'Comprehensive diagnostic explanation detailing why records diverged (e.g. name spelling discrepancy, DOB variance, missing NIK).';
COMMENT ON COLUMN manual_matches.pattern_name IS 'Classification pattern identifier detected by the matching engine (e.g. pattern_NAMA_DIFF_TMPT_DIFF_...).';
COMMENT ON COLUMN manual_matches.reasoning_source IS 'Source of the diagnostic reasoning evaluation (CACHE, LLM, or RULE).';
COMMENT ON COLUMN manual_matches.reasoning_status IS 'Current status of the review or diagnostic evaluation (COMPLETED, MANUAL_REVIEW, etc.).';

-- --------------------------------------------------------------------
-- 4. TABLE: institution (Incoming Records & Match Results)
-- --------------------------------------------------------------------
COMMENT ON TABLE institution IS 'All incoming citizen records processed per batch paired with matching confidence scores and outcome classifications.';

COMMENT ON COLUMN institution.file_id IS 'Batch dataset identifier (e.g. qa/grade_b_warm, qa/grade_b_cold, qa/edge_cases_matrix).';
COMMENT ON COLUMN institution.id_incoming IS 'Unique record identifier from the incoming institution.';
COMMENT ON COLUMN institution.nik_master IS 'Matched candidate NIK from the national master population registry (sensitive PII).';
COMMENT ON COLUMN institution.match_score IS 'Probabilistic matching confidence score (ranging between 0.00 and 1.00).';
COMMENT ON COLUMN institution.match_result IS 'Matching classification status code (1=AUTO_MATCH, 2=MANUAL_REVIEW, 3=AUTO_UNMATCH, 4=MANUAL_MATCH, 5=MANUAL_UNMATCH).';
COMMENT ON COLUMN institution.upload_date IS 'Timestamp when the record was processed by the ingestion and matching pipeline.';
COMMENT ON COLUMN institution.inserted_date IS 'Database insertion timestamp.';

-- --------------------------------------------------------------------
-- 5. REFERENCE LOOKUP TABLES
-- --------------------------------------------------------------------
COMMENT ON TABLE ref_grades IS 'Lookup table mapping numeric grade identifiers to official data quality grade letters (A through F).';
COMMENT ON COLUMN ref_grades.grade_id IS 'Numeric grade primary key (1, 2, 3, 4, 5, 6).';
COMMENT ON COLUMN ref_grades.grade_code IS 'Letter code representation of data quality (A, B, C, D, E, F).';

COMMENT ON TABLE ref_sync_statuses IS 'Lookup table mapping numeric sync identifiers to human-readable batch synchronization statuses.';
COMMENT ON COLUMN ref_sync_statuses.sync_status_id IS 'Numeric sync status primary key (1, 2, 3).';
COMMENT ON COLUMN ref_sync_statuses.status_code IS 'Status label (In Progress, Awaiting Action, Completed).';

COMMENT ON TABLE ref_match_results IS 'Lookup table mapping identity matching result codes to classification names.';
COMMENT ON COLUMN ref_match_results.match_result_id IS 'Result identifier primary key (1 to 5).';
COMMENT ON COLUMN ref_match_results.match_result_name IS 'Status category name (AUTO_MATCH, MANUAL_REVIEW, AUTO_UNMATCH, MANUAL_MATCH, MANUAL_UNMATCH).';

COMMENT ON TABLE ref_process IS 'Lookup table for batch processing pipeline stages.';
COMMENT ON COLUMN ref_process.process_id IS 'Process stage identifier primary key (1, 2).';
COMMENT ON COLUMN ref_process.process_name IS 'Process stage name (UPLOADED, GRADED).';

COMMENT ON TABLE grade_bands IS 'Quality thresholds, score boundaries, and completeness criteria for Grades A through F.';
COMMENT ON COLUMN grade_bands.grade_id IS 'Numeric grade identifier matching ref_grades.grade_id.';
COMMENT ON COLUMN grade_bands.grade_letter IS 'Grade letter code (A, B, C, D, E, F).';
COMMENT ON COLUMN grade_bands.score_min IS 'Minimum completeness score required for this grade.';
COMMENT ON COLUMN grade_bands.score_max IS 'Maximum completeness score for this grade.';
COMMENT ON COLUMN grade_bands.severity_label IS 'Severity description (e.g. Very Complete, Minimum Requirements with Incomplete NIK).';
COMMENT ON COLUMN grade_bands.can_proceed IS 'Boolean flag indicating whether the dataset can proceed automatically without manual intervention.';
COMMENT ON COLUMN grade_bands.criteria_description IS 'Detailed requirements covering the 6 core identity attributes (NIK, Name, Place of Birth, Date of Birth, Gender, Mother Name).';

COMMENT ON TABLE master IS 'National population master identity registry (~1 billion rows). Read-only source of truth. Mandatory selective filters and LIMIT.';
COMMENT ON COLUMN master.id IS 'Unique national registry record identifier.';
COMMENT ON COLUMN master.nik IS 'Official 16-digit National Identity Number (NIK).';
COMMENT ON COLUMN master.nama_lengkap IS 'Official registered full name.';
COMMENT ON COLUMN master.tempat_lahir IS 'Official registered place of birth.';
COMMENT ON COLUMN master.tanggal_lahir IS 'Official registered date of birth (YYYY-MM-DD).';
COMMENT ON COLUMN master.jenis_kelamin IS 'Official registered gender.';
COMMENT ON COLUMN master.nama_ibu IS 'Official registered biological mother name.';
COMMENT ON COLUMN master.status_kematian IS 'Vital status indicator (ALIVE or DECEASED).';
COMMENT ON COLUMN master.provinsi IS 'Domicile province name.';
COMMENT ON COLUMN master.kabupaten IS 'Domicile regency or city name.';
COMMENT ON COLUMN master.kecamatan IS 'Domicile district name.';
COMMENT ON COLUMN master.kelurahan IS 'Domicile subdistrict or village name.';
