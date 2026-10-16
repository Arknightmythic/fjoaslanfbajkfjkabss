import os
import pytest
from loguru import logger
from sqlalchemy import text

from src.databases.connectors.sqlalchemy import (
    AnalyticsConnector,
    is_excluded_table,
    normalize_db_uri,
)
from src.tests.demo_analytics import seed_demo_analytics


def test_scheme_normalization() -> None:
    """Test scheme normalization without live database connection."""
    assert normalize_db_uri("postgresql://user:pass@localhost:5432/db") == "postgresql+psycopg://user:pass@localhost:5432/db"
    assert normalize_db_uri("postgres://user:pass@localhost:5432/db") == "postgresql+psycopg://user:pass@localhost:5432/db"
    assert normalize_db_uri("postgresql+psycopg://user:pass@localhost:5432/db") == "postgresql+psycopg://user:pass@localhost:5432/db"
    assert normalize_db_uri("mysql://user:pass@localhost:3306/db") == "mysql+pymysql://user:pass@localhost:3306/db"
    assert normalize_db_uri("mysql+pymysql://user:pass@localhost:3306/db") == "mysql+pymysql://user:pass@localhost:3306/db"
    assert normalize_db_uri("sqlite:///:memory:") == "sqlite:///:memory:"


def test_connector_lazy_import_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raw instantiation does not connect or create an engine."""
    monkeypatch.delenv("ANALYTICS_DB_URI", raising=False)
    connector = AnalyticsConnector()
    assert connector._engine is None
    # close on uninitialized connector is a no-op
    connector.close()
    assert connector._engine is None


def test_missing_and_empty_uri_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connector fails clearly when ANALYTICS_DB_URI is missing or empty, with no demo fallback."""
    monkeypatch.delenv("ANALYTICS_DB_URI", raising=False)
    connector = AnalyticsConnector()
    with pytest.raises(ValueError, match="ANALYTICS_DB_URI is not configured"):
        _ = connector.engine

    monkeypatch.setenv("ANALYTICS_DB_URI", "")
    connector_empty = AnalyticsConnector()
    with pytest.raises(ValueError, match="ANALYTICS_DB_URI is not configured"):
        _ = connector_empty.engine

    monkeypatch.setenv("ANALYTICS_DB_URI", "   ")
    connector_spaces = AnalyticsConnector()
    with pytest.raises(ValueError, match="ANALYTICS_DB_URI is not configured"):
        _ = connector_spaces.engine


def test_invalid_uri_fails_safely() -> None:
    """Invalid URI syntax raises ValueError without exposing credentials."""
    connector = AnalyticsConnector(uri="invalid_scheme://user:super_secret_pw@host:1234/db")
    with pytest.raises((ValueError, Exception)) as exc_info:
        _ = connector.engine
    assert "super_secret_pw" not in str(exc_info.value)


def test_loguru_error_does_not_leak_password(caplog: pytest.LogCaptureFixture) -> None:
    """Loguru logs must not leak URI credentials."""
    secret_pass = "ultra_confidential_pass_123"
    bad_uri = f"postgresql://user:{secret_pass}@127.0.0.1:59999/dummy_db"

    connector = AnalyticsConnector(uri=bad_uri)
    with pytest.raises(Exception):
        connector.initialize()

    # Verify secret is not in pytest/loguru captured logs
    for record in caplog.records:
        assert secret_pass not in record.message


def test_demo_analytics_seed_and_table_names() -> None:
    """Explicit SQLite in-memory engine seeds and reflects demo tables."""
    connector = AnalyticsConnector(uri="sqlite:///:memory:")
    connector.initialize()
    seed_demo_analytics(connector.engine)

    names = connector.get_table_names()
    expected_tables = {
        "ref_grades",
        "ref_sync_statuses",
        "ref_process",
        "ref_match_results",
        "uploaded_files",
        "manual_matches",
        "institution",
    }
    assert expected_tables.issubset(set(names))
    # Excluded and sqlite internal tables must not be returned
    assert not any(t.startswith("sqlite_") for t in names)
    assert not any(is_excluded_table(t) for t in names)


