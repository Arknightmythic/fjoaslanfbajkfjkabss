import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from langchain.messages import AIMessage, AIMessageChunk
from src.semantic_cache import SemanticCache
from src.handler import ChatbotHandler


class DummyEmbedding:
    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


def test_semantic_cache_normalize_query():
    # NIK 16 digits should be masked
    query = "Tolong cek data dengan NIK 1234567890123456 sekarang"
    normalized = SemanticCache.normalize_query(query)
    assert "[NIK]" in normalized
    assert "1234567890123456" not in normalized
    assert normalized.startswith("tolong cek data")


def test_semantic_cache_retrieve_document_above_90_percent_conf():
    """Cache hit: when retrieved document confidence > 90% (distance < 0.10), returns cached answer."""
    cache = SemanticCache(
        embedding=DummyEmbedding(),
        min_confidence=0.90,
        max_distance=0.10,
    )
    cache._ready = True
    cache._unavailable = False

    # Mock Valkey client FT.SEARCH returning distance 0.05 (confidence = 1 - 0.05 = 0.95 > 0.90)
    mock_client = MagicMock()
    mock_client.execute_command.return_value = [
        1,
        "query_cache:doc1",
        [b"final_answer", b"Jawaban dari cache", b"distance", b"0.05"],
    ]
    cache._client = mock_client

    result = cache.get("Berapa file diunggah?")
    assert result == "Jawaban dari cache"


def test_semantic_cache_retrieve_document_below_or_equal_90_percent_conf():
    """Cache miss: when retrieved document confidence <= 90% (e.g. 88%, distance 0.12), returns None."""
    cache = SemanticCache(
        embedding=DummyEmbedding(),
        min_confidence=0.90,
        max_distance=0.10,
    )
    cache._ready = True
    cache._unavailable = False

    # Mock Valkey client FT.SEARCH returning distance 0.12 (confidence = 0.88 <= 0.90)
    mock_client = MagicMock()
    mock_client.execute_command.return_value = [
        1,
        "query_cache:doc2",
        [b"final_answer", b"Jawaban kadaluarsa", b"distance", b"0.12"],
    ]
    cache._client = mock_client

    result = cache.get("Berapa file diunggah?")
    assert result is None


def test_semantic_cache_retrieve_document_exactly_90_percent_conf():
    """Cache miss: condition is >90% conf, so exactly 90% (distance 0.10) must be a miss."""
    cache = SemanticCache(
        embedding=DummyEmbedding(),
        min_confidence=0.90,
        max_distance=0.10,
    )
    cache._ready = True
    cache._unavailable = False

    # Distance 0.10 -> confidence = 0.90, not strictly > 0.90
    mock_client = MagicMock()
    mock_client.execute_command.return_value = [
        1,
        "query_cache:doc3",
        [b"final_answer", b"Borderline answer", b"distance", b"0.10"],
    ]
    cache._client = mock_client

    result = cache.get("Cek status")
    assert result is None


def test_semantic_cache_set():
    cache = SemanticCache(
        embedding=DummyEmbedding(),
        min_confidence=0.90,
    )
    cache._ready = True
    cache._unavailable = False

    mock_client = MagicMock()
    cache._client = mock_client

    cache.set(
        query="Berapa total data?",
        final_answer="Total data adalah 1000",
        retrieved_chunks=[(0.95, MagicMock(page_content="chunk 1", metadata={"source": "test"}))],
    )

    assert mock_client.hset.called
    assert mock_client.expire.called
    call_args = mock_client.hset.call_args[1]
    mapping = call_args["mapping"]
    assert mapping["final_answer"] == "Total data adalah 1000"
    assert "retrieved_chunks" in mapping


def test_handler_invoke_cache_hit():
    mock_cache = MagicMock(spec=SemanticCache)
    mock_cache.get.return_value = "Jawaban Cepat dari Cache (>90% conf)"

    with patch("src.handler.ChatOpenAI"), \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.PostgresSaver"):
        handler = ChatbotHandler(semantic_cache=mock_cache)
        answer = handler.invoke(thread_id="t1", question="Halo apa kabar?")

    assert answer == "Jawaban Cepat dari Cache (>90% conf)"
    mock_cache.get.assert_called_once_with("Halo apa kabar?")
    assert not mock_cache.set.called


