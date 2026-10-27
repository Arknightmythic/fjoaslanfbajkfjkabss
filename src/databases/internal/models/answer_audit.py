import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, text

from src.databases.internal.models.base import Base
from src.time_utils import format_wib_timestamp, now_wib


class AnswerAudit(Base):
    """Audit trail for AI-generated answers and their retrieval confidence."""

    __tablename__ = "answer_audits"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=True, index=True)
    thread_id = Column(String(100), nullable=True, index=True)
    route = Column(String(50), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    confidence_score = Column(Float, nullable=True)
    retrieval_score = Column(Float, nullable=True)
    source_count = Column(Integer, nullable=True)
    created_at_wib = Column(
        String(40),
        nullable=False,
        default=format_wib_timestamp,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=now_wib,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )
