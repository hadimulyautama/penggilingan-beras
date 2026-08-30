"""Akses DB modul Timbangan.

Selalu mengambil `SessionLocal` LEWAT modul `app.database` (bukan meng-import
objeknya langsung) agar pengujian bisa mengalihkan koneksi ke DB uji.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app import database
from app.config import settings


def sesi_db():
    """Context manager satu sesi DB async."""
    return database.SessionLocal()


async def get_db():
    """Dependency FastAPI: satu sesi per request."""
    async with sesi_db() as db:
        yield db


def sekarang() -> datetime:
    """Waktu sekarang di zona aplikasi (Asia/Jakarta)."""
    return datetime.now(ZoneInfo(settings.app_timezone))


def hari_ini():
    return sekarang().date()


def berzona(waktu: datetime | None) -> datetime | None:
    """Pastikan waktu punya zona sebelum dibandingkan.

    Postgres mengembalikan waktu berzona, SQLite (dipakai pengujian) tidak.
    Tanpa penyeragaman ini, perbandingan keduanya melempar TypeError.
    """
    if waktu is None or waktu.tzinfo is not None:
        return waktu
    return waktu.replace(tzinfo=ZoneInfo(settings.app_timezone))
