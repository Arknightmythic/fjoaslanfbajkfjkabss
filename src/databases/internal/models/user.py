from sqlalchemy import Column, String

from src.databases.internal.models.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
