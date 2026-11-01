from src.celery_app import LOG_QUEUE, celery_app, log_queue

LOG_TASKS = ("src.tasks.logs.archive_daily_chat_log", "src.tasks.logs.archive_current_day_chat_log")


def test_log_queue_defaults_to_document_queue(monkeypatch):
    monkeypatch.delenv("CHATBOT_LOG_QUEUE", raising=False)
    assert log_queue() == "document_ingest"
    monkeypatch.setenv("CHATBOT_LOG_QUEUE", "  ")
    assert log_queue() == "document_ingest"


def test_log_queue_follows_chatbot_log_queue(monkeypatch):
    monkeypatch.setenv("CHATBOT_LOG_QUEUE", "chatbot_logs")
    assert log_queue() == "chatbot_logs"


def test_only_log_archive_tasks_use_the_log_queue():
    routes = celery_app.conf.task_routes
    for task in LOG_TASKS:
        assert routes[task] == {"queue": LOG_QUEUE}
    assert routes["src.tasks.documents.ingest_uploaded_document"] == {"queue": "document_ingest"}
