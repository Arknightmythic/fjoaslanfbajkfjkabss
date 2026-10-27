import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from langchain.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from src.handler import ChatbotHandler
from src.middlewares.pii import PIIMiddleware, PIIStreamSanitizer


def test_before_model_masks_user_and_database_tool_messages():
    middleware = PIIMiddleware()
    state = {
        "messages": [
            HumanMessage("Cari NIK 3171012345678901"),
            ToolMessage("Row from database: 3271019876543210", tool_call_id="db-1"),
        ]
    }

    result = middleware.before_model(state, runtime=None)

    assert result is not None
    assert "3171012345678901" not in result["messages"][0].content
    assert "*************901" in result["messages"][0].content
    assert "3271019876543210" not in result["messages"][1].content
    assert "*************210" in result["messages"][1].content


def test_stream_sanitizer_handles_nik_split_across_model_chunks():
    sanitizer = PIIStreamSanitizer(PIIMiddleware())
    result = "".join([
        sanitizer.feed("Data NIK 31710123"),
        sanitizer.feed("45678901 ditemukan"),
        sanitizer.feed(".", final=True),
    ])

    assert "3171012345678901" not in result
    assert "*************901" in result


def test_handler_masks_question_before_cache_lookup_and_cache_answer_before_return():
    cache = MagicMock()
    cache.get.return_value = "NIK ditemukan: 3271019876543210"
    with patch("src.handler.ChatOpenAI"), patch("src.handler.TitleGenerator"):
        handler = ChatbotHandler(semantic_cache=cache)

    answer = handler.invoke(
        thread_id="pii-test",
        question="Apa peran AI Synchrono?",
        enable_pii=True,
    )

    lookup_question = cache.get.call_args.args[0]
    assert lookup_question == "Apa peran AI Synchrono?"
    assert "3271019876543210" not in answer
    assert "*************210" in answer


def test_dynamic_question_with_nik_bypasses_faq_cache():
    cache = MagicMock()
    with patch("src.handler.ChatOpenAI"), \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.create_agent") as create_agent, \
         patch("src.handler.PostgresSaver"):
        agent = MagicMock()
        agent.invoke.return_value = {"messages": [AIMessage(content="Informasi tidak ditemukan.")]}
        create_agent.return_value = agent
        handler = ChatbotHandler(semantic_cache=cache, checkpointer=MagicMock())
        handler.invoke(
            thread_id="pii-test-off",
            question="Cari batch berdasarkan NIK 3171012345678901",
            enable_pii=True,
        )

    cache.get.assert_not_called()
    cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_stream_masks_request_before_storage_and_masks_split_model_output():
    cache = MagicMock()
    cache.get.return_value = None
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = object()
    mock_agent = MagicMock()

    async def fake_astream(input_state, **kwargs):
        assert input_state["messages"][0].content == "Tolong tampilkan NIK *************901"
        yield ToolMessage(content="Database row includes NIK 3271019876543210", tool_call_id="db-1"), {"langgraph_node": "tools"}
        yield AIMessageChunk(content="NIK 31710123"), {"langgraph_node": "model"}
        yield AIMessageChunk(content="45678901 ditemukan"), {"langgraph_node": "model"}

    mock_agent.astream = fake_astream

    @asynccontextmanager
    async def fake_checkpointer():
        yield MagicMock()

    with patch("src.handler.ChatOpenAI"), \
         patch("src.handler.TitleGenerator"), \
         patch("src.handler.SessionLocal", return_value=session), \
         patch("src.handler.create_agent", return_value=mock_agent):
        handler = ChatbotHandler(semantic_cache=cache)
        handler._get_async_checkpointer = fake_checkpointer

        events = []
        async for event in handler.stream(
            user_id="qa-user",
            conversation_id="pii-stream-test",
            question="Tolong tampilkan NIK 3171012345678901",
            enable_pii=True,
        ):
            events.append(event)

    wire = "".join(events)
    assert "3171012345678901" not in wire
    assert "3271019876543210" not in wire
    parsed = [json.loads(line[6:]) for line in wire.splitlines() if line.startswith("data: ")]
    streamed_text = "".join(event.get("content", "") for event in parsed)
    assert "*************901" in streamed_text
    assert "*************210" in streamed_text
    stored_messages = [call.args[0].content for call in session.add.call_args_list]
    assert any("Tolong tampilkan NIK *************901" == text for text in stored_messages)
    assert all("3171012345678901" not in text for text in stored_messages)
    cache.get.assert_not_called()
    cache.set.assert_not_called()
