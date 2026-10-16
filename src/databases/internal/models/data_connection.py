from sqlalchemy import Column, String

from src.databases.internal.models.base import Base


class DataConnection(Base):
    __tablename__ = "data_connections"

    id = Column(String(36), primary_key=True)
