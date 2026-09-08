"""Scheduler latar: tandai pengeringan yang kadar airnya telat diperbarui.

Dulu ia juga mengirim peringatan Telegram — lewat `bots["gudang1"]`, bot yang
sudah dibubarkan 3 September 2026. Sejak itu barisnya tetap jalan tiap putaran
dan tak pernah mengirim apa-apa: `bots.get("gudang1")` selalu None. Peringatan
yang mati diam-diam lebih buruk daripada peringatan yang tak pernah ada, jadi
sisanya dibuang dan yang tinggal adalah yang memang bekerja — catatan
notifikasi di basis data, yang dibaca Pos Produksi.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.database import SessionLocal
from app.penggilingan.gudang1.services.drying import check_late_drying

log = logging.getLogger("scheduler")


async def run_late_drying_scheduler() -> None:
    """Loop periodik: cek lot yang telat diperbarui, catat notifikasinya."""
    interval = settings.drying_check_interval_seconds
    late = settings.drying_late_hours
    log.info("Scheduler pengeringan aktif (cek tiap %ss, batas telat %sj)", interval, late)
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as db:
                alerts = await check_late_drying(db, late)
            if alerts:
                log.info("Pengeringan telat: %s lot ditandai.", len(alerts))
        except Exception:
            log.exception("Gagal cek keterlambatan pengeringan")