def test_table_schema_output() -> None:
    """get_table_schema returns expected DDL and sample data."""
    connector = AnalyticsConnector(uri="sqlite:///:memory:")
    seed_demo_analytics(connector.engine)

    schema_doc = connector.get_table_schema("uploaded_files")
    assert "### TABLE uploaded_files DDL" in schema_doc
    assert "CREATE TABLE" in schema_doc
    assert "### SAMPLE DATA" in schema_doc
    assert "file_id" in schema_doc
    assert "fav-001" in schema_doc


def test_table_metadata_shape_matches_contract() -> None:
    """get_table_metadata returns exact schema_context dict shape."""
    connector = AnalyticsConnector(uri="sqlite:///:memory:")
    seed_demo_analytics(connector.engine)

    meta = connector.get_table_metadata("uploaded_files")
    assert meta["table_name"] == "uploaded_files"
    assert "table_description" in meta
    assert isinstance(meta["columns"], list)
    assert len(meta["columns"]) > 0

    col_names = [c["name"] for c in meta["columns"]]
    assert "file_id" in col_names
    assert "parquet_path" in col_names

    for col in meta["columns"]:
        assert isinstance(col["name"], str)
        assert isinstance(col["type"], str)
        assert col["nullable"] in ("YES", "NO")
        assert isinstance(col["description"], str)

    assert isinstance(meta["constraints"], list)
    for con in meta["constraints"]:
        assert isinstance(con["name"], str)
        assert isinstance(con["type"], str)
        assert isinstance(con["definition"], str)
        assert isinstance(con["business_context"], str)


def test_query_execution_tsv_and_empty() -> None:
    """execute_query returns TSV string for data and standard string for empty."""
    connector = AnalyticsConnector(uri="sqlite:///:memory:")
    seed_demo_analytics(connector.engine)

    result = connector.execute_query("SELECT grade_id, grade_code FROM ref_grades ORDER BY grade_id LIMIT 2;")
    lines = result.splitlines()
    assert lines[0] == "grade_id\tgrade_code"
    assert lines[1] == "1\tA"
    assert lines[2] == "2\tB"

    empty_result = connector.execute_query("SELECT * FROM ref_grades WHERE grade_id = 999")
    assert empty_result == "No records returned from query."

    # Markdown wrapped query
    wrapped = "```sql\nSELECT grade_code FROM ref_grades WHERE grade_id = 1;\n```"
    res_wrapped = connector.execute_query(wrapped)
    assert res_wrapped == "grade_code\nA"

    # CTE query
    cte_query = "WITH gr AS (SELECT grade_code FROM ref_grades WHERE grade_id = 3) SELECT * FROM gr;"
    res_cte = connector.execute_query(cte_query)
    assert res_cte == "grade_code\nC"


