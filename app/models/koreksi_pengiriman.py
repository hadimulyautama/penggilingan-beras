"""Jejak tambah-saja; outgoing_items tetap menjadi proyeksi efektif stok lama."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class KoreksiPengiriman(Base):
    __tablename__ = 'koreksi_pengiriman'
    __table_args__ = (UniqueConstraint('outgoing_record_id', 'versi', name='uq_koreksi_pengiriman_versi'),)
    kunci: Mapped[str] = mapped_column(String(64), primary_key=True)
    outgoing_record_id: Mapped[int] = mapped_column(ForeignKey('outgoing_records.id'), index=True)
    versi: Mapped[int] = mapped_column()
    sidik_input: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    input_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True))
