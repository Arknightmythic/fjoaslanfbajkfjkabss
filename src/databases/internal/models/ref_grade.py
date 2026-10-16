from sqlalchemy import Column, Integer, String

from src.databases.internal.models.base import Base


class RefGrade(Base):
    __tablename__ = "ref_grades"

    grade_id = Column(Integer, primary_key=True, nullable=True)
    grade_code = Column(String(10), nullable=False)
