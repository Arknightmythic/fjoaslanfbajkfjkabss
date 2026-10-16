import importlib.util
from pathlib import Path
import sys
import types
import pytest
from sqlalchemy import text


@pytest.fixture
def mock_analytics_env(monkeypatch):
    """Safely load internal.models package and query_engine without triggering unrelated package imports."""
    monkeypatch.setenv("ANALYTICS_DB_URI", "")

    db_dir = Path(__file__).resolve().parent.parent / "databases"
    internal_dir = db_dir / "internal"
    models_dir = internal_dir / "models"

    pkg_db = types.ModuleType("src.databases")
    pkg_db.__path__ = [str(db_dir)]
    monkeypatch.setitem(sys.modules, "src.databases", pkg_db)

    pkg_internal = types.ModuleType("src.databases.internal")
    pkg_internal.__path__ = [str(internal_dir)]
    monkeypatch.setitem(sys.modules, "src.databases.internal", pkg_internal)

    pkg_models = types.ModuleType("src.databases.internal.models")
    pkg_models.__path__ = [str(models_dir)]
    monkeypatch.setitem(sys.modules, "src.databases.internal.models", pkg_models)

    submodules = [
        ("src.databases.internal.models.base", models_dir / "base.py"),
        ("src.databases.internal.models.ref_grade", models_dir / "ref_grade.py"),
        ("src.databases.internal.models.ref_sync_status", models_dir / "ref_sync_status.py"),
        ("src.databases.internal.models.ref_process", models_dir / "ref_process.py"),
        ("src.databases.internal.models.ref_match_result", models_dir / "ref_match_result.py"),
        ("src.databases.internal.models.uploaded_file", models_dir / "uploaded_file.py"),
        ("src.databases.internal.models.manual_match", models_dir / "manual_match.py"),
        ("src.databases.internal.models.institution", models_dir / "institution.py"),
        ("src.databases.internal.models.conversation", models_dir / "conversation.py"),
        ("src.databases.internal.models.message", models_dir / "message.py"),
        ("src.databases.internal.models", models_dir / "__init__.py"),
    ]

    for mod_name, file_path in submodules:
        spec = importlib.util.spec_from_file_location(mod_name, file_path)
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, mod_name, mod)
        spec.loader.exec_module(mod)

    spec_q = importlib.util.spec_from_file_location(
        "src.databases.query_engine",
        db_dir / "query_engine.py",
    )
    mod_q = importlib.util.module_from_spec(spec_q)
    monkeypatch.setitem(sys.modules, "src.databases.query_engine", mod_q)
    spec_q.loader.exec_module(mod_q)

    # Use existing singleton initialized during module import with empty ANALYTICS_DB_URI
    qe = mod_q.query_engine
    try:
        yield sys.modules["src.databases.internal.models"], mod_q, qe
    finally:
        if qe.engine:
            qe.engine.dispose()


def test_model_file_class_layout(mock_analytics_env):
    """Verify each model class lives in its dedicated file and shares Base with Conversation."""
    models, _, _ = mock_analytics_env
    conv_mod = sys.modules["src.databases.internal.models.conversation"]

    expected_mapping = {
        "RefGrade": "src.databases.internal.models.ref_grade",
        "RefSyncStatus": "src.databases.internal.models.ref_sync_status",
        "RefProcess": "src.databases.internal.models.ref_process",
        "RefMatchResult": "src.databases.internal.models.ref_match_result",
        "UploadedFile": "src.databases.internal.models.uploaded_file",
        "ManualMatch": "src.databases.internal.models.manual_match",
        "Institution": "src.databases.internal.models.institution",
    }
    for cls_name, mod_path in expected_mapping.items():
        obj = getattr(models, cls_name)
        assert getattr(obj, "__module__", None) == mod_path
        # All analytic models inherit the EXACT same Base as Conversation
        assert issubclass(obj, models.Base)

    assert issubclass(conv_mod.Conversation, models.Base)

    # Verify no mock_base exists or is exposed
    assert not hasattr(models, "MockAnalyticsBase")
    mock_base_path = Path(__file__).resolve().parent.parent / "databases" / "internal" / "models" / "mock_base.py"
    assert not mock_base_path.exists()

    # Verify old src/databases/models package is absent
    old_models_dir = Path(__file__).resolve().parent.parent / "databases" / "models"
    assert not old_models_dir.exists()


