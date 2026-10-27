from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, text

from src.databases.internal.models.base import Base


class KnowledgeIndexState(Base):
    """Per-source-type pointer for atomic activation of an ingested snapshot."""

    __tablename__ = "knowledge_index_state"

    source_type = Column(String(20), primary_key=True)
    active_version = Column(Integer, nullable=False, default=0, server_default=text("0"))
    next_version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
