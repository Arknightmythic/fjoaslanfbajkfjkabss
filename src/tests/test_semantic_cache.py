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


def test_faq_semantic_cache_default_ttl_is_twelve_hours():
    cache = SemanticCache(embedding=DummyEmbedding())
    assert cache._ttl == 12 * 60 * 60


def test_document_semantic_cache_uses_separate_index_and_key_prefix():
    faq_cache = SemanticCache(embedding=DummyEmbedding())
    document_cache = SemanticCache(embedding=DummyEmbedding(), scope="document")

    assert faq_cache.scope == "faq"
    assert faq_cache._index_name == "idx:query_cache"
    assert faq_cache._key_prefix == "query_cache:"
    assert document_cache.scope == "document"
    assert document_cache._index_name == "idx:query_cache_document"
    assert document_cache._key_prefix == "query_cache_document:"


def test_semantic_cache_rejects_unknown_scope():
    with pytest.raises(ValueError, match="Unsupported semantic cache scope"):
        SemanticCache(embedding=DummyEmbedding(), scope="agent")


def test_semantic_cache_clear_deletes_scoped_keys_without_dropping_index():
    cache = SemanticCache(embedding=DummyEmbedding(), scope="document")
    mock_client = MagicMock()
    mock_client.scan.return_value = (0, [b"query_cache_document:a", b"query_cache_document:b"])
    mock_client.delete.return_value = 2
    cache._client = mock_client

    cleared = cache.clear()

    assert cleared == 2
    mock_client.scan.assert_called_once_with(
        cursor=0,
        match="query_cache_document:*",
        count=200,
    )
    mock_client.delete.assert_called_once_with(
        b"query_cache_document:a",
        b"query_cache_document:b",
    )
    mock_client.execute_command.assert_not_called()


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
         patch("src.handler.PostgresSaver"), \
         patch("src.handler.create_agent") as create_agent:
        handler = ChatbotHandler(semantic_cache=mock_cache)
        answer = handler.invoke(thread_id="t1", question="Apa peran AI Synchrono?")

    assert answer == "Jawaban Cepat dari Cache (>90% conf)"
    mock_cache.get.assert_called_once_with("Apa peran AI Synchrono?")
    assert not mock_cache.set.called
    create_agent.assert_not_called()


def test_handler_direct_faq_miss_synthesizes_from_chunks_and_caches_answer():
    mock_cache = MagicMock(spec=SemanticCache)
    mock_cache.get.return_value = None
    chunks = [{
        "answer": "AI tidak mengubah status padan.",
        "matched_question": "Apakah AI menentukan status padan?",
        "source": "synchrono_platform_faq.md",
        "score": 8.0,
        "content": "FAQ chunk content",
    }]

    with patch("src.handler.ChatOpenAI") as model_cls, \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.create_agent") as create_agent, \
         patch(
             "src.knowledge.faq_service.retrieve_platform_faq_chunks",
             return_value=chunks,
         ):
        model_cls.return_value.invoke.return_value = AIMessage(content="AI tidak mengubah status padan.")
        handler = ChatbotHandler(semantic_cache=mock_cache)
        answer = handler.invoke(thread_id="faq-direct", question="Apa arti status padan dan apakah AI mengubahnya?")

    assert answer == "AI tidak mengubah status padan.\n\nSumber FAQ: synchrono_platform_faq.md"
    mock_cache.get.assert_called_once_with("Apa arti status padan dan apakah AI mengubahnya?")
    mock_cache.set.assert_called_once_with("Apa arti status padan dan apakah AI mengubahnya?", answer)
    model_cls.return_value.invoke.assert_called_once()
    create_agent.assert_not_called()


def test_handler_invoke_database_answer_is_not_semantic_cached():
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
    mock_cache.get.assert_not_called()
    mock_cache.set.assert_not_called()


