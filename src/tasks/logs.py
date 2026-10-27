"""Celery jobs for archiving chatbot logs."""

from datetime import date
from typing import Optional

from celery.utils.log import get_task_logger

from src.celery_app import celery_app
from src.observability.log_archiver import archive_daily_log
from src.time_utils import now_wib

logger = get_task_logger(__name__)


def _archive_with_retry(task, target_date: Optional[date]) -> dict:
    logger.info("Starting daily chat log archive for target_date=%s", target_date)
    try:
        return archive_daily_log(target_date)
    except Exception as exc:
        logger.exception("Daily chat log archive failed")
        if task.request.retries < task.max_retries:
            raise task.retry(exc=exc, countdown=min(60 * (2 ** task.request.retries), 900))
        raise


@celery_app.task(
    bind=True,
    name="src.tasks.logs.archive_daily_chat_log",
    max_retries=3,
    acks_late=True,
)
def archive_daily_chat_log(self, target_date: Optional[str] = None) -> dict:
    parsed = date.fromisoformat(target_date) if target_date else None
    return _archive_with_retry(self, parsed)


@celery_app.task(
    bind=True,
    name="src.tasks.logs.archive_current_day_chat_log",
    max_retries=3,
    acks_late=True,
)
def archive_current_day_chat_log(self) -> dict:
    return _archive_with_retry(self, now_wib().date())
