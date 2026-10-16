import json
import pytest
from unittest.mock import MagicMock, patch
from langchain.messages import AIMessage, AIMessageChunk


@pytest.fixture
def mock_conv_db():
    """Mock conv_db calls so tests remain pure unit tests without disk or database access."""
    with patch("src.handler.conv_db") as m_db:
        m_db.conversation_exists.return_value = False
        m_db.get_messages.return_value = []
        m_db.insert_conversation.return_value = None
        m_db.update_conversation_timestamp.return_value = None
        m_db.insert_message.return_value = None
        yield m_db


@pytest.fixture
def handler(mock_conv_db):
    """Instantiate ChatbotHandler with mocked base LLM and title generator."""
    with patch("src.handler.ChatOpenAI") as mock_init:
        mock_init.return_value = MagicMock()
        from src.handler import ChatbotHandler
        h = ChatbotHandler()
        h.title_generator.generate_title = MagicMock(return_value="Percakapan Uji")
        yield h


def test_ask_success(handler, mock_conv_db):
    """Verify ask() returns expected answer and updates conversation record on success."""
    sample_answer = "Total batch file berhasil diproses: 5 berkas."
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"messages": [AIMessage(sample_answer)]}

    with patch.object(handler, "_get_agent", return_value=mock_agent):
        result = handler.invoke(thread_id="t-success-1", question="Berapa berkas?", user_id="u-1")

    assert result == sample_answer
    inserted_roles = [
        call.kwargs.get("role") or (call.args[2] if len(call.args) > 2 else None)
        for call in mock_conv_db.insert_message.call_args_list
    ]
    assert "human" in inserted_roles
    assert "ai" in inserted_roles


def test_ask_failure_reraises(handler, mock_conv_db):
    """Verify ask() logs error and re-raises model failure without persisting fake AI answer."""
    mock_agent = MagicMock()
    mock_agent.invoke.side_effect = RuntimeError("Model provider timeout")

    with patch.object(handler, "_get_agent", return_value=mock_agent):
        with pytest.raises(RuntimeError, match="Model provider timeout"):
            handler.invoke(thread_id="t-fail-1", question="Tampilkan ringkasan", user_id="u-1")

    inserted_roles = [
        call.kwargs.get("role") or (call.args[2] if len(call.args) > 2 else None)
        for call in mock_conv_db.insert_message.call_args_list
    ]
    assert "human" in inserted_roles
    assert "ai" not in inserted_roles


def test_ask_with_trajectory_success(handler, mock_conv_db):
    """Verify ask_with_trajectory() returns trajectory, hop count, and persists conversation."""
    sample_answer = "Semua query berhasil dijalankan."
    tool_chunk = MagicMock()
    tool_chunk.tool_calls = [{"name": "run_query", "args": {"query": "SELECT count(*) FROM files;"}}]
    ai_chunk = AIMessage(sample_answer)

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"messages": [tool_chunk, ai_chunk]}

    with patch.object(handler, "_get_agent", return_value=mock_agent):
        traj = handler.invoke_with_trajectory(thread_id="t-traj-1", question="Cek status", user_id="u-1")

    assert traj["answer"] == sample_answer
    assert traj["hop_count"] == 1
    assert traj["tool_calls"] == [{"name": "run_query", "args": {"query": "SELECT count(*) FROM files;"}}]
    assert traj["thread_id"] == "t-traj-1"

    inserted_roles = [
        call.kwargs.get("role") or (call.args[2] if len(call.args) > 2 else None)
        for call in mock_conv_db.insert_message.call_args_list
    ]
    assert "human" in inserted_roles
    assert "ai" in inserted_roles


def test_ask_with_trajectory_failure_reraises(handler, mock_conv_db):
    """Verify ask_with_trajectory() re-raises exceptions without fake AI persistence."""
    mock_agent = MagicMock()
    mock_agent.invoke.side_effect = ValueError("Rate limit reached")

    with patch.object(handler, "_get_agent", return_value=mock_agent):
        with pytest.raises(ValueError, match="Rate limit reached"):
            handler.invoke_with_trajectory(thread_id="t-traj-fail", question="Cek status", user_id="u-1")

    inserted_roles = [
        call.kwargs.get("role") or (call.args[2] if len(call.args) > 2 else None)
        for call in mock_conv_db.insert_message.call_args_list
    ]
    assert "human" in inserted_roles
    assert "ai" not in inserted_roles


