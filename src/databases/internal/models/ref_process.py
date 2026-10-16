from sqlalchemy import Column, Integer, String

from src.databases.internal.models.base import Base


class RefProcess(Base):
    __tablename__ = "ref_process"

    process_id = Column(Integer, primary_key=True, nullable=True)
    process_name = Column(String(20), nullable=False)
