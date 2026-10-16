import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey

from src.databases.internal.models.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True
    )
    thread_id = Column(String(150), nullable=False, unique=True, index=True)
    title = Column(String(255), nullable=True)
    connection_id = Column(
        String(36),
        ForeignKey("data_connections.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True
    )
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