def test_query_validation_rejections() -> None:
    """Security validations reject multiple statements, comments, DML, DDL, and excluded tables."""
    connector = AnalyticsConnector(uri="sqlite:///:memory:")
    seed_demo_analytics(connector.engine)

    # Concatenated statements
    with pytest.raises(PermissionError, match="Multiple SQL statements"):
        connector.execute_query("SELECT 1; DELETE FROM uploaded_files;")

    with pytest.raises(PermissionError, match="Multiple SQL statements"):
        connector.execute_query("SELECT 1; SELECT 2;")

    with pytest.raises(PermissionError, match="Multiple SQL statements"):
        connector.execute_query("SELECT 1;;")

    # Comments
    with pytest.raises(PermissionError, match="comments"):
        connector.execute_query("SELECT * FROM ref_grades -- drop table")

    with pytest.raises(PermissionError, match="comments"):
        connector.execute_query("SELECT * FROM ref_grades /* drop table */")

    # DML and DDL mutations
    with pytest.raises(PermissionError, match="READ-ONLY"):
        connector.execute_query("INSERT INTO ref_grades VALUES (99, 'Z')")

    with pytest.raises(PermissionError, match="READ-ONLY"):
        connector.execute_query("UPDATE ref_grades SET grade_code = 'X'")

    with pytest.raises(PermissionError, match="READ-ONLY"):
        connector.execute_query("DELETE FROM ref_grades")

    with pytest.raises(PermissionError, match="READ-ONLY"):
        connector.execute_query("DROP TABLE ref_grades")

    with pytest.raises(PermissionError, match="READ-ONLY"):
        connector.execute_query("ALTER TABLE ref_grades ADD COLUMN extra TEXT")

    with pytest.raises(PermissionError, match="READ-ONLY"):
        connector.execute_query("CREATE TABLE hacked (id INT)")

    with pytest.raises(PermissionError, match="READ-ONLY"):
        connector.execute_query("TRUNCATE TABLE ref_grades")

    with pytest.raises(PermissionError, match="READ-ONLY"):
        connector.execute_query("SELECT * INTO new_tbl FROM ref_grades")

    # Mutating CTE
    with pytest.raises(PermissionError, match="READ-ONLY"):
        connector.execute_query("WITH d AS (DELETE FROM ref_grades) SELECT * FROM d")

    # Excluded tables check
    excluded_queries = [
        "SELECT * FROM conversations",
        'SELECT * FROM "conversations"',
        "SELECT * FROM public.conversations",
        'SELECT * FROM "public"."conversations"',
        "SELECT * FROM messages",
        "SELECT * FROM checkpoint",
        "SELECT * FROM checkpoints",
        "SELECT * FROM checkpoint_blobs",
        "SELECT * FROM public.checkpoint_writes",
        "SELECT * FROM write",
        "SELECT * FROM writes",
        "SELECT * FROM access_event",
        "SELECT * FROM audit_event",
        "SELECT * FROM retention_action",
        "SELECT * FROM retention_policy",
    ]
    for q in excluded_queries:
        with pytest.raises(PermissionError, match="internal tables"):
            connector.execute_query(q)


def test_query_validation_allows_non_excluded_prefixes() -> None:
    """Non-excluded tables with similar substrings are not falsely blocked by regex."""
    connector = AnalyticsConnector(uri="sqlite:///:memory:")
    seed_demo_analytics(connector.engine)

    # messages_archive is not an excluded table (fails with table not found RuntimeError, not PermissionError)
    with pytest.raises(RuntimeError, match="no such table"):
        connector.execute_query("SELECT * FROM messages_archive")


def test_invalid_table_identifier_injection() -> None:
    """Injection attempts in table_name parameters are rejected."""
    connector = AnalyticsConnector(uri="sqlite:///:memory:")
    seed_demo_analytics(connector.engine)

    injection = "uploaded_files; DROP TABLE ref_grades;"
    schema_res = connector.get_table_schema(injection)
    assert "Invalid table name" in schema_res

    with pytest.raises(ValueError, match="Invalid table name"):
        connector.get_table_metadata(injection)

    # Excluded table rejection
    assert "Not allowed" in connector.get_table_schema("conversations")
    assert "Not allowed" in connector.get_table_schema("checkpoint_blobs")

    with pytest.raises(PermissionError):
        connector.get_table_metadata("conversations")

    with pytest.raises(PermissionError):
        connector.get_table_metadata("checkpoint_blobs")

    # Non-existent table
    assert "Table does not exist" in connector.get_table_schema("non_existent_xyz")
    with pytest.raises(ValueError, match="does not exist"):
        connector.get_table_metadata("non_existent_xyz")


def test_engine_lifecycle_and_reinitialize() -> None:
    """Lifecycle methods initialize and close properly manage the engine state."""
    connector = AnalyticsConnector(uri="sqlite:///:memory:")
    connector.initialize()
    assert connector._engine is not None

    connector.close()
    assert connector._engine is None

    # Re-accessing .engine creates a new instance
    new_eng = connector.engine
    assert new_eng is not None
    connector.close()
