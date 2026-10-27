import json
from unittest.mock import MagicMock, patch

import pytest
from langchain.messages import AIMessage

from src.handler import ChatbotHandler


def make_handler(cached_answer=None):
    cache = MagicMock()
    cache.get.return_value = cached_answer

    with patch("src.handler.ChatOpenAI") as chat_openai:
        chat_openai.return_value = MagicMock()
        handler = ChatbotHandler(semantic_cache=cache, checkpointer=object())

    handler.title_generator.generate_title = MagicMock(return_value="Judul Uji")
    handler._trace_enabled = False
    return handler, cache


def test_invoke_agent_returns_answer():
    handler, _ = make_handler()
    fake_agent = MagicMock()
    fake_agent.invoke.return_value = {"messages": [AIMessage("Jawaban agent")]}

    with patch("src.handler.create_agent", return_value=fake_agent) as create_agent:
        result = handler.invoke(
            thread_id="thread-agent-1",
            question="Tampilkan ringkasan batch terbaru",
            user_id="user-1",
        )

    assert result == "Jawaban agent"
    create_agent.assert_called_once()


def test_invoke_agent_failure_propagates():
    handler, _ = make_handler()
    fake_agent = MagicMock()
    fake_agent.invoke.side_effect = RuntimeError("Model provider timeout")

    with patch("src.handler.create_agent", return_value=fake_agent):
        with pytest.raises(RuntimeError, match="Model provider timeout"):
            handler.invoke(
                thread_id="thread-agent-err",
                question="Tampilkan ringkasan batch terbaru",
                user_id="user-1",
            )


def test_invoke_rejects_out_of_scope_public_service_question():
    handler, cache = make_handler()

    with patch("src.handler.create_agent") as create_agent:
        result = handler.invoke(
            thread_id="thread-scope",
            question="Apa syarat mengurus KTP-el?",
            user_id="user-1",
        )

    assert "bukan prosedur layanan publik" in result
    create_agent.assert_not_called()
    cache.get.assert_not_called()


def test_invoke_faq_cache_hit_skips_retrieval_and_agent(monkeypatch):
    handler, cache = make_handler(cached_answer="Jawaban dari cache")
    handler._lookup_platform_faq_chunks = MagicMock()

    with patch("src.handler.create_agent") as create_agent:
        result = handler.invoke(
            thread_id="thread-faq-cache",
            question="Apa peran AI Synchrono?",
            user_id="user-1",
        )

    assert result == "Jawaban dari cache"
    cache.get.assert_called_once()
    handler._lookup_platform_faq_chunks.assert_not_called()
    create_agent.assert_not_called()


def test_invoke_faq_miss_synthesizes_answer_and_populates_cache():
    handler, cache = make_handler(cached_answer=None)
    chunks = [
        {
            "source": "synchrono_platform_faq.md",
            "matched_question": "Apa peran AI Synchrono?",
            "answer": "AI menjelaskan dan merekomendasikan.",
        }
    ]
    handler._lookup_platform_faq_chunks = MagicMock(return_value=chunks)
    handler._synthesize_faq_answer = MagicMock(return_value="Jawaban sintesis FAQ")

    with patch("src.handler.create_agent") as create_agent:
        result = handler.invoke(
            thread_id="thread-faq-miss",
            question="Apa peran AI Synchrono?",
            user_id="user-1",
        )

    assert result == "Jawaban sintesis FAQ"
    handler._lookup_platform_faq_chunks.assert_called_once()
    cache.set.assert_called_once_with("Apa peran AI Synchrono?", "Jawaban sintesis FAQ")
    create_agent.assert_not_called()


def test_invoke_faq_records_answer_audit(monkeypatch):
    monkeypatch.setenv("CHATBOT_ANSWER_AUDIT_ENABLED", "true")
    handler, _ = make_handler(cached_answer=None)
    handler._lookup_platform_faq_chunks = MagicMock(
        return_value=[
            {
                "source": "synchrono_platform_faq.md",
                "matched_question": "Apa peran AI Synchrono?",
                "answer": "AI menjelaskan dan merekomendasikan.",
                "score": 2.0,
            }
        ]
    )
    handler._synthesize_faq_answer = MagicMock(return_value="Jawaban sintesis FAQ")

    with patch("src.handler.record_answer_audit") as audit:
        handler.invoke(
            thread_id="thread-faq-audit",
            question="Apa peran AI Synchrono?",
            user_id="user-1",
        )

    audit.assert_called_once()
    kwargs = audit.call_args.kwargs
    assert kwargs["route"] == "faq_synthesized"
    assert kwargs["thread_id"] == "thread-faq-audit"
    assert kwargs["user_id"] == "user-1"
    assert kwargs["retrieval_score"] == 2.0
    assert kwargs["source_count"] == 1


