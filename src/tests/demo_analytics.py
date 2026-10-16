from sqlalchemy import text
from sqlalchemy.engine import Engine


def seed_demo_analytics(engine: Engine) -> None:
    """Populate database with Synchrono demo analytics sample data."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ref_grades (
                grade_id INTEGER PRIMARY KEY,
                grade_code VARCHAR(10) NOT NULL
            );
        """))
        conn.execute(text("""
            INSERT INTO ref_grades (grade_id, grade_code) VALUES
            (1, 'A'), (2, 'B'), (3, 'C'), (4, 'D'), (5, 'E'), (6, 'F');
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ref_sync_statuses (
                sync_status_id INTEGER PRIMARY KEY,
                status_code VARCHAR(20) NOT NULL
            );
        """))
        conn.execute(text("""
            INSERT INTO ref_sync_statuses (sync_status_id, status_code) VALUES
            (1, 'In Progress'), (2, 'Awaiting Action'), (3, 'Completed');
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ref_process (
                process_id INTEGER PRIMARY KEY,
                process_name VARCHAR(20) NOT NULL
            );
        """))
        conn.execute(text("""
            INSERT INTO ref_process (process_id, process_name) VALUES
            (1, 'UPLOADED'), (2, 'GRADED');
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ref_match_results (
                match_result_id INTEGER PRIMARY KEY,
                match_result_name VARCHAR(20) NOT NULL
            );
        """))
        conn.execute(text("""
            INSERT INTO ref_match_results (match_result_id, match_result_name) VALUES
            (1, 'AUTO_MATCH'), (2, 'MANUAL_REVIEW'), (3, 'AUTO_UNMATCH'),
            (4, 'MANUAL_MATCH'), (5, 'MANUAL_UNMATCH');
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS uploaded_files (
                file_id VARCHAR(64) PRIMARY KEY,
                original_filename TEXT NOT NULL,
                institution_name TEXT NOT NULL,
                parquet_path TEXT NOT NULL,
                upload_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                row_count INTEGER,
                grade INTEGER REFERENCES ref_grades(grade_id),
                processing_status INTEGER,
                sync_status INTEGER REFERENCES ref_sync_statuses(sync_status_id),
                is_sync BOOLEAN DEFAULT 1,
                matching_task_status VARCHAR(20) DEFAULT 'SUCCESS',
                reasoning_task_status VARCHAR(20) DEFAULT 'SUCCESS',
                preview_url TEXT,
                investigate_url TEXT
            );
        """))

        conn.execute(text("""
            INSERT INTO uploaded_files (
                file_id, original_filename, institution_name, parquet_path,
                upload_timestamp, row_count, grade, processing_status, sync_status,
                is_sync, matching_task_status, reasoning_task_status, preview_url, investigate_url
            ) VALUES
            (
                'fav-001', 'peserta_diklat_fav.parquet', 'Fav Institute', 's3://synchrono/curated/fav-001.parquet',
                datetime('now', '-25 days'), 15000, 4, 2, 2, 1, 'SUCCESS', 'SUCCESS', NULL,
                'https://synchrono.internal/batch-synchronization/investigate?file_id=fav-001&grade=D&name=peserta_diklat_fav.parquet'
            ),
            (
                'fav-002', 'peserta_diklat_fav.parquet', 'Fav Institute', 's3://synchrono/curated/fav-002.parquet',
                datetime('now', '-10 days'), 12500, 4, 2, 2, 1, 'SUCCESS', 'SUCCESS', NULL,
                'https://synchrono.internal/batch-synchronization/investigate?file_id=fav-002&grade=D&name=peserta_diklat_fav.parquet'
            ),
            (
                'fav-003', 'alumni_fav_2025.parquet', 'Fav Institute', 's3://synchrono/curated/fav-003.parquet',
                datetime('now', '-5 days'), 8200, 4, 2, 2, 1, 'SUCCESS', 'SUCCESS', NULL,
                'https://synchrono.internal/batch-synchronization/investigate?file_id=fav-003&grade=D&name=alumni_fav_2025.parquet'
            ),
            (
                'telkom-001', 'pegawai_telkomsel_q1.parquet', 'PT Telekomunikasi Selular', 's3://synchrono/curated/telkom-001.parquet',
                datetime('now', '-60 days'), 45000, 1, 2, 3, 1, 'SUCCESS', 'SUCCESS',
                'https://synchrono.internal/batch-synchronization/preview?file_id=telkom-001&grade=A&name=pegawai_telkomsel_q1.parquet',
                NULL
            ),
            (
                'dukcapil-001', 'penduduk_sample_jabar.parquet', 'Dukcapil Jawa Barat', 's3://synchrono/curated/dukcapil-001.parquet',
                datetime('now', '-180 days'), 100000, 1, 2, 3, 1, 'SUCCESS', 'SUCCESS',
                'https://synchrono.internal/batch-synchronization/preview?file_id=dukcapil-001&grade=A&name=penduduk_sample_jabar.parquet',
                NULL
            ),
            (
                'bpjs-001', 'peserta_pbi_2025.parquet', 'BPJS Kesehatan', 's3://synchrono/curated/bpjs-001.parquet',
                datetime('now', '-90 days'), 32000, 2, 2, 2, 1, 'SUCCESS', 'SUCCESS', NULL,
                'https://synchrono.internal/batch-synchronization/investigate?file_id=bpjs-001&grade=B&name=peserta_pbi_2025.parquet'
            );
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS manual_matches (
                file_id VARCHAR(64) NOT NULL,
                id_incoming TEXT NOT NULL,
                nama_incoming TEXT,
                tempat_lahir_incoming TEXT,
                tanggal_lahir_incoming TEXT,
                jenis_kelamin_incoming TEXT,
                nama_ibu_incoming TEXT,
                reason TEXT,
                pattern_name VARCHAR(255),
                reasoning_status VARCHAR(30) NOT NULL
            );
        """))

        conn.execute(text("""
            INSERT INTO manual_matches (
                file_id, id_incoming, nama_incoming, tempat_lahir_incoming,
                tanggal_lahir_incoming, jenis_kelamin_incoming, nama_ibu_incoming,
                reason, pattern_name, reasoning_status
            ) VALUES
            (
                'fav-001', 'fav-row-101', 'DANUJA JUMARI NASHIRUDDIN', 'JAKARTA',
                '1992-05-14', 'LAKI-LAKI', 'SITI AMINAH',
                'NIK kosong pada data incoming; nama dan tanggal lahir cocok 95% dengan master NIK 317101...',
                'EMPTY_NIK_PROBABILISTIC_MATCH', 'MANUAL_REVIEW'
            ),
            (
                'fav-001', 'fav-row-102', 'ZULAIKHA NAPITUPULU', 'MEDAN',
                '1995-11-20', 'PEREMPUAN', 'NURHAYATI',
                'NIK tidak valid (hanya 12 digit: 120102...); nama identik dengan kandidat master',
                'INVALID_NIK_LENGTH', 'MANUAL_REVIEW'
            ),
            (
                'fav-001', 'fav-row-103', 'BUDI SANTOSO', 'SURABAYA',
                '1988-08-17', 'LAKI-LAKI', 'SUMIATI',
                'Perbedaan 1 digit pada tanggal lahir; nama lengkap dan nama ibu cocok 98% dengan data kependudukan',
                'SINGLE_DIGIT_TYPO_MATCH', 'MANUAL_REVIEW'
            );
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS institution (
                file_id VARCHAR(64) NOT NULL,
                id_incoming TEXT NOT NULL,
                nama_incoming TEXT,
                tempat_lahir_incoming TEXT,
                tanggal_lahir_incoming TEXT,
                jenis_kelamin_incoming TEXT,
                nama_ibu_incoming TEXT,
                match_result INTEGER REFERENCES ref_match_results(match_result_id),
                match_score FLOAT DEFAULT 0.0
            );
        """))

        conn.execute(text("""
            INSERT INTO institution (
                file_id, id_incoming, nama_incoming, tempat_lahir_incoming,
                tanggal_lahir_incoming, jenis_kelamin_incoming, nama_ibu_incoming,
                match_result, match_score
            ) VALUES
            ('fav-001', 'fav-row-101', 'DANUJA JUMARI NASHIRUDDIN', 'JAKARTA', '1992-05-14', 'LAKI-LAKI', 'SITI AMINAH', 2, 0.95),
            ('fav-001', 'fav-row-102', 'ZULAIKHA NAPITUPULU', 'MEDAN', '1995-11-20', 'PEREMPUAN', 'NURHAYATI', 2, 0.88),
            ('fav-001', 'fav-row-103', 'BUDI SANTOSO', 'SURABAYA', '1988-08-17', 'LAKI-LAKI', 'SUMIATI', 2, 0.98),
            ('qa/grade_b_warm', 'qa-001', 'BUDI SETIAWAN', 'BANDUNG', '1990-01-01', 'LAKI-LAKI', 'MARLINA', 1, 1.0);
        """))