@pytest.mark.asyncio
async def test_stream_success(handler, mock_conv_db):
    """Verify stream() emits START, TITLE, TOOL_CALL, AIMessageChunk, and END on successful run."""
    mock_agent = MagicMock()

    async def sample_astream(*args, **kwargs):
        yield AIMessageChunk(content="", tool_calls=[{"name": "get_schemas", "args": {}, "id": "call_1"}]), {"langgraph_node": "agent"}
        yield AIMessageChunk(content="Analisis "), {"langgraph_node": "agent"}
        yield AIMessageChunk(content="selesai."), {"langgraph_node": "agent"}

    mock_agent.astream = sample_astream

    with patch.object(handler, "_get_agent", return_value=mock_agent):
        events = []
        async for chunk in handler.stream(user_id="u-1", conversation_id="t-stream-ok", question="Bantu cek"):
            events.append(chunk)

    parsed_steps = []
    for ev in events:
        if ev.startswith("data: "):
            payload = json.loads(ev[6:].strip())
            parsed_steps.append(payload.get("step"))

    assert "START" in parsed_steps
    assert "TITLE" in parsed_steps
    assert "TOOL_CALL" in parsed_steps
    assert "AIMessageChunk" in parsed_steps
    assert "END" in parsed_steps

    ai_calls = [
        call for call in mock_conv_db.insert_message.call_args_list
        if (call.kwargs.get("role") == "ai" or (len(call.args) > 2 and call.args[2] == "ai"))
    ]
    assert len(ai_calls) == 1


@pytest.mark.asyncio
async def test_stream_failure_during_astream(handler, mock_conv_db):
    """Verify stream() failure yields ERROR, stops without END, and does not persist AI answer."""
    mock_agent = MagicMock()

    async def failing_astream(*args, **kwargs):
        yield AIMessageChunk(content="Mulai "), {"langgraph_node": "agent"}
        raise RuntimeError("LLM stream disconnected unexpectedly")

    mock_agent.astream = failing_astream

    with patch.object(handler, "_get_agent", return_value=mock_agent):
        events = []
        async for chunk in handler.stream(user_id="u-1", conversation_id="t-stream-err", question="Koneksi terputus"):
            events.append(chunk)

    parsed_steps = []
    error_payload = None
    for ev in events:
        if ev.startswith("data: "):
            payload = json.loads(ev[6:].strip())
            parsed_steps.append(payload.get("step"))
            if payload.get("step") == "ERROR":
                error_payload = payload

    assert "START" in parsed_steps
    assert "AIMessageChunk" in parsed_steps
    assert "ERROR" in parsed_steps
    assert "END" not in parsed_steps
    assert error_payload is not None
    assert "Maaf, terjadi kendala saat memproses respons AI." in error_payload["content"]
    assert "LLM stream disconnected unexpectedly" not in error_payload["content"]

    ai_calls = [
        call for call in mock_conv_db.insert_message.call_args_list
        if (call.kwargs.get("role") == "ai" or (len(call.args) > 2 and call.args[2] == "ai"))
    ]
    assert len(ai_calls) == 0


@pytest.mark.asyncio
async def test_stream_failure_during_get_agent(handler, mock_conv_db):
    """Verify stream() failure during _get_agent yields ERROR and stops without END or AI save."""
    with patch.object(handler, "_get_agent", side_effect=RuntimeError("Agent creation failed")):
        events = []
        async for chunk in handler.stream(user_id="u-1", conversation_id="t-stream-agent-err", question="Test"):
            events.append(chunk)

    parsed_steps = []
    for ev in events:
        if ev.startswith("data: "):
            payload = json.loads(ev[6:].strip())
            parsed_steps.append(payload.get("step"))

    assert "START" in parsed_steps
    assert "ERROR" in parsed_steps
    assert "END" not in parsed_steps

    ai_calls = [
        call for call in mock_conv_db.insert_message.call_args_list
        if (call.kwargs.get("role") == "ai" or (len(call.args) > 2 and call.args[2] == "ai"))
    ]
    assert len(ai_calls) == 0
