from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.routers import chat
from src.api.server import app
from src.messages import GENERIC_FALLBACK_MESSAGE

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "synchrono-chatbot"}


def test_docs_and_openapi_are_available():
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_static_ui_and_investigate_pages_are_served():
    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers.get("content-type", "")

    assert client.get("/static/style.css").status_code == 200
    assert client.get("/batch-synchronization/investigate").status_code == 200


def test_chat_endpoint_streams_sse_events():
    async def fake_stream(**_kwargs):
        yield 'data: {"step": "START", "content": ""}\n\n'
        yield 'data: {"step": "AIMessageChunk", "content": "Halo"}\n\n'
        yield 'data: {"step": "END", "content": ""}\n\n'

    with patch.object(chat.chatbot_handler, "stream", side_effect=fake_stream) as stream:
        response = client.post(
            "/chat",
            json={
                "user_id": "user-1",
                "thread_id": "thread-1",
                "question": "Halo",
            },
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert '"step": "START"' in response.text
    assert '"content": "Halo"' in response.text
    stream.assert_called_once()
    assert stream.call_args.kwargs["conversation_id"] == "thread-1"


def test_chat_endpoint_emits_error_fallback_on_unhandled_stream_exception():
    async def failing_stream(**_kwargs):
        yield 'data: {"step": "START", "content": ""}\n\n'
        raise RuntimeError("boom")

    with patch.object(chat.chatbot_handler, "stream", side_effect=failing_stream):
        response = client.post(
            "/chat",
            json={
                "user_id": "user-1",
                "thread_id": "thread-1",
                "question": "Halo",
            },
        )

    assert response.status_code == 200
    assert '"step": "ERROR"' in response.text
    assert GENERIC_FALLBACK_MESSAGE in response.text


def test_chat_endpoint_validates_required_fields():
    response = client.post("/chat", json={"user_id": "user-1"})

    assert response.status_code == 422


def test_ingest_from_server_path_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("KNOWLEDGE_INGEST_FILE_ENABLED", raising=False)

    response = client.post("/api/v1/ingest/file", json={"file_path": "/proc/self/environ"})

    assert response.status_code == 403
    assert "/api/v1/knowledge/documents" in response.json()["detail"]
