"""Transfer internal Gudang 1 → Gudang 2 (PK siap transfer)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class InternalTransfer(Base, TimestampMixin):
    """Transfer PK dari Gudang 1 ke Gudang 2. Dibuat staff/admin.

    Kode: TRF-YYYYMMDD-NN. Tidak pakai kendaraan (tanpa plat).
    """

    __tablename__ = "internal_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_transfer: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    milling_process_id: Mapped[int] = mapped_column(
        ForeignKey("milling_process.id"), nullable=False
    )
    drying_lot_id: Mapped[int | None] = mapped_column(ForeignKey("drying_lots.id"))
    berat_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # silo_a / silo_b / ditumpuk  (lokasi di Gudang 2)
    lokasi_tujuan: Mapped[str] = mapped_column(String(20), nullable=False)
    # Snapshot HPP per kg PK saat transfer (bila milling sudah diverifikasi).
    hpp_per_kg: Mapped[float | None] = mapped_column(Numeric(12, 2))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # terkirim / dibatalkan
    status: Mapped[str] = mapped_column(String(20), default="terkirim")
