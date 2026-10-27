import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from langchain.messages import AIMessage, AIMessageChunk
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.databases.internal.models import Base, Conversation, Message, User
from src.handler import ChatbotHandler


@pytest.fixture
def sqlite_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def handler():
    with patch("src.handler.ChatOpenAI") as chat_openai:
        chat_openai.return_value = MagicMock()
        instance = ChatbotHandler(semantic_cache=MagicMock(), checkpointer=object())
    instance.title_generator.generate_title = MagicMock(return_value="Judul Uji")
    instance._trace_enabled = False
    return instance


def test_sync_invoke_uses_configured_checkpointer_and_thread_config(handler):
    fake_agent = MagicMock()
    fake_agent.invoke.return_value = {"messages": [AIMessage("Jawaban dari agent")]}

    with patch("src.handler.create_agent", return_value=fake_agent) as create_agent:
        result = handler.invoke(
            thread_id="thread-sync-1",
            question="Tampilkan ringkasan batch terbaru",
            user_id="user-1",
        )

    assert result == "Jawaban dari agent"
    assert create_agent.call_args.kwargs["checkpointer"] is handler._custom_checkpointer
    config = fake_agent.invoke.call_args.kwargs["config"]
    assert config["configurable"] == {"thread_id": "thread-sync-1", "user_id": "user-1"}


@pytest.mark.asyncio
async def test_async_stream_persists_current_orm_rows_and_closes_checkpointer(
    handler, sqlite_session_factory, monkeypatch
):
    monkeypatch.setattr("src.handler.SessionLocal", sqlite_session_factory)
    lifecycle = {"entered": 0, "exited": 0}

    @asynccontextmanager
    async def tracked_checkpointer():
        lifecycle["entered"] += 1
        try:
            yield object()
        finally:
            lifecycle["exited"] += 1

    handler._get_async_checkpointer = tracked_checkpointer

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
            yield AIMessageChunk(content="Analisis "), {"langgraph_node": "model"}
            yield AIMessageChunk(content="selesai."), {"langgraph_node": "model"}

    with patch("src.handler.create_agent", return_value=FakeAgent()):
        events = []
        async for event in handler.stream(
            user_id="user-1",
            conversation_id="thread-stream-1",
            question="Tolong analisis data batch",
        ):
            events.append(event)

    steps = [json.loads(event[6:].strip())["step"] for event in events if event.startswith("data: ")]
    assert steps[0] == "START"
    assert "AIMessageChunk" in steps
    assert steps[-2:] == ["END", "TITLE"]
    assert lifecycle == {"entered": 1, "exited": 1}

    session = sqlite_session_factory()
    try:
        conversation = session.scalar(select(Conversation).where(Conversation.id == "thread-stream-1"))
        assert conversation is not None
        assert conversation.title == "Judul Uji"
        assert session.get(User, "user-1") is not None

        messages = session.scalars(
            select(Message)
            .where(Message.conversation_id == "thread-stream-1")
            .order_by(Message.created_at)
        ).all()
        assert [message.role for message in messages] == ["user", "ai"]
        assert messages[0].content == "Tolong analisis data batch"
        assert messages[1].content == "Analisis selesai."
    finally:
        session.close()


@pytest.mark.asyncio
async def test_stream_propagates_agent_failure_and_closes_checkpointer(
    handler, sqlite_session_factory, monkeypatch
):
    monkeypatch.setattr("src.handler.SessionLocal", sqlite_session_factory)
    lifecycle = {"entered": 0, "exited": 0}

    @asynccontextmanager
    async def tracked_checkpointer():
        lifecycle["entered"] += 1
        try:
            yield object()
        finally:
            lifecycle["exited"] += 1

    handler._get_async_checkpointer = tracked_checkpointer

    class FailingAgent:
        async def astream(self, *_args, **_kwargs):
            yield AIMessageChunk(content="Mulai "), {"langgraph_node": "model"}
            raise RuntimeError("LLM stream disconnected")

    async def consume():
        async for _ in handler.stream(
            user_id="user-1",
            conversation_id="thread-stream-err",
            question="Tolong analisis data batch",
        ):
            pass

    with patch("src.handler.create_agent", return_value=FailingAgent()):
        with pytest.raises(RuntimeError, match="LLM stream disconnected"):
            await consume()

    assert lifecycle == {"entered": 1, "exited": 1}

    session = sqlite_session_factory()
    try:
        messages = session.scalars(
            select(Message).where(Message.conversation_id == "thread-stream-err")
        ).all()
        assert [message.role for message in messages] == ["user"]
    finally:
        session.close()
