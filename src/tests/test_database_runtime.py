import asyncio
import os
import socket
import sys
import types
from contextlib import contextmanager, asynccontextmanager
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from src.databases.internal.config import (
    get_internal_db_params,
    get_internal_db_url,
    get_postgres_conn_string,
)
from src.databases.connectors.factory import (
    get_analytics_db_params,
    get_active_connector,
)
from src.databases.internal.models.base import Base
from src.databases.internal.models.user import User
from src.databases.internal.models.data_connection import DataConnection
from src.databases.internal.models.conversation import Conversation
from src.databases.internal.models.message import Message
from src.databases.internal.store import ORMConversationDB, REQUIRED_TABLES
from src.handler import ChatbotHandler


@pytest.fixture(autouse=True)
def block_sockets(monkeypatch):
    """Ensure zero network socket connections occur across all tests."""
    socket_calls = []

    def fail_connect(self, *args, **kwargs):
        socket_calls.append(args)
        raise RuntimeError(f"Network socket connection forbidden in offline tests: {args}")

    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    yield socket_calls
    assert len(socket_calls) == 0, f"Attempted network socket calls: {socket_calls}"


@pytest.fixture(autouse=True)
def sanitize_env(monkeypatch):
    """Ensure clean test environment without Opik cloud telemetry or live credentials."""
    monkeypatch.setenv("USE_OPIK", "false")
    monkeypatch.delenv("OPIK_API_KEY", raising=False)
    monkeypatch.delenv("OPIK_PROJECT_NAME", raising=False)


def test_config_env_names_and_special_character_escaping(monkeypatch):
    """Verify canonical env resolution and URL.create credential escaping for special chars."""
    special_password = "p@ss:w/ord?#&=![]+^"
    monkeypatch.setenv("INTERNAL_HOST", "127.0.0.1")
    monkeypatch.setenv("INTERNAL_PORT", "5433")
    monkeypatch.setenv("INTERNAL_USER", "sync_user")
    monkeypatch.setenv("INTERNAL_PASSWORD", special_password)
    monkeypatch.setenv("INTERNAL_DATABASE", "sync_db")

    params = get_internal_db_params()
    assert params["host"] == "127.0.0.1"
    assert params["port"] == 5433
    assert params["user"] == "sync_user"
    assert params["password"] == special_password
    assert params["database"] == "sync_db"

    # URL.create must safely handle special characters without raising
    db_url = get_internal_db_url()
    assert db_url.drivername == "postgresql+psycopg"
    assert db_url.username == "sync_user"
    assert db_url.password == special_password
    assert db_url.host == "127.0.0.1"
    assert db_url.port == 5433
    assert db_url.database == "sync_db"

    # libpq conninfo generation via psycopg.conninfo.make_conninfo
    conn_str = get_postgres_conn_string()
    assert "host=127.0.0.1" in conn_str
    assert "port=5433" in conn_str
    assert "user=sync_user" in conn_str
    assert "dbname=sync_db" in conn_str

    # Analytics config check
    monkeypatch.setenv("DB_HOST", "10.0.0.5")
    monkeypatch.setenv("DB_PORT", "9030")
    monkeypatch.setenv("DB_NAME", "analytics_db")
    monkeypatch.setenv("DB_USER", "analytics_reader")
    monkeypatch.setenv("DB_PASSWORD", "sr_p@ss#123")

    a_params = get_analytics_db_params()
    assert a_params["host"] == "10.0.0.5"
    assert a_params["port"] == 9030
    assert a_params["database"] == "analytics_db"
    assert a_params["username"] == "analytics_reader"
    assert a_params["password"] == "sr_p@ss#123"


def test_orm_conversation_db_crud_and_fk_semantics():
    """Verify ORMConversationDB CRUD, FK satisfying logic, role translations, and cascades."""
    test_engine = create_engine("sqlite:///:memory:")
    db = ORMConversationDB(engine=test_engine)
    db.init_schema()

    # 1. Insert conversation auto-creates referent User to satisfy FK
    db.insert_conversation(
        conversation_id="conv-thread-100",
        title="Analisis Kualitas Data",
        user_id="analyst-user-1",
    )
    assert db.conversation_exists("conv-thread-100") is True
    assert db.conversation_exists("nonexistent-conv") is False

    # Verify underlying Conversation row
    with db._get_session() as session:
        conv_row = session.get(Conversation, "conv-thread-100")
        assert conv_row is not None
        assert conv_row.thread_id == "conv-thread-100"
        assert conv_row.user_id == "analyst-user-1"
        assert conv_row.title == "Analisis Kualitas Data"
        assert conv_row.connection_id is None

        # Verify User row was created
        user_row = session.get(User, "analyst-user-1")
        assert user_row is not None
        assert user_row.id == "analyst-user-1"

    # 2. Insert messages with varied input role formats
    db.insert_message("conv-thread-100", "Berapa file yang diupload?", role="human")
    db.insert_message("conv-thread-100", "Ada 10 file yang diupload.", role="ai")
    db.insert_message("conv-thread-100", "User feedback", role="user")
    db.insert_message("conv-thread-100", "Assistant clarification", role="assistant")
    db.insert_message("conv-thread-100", "System audit notice", role="system")

    # 3. Retrieve messages and verify public contract mapping (stored 'user' -> 'human')
    messages = db.get_messages("conv-thread-100")
    assert len(messages) == 5
    assert messages[0]["role"] == "human"
    assert messages[1]["role"] == "ai"
    assert messages[2]["role"] == "human"
    assert messages[3]["role"] == "ai"
    assert messages[4]["role"] == "system"

    # 4. List conversations by user
    conv_list = db.get_conversations("analyst-user-1")
    assert len(conv_list) == 1
    assert conv_list[0]["id"] == "conv-thread-100"
    assert conv_list[0]["title"] == "Analisis Kualitas Data"

    # 5. Timestamp update
    db.update_conversation_timestamp("conv-thread-100")

    # 6. Delete conversation cascades to messages
    assert db.delete_conversation("conv-thread-100") is True
    assert db.delete_conversation("conv-thread-100") is False
    assert db.conversation_exists("conv-thread-100") is False
    assert len(db.get_messages("conv-thread-100")) == 0


