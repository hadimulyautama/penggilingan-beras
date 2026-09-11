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
from hmu_core import Base, TimestampMixin  # noqa: F401 — Base & skema master bersama (paket core)

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def now_local() -> datetime:
    """Waktu sekarang di zona waktu aplikasi (default Asia/Jakarta)."""
    return datetime.now(ZoneInfo(settings.app_timezone))


def berzona(saat: datetime | None) -> datetime | None:
    """Ubah ke waktu Jakarta. None tetap None.

    asyncpg mengembalikan timestamptz sebagai datetime ber-UTC, dan jam yang
    ditampilkan apa adanya meleset tujuh jam — cukup untuk membuat "pukul
    10:42" terbaca sebagai kejadian yang belum terjadi.
    """
    if saat is None:
        return None
    if saat.tzinfo is None:
        return saat
    return saat.astimezone(ZoneInfo(settings.app_timezone))


def tanggal_lokal(saat: datetime | None) -> date | None:
    """Tanggal Asia/Jakarta dari sebuah waktu — juga bila waktunya dari DB.

    asyncpg mengembalikan `timestamptz` sebagai datetime ber-UTC. Mengambil
    `.date()` darinya langsung memberi tanggal UTC, dan antara 00:00 dan 07:00
    WIB itu tanggal KEMARIN: truk yang ditimbang 05:30 WIB tanggal 11
    dibukukan sebagai GB-20260910-01, sementara nota timbangnya bertanggal 11.
    Temuan QA X-09.

    Waktu tanpa zona dianggap sudah lokal — itulah yang dihasilkan
    `input_time` saat operator menyebut tanggalnya sendiri.
    """
    if saat is None:
        return None
    if saat.tzinfo is None:
        return saat.date()
    return saat.astimezone(ZoneInfo(settings.app_timezone)).date()


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


# Base & TimestampMixin kini dari paket bersama `hmu_core` (di-import di atas).
# Semua sistem memakai SATU Base yang sama → relasi lintas-modul tetap resolve,
# dan tabel master dikelola oleh chain migrasi core (alembic_version_core).


async def get_session() -> AsyncSession:
    """Dependency FastAPI: satu session per request."""
    async with SessionLocal() as session:
        yield session
