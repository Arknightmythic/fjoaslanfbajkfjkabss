from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, text

from src.databases.internal.models.base import Base


class Institution(Base):
    __tablename__ = "institution"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(64), nullable=False)
    id_incoming = Column(Text, nullable=False)
    nama_incoming = Column(Text)
    tempat_lahir_incoming = Column(Text)
    tanggal_lahir_incoming = Column(Text)
    jenis_kelamin_incoming = Column(Text)
    nama_ibu_incoming = Column(Text)
    match_result = Column(Integer, ForeignKey("ref_match_results.match_result_id"))
    match_score = Column(Float, server_default=text("0.0"))
