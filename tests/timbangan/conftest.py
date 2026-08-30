"""Perkakas uji modul Timbangan: satu database SQLite sementara per uji.

DB uji dibuat dari metadata model, BUKAN dari migrasi — kesepadanan keduanya
sudah dijaga terpisah oleh `test_skema.py`. Dengan begitu uji layanan tetap
cepat dan tidak menyentuh Postgres produksi sama sekali.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.gudang1.models  # noqa: F401
import app.gudang2.models  # noqa: F401
import app.models  # noqa: F401
from app.database import Base
from app.models import Supplier
from app.timbangan import logic, service
from app.timbangan.models import ROLE_ADMIN, ROLE_PETUGAS, TimbanganAkun


@pytest_asyncio.fixture
async def db():
    mesin = create_async_engine("sqlite+aiosqlite://")
    async with mesin.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Sesi = async_sessionmaker(mesin, expire_on_commit=False)
    async with Sesi() as sesi:
        yield sesi
    await mesin.dispose()


async def _akun(db, username: str, role: str, perangkat: str) -> TimbanganAkun:
    akun = TimbanganAkun(
        username=username, nama=username.title(), role=role,
        password_hash="x", perangkat_kode=perangkat,
    )
    db.add(akun)
    await db.flush()
    return akun


@pytest_asyncio.fixture
async def petugas(db):
    return await _akun(db, "budi", ROLE_PETUGAS, "P1")


@pytest_asyncio.fixture
async def petugas2(db):
    """Petugas shift berikutnya — timbang kedua bisa orang lain."""
    return await _akun(db, "sari", ROLE_PETUGAS, "P2")


@pytest_asyncio.fixture
async def admin2(db):
    """Admin kedua — pembatalan dan penutupan pemeriksaan kini wewenang Admin."""
    return await _akun(db, "miftah", ROLE_ADMIN, "P9")


@pytest_asyncio.fixture
async def admin(db):
    return await _akun(db, "wahid", ROLE_ADMIN, "P0")


@pytest_asyncio.fixture
async def supplier(db):
    s = Supplier(nama_supplier="H. Anton")
    db.add(s)
    await db.flush()
    return s


@pytest_asyncio.fixture
async def jenis_tersemai(db):
    """Master komoditas terisi dari aturan awal."""
    jumlah = await service.pastikan_jenis(db)
    assert jumlah == len(logic.JENIS_AWAL)
    return jumlah
