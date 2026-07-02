"""Async SQLAlchemy engine, session factory, dan declarative Base."""
from __future__ import annotations

from datetime import datetime, timezone
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
