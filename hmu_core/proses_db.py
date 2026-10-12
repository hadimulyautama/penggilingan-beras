"""Tabel identitas dan arus proses yang dipakai lintas aplikasi.

Tabel domain lama tetap menjadi sumber detail operasional. Baris di sini
menjadi identitas bersama yang dapat dirujuk Produksi, Timbangan, dan Kantor.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        JSON, Numeric, String, UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hmu_core.base import Base, TimestampMixin


class ProsesTerpadu(Base, TimestampMixin):
    __tablename__ = "proses_terpadu"
    __table_args__ = (
        UniqueConstraint("aplikasi", "tabel_sumber", "id_sumber",
                         name="uq_proses_terpadu_sumber"),
        CheckConstraint(
            "status IN ('menunggu','berjalan','dihentikan','selesai','dibatalkan')",
            name="ck_proses_terpadu_status",
        ),
        Index("ix_proses_terpadu_jenis_status", "jenis", "status"),
        Index("ix_proses_terpadu_pemilik", "jenis_pemilik", "id_pemilik"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    aplikasi: Mapped[str] = mapped_column(String(30), nullable=False)
    tabel_sumber: Mapped[str] = mapped_column(String(80), nullable=False)
    id_sumber: Mapped[str] = mapped_column(String(80), nullable=False)
    kode: Mapped[str] = mapped_column(String(80), nullable=False)
    jenis: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    jenis_pemilik: Mapped[str] = mapped_column(String(20), nullable=False)
    id_pemilik: Mapped[int | None] = mapped_column(Integer)
    nama_pemilik: Mapped[str | None] = mapped_column(String(160))
    waktu_mulai: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waktu_selesai: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pelaksana_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    referensi_asal: Mapped[list] = mapped_column(JSON, nullable=False,
                                                 default=list, server_default=text("'[]'"))
    metadata_domain: Mapped[dict] = mapped_column(JSON, nullable=False,
                                                  default=dict, server_default=text("'{}'"))

    arus: Mapped[list["ArusProsesTerpadu"]] = relationship(
        back_populates="proses", cascade="all, delete-orphan",
        order_by="ArusProsesTerpadu.id",
    )


class ArusProsesTerpadu(Base):
    __tablename__ = "arus_proses_terpadu"
    __table_args__ = (
        CheckConstraint("arah IN ('bahan','hasil')", name="ck_arus_proses_arah"),
        CheckConstraint("berat_kg >= 0", name="ck_arus_proses_berat_nonnegatif"),
        Index("ix_arus_proses_terpadu_proses", "proses_id", "arah"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proses_id: Mapped[int] = mapped_column(
        ForeignKey("proses_terpadu.id", ondelete="CASCADE"), nullable=False)
    arah: Mapped[str] = mapped_column(String(10), nullable=False)
    komoditas: Mapped[str] = mapped_column(String(40), nullable=False)
    atribut_produk: Mapped[dict] = mapped_column(JSON, nullable=False,
                                                 default=dict, server_default=text("'{}'"))
    berat_kg: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    referensi: Mapped[str | None] = mapped_column(String(100))
    lokasi_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False,
                                         default=dict, server_default=text("'{}'"))

    proses: Mapped[ProsesTerpadu] = relationship(back_populates="arus")
