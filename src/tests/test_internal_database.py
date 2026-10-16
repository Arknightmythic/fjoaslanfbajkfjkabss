from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.databases.internal.config import (
    _normalize_postgres_uri,
    close_db,
    create_internal_engine,
    get_db,
    init_db,
)
from src.databases.internal.models import Base, Conversation, Message
from src.databases.internal.repository import ConversationRepository


@pytest.fixture
def memory_engine():
    """Isolated in-memory SQLite engine with foreign keys enabled."""
    eng = create_internal_engine("sqlite:///:memory:")
    init_db(eng)
    yield eng
    close_db(eng)


@pytest.fixture
def repo(memory_engine):
    """ConversationRepository bound to the test memory engine."""
    sm = sessionmaker(bind=memory_engine, autoflush=False, expire_on_commit=False)
    return ConversationRepository(session_factory=sm)


def test_uri_normalization():
    assert (
        _normalize_postgres_uri("postgresql://user:pass@localhost:5432/mydb")
        == "postgresql+psycopg://user:pass@localhost:5432/mydb"
    )
    assert (
        _normalize_postgres_uri("postgres://user:pass@localhost:5432/mydb")
        == "postgresql+psycopg://user:pass@localhost:5432/mydb"
    )
    assert (
        _normalize_postgres_uri("postgresql+psycopg://user:pass@localhost:5432/mydb")
        == "postgresql+psycopg://user:pass@localhost:5432/mydb"
    )
    assert _normalize_postgres_uri("sqlite:///:memory:") == "sqlite:///:memory:"


def test_sqlite_engine_configuration():
    eng = create_internal_engine("sqlite:///:memory:")
    assert isinstance(eng.pool, StaticPool)
    with eng.connect() as conn:
        fk_status = conn.execute(text("PRAGMA foreign_keys;")).scalar()
        assert fk_status == 1
    eng.dispose()


def test_import_and_engine_creation_makes_no_connections():
    with patch("socket.socket.connect") as mock_connect:
        eng = create_internal_engine(
            "postgresql+psycopg://synchrono:synchrono123@localhost:5433/synchrono_chatbot"
        )
        sm = sessionmaker(bind=eng)
        test_repo = ConversationRepository(session_factory=sm)
        assert test_repo.engine is eng
        assert not mock_connect.called


