"""Perakitan seluruh rute modul Timbangan menjadi satu router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan import setelan
from app.timbangan.db import get_db
from app.timbangan.routes import auth, laporan, master, pos, transaksi


async def _muat_setelan(request: Request, db: AsyncSession = Depends(get_db)):
    """Setelan & jumlah tiket terbuka, tersedia untuk setiap halaman."""
    await setelan.muat_ke_permintaan(request, db)

    # Dipakai bilah navigasi bawah. Truk yang sedang menunggu adalah hal
    # paling mendesak di pos timbang — angkanya harus terlihat dari mana pun,
    # bukan hanya saat petugas kebetulan membuka beranda.
    from sqlalchemy import func, select

    from app.timbangan.models import TIKET_TERBUKA, TRX_AKTIF, TimbanganTransaksi
    try:
        request.state.jumlah_tiket = (await db.execute(
            select(func.count(TimbanganTransaksi.id)).where(
                TimbanganTransaksi.status_tiket == TIKET_TERBUKA,
                TimbanganTransaksi.status_transaksi == TRX_AKTIF,
            )
        )).scalar_one()
    except Exception:
        request.state.jumlah_tiket = 0


router = APIRouter(dependencies=[Depends(_muat_setelan)])
# Urutan penting: rute berpola tetap (auth, laporan, master) didaftarkan lebih
# dulu agar tidak tertangkap pola dinamis seperti /pilih/{arah}.
router.include_router(auth.router)
router.include_router(laporan.router)
router.include_router(master.router)
router.include_router(transaksi.router)
router.include_router(pos.router)

__all__ = ["router"]
