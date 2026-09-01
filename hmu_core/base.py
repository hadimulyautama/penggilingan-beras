"""Base ORM + TimestampMixin bersama — dipakai SEMUA sistem lewat submodule `core`.

Diekstrak dari app/database.py (repo produksi). Sengaja TANPA engine/session di sini:
tiap aplikasi membawa koneksi/sesinya sendiri; core hanya mendefinisikan skema master.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base untuk semua model master bersama."""


class TimestampMixin:
    """Kolom created_at / updated_at otomatis (timestamp selalu otomatis)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
