from sqlalchemy import Column, Integer, String, Text

from src.databases.internal.models.base import Base


class ManualMatch(Base):
    __tablename__ = "manual_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(64), nullable=False)
    id_incoming = Column(Text, nullable=False)
    nama_incoming = Column(Text)
    tempat_lahir_incoming = Column(Text)
    tanggal_lahir_incoming = Column(Text)
    jenis_kelamin_incoming = Column(Text)
    nama_ibu_incoming = Column(Text)
    reason = Column(Text)
    pattern_name = Column(String(255))
    reasoning_status = Column(String(30), nullable=False)
