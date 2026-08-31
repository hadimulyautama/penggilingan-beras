"""Gudang 1 — Proses Pecah Kulit (Milling) & buffer PK. Migrasi 0002."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class MillingProcess(Base, TimestampMixin):
    """Proses pecah kulit per silo. Kode: MIL-YYYYMMDD-NN."""

    __tablename__ = "milling_process"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_proses: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    silo_id: Mapped[int] = mapped_column(ForeignKey("silos.id"), nullable=False)
    silo_storage_id: Mapped[int | None] = mapped_column(ForeignKey("silo_storage.id"))
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_batches.id")
    )
    berat_gabah_masuk_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    waktu_mulai: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    waktu_selesai: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # proses / selesai
    status: Mapped[str] = mapped_column(String(20), default="proses")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class MillingProgressLog(Base):
    """Monitoring berat kumulatif PK yang keluar (informatif)."""

    __tablename__ = "milling_progress_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    waktu_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    berat_kumulatif_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class MillingPkRouting(Base):
    """Tujuan tiap batch PK keluar: tumpuk (buffer) atau siap_transfer."""

    __tablename__ = "milling_pk_routing"

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # tumpuk / siap_transfer
    tujuan: Mapped[str] = mapped_column(String(20), nullable=False)
    # menunggu / ditransfer (khusus siap_transfer)
    status_transfer: Mapped[str | None] = mapped_column(String(20))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class MillingQcLog(Base):
    """QC hasil PK oleh staff/admin (min. 1x per lot)."""

    __tablename__ = "milling_qc_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    kadar_air: Mapped[float | None] = mapped_column(Numeric(5, 2))
    broken_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    susut_persen: Mapped[float | None] = mapped_column(Numeric(5, 2))
    # KS / KL
    kondisi: Mapped[str | None] = mapped_column(String(10))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class MillingProcessVerification(Base, TimestampMixin):
    """Verifikasi berat output PK final oleh staff/admin."""

    __tablename__ = "milling_process_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), unique=True, nullable=False
    )
    berat_output_final_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_verifikasi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_verifikasi: Mapped[str] = mapped_column(String(20), default="terverifikasi")


class PkStockGudang1(Base, TimestampMixin):
    """Stok PK di buffer tumpukan Gudang 1 (maks 30 ton, dipisah per lot)."""

    __tablename__ = "pk_stock_gudang1"

    id: Mapped[int] = mapped_column(primary_key=True)
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    # tersedia / habis
    status: Mapped[str] = mapped_column(String(20), default="tersedia")
