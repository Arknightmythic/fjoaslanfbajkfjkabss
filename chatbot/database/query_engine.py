import os
import re
from typing import Any, List, Optional
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

load_dotenv()

EXCLUDED_TABLES = [
    "checkpoint",
    "write",
    "conversations",
    "messages",
    "access_event",
    "audit_event",
    "retention_action",
    "retention_policy",
]

class AnalyticsQueryEngine:
    def __init__(self, uri: Optional[str] = None):
        self.uri = uri or os.getenv("ANALYTICS_DB_URI")
        self.engine: Optional[Engine] = None
        self._init_connection()

    def _init_connection(self) -> None:
        if self.uri:
            try:
                uri = self.uri
                if uri.startswith("postgresql://") and "+psycopg" not in uri:
                    uri = uri.replace("postgresql://", "postgresql+psycopg://")
                self.engine = create_engine(
                    uri,
                    pool_size=5,
                    max_overflow=10,
                    pool_pre_ping=True,
                )
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1;"))
                print(f"[Analytics DB] Terhubung ke database analitik: {self.uri.split('@')[-1]}")
                return
            except Exception as e:
                print(f"[Analytics DB] Gagal terhubung ke {self.uri}: {e}. Memasang Mock / In-Memory Database untuk demonstrasi.")
        
        # Fallback to SQLite in-memory with preloaded sample data matching the Synchrono schema
        self._setup_mock_database()

    def _setup_mock_database(self) -> None:
        """Create an in-memory SQLite database populated with realistic demo data for testing."""
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with self.engine.begin() as conn:
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

        print("[Analytics DB] In-Memory Demonstration Database berhasil dikonfigurasi dengan data Synchrono!")

    def get_table_names(self) -> List[str]:
        try:
            with self.engine.connect() as conn:
                dialect = self.engine.dialect.name.lower()
                if "sqlite" in dialect:
                    res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';")).fetchall()
                    names = [r[0] for r in res]
                elif "postgres" in dialect:
                    res = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")).fetchall()
                    names = [r[0] for r in res]
                else:
                    res = conn.execute(text("SHOW TABLES;")).fetchall()
                    names = [r[0] for r in res]
                return [t for t in names if t not in EXCLUDED_TABLES and not t.startswith("sqlite_")]
        except Exception as e:
            print(f"[Analytics DB Error] get_table_names: {e}")
            return []

    def get_table_schema(self, table_name: str) -> str:
        if table_name in EXCLUDED_TABLES:
            return f"Not allowed to read table {table_name}"
        try:
            with self.engine.connect() as conn:
                dialect = self.engine.dialect.name.lower()
                if "sqlite" in dialect:
                    schema_res = conn.execute(text(f"SELECT sql FROM sqlite_master WHERE name='{table_name}';")).fetchone()
                    schema_str = schema_res[0] if schema_res else "N/A"
                elif "postgres" in dialect:
                    cols_res = conn.execute(text(f"""
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_name = '{table_name}' AND table_schema = 'public'
                        ORDER BY ordinal_position;
                    """)).fetchall()
                    col_defs = [f"  {r[0]} {r[1]} {'NULL' if r[2]=='YES' else 'NOT NULL'}" for r in cols_res]
                    schema_str = f"CREATE TABLE {table_name} (\n" + ",\n".join(col_defs) + "\n);"
                else:
                    schema_res = conn.execute(text(f"SHOW CREATE TABLE `{table_name}`;")).fetchone()
                    schema_str = schema_res[1] if schema_res else "N/A"

                sample_res = conn.execute(text(f"SELECT * FROM {table_name} LIMIT 3;"))
                keys = sample_res.keys()
                rows = sample_res.fetchall()

                sample_lines = ["\t".join(keys)]
                for row in rows:
                    sample_lines.append("\t".join(str(c) for c in list(row)))

                return f"### TABLE {table_name} DDL\n{schema_str}\n\n### SAMPLE DATA\n" + "\n".join(sample_lines)
        except Exception as e:
            return f"Error retrieving schema for {table_name}: {e}"

    def execute_query(self, query: str) -> Any:
        query_clean = re.sub(r"```(?:sql)?\s*|\s*```|;", "", query, flags=re.IGNORECASE).strip()
        forbidden_patterns = [
            r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke)\b",
            r";",
            r"--",
            r"/\*",
        ]
        for pat in forbidden_patterns:
            if re.search(pat, query_clean, re.IGNORECASE):
                raise PermissionError("Operasi penulisan atau manipulasi data dilarang. AI hanya memiliki akses READ-ONLY.")

        try:
            with self.engine.connect() as conn:
                res = conn.execute(text(query_clean))
                keys = res.keys()
                rows = res.fetchall()

                if not rows:
                    return "No records returned from query."

                output_lines = ["\t".join(keys)]
                for row in rows:
                    output_lines.append("\t".join(str(c) for c in list(row)))
                return "\n".join(output_lines)
        except Exception as e:
            raise RuntimeError(f"Database query error: {e}")

# Global instance
query_engine = AnalyticsQueryEngine()