def test_incompatible_legacy_schema_detection():
    """Verify that existing legacy table missing thread_id raises explicit RuntimeError without drop."""
    legacy_engine = create_engine("sqlite:///:memory:")
    with legacy_engine.connect() as conn:
        conn.execute(text("CREATE TABLE conversations (id VARCHAR(64) PRIMARY KEY, user_id VARCHAR(64), title TEXT);"))
        conn.commit()

    db = ORMConversationDB(engine=legacy_engine)
    with pytest.raises(RuntimeError, match="Incompatible legacy table schema detected"):
        db.init_schema()


def test_saver_sync_and_async_context_lifecycles(monkeypatch):
    """Verify that sync ask and async stream use appropriate checkpointer contexts and close reliably."""
    fake_conv_db = types.SimpleNamespace(
        conversation_exists=lambda conversation_id: False,
        get_messages=lambda conversation_id: [],
        insert_conversation=lambda *a, **k: None,
        update_conversation_timestamp=lambda conversation_id: None,
        insert_message=lambda *a, **k: None,
    )
    monkeypatch.setattr("src.handler.conv_db", fake_conv_db)

    closed_sync = []
    closed_async = []

    class MockSyncSaver:
        def __init__(self):
            self.invoked = False

        def get(self, config):
            self.invoked = True
            return None

    class MockAsyncSaver:
        def __init__(self):
            self.invoked = False

        async def aget(self, config):
            self.invoked = True
            return None

    sync_saver = MockSyncSaver()
    async_saver = MockAsyncSaver()

    @contextmanager
    def fake_sync_context():
        try:
            yield sync_saver
        finally:
            closed_sync.append(True)

    @asynccontextmanager
    async def fake_async_context():
        try:
            yield async_saver
        finally:
            closed_async.append(True)

    handler = ChatbotHandler()
    handler.title_generator.generate_title = MagicMock(return_value="Judul Uji")
    handler._get_sync_checkpointer = fake_sync_context
    handler._get_async_checkpointer = fake_async_context

    # 1. Execute sync ask
    mock_sync_agent = MagicMock()
    mock_sync_agent.invoke.return_value = {"messages": [MagicMock(content="Jawaban pengujian")]}
    handler._get_agent = lambda checkpointer=None, enable_pii=True: mock_sync_agent

    res = handler.invoke(thread_id="t-sync-1", question="Halo")
    assert res == "Jawaban pengujian"
    assert sync_saver.invoked is True
    assert len(closed_sync) == 1

    # Execute sync ask error propagation and context close
    mock_sync_agent.invoke.side_effect = RuntimeError("LLM boom")
    with pytest.raises(RuntimeError, match="LLM boom"):
        handler.invoke(thread_id="t-sync-2", question="Halo")
    assert len(closed_sync) == 2

    # 2. Execute async stream
    async def fake_astream(*args, **kwargs):
        yield MagicMock(content="Chunk"), {"langgraph_node": "model"}

    mock_async_agent = MagicMock()
    mock_async_agent.astream = fake_astream
    handler._get_agent = lambda checkpointer=None, enable_pii=True: mock_async_agent

    async def run_stream():
        events = []
        async for ev in handler.stream(user_id="u1", conversation_id="c1", question="Halo async"):
            events.append(ev)
        return events

    events = asyncio.run(run_stream())
    assert len(events) >= 2
    assert async_saver.invoked is True
    assert len(closed_async) == 1

    # Execute async stream error propagation and context close
    async def fake_failing_astream(*args, **kwargs):
        raise RuntimeError("Stream error")
        yield MagicMock(content="Never"), {}

    mock_async_agent.astream = fake_failing_astream
    events_err = []
    async def run_err_stream():
        async for ev in handler.stream(user_id="u1", conversation_id="c2", question="Halo err"):
            events_err.append(ev)

    asyncio.run(run_err_stream())
    assert any("ERROR" in ev for ev in events_err)
    assert len(closed_async) == 2

    # Execute early consumer cancellation / disconnect
    mock_async_agent.astream = fake_astream
    async def run_cancelled_stream():
        async for ev in handler.stream(user_id="u1", conversation_id="c3", question="Cancel test"):
            break

    asyncio.run(run_cancelled_stream())
    assert len(closed_async) == 3


def test_import_safety_zero_sockets():
    """Verify that importing all core database, tool, handler, and API modules triggers 0 network sockets."""
    # Force reload of core modules
    modules_to_test = [
        "src.databases.internal.config",
        "src.databases.internal.store",
        "src.databases.internal.checkpoints",
        "src.databases.connectors.factory",
        "src.databases.connectors.mysql",
        "src.tools.database",
        "src.handler",
        "src.api.routers.chatbot",
        "src.api.server",
    ]
    for mod in modules_to_test:
        sys.modules.pop(mod, None)

    for mod in modules_to_test:
        __import__(mod)

    # Factory lazy connector should not connect on import
    connector = get_active_connector()
    assert connector is not None
    assert connector.dialect == "mysql"