def test_preserve_existing_rows_with_raw_ddl():
    raw_engine = create_internal_engine("sqlite:///:memory:")
    with raw_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE conversations (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    title TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE messages (
                    id VARCHAR(64) PRIMARY KEY,
                    conversation_id VARCHAR(64) NOT NULL,
                    role VARCHAR(16) NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO conversations (id, user_id, title, created_at, updated_at)
                VALUES ('legacy_conv_1', 'user_100', 'Legacy Session', '2026-01-01 10:00:00', '2026-01-01 10:00:00');
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO messages (id, conversation_id, role, content, created_at)
                VALUES ('legacy_msg_1', 'legacy_conv_1', 'human', 'Legacy message content', '2026-01-01 10:00:05');
                """
            )
        )

    # Calling init_db must be non-destructive and retain existing rows
    init_db(raw_engine)

    sm = sessionmaker(bind=raw_engine, autoflush=False, expire_on_commit=False)
    repo = ConversationRepository(session_factory=sm)

    convs = repo.get_conversations("user_100")
    assert len(convs) == 1
    assert convs[0]["id"] == "legacy_conv_1"
    assert convs[0]["title"] == "Legacy Session"

    msgs = repo.get_messages("legacy_conv_1")
    assert len(msgs) == 1
    assert msgs[0]["id"] == "legacy_msg_1"
    assert msgs[0]["content"] == "Legacy message content"

    # Insert new record through ORM repository into same schema
    repo.insert_conversation("orm_conv_2", "New Session", "user_100")
    convs_after = repo.get_conversations("user_100")
    assert len(convs_after) == 2
    raw_engine.dispose()


def test_all_seven_crud_methods(repo):
    user_id = "user_test_crud"
    conv_id = "conv_test_1"

    # 1. conversation_exists before insertion
    assert not repo.conversation_exists(conv_id)

    # 2. insert_conversation
    repo.insert_conversation(conv_id, "Initial Title", user_id)
    assert repo.conversation_exists(conv_id)

    # 3. get_conversations
    convs = repo.get_conversations(user_id)
    assert len(convs) == 1
    c = convs[0]
    assert c["id"] == conv_id
    assert c["user_id"] == user_id
    assert c["title"] == "Initial Title"
    created_at = c["created_at"]
    updated_at = c["updated_at"]

    # 4. update_conversation_timestamp
    repo.update_conversation_timestamp(conv_id)
    convs_updated = repo.get_conversations(user_id)
    assert convs_updated[0]["updated_at"] >= updated_at

    # 5. insert_message & get_messages
    repo.insert_message(conv_id, "Hello from human", "human")
    repo.insert_message(conv_id, "Hello from bot", "ai")

    msgs = repo.get_messages(conv_id)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "human"
    assert msgs[0]["content"] == "Hello from human"
    assert msgs[1]["role"] == "ai"
    assert msgs[1]["content"] == "Hello from bot"
    assert msgs[0]["created_at"] <= msgs[1]["created_at"]

    # 6. delete_conversation
    deleted = repo.delete_conversation(conv_id)
    assert deleted is True
    assert not repo.conversation_exists(conv_id)
    assert len(repo.get_conversations(user_id)) == 0
    assert len(repo.get_messages(conv_id)) == 0


def test_cascade_deletion(repo):
    conv_id = "conv_cascade_target"
    repo.insert_conversation(conv_id, "Cascade Title", "user_cascade")
    repo.insert_message(conv_id, "Msg 1", "human")
    repo.insert_message(conv_id, "Msg 2", "ai")
    repo.insert_message(conv_id, "Msg 3", "human")

    assert len(repo.get_messages(conv_id)) == 3

    # Delete parent conversation
    assert repo.delete_conversation(conv_id) is True

    # Child messages must be cascade deleted by DB constraint
    assert len(repo.get_messages(conv_id)) == 0


def test_transaction_rollback_on_error(repo):
    conv_id = "conv_rollback_test"
    repo.insert_conversation(conv_id, "Original", "user_rollback")

    # Duplicate primary key insert must propagate exception and roll back
    with pytest.raises(Exception):
        repo.insert_conversation(conv_id, "Duplicate", "user_rollback")

    convs = repo.get_conversations("user_rollback")
    assert len(convs) == 1
    assert convs[0]["title"] == "Original"


def test_delete_conversation_operation_semantics(repo):
    conv_id = "conv_semantic_test"
    repo.insert_conversation(conv_id, "Title", "user_semantic")

    # True when existing row deleted
    assert repo.delete_conversation(conv_id) is True
    # False when conversation already gone or nonexistent (rowcount == 0)
    assert repo.delete_conversation(conv_id) is False
    assert repo.delete_conversation("totally_unknown_id") is False


def test_reads_and_writes_propagate_db_outage():
    broken_engine = create_engine("sqlite:////unresolvable_directory_9999/test.db")
    broken_sm = sessionmaker(bind=broken_engine)
    broken_repo = ConversationRepository(session_factory=broken_sm)

    # Reads must propagate outage rather than silently returning [] or False
    with pytest.raises(Exception):
        broken_repo.conversation_exists("c1")

    with pytest.raises(Exception):
        broken_repo.get_conversations("u1")

    with pytest.raises(Exception):
        broken_repo.get_messages("c1")

    # Writes must propagate outage
    with pytest.raises(Exception):
        broken_repo.insert_conversation("c1", "title", "u1")

    with pytest.raises(Exception):
        broken_repo.insert_message("c1", "content", "role")

    with pytest.raises(Exception):
        broken_repo.update_conversation_timestamp("c1")

    with pytest.raises(Exception):
        broken_repo.delete_conversation("c1")


def test_get_db_closure(monkeypatch, memory_engine):
    test_sm = sessionmaker(bind=memory_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("src.databases.internal.config.SessionLocal", test_sm)

    # 1. Normal iteration closure calls session.close()
    with patch.object(Session, "close", autospec=True) as mock_close:
        gen = get_db()
        session = next(gen)
        assert isinstance(session, Session)
        assert not mock_close.called

        with pytest.raises(StopIteration):
            next(gen)
        assert mock_close.called

    # 2. Closure on generator throw/exception calls session.close()
    with patch.object(Session, "close", autospec=True) as mock_close:
        gen_err = get_db()
        session_err = next(gen_err)
        assert isinstance(session_err, Session)
        assert not mock_close.called

        try:
            gen_err.throw(RuntimeError("Simulated client error"))
        except RuntimeError:
            pass
        assert mock_close.called


def test_init_and_close_db_lifecycle(memory_engine):
    # Verify init_db can be called idempotently
    init_db(memory_engine)

    with memory_engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        ).scalars().all()
        assert "conversations" in tables
        assert "messages" in tables

    close_db(memory_engine)
