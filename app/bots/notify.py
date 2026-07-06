"""Kirim notifikasi ke pengguna berdasarkan peran (mis. laporan HPP ke admin).

Referensi instance Bot disimpan saat startup agar handler bisa mengirim lintas
bot (mis. proses selesai di bot Gudang 1 -> laporan ke bot Admin).
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User

log = logging.getLogger("bots.notify")

_bots: dict = {}


def set_bots(bots: dict) -> None:
    global _bots
    _bots = bots


async def notify_user(telegram_user_id: int | None, text: str, bot_name: str = "admin") -> bool:
    """Kirim `text` ke SATU user via bot tertentu (mis. konfirmasi aksi cepat
    Mini App ke chat). True bila terkirim. Aman bila bot/tid tak ada."""
    bot = _bots.get(bot_name) or next(iter(_bots.values()), None)
    if bot is None or not telegram_user_id:
        return False
    try:
        await bot.send_message(telegram_user_id, text, parse_mode="Markdown")
        return True
    except Exception:
        log.exception("Gagal kirim ke user %s via %s", telegram_user_id, bot_name)
        return False


async def notify_roles(text: str, roles: tuple[str, ...] = ("admin", "staff")) -> None:
    """Kirim `text` (Markdown) ke semua user aktif dengan peran tsb via bot admin."""
    bot = _bots.get("admin")
    if bot is None:
        return
    async with SessionLocal() as db:
        ids = (
            await db.execute(
                select(User.telegram_user_id).where(
                    User.role.in_(list(roles)),
                    User.telegram_user_id.isnot(None),
                    User.status == "aktif",
                )
            )
        ).scalars().all()
    for tid in ids:
        try:
            await bot.send_message(tid, text, parse_mode="Markdown")
        except Exception:
            log.exception("Gagal kirim notifikasi ke %s", tid)
