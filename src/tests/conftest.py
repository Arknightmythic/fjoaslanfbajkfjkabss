"""
Shared Pytest Configuration and Test Fixtures.
Ensures zero touch to live production databases, external LLM APIs, and Opik cloud.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
import pytest

# 1. Disable Opik tracing completely across all test sessions
os.environ["USE_OPIK"] = "false"
os.environ.pop("OPIK_API_KEY", None)

# Set model defaults for test environment
os.environ.setdefault("OPENAI_MODEL_NAME", "gemma4:31b-cloud")
os.environ.setdefault("OPENAI_API_KEY", "offline-test")

# 2. Isolate conversation database to a temporary SQLite database
# tempfile default honors TMPDIR (such as /tmp/opencode), TEMP, or system default
_test_db_dir = tempfile.mkdtemp(prefix="synchrono_test_db_")
_test_db_path = Path(_test_db_dir) / "test_conversations.db"
os.environ["POSTGRES_URI"] = f"sqlite:///{_test_db_path}"

# 3. Analytics DB: Clear ANALYTICS_DB_URI to force AnalyticsQueryEngine to use seeded in-memory demo DB
os.environ["ANALYTICS_DB_URI"] = ""


def pytest_sessionfinish(session, exitstatus):
    """Dispose database engines if loaded and clean up temporary test directory."""
    if "src.database.postgres" in sys.modules:
        try:
            from src.databases.postgres import conv_db
            conv_db.engine.dispose()
        except Exception:
            pass
    if "src.database.query_engine" in sys.modules:
        try:
            from src.databases.query_engine import query_engine
            if query_engine.engine:
                query_engine.engine.dispose()
        except Exception:
            pass
    shutil.rmtree(_test_db_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def _disable_offline_demo_for_evals(request, monkeypatch):
    """Disable offline demo fallback in live eval tests so model failures raise errors."""
    if "eval" in request.keywords:
        from src.handler import ChatbotHandler

        def _raise_offline_error(self, question: str):
            raise RuntimeError(f"Offline demo fallback disabled in evaluation tests: {question}")

        monkeypatch.setattr(ChatbotHandler, "_generate_offline_demo_response", _raise_offline_error)


@pytest.fixture
def unique_conversation_id():
    """Yield a unique conversation ID and cleans it up after test completion."""
    import uuid
    from src.databases import conv_db

    conv_id = f"test-conv-{uuid.uuid4().hex[:8]}"
    yield conv_id
    try:
        conv_db.delete_conversation(conv_id)
    except Exception:
        pass
