import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, text

from src.databases.internal.models.base import Base


class KnowledgeDocument(Base):
    """Uploaded source document and asynchronous RAG ingestion status."""

    __tablename__ = "knowledge_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    original_filename = Column(Text, nullable=False)
    object_key = Column(Text, nullable=False, unique=True)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False, index=True)
    source_type = Column(String(20), nullable=False, default="faq", server_default=text("'faq'"), index=True)
    version_number = Column(Integer, nullable=False, default=1, server_default=text("1"))
    status = Column(String(20), nullable=False, default="uploaded", index=True)
    celery_task_id = Column(String(100), nullable=True, index=True)
    retry_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    chunk_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
    completed_at = Column(DateTime, nullable=True)
