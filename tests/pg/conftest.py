"""Uji yang menyentuh Postgres sungguhan.

Suite ini sampai 11 September 2026 tak punya satu pun uji ber-Postgres, dan
akibatnya satu kelas kesalahan tak pernah terlihat sama sekali: BALAPAN. Dua
operator yang menekan simpan pada detik yang sama, atau satu pembatalan yang
menggeser hitungan — keduanya hanya muncul bila dua transaksi sungguhan
memperebutkan baris yang sama. SQLite tak menirukannya.

Berjalan HANYA bila `UJI_PG_URL` disetel; tanpa itu dilewati, dengan alasan
yang disebutkan di layar. Uji yang dilewati diam-diam adalah uji yang tak
menjaga apa pun.

    createdb uji_produksi
    UJI_PG_URL=postgresql+asyncpg://postgres:pw@127.0.0.1:5432/uji_produksi \\
        .venv/bin/python -m pytest -q tests/pg
"""
from __future__ import annotations

import os
import pathlib

import pytest
import pytest_asyncio


def _url() -> str | None:
    """Alamat Postgres uji — berpagar, bukan sekadar dibaca.

    Dua syarat, dan keduanya perlu. Host wajib loopback: uji ini MEMBANGUN dan
    MENJATUHKAN skema, dan basis data di mesin lain bisa saja basis data yang
    sedang dipakai orang. Namanya wajib berawalan "uji_": satu salah ketik
    pada alamat loopback pun masih bisa mengenai basis data pengembangan yang
    isinya dipakai orang lain di kantor.

    Gagal keras, bukan dilewati: alamat yang salah bentuk adalah kekeliruan
    yang harus diperbaiki, bukan keadaan yang boleh didiamkan.
    """
    url = os.environ.get("UJI_PG_URL", "").strip()
    if not url:
        return None
    if not ("127.0.0.1" in url or "localhost" in url):
        pytest.fail(f"UJI_PG_URL bukan loopback: {url.rsplit('@', 1)[-1]}")
    nama = url.rsplit("/", 1)[-1].split("?")[0]
    if not nama.startswith("uji_"):
        pytest.fail(f"nama basis data uji wajib berawalan 'uji_', bukan '{nama}'")
    return url


@pytest_asyncio.fixture
async def pg():
    """Basis data kosong dengan skema dari MIGRASI, bukan dari metadata.

    Sengaja lewat `alembic upgrade head`: yang diuji di sini termasuk migrasi
    penghitung kode, dan membangun skema dari metadata akan melewatkannya —
    lalu uji lulus di laptop dan gagal di Railway.
    """
    url = _url()
    if url is None:
        pytest.skip("UJI_PG_URL kosong — uji Postgres dilewati")

    import subprocess

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    akar = pathlib.Path(__file__).resolve().parents[2]
    lingk = {**os.environ, "DATABASE_URL": url}
    hasil = subprocess.run(
        [str(akar / ".venv/bin/python"), "-m", "alembic", "upgrade", "head"],
        cwd=akar, env=lingk, capture_output=True, text=True, timeout=300,
    )
    if hasil.returncode != 0:
        pytest.fail(f"alembic upgrade head gagal:\n{hasil.stderr[-2000:]}")

    mesin = create_async_engine(url)
    Sesi = async_sessionmaker(mesin, expire_on_commit=False)

    # Layanannya memakai `SessionLocal` modulnya sendiri; diarahkan ke mesin
    # uji supaya yang diuji benar-benar kode yang dipakai, bukan salinannya.
    from app import database
    asli = database.SessionLocal
    database.SessionLocal = Sesi
    try:
        yield Sesi
    finally:
        database.SessionLocal = asli
        await mesin.dispose()


@pytest_asyncio.fixture
async def pemakai(pg):
    """Satu orang yang mencatat — operator Gudang 1."""
    from sqlalchemy import select

    from app.models import User

    async with pg() as db:
        u = (await db.execute(select(User).limit(1))).scalars().first()
        if u is None:
            u = User(nama="Uji", role="operator", status="aktif")
            db.add(u)
            await db.commit()
            await db.refresh(u)
        return u


@pytest_asyncio.fixture
async def pemasok(pg):
    """Satu pemasok — `purchase_batches.supplier_id` wajib isi."""
    from sqlalchemy import select

    from app.models import Supplier

    async with pg() as db:
        s = (await db.execute(select(Supplier).limit(1))).scalars().first()
        if s is None:
            s = Supplier(nama_supplier="Pemasok Uji")
            db.add(s)
            await db.commit()
            await db.refresh(s)
        return s
