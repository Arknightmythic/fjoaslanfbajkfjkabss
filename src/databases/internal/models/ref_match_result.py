from sqlalchemy import Column, Integer, String

from src.databases.internal.models.base import Base


class RefMatchResult(Base):
    __tablename__ = "ref_match_results"

    match_result_id = Column(Integer, primary_key=True)
    match_result_name = Column(String(20), nullable=False)
