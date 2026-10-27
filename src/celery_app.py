import os

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

celery_app = Celery(
    "synchrono_chatbot",
    broker=os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/1"),
    include=["src.tasks.documents", "src.tasks.logs"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Jakarta",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_ignore_result=True,
    task_default_queue="document_ingest",
    task_routes={
        "src.tasks.documents.ingest_uploaded_document": {"queue": "document_ingest"},
        "src.tasks.logs.archive_daily_chat_log": {"queue": "document_ingest"},
        "src.tasks.logs.archive_current_day_chat_log": {"queue": "document_ingest"},
    },
    beat_schedule={
        "archive-current-day-chat-log": {
            "task": "src.tasks.logs.archive_current_day_chat_log",
            "schedule": crontab(hour=23, minute=0),
        },
        "archive-daily-chat-log": {
            "task": "src.tasks.logs.archive_daily_chat_log",
            "schedule": crontab(hour=0, minute=5),
        },
    },
)
