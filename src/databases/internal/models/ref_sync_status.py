from sqlalchemy import Column, Integer, String

from src.databases.internal.models.base import Base


class RefSyncStatus(Base):
    __tablename__ = "ref_sync_statuses"

    sync_status_id = Column(Integer, primary_key=True)
    status_code = Column(String(20), nullable=False)
