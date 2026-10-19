"""Draf pribadi belum merupakan perintah, reservasi, atau pergerakan stok."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class DrafKeluar(Base):
    __tablename__ = 'draf_keluar'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pemilik_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    isi: Mapped[dict] = mapped_column(JSON, nullable=False)
    revisi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kiriman: Mapped[str | None] = mapped_column(String(36))
    sidik: Mapped[str | None] = mapped_column(String(64))
    perintah_id: Mapped[int | None] = mapped_column(ForeignKey('outgoing_records.id'), unique=True)
    diperbarui: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
