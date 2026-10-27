import math
from unittest.mock import MagicMock, patch

from src.observability.answer_audit import (
    confidence_from_retrieval_score,
    record_answer_audit,
)


def test_confidence_score_is_sigmoid_of_raw_retrieval_score():
    assert confidence_from_retrieval_score(None) is None
    assert confidence_from_retrieval_score(0.0) == 0.5
    expected = round(1.0 / (1.0 + math.exp(-2.0)), 6)
    assert confidence_from_retrieval_score(2.0) == expected


def test_record_answer_audit_persists_scores_and_timestamp():
    session = MagicMock()

    with patch("src.observability.answer_audit.SessionLocal", return_value=session):
        record_answer_audit(
            user_id="user-1",
            thread_id="thread-1",
            route="faq_synthesized",
            question="Apa itu Grade A?",
            answer="Grade A adalah kualitas terbaik.",
            retrieval_score=2.0,
            source_count=1,
        )

    audit = session.add.call_args.args[0]
    assert audit.user_id == "user-1"
    assert audit.thread_id == "thread-1"
    assert audit.route == "faq_synthesized"
    assert audit.question == "Apa itu Grade A?"
    assert audit.answer == "Grade A adalah kualitas terbaik."
    assert audit.retrieval_score == 2.0
    assert audit.source_count == 1
    assert audit.confidence_score == 0.880797
    assert audit.created_at.utcoffset().total_seconds() == 7 * 3600
    import re
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$", audit.created_at_wib)
    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_record_answer_audit_failure_does_not_raise():
    session = MagicMock()
    session.commit.side_effect = RuntimeError("database unavailable")

    with patch("src.observability.answer_audit.SessionLocal", return_value=session):
        record_answer_audit(
            user_id="user-1",
            thread_id="thread-1",
            route="agent",
            question="Halo",
            answer="Hai",
        )

    session.rollback.assert_called_once()
    session.close.assert_called_once()
