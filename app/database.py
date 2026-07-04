"""Async SQLAlchemy engine, session factory, dan declarative Base."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def now_local() -> datetime:
    """Waktu sekarang di zona waktu aplikasi (default Asia/Jakarta)."""
    return datetime.now(ZoneInfo(settings.app_timezone))


class BackdateError(Exception):
    """Tanggal backdate tidak valid (mis. di masa depan)."""


def input_time(tanggal: date | None, jam: time | None = None) -> datetime:
    """Timestamp untuk mencatat sebuah kejadian (mendukung backdate).

    - Tanpa `tanggal`/`jam`  → waktu sekarang (perilaku normal).
    - `tanggal` saja         → tanggal itu dengan JAM saat ini.
    - `jam` saja             → hari ini pada jam itu.
    - keduanya               → tanggal & jam persis yang disebut.

    Melempar BackdateError bila hasilnya di masa depan.
    """
    now = now_local()
    if tanggal is None and jam is None:
        return now
    d = tanggal or now.date()
    t = jam or now.timetz()
    dt = datetime.combine(d, t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    if dt > now:
        raise BackdateError(
            f"Waktu {dt:%d-%m-%Y %H:%M} ada di masa depan — tidak bisa dicatat."
        )
    return dt


class Base(DeclarativeBase):
    """Base untuk semua model."""


class TimestampMixin:
    """Kolom created_at / updated_at otomatis (prinsip: timestamp selalu otomatis)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


async def get_session() -> AsyncSession:
    """Dependency FastAPI: satu session per request."""
    async with SessionLocal() as session:
        yield session