def _make_document_cache_handler(cached_document_answer=None, active_version=1):
    faq_cache = MagicMock(spec=SemanticCache)
    faq_cache.get.return_value = None
    document_cache = MagicMock(spec=SemanticCache)
    document_cache.get.return_value = cached_document_answer

    with patch("src.handler.ChatOpenAI"), patch("src.handler.TitleGenerator"):
        handler = ChatbotHandler(semantic_cache=faq_cache)

    handler._document_cache = document_cache
    handler._active_document_version = MagicMock(return_value=active_version)
    handler._trace_enabled = False
    handler.title_generator.generate_title = MagicMock(return_value="Judul Uji")
    return handler, faq_cache, document_cache


def test_handler_invoke_document_cache_hit_skips_retrieval():
    handler, faq_cache, document_cache = _make_document_cache_handler("Jawaban dokumen cache")
    handler._lookup_platform_document_chunks = MagicMock()

    with patch("src.handler.create_agent") as create_agent:
        answer = handler.invoke(
            thread_id="doc-cache-hit",
            question="Jelaskan isi dokumen SOP terbaru",
        )

    assert answer == "Jawaban dokumen cache"
    document_cache.get.assert_called_once_with("Jelaskan isi dokumen SOP terbaru")
    document_cache.set.assert_not_called()
    faq_cache.get.assert_not_called()
    handler._lookup_platform_document_chunks.assert_not_called()
    create_agent.assert_not_called()


def test_handler_invoke_document_miss_synthesizes_and_caches_answer():
    handler, faq_cache, document_cache = _make_document_cache_handler(None)
    chunks = [{"content": "Isi SOP", "source": "sop.md", "chunk": 1, "score": 0.9}]
    handler._lookup_platform_document_chunks = MagicMock(return_value=chunks)
    handler._synthesize_document_answer = MagicMock(return_value="Jawaban dokumen sintesis")

    with patch("src.handler.create_agent") as create_agent:
        answer = handler.invoke(
            thread_id="doc-cache-miss",
            question="Jelaskan isi dokumen SOP terbaru",
        )

    assert answer == "Jawaban dokumen sintesis"
    document_cache.get.assert_called_once_with("Jelaskan isi dokumen SOP terbaru")
    document_cache.set.assert_called_once_with(
        "Jelaskan isi dokumen SOP terbaru",
        "Jawaban dokumen sintesis",
        chunks,
    )
    faq_cache.set.assert_not_called()
    create_agent.assert_not_called()


def test_handler_document_cache_disabled_without_active_document_version():
    handler, _, document_cache = _make_document_cache_handler("Jawaban cache lama", active_version=0)
    chunks = [{"content": "Isi SOP", "source": "sop.md", "chunk": 1, "score": 0.9}]
    handler._lookup_platform_document_chunks = MagicMock(return_value=chunks)
    handler._synthesize_document_answer = MagicMock(return_value="Jawaban dokumen baru")

    answer = handler.invoke(
        thread_id="doc-cache-no-active",
        question="Jelaskan isi dokumen SOP terbaru",
    )

    assert answer == "Jawaban dokumen baru"
    document_cache.get.assert_not_called()
    document_cache.set.assert_not_called()


