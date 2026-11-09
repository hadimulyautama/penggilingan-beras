"""Identitas sampel beras tidak bergantung pada hasil timbang atau merek."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SampelQcSosoh(Base):
    __tablename__ = "sampel_qc_sosoh"
    __table_args__ = (
        Index("ix_sampel_qc_sosoh_proses_waktu", "polishing_process_id", "waktu_sampel", "id"),
        UniqueConstraint("polishing_process_id", "kunci_kiriman", name="uq_sampel_sosoh_kiriman"),
        CheckConstraint("hasil_pada IS NULL OR hasil_pada >= waktu_sampel", name="ck_sampel_sosoh_waktu"),
        *(CheckConstraint(f"{kolom} BETWEEN 0 AND 100", name=f"ck_sampel_sosoh_{kolom}")
          for kolom in ("kadar_air", "broken_persen")),
        *(CheckConstraint(f"{kolom} >= 0", name=f"ck_sampel_sosoh_{kolom}")
          for kolom in ("md", "transparant", "whiteness")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    polishing_process_id: Mapped[int] = mapped_column(ForeignKey("polishing_process.id"), nullable=False)
    jenis: Mapped[str] = mapped_column(String(20), nullable=False)
    kunci_kiriman: Mapped[str | None] = mapped_column(String(80))
    waktu_sampel: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dicatat_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pengambil_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Waktu pemeriksaan disimpan terpisah. Mengisi lab belakangan tidak boleh
    # memindahkan sampel premium ke medium yang sedang dikerjakan saat itu.
    hasil_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pemeriksa_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kadar_air: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    broken_persen: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    md: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    transparant: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    whiteness: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    catatan_lab: Mapped[str | None] = mapped_column(String(500))
    dibatalkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dibatalkan_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    alasan_batal: Mapped[str | None] = mapped_column(String(500))