def test_model_table_isolation_and_mock_tables(mock_analytics_env):
    """Metadata contains chat and mock tables, but mock DB creates only seven analytics tables."""
    models, _, qe = mock_analytics_env

    # Base metadata contains chat tables too
    assert "conversations" in models.Base.metadata.tables
    assert "messages" in models.Base.metadata.tables

    # Physical mock database only created the seven analytics tables
    expected_analytics_tables = {
        "ref_grades",
        "ref_sync_statuses",
        "ref_process",
        "ref_match_results",
        "uploaded_files",
        "manual_matches",
        "institution",
    }
    with qe.engine.connect() as conn:
        mock_tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert mock_tables == expected_analytics_tables
    assert "conversations" not in mock_tables
    assert "messages" not in mock_tables


def test_mock_database_row_counts(mock_analytics_env):
    """Mock database row counts match expected seeded totals (6, 3, 2, 5, 6, 3, 4)."""
    _, _, qe = mock_analytics_env
    expected_counts = {
        "ref_grades": 6,
        "ref_sync_statuses": 3,
        "ref_process": 2,
        "ref_match_results": 5,
        "uploaded_files": 6,
        "manual_matches": 3,
        "institution": 4,
    }
    with qe.engine.connect() as conn:
        for table, expected in expected_counts.items():
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            assert count == expected, f"Expected {expected} rows for {table}, got {count}"


def test_seeded_readonly_select_output(mock_analytics_env):
    """Read-only queries return formatted rows and mutation queries are rejected."""
    _, _, qe = mock_analytics_env
    out = qe.execute_query("SELECT grade_id, grade_code FROM ref_grades WHERE grade_id = 1")
    assert out == "grade_id\tgrade_code\n1\tA"

    with pytest.raises(PermissionError):
        qe.execute_query("DELETE FROM ref_grades WHERE grade_id = 1")


def test_defaults_and_surrogate_key_schema(mock_analytics_env):
    """Preserve literal SQL defaults, nullable PKs, and surrogate id PKs on ManualMatch/Institution."""
    models, _, qe = mock_analytics_env

    # Mapped primary key identity is now surrogate id
    assert [c.name for c in models.ManualMatch.__mapper__.primary_key] == ["id"]
    assert [c.name for c in models.Institution.__mapper__.primary_key] == ["id"]

    with qe.engine.connect() as conn:
        # manual_matches has physical id primary key
        mm_info = {r[1]: r for r in conn.execute(text("PRAGMA table_info(manual_matches)")).fetchall()}
        assert mm_info["id"][5] == 1
        assert mm_info["file_id"][5] == 0
        assert mm_info["id_incoming"][5] == 0

        # institution has physical id primary key and match_score default 0.0
        inst_info = {r[1]: r for r in conn.execute(text("PRAGMA table_info(institution)")).fetchall()}
        assert inst_info["id"][5] == 1
        assert inst_info["file_id"][5] == 0
        assert inst_info["id_incoming"][5] == 0
        assert inst_info["match_score"][4] == "0.0"

        # seeded rows without explicit id get distinct non-null IDs
        mm_rows = conn.execute(text("SELECT id, file_id, id_incoming FROM manual_matches")).fetchall()
        assert len(mm_rows) == 3
        assert all(isinstance(r[0], int) for r in mm_rows)
        assert len({r[0] for r in mm_rows}) == 3

        inst_rows = conn.execute(text("SELECT id, file_id, id_incoming FROM institution")).fetchall()
        assert len(inst_rows) == 4
        assert all(isinstance(r[0], int) for r in inst_rows)
        assert len({r[0] for r in inst_rows}) == 4

        # duplicate (file_id, id_incoming) allowed; former composite identity constraint gone
        with conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO manual_matches (file_id, id_incoming, reasoning_status) "
                    "VALUES ('fav-001', 'fav-row-101', 'DUP_TEST')"
                )
            )
            dups = conn.execute(
                text("SELECT id FROM manual_matches WHERE file_id = 'fav-001' AND id_incoming = 'fav-row-101'")
            ).fetchall()
            assert len(dups) == 2
            assert dups[0][0] != dups[1][0]
            conn.rollback()

        # uploaded_files defaults and nullable single PK
        uf_info = {r[1]: r for r in conn.execute(text("PRAGMA table_info(uploaded_files)")).fetchall()}
        assert uf_info["file_id"][3] == 0  # notnull=0 preserved
        assert uf_info["file_id"][5] == 1  # pk=1
        assert uf_info["upload_timestamp"][4] == "CURRENT_TIMESTAMP"
        assert uf_info["is_sync"][4] == "1"
        assert uf_info["matching_task_status"][4] == "'SUCCESS'"
        assert uf_info["reasoning_task_status"][4] == "'SUCCESS'"

        # ref_grades nullable single PK
        rg_info = {r[1]: r for r in conn.execute(text("PRAGMA table_info(ref_grades)")).fetchall()}
        assert rg_info["grade_id"][3] == 0  # notnull=0 preserved
        assert rg_info["grade_id"][5] == 1  # pk=1