def test_invoke_faq_without_chunks_returns_not_found_message():
    handler, cache = make_handler(cached_answer=None)
    handler._lookup_platform_faq_chunks = MagicMock(return_value=[])

    result = handler.invoke(
        thread_id="thread-faq-empty",
        question="Apa peran AI Synchrono?",
        user_id="user-1",
    )

    assert result == "Saya belum menemukan FAQ Synchrono yang cukup relevan untuk menjawab pertanyaan itu."
    cache.set.assert_not_called()


def test_invoke_document_content_uses_document_answer():
    handler, cache = make_handler(cached_answer=None)
    handler._lookup_platform_document_chunks = MagicMock(
        return_value=[{"content": "Isi SOP", "source": "sop.md", "chunk": 1, "score": 0.9}]
    )
    handler._synthesize_document_answer = MagicMock(return_value="Jawaban dari dokumen")

    with patch("src.handler.create_agent") as create_agent:
        result = handler.invoke(
            thread_id="thread-document",
            question="Jelaskan isi dokumen SOP terbaru",
            user_id="user-1",
        )

    assert result == "Jawaban dari dokumen"
    handler._lookup_platform_document_chunks.assert_called_once()
    handler._synthesize_document_answer.assert_called_once()
    cache.set.assert_not_called()
    create_agent.assert_not_called()


def test_invoke_document_question_without_chunks_returns_not_found_message():
    handler, _ = make_handler(cached_answer=None)
    handler._lookup_platform_document_chunks = MagicMock(return_value=[])

    with patch("src.handler.create_agent") as create_agent:
        result = handler.invoke(
            thread_id="thread-document-empty",
            question="Jelaskan isi dokumen SOP terbaru",
            user_id="user-1",
        )

    assert result == "Saya belum menemukan dokumen yang cukup relevan untuk menjawab pertanyaan itu."
    create_agent.assert_not_called()


@pytest.mark.asyncio
async def test_stream_document_question_emits_grounded_answer(monkeypatch):
    handler, cache = make_handler(cached_answer=None)
    handler._lookup_platform_document_chunks = MagicMock(
        return_value=[{"content": "Isi SOP", "source": "sop.md", "chunk": 1, "score": 0.9}]
    )
    handler._synthesize_document_answer = MagicMock(return_value="Jawaban dokumen streaming")

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    monkeypatch.setattr("src.handler.SessionLocal", lambda: db)

    checkpointed = []

    class FakeAgent:
        async def aupdate_state(self, config, state):
            checkpointed.append((config, state))

    with patch("src.handler.create_agent", return_value=FakeAgent()):
        events = []
        async for event in handler.stream(
            user_id="user-1",
            conversation_id="thread-document-stream",
            question="Jelaskan isi dokumen SOP terbaru",
        ):
            events.append(event)

    payloads = [json.loads(event[6:].strip()) for event in events if event.startswith("data: ")]
    assert payloads[0]["step"] == "START"
    assert any(
        payload["step"] == "AIMessageChunk" and payload["content"] == "Jawaban dokumen streaming"
        for payload in payloads
    )
    assert payloads[-1]["step"] == "END"
    cache.get.assert_not_called()
    handler._lookup_platform_document_chunks.assert_called_once()
    assert len(checkpointed) == 1


@pytest.mark.asyncio
async def test_stream_faq_cache_hit_emits_answer_without_retrieval(monkeypatch):
    handler, cache = make_handler(cached_answer="Jawaban cache streaming")
    handler._lookup_platform_faq_chunks = MagicMock()

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    monkeypatch.setattr("src.handler.SessionLocal", lambda: db)

    checkpointed = []

    class FakeAgent:
        async def aupdate_state(self, config, state):
            checkpointed.append((config, state))

    with patch("src.handler.create_agent", return_value=FakeAgent()):
        events = []
        async for event in handler.stream(
            user_id="user-1",
            conversation_id="thread-faq-stream",
            question="Apa peran AI Synchrono?",
        ):
            events.append(event)

    payloads = [json.loads(event[6:].strip()) for event in events if event.startswith("data: ")]
    assert payloads[0]["step"] == "START"
    assert any(
        payload["step"] == "AIMessageChunk" and payload["content"] == "Jawaban cache streaming"
        for payload in payloads
    )
    assert payloads[-1]["step"] == "END"
    cache.get.assert_called_once()
    handler._lookup_platform_faq_chunks.assert_not_called()
    assert len(checkpointed) == 1