def test_handler_invoke_cache_miss_saves_to_cache():
    mock_cache = MagicMock(spec=SemanticCache)
    mock_cache.get.return_value = None

    with patch("src.handler.ChatOpenAI"), \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.PostgresSaver"), \
         patch("src.handler.create_agent") as mock_create_agent:
        
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": [AIMessage(content="Jawaban baru dari model")]}
        mock_create_agent.return_value = mock_agent

        handler = ChatbotHandler(semantic_cache=mock_cache)
        answer = handler.invoke(thread_id="t1", question="Berapa total file?")

    assert answer == "Jawaban baru dari model"
    mock_cache.get.assert_called_once_with("Berapa total file?")
    mock_cache.set.assert_called_once_with("Berapa total file?", "Jawaban baru dari model")


@pytest.mark.asyncio
async def test_handler_stream_cache_hit():
    mock_cache = MagicMock(spec=SemanticCache)
    mock_cache.get.return_value = "Streaming Jawaban dari Cache"

    with patch("src.handler.ChatOpenAI"), \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.PostgresSaver"), \
         patch("src.handler.SessionLocal"):
        handler = ChatbotHandler(semantic_cache=mock_cache)

        events = []
        async for chunk in handler.stream(
            user_id="u1",
            conversation_id="c1",
            question="Pertanyaan berulang",
        ):
            events.append(chunk)

    parsed_steps = []
    for ev in events:
        if ev.startswith("data: "):
            payload = json.loads(ev[6:].strip())
            parsed_steps.append(payload.get("step"))
            if payload.get("step") == "AIMessageChunk":
                assert payload.get("content") == "Streaming Jawaban dari Cache"

    assert "START" in parsed_steps
    assert "AIMessageChunk" in parsed_steps
    assert "END" in parsed_steps


def test_get_postgres_saver_uri_normalization():
    from src.handler import get_postgres_saver_uri
    with patch("src.handler.INTERNAL_DB_URL", "postgresql+psycopg://synchrono:secret@127.0.0.1:5433/synchrono_chatbot"):
        uri = get_postgres_saver_uri()
        assert uri == "postgresql://synchrono:secret@127.0.0.1:5433/synchrono_chatbot"
        assert not uri.startswith("postgresql+psycopg")

    with patch("src.handler.INTERNAL_DB_URL", "postgres://user:pass@localhost:5432/db"):
        uri = get_postgres_saver_uri()
        assert uri == "postgres://user:pass@localhost:5432/db"


def test_handler_uses_postgres_saver_checkpointer():
    """Verify that ChatbotHandler invokes PostgresSaver as checkpointer."""
    from contextlib import contextmanager
    mock_cp = MagicMock()

    @contextmanager
    def fake_from_conn_string(conn_str):
        yield mock_cp

    with patch("src.handler.ChatOpenAI"), \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.PostgresSaver.from_conn_string", side_effect=fake_from_conn_string):
        handler = ChatbotHandler(semantic_cache=MagicMock(get=MagicMock(return_value=None)))
        with handler._get_checkpointer() as cp:
            assert cp == mock_cp
            mock_cp.setup.assert_called_once()


@pytest.mark.asyncio
async def test_handler_uses_async_postgres_saver_checkpointer():
    """Verify that ChatbotHandler stream uses AsyncPostgresSaver as checkpointer."""
    from contextlib import asynccontextmanager
    mock_async_cp = MagicMock()
    mock_async_cp.setup = AsyncMock()

    @asynccontextmanager
    async def fake_from_conn_string(conn_str):
        yield mock_async_cp

    with patch("src.handler.ChatOpenAI"), \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.AsyncPostgresSaver.from_conn_string", side_effect=fake_from_conn_string):
        handler = ChatbotHandler(semantic_cache=MagicMock(get=MagicMock(return_value=None)))
        async with handler._get_async_checkpointer() as cp:
            assert cp == mock_async_cp
            mock_async_cp.setup.assert_called_once()

