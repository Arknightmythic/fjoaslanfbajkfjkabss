from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, text, true

from src.databases.internal.models.base import Base


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    file_id = Column(String(64), primary_key=True)
    original_filename = Column(Text, nullable=False)
    institution_name = Column(Text, nullable=False)
    parquet_path = Column(Text, nullable=False)
    upload_timestamp = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    row_count = Column(Integer)
    grade = Column(Integer, ForeignKey("ref_grades.grade_id"))
    processing_status = Column(Integer)
    sync_status = Column(Integer, ForeignKey("ref_sync_statuses.sync_status_id"))
    is_sync = Column(Boolean, server_default=true())
    matching_task_status = Column(String(20), server_default=text("'SUCCESS'"))
    reasoning_task_status = Column(String(20), server_default=text("'SUCCESS'"))
    preview_url = Column(Text)
    investigate_url = Column(Text)
