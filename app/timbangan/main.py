"""Titik masuk service Timbangan.

Service kedua di Railway, database yang sama. Sengaja TIDAK memuat bot
Telegram, poller, maupun modul produksi — deploy pos timbang tidak boleh
sanggup menjatuhkan bot yang sedang melayani manajemen, dan sebaliknya.

Dua hal yang khas di sini:

  · **Tidak menjalankan migrasi Alembic.** Riwayat migrasi hanya milik service
    `app`. Dua service yang bermigrasi bersamaan akan berebut skema.
  · **Menyemai master komoditas.** Aman dijalankan berulang: hanya menambah
    baris yang belum ada, tidak pernah menimpa aturan yang sudah disetel.

Jalankan:  uvicorn app.timbangan.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.timbangan.web import PREFIX, pasang

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s"
)
log = logging.getLogger("timbangan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.timbangan import service
    from app.timbangan.db import sesi_db

    try:
        async with sesi_db() as db:
            ditambah = await service.pastikan_jenis(db)
            if ditambah:
                log.info("Master komoditas: %d baris ditambahkan", ditambah)
            if await service.pastikan_admin(db):
                log.info("Akun admin awal dibuat")
    except Exception:
        # Penyemaian gagal tidak boleh menahan service menyala — halaman
        # tetap dapat dilayani, dan aturan bawaan dari kode tetap berlaku.
        log.exception("Penyemaian awal gagal (lanjut jalan)")
    yield


app = FastAPI(title="Pos Timbang — PT Hadi Mulya Utama", lifespan=lifespan)
pasang(app)


@app.get("/")
async def akar():
    return RedirectResponse(f"{PREFIX}/")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "modul": "timbangan"}
