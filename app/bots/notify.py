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
    Mini App ke chat). True bila terkirim.

    Tahan banting: coba bot yang diminta dulu, lalu bot lain sebagai fallback
    (user mungkin belum pernah start bot tertentu → 403). Bila Markdown gagal
    di-parse (400), ulangi sebagai teks biasa agar pesan tetap sampai."""
    if not telegram_user_id or not _bots:
        return False
    from aiogram.exceptions import TelegramBadRequest

    names = [bot_name] + [n for n in _bots if n != bot_name]
    for n in names:
        bot = _bots.get(n)
        if bot is None:
            continue
        for pm in ("Markdown", None):
            try:
                await bot.send_message(telegram_user_id, text, parse_mode=pm)
                return True
            except TelegramBadRequest:
                continue  # kemungkinan Markdown invalid → coba teks biasa
            except Exception:
                break  # bot ini tak bisa menjangkau user (mis. 403) → bot lain
    log.warning("Gagal kirim ke user %s (semua bot dicoba)", telegram_user_id)
    return False


async def notify_roles(text: str, roles: tuple[str, ...] = ("superadmin", "admin", "staff")) -> None:
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
