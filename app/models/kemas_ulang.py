"""Perpindahan kemasan; kemasan lama tetap habis, pemilik tidak berubah."""
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, Numeric, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class KemasUlang(Base):
    __tablename__ = 'kemas_ulang'
    id: Mapped[int] = mapped_column(primary_key=True)
    kunci: Mapped[str] = mapped_column(String(64), unique=True)
    sidik: Mapped[str] = mapped_column(String(64))
    sumber_id: Mapped[int] = mapped_column(ForeignKey('finished_goods_stock.id'))
    sku_asal_id: Mapped[int] = mapped_column(ForeignKey('product_skus.id'))
    sku_baru_id: Mapped[int] = mapped_column(ForeignKey('product_skus.id'))
    jasa_id: Mapped[int | None] = mapped_column(ForeignKey('jasa.id'))
    karung_dibuka: Mapped[int] = mapped_column(Integer)
    karung_lama_dihitung: Mapped[int] = mapped_column(Integer)
    berat_asal_kg: Mapped[float] = mapped_column(Numeric(12,2))
    karung_baru: Mapped[int] = mapped_column(Integer)
    berat_baru_kg: Mapped[float] = mapped_column(Numeric(12,2))
    sisa_kg: Mapped[float] = mapped_column(Numeric(12,2))
    petugas_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True))
