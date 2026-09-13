#!/usr/bin/env python3
"""Bangun ulang seluruh proyeksi dari buku besar peristiwa (Tahap 3).

    DATABASE_URL=... python -m scripts.bangun_ulang_proyeksi

Proyeksi adalah turunan; perintah ini mengosongkannya lalu menerapkan kembali
semua peristiwa berurutan. Aman diulang. Tabel lama (cermin) tidak disentuh.
"""
from __future__ import annotations

import asyncio

from app.database import SessionLocal
from app.services.peristiwa import bangun_ulang


async def _jalan() -> None:
    async with SessionLocal() as db:
        laporan = await bangun_ulang(db)
    for k, v in laporan.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    asyncio.run(_jalan())
