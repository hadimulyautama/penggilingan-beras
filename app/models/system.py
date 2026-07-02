"""Sistem pendukung: activity_logs (audit trail), notifications."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActivityLog(Base):
    """Audit trail SEMUA perubahan — transaksi DAN master data (soft delete)."""

    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_name: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # INSERT / UPDATE / DELETE
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(64))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waktu_perubahan: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    alasan_perubahan: Mapped[str | None] = mapped_column(Text)


class Notification(Base):
    """Notifikasi otomatis 🔴🟡🟢. Eskalasi 24 jam ke admin. Laporan harian 21:00."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipe: Mapped[str] = mapped_column(String(50), nullable=False)
    record_id: Mapped[int | None] = mapped_column(Integer)
    table_name: Mapped[str | None] = mapped_column(String(64))
    # admin / staff / operator
    target_role: Mapped[str | None] = mapped_column(String(20))
    pesan: Mapped[str] = mapped_column(Text, nullable=False)
    # merah / kuning / hijau
    prioritas: Mapped[str] = mapped_column(String(10), default="kuning")
    # baru / dibaca / selesai
    status: Mapped[str] = mapped_column(String(20), default="baru")
    eskalasi_target: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    eskalasi_jam: Mapped[int] = mapped_column(Integer, default=24)
    # belum / sudah
    status_eskalasi: Mapped[str] = mapped_column(String(20), default="belum")
    waktu_eskalasi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
