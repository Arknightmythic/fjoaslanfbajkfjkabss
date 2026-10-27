"""Persist AI answer quality metrics for later review."""

import math
from typing import Optional

from loguru import logger

from src.databases.internal.config import SessionLocal
from src.databases.internal.models import AnswerAudit
from src.time_utils import format_wib_timestamp, now_wib


def confidence_from_retrieval_score(score: Optional[float]) -> Optional[float]:
    """Map a raw reranker logit to a bounded 0..1 confidence score."""
    if score is None:
        return None
    bounded = max(-60.0, min(60.0, float(score)))
    return round(1.0 / (1.0 + math.exp(-bounded)), 6)


def record_answer_audit(
    *,
    user_id: Optional[str],
    thread_id: Optional[str],
    route: str,
    question: str,
    answer: str,
    retrieval_score: Optional[float] = None,
    source_count: Optional[int] = None,
) -> None:
    """Write one audit row without allowing telemetry failures to break chat."""
    session = None
    created_at = now_wib()
    try:
        session = SessionLocal()
        session.add(
            AnswerAudit(
                user_id=user_id,
                thread_id=thread_id,
                route=route,
                question=question,
                answer=answer,
                confidence_score=confidence_from_retrieval_score(retrieval_score),
                retrieval_score=retrieval_score,
                source_count=source_count,
                created_at=created_at,
                created_at_wib=format_wib_timestamp(created_at),
            )
        )
        session.commit()
    except Exception as exc:
        if session is not None:
            session.rollback()
        logger.warning(f"[AnswerAudit] Could not persist answer audit: {exc}")
    finally:
        if session is not None:
            session.close()