def test_handler_document_not_found_is_not_cached():
    handler, _, document_cache = _make_document_cache_handler(None)
    handler._lookup_platform_document_chunks = MagicMock(return_value=[])

    answer = handler.invoke(
        thread_id="doc-cache-not-found",
        question="Jelaskan isi dokumen SOP terbaru",
    )

    assert "belum menemukan dokumen" in answer
    document_cache.get.assert_called_once()
    document_cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_handler_stream_document_cache_hit_skips_retrieval():
    from contextlib import asynccontextmanager

    handler, faq_cache, document_cache = _make_document_cache_handler("Jawaban dokumen cache streaming")
    handler._lookup_platform_document_chunks = MagicMock()
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = object()
    mock_checkpointer = MagicMock()
    mock_agent = MagicMock()
    mock_agent.aupdate_state = AsyncMock()

    @asynccontextmanager
    async def fake_async_checkpointer():
        yield mock_checkpointer

    with patch("src.handler.SessionLocal", return_value=session), \
         patch("src.handler.create_agent", return_value=mock_agent):
        handler._get_async_checkpointer = fake_async_checkpointer
        events = []
        async for event in handler.stream(
            user_id="u-doc-cache",
            conversation_id="doc-cache-stream",
            question="Jelaskan isi dokumen SOP terbaru",
        ):
            events.append(event)

    payloads = [json.loads(event[6:]) for event in events if event.startswith("data: ")]
    assert any(
        payload.get("step") == "AIMessageChunk"
        and payload.get("content") == "Jawaban dokumen cache streaming"
        for payload in payloads
    )
    document_cache.get.assert_called_once_with("Jelaskan isi dokumen SOP terbaru")
    document_cache.set.assert_not_called()
    faq_cache.get.assert_not_called()
    handler._lookup_platform_document_chunks.assert_not_called()
    mock_agent.aupdate_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_stream_document_miss_synthesizes_and_caches_answer():
    from contextlib import asynccontextmanager

    handler, faq_cache, document_cache = _make_document_cache_handler(None)
    chunks = [{"content": "Isi SOP", "source": "sop.md", "chunk": 1, "score": 0.9}]
    handler._lookup_platform_document_chunks = MagicMock(return_value=chunks)
    handler._synthesize_document_answer = MagicMock(return_value="Jawaban dokumen streaming")
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = object()
    mock_checkpointer = MagicMock()
    mock_agent = MagicMock()
    mock_agent.aupdate_state = AsyncMock()

    @asynccontextmanager
    async def fake_async_checkpointer():
        yield mock_checkpointer

    with patch("src.handler.SessionLocal", return_value=session), \
         patch("src.handler.create_agent", return_value=mock_agent):
        handler._get_async_checkpointer = fake_async_checkpointer
        events = []
        async for event in handler.stream(
            user_id="u-doc-miss",
            conversation_id="doc-miss-stream",
            question="Jelaskan isi dokumen SOP terbaru",
        ):
            events.append(event)

    payloads = [json.loads(event[6:]) for event in events if event.startswith("data: ")]
    assert any(
        payload.get("step") == "AIMessageChunk"
        and payload.get("content") == "Jawaban dokumen streaming"
        for payload in payloads
    )
    document_cache.get.assert_called_once_with("Jelaskan isi dokumen SOP terbaru")
    document_cache.set.assert_called_once_with(
        "Jelaskan isi dokumen SOP terbaru",
        "Jawaban dokumen streaming",
        chunks,
    )
    faq_cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_handler_stream_cache_hit():
    from contextlib import asynccontextmanager

    mock_cache = MagicMock(spec=SemanticCache)
    mock_cache.get.return_value = "Streaming Jawaban dari Cache"
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = object()
    mock_checkpointer = MagicMock()
    mock_agent = MagicMock()
    mock_agent.aupdate_state = AsyncMock()

    @asynccontextmanager
    async def fake_async_checkpointer():
        yield mock_checkpointer

    with patch("src.handler.ChatOpenAI"), \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.SessionLocal", return_value=session), \
         patch("src.handler.create_agent", return_value=mock_agent) as create_agent:
        handler = ChatbotHandler(semantic_cache=mock_cache)
        handler._get_async_checkpointer = fake_async_checkpointer

        events = []
        async for chunk in handler.stream(
            user_id="u1",
            conversation_id="c1",
            question="Apa peran AI Synchrono?",
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
    create_agent.assert_called_once()
    mock_agent.aupdate_state.assert_awaited_once()
    checkpoint_config, checkpoint_values = mock_agent.aupdate_state.call_args.args
    assert checkpoint_config["configurable"]["thread_id"] == "c1"
    assert checkpoint_config["configurable"]["user_id"] == "u1"
    assert [message.content for message in checkpoint_values["messages"]] == [
        "Apa peran AI Synchrono?",
        "Streaming Jawaban dari Cache",
    ]


@pytest.mark.asyncio
async def test_handler_stream_direct_faq_miss_synthesizes_grounded_answer():
    from contextlib import asynccontextmanager

    mock_cache = MagicMock(spec=SemanticCache)
    mock_cache.get.return_value = None
    mock_checkpointer = MagicMock()
    mock_agent = MagicMock()
    mock_agent.aupdate_state = AsyncMock()

    @asynccontextmanager
    async def fake_async_checkpointer():
        yield mock_checkpointer

    faq_chunks = [{
        "answer": "AI menjelaskan alasan data tidak padan.",
        "matched_question": "Apa peran AI Synchrono?",
        "source": "synchrono_platform_faq.md",
        "score": 8.0,
        "content": "FAQ chunk content",
    }]
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = object()

    with patch("src.handler.ChatOpenAI") as model_cls, \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.SessionLocal", return_value=session), \
         patch("src.handler.create_agent", return_value=mock_agent) as create_agent, \
         patch("src.knowledge.faq_service.retrieve_platform_faq_chunks", return_value=faq_chunks):
        model_cls.return_value.invoke.return_value = AIMessage(content="AI dapat menjelaskan alasan data tidak padan.")
        handler = ChatbotHandler(semantic_cache=mock_cache)
        handler._get_async_checkpointer = fake_async_checkpointer
        events = []
        async for event in handler.stream(
            user_id="u-faq",
            conversation_id="faq-direct-thread",
            question="Apa peran AI Synchrono?",
        ):
            events.append(event)

    payloads = [json.loads(event[6:]) for event in events if event.startswith("data: ")]
    assert any(p.get("content", "").startswith("AI dapat menjelaskan alasan") for p in payloads)
    assert model_cls.return_value.invoke.call_count == 1
    assert not mock_agent.astream.called
    mock_agent.aupdate_state.assert_awaited_once()
    mock_cache.get.assert_called_once_with("Apa peran AI Synchrono?")
    mock_cache.set.assert_called_once()
    create_agent.assert_called_once()


@pytest.mark.asyncio
async def test_handler_stream_database_answer_is_not_semantic_cached():
    mock_cache = MagicMock(spec=SemanticCache)
    mock_agent = MagicMock()

    async def fake_astream(*args, **kwargs):
        yield AIMessageChunk(content="Total batch adalah 154."), {"langgraph_node": "model"}

    mock_agent.astream = fake_astream

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_async_checkpointer():
        yield MagicMock()

    with patch("src.handler.ChatOpenAI"), \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.SessionLocal") as session_cls, \
         patch("src.handler.create_agent", return_value=mock_agent):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = object()
        session_cls.return_value = session
        handler = ChatbotHandler(semantic_cache=mock_cache)
        handler._get_async_checkpointer = fake_async_checkpointer

        events = []
        async for event in handler.stream(
            user_id="u1",
            conversation_id="db-live-question",
            question="Berapa total batch berkas?",
        ):
            events.append(event)

    mock_cache.get.assert_not_called()
    mock_cache.set.assert_not_called()


def test_public_service_procedure_is_refused_without_tools_or_cache():
    mock_cache = MagicMock(spec=SemanticCache)
    with patch("src.handler.ChatOpenAI"), patch("src.handler.TitleGenerator"), patch("src.handler.create_agent") as create_agent:
        handler = ChatbotHandler(semantic_cache=mock_cache)
        answer = handler.invoke(thread_id="out-of-scope", question="Apa syarat membuat KTP-el baru?")

    assert "bukan prosedur layanan publik" in answer
    mock_cache.get.assert_not_called()
    mock_cache.set.assert_not_called()
    create_agent.assert_not_called()


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
