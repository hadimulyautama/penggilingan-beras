"""Scheduler latar: notifikasi otomatis kadar air pengeringan telat > 5 jam."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.gudang1.services.drying import check_late_drying

log = logging.getLogger("scheduler")


async def _alert_recipients(db) -> list[int]:
    """Telegram id operator & admin aktif (penerima peringatan pengeringan)."""
    stmt = select(User.telegram_user_id).where(
        User.role.in_(["operator", "admin"]),
        User.telegram_user_id.is_not(None),
        User.status == "aktif",
    )
    return [r for r in (await db.execute(stmt)).scalars().all() if r]


async def run_late_drying_scheduler(bots: dict[str, Bot]) -> None:
    """Loop periodik: cek lot telat, buat notifikasi, kirim alert via Telegram."""
    interval = settings.drying_check_interval_seconds
    late = settings.drying_late_hours
    log.info("Scheduler pengeringan aktif (cek tiap %ss, batas telat %sj)", interval, late)
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as db:
                alerts = await check_late_drying(db, late)
                recipients = await _alert_recipients(db) if alerts else []
        except Exception:
            log.exception("Gagal cek keterlambatan pengeringan")
            continue

        bot = bots.get("gudang1")
        if not bot or not alerts:
            continue
        for lot, gap in alerts:
            teks = (
                f"🔴 Peringatan: {lot.kode_lot} belum diupdate kadar air "
                f"{gap:.1f} jam (batas {late:g} jam). Segera cek."
            )
            for tg_id in recipients:
                try:
                    await bot.send_message(tg_id, teks)
                except Exception:
                    log.exception("Gagal kirim alert ke %s", tg_id)
