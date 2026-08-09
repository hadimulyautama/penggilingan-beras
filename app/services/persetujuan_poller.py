"""Poller latar: kirim tombol PERSETUJUAN aksi Drive ke pemilik via bot kantor.

Baris AksiPending status='pending' (dibuat MCP) → kirim ✅/❌ ke
settings.admin_telegram_id → set status='menunggu' (agar tak dikirim ulang).
Keputusan ditangani callback di app/kantor/bot.py (on_persetujuan).

Poller jalan di service `penggilingan-beras` (yang memegang bot + kredensial
Drive). MCP hanya menulis baris pending; poller & eksekutor ada di sini.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.kantor import persetujuan as pst
from app.kantor.models import AksiPending

log = logging.getLogger("persetujuan.poller")

_INTERVAL = 15  # detik


def _keyboard(aksi_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Setujui", callback_data=f"kaksi:ok:{aksi_id}"),
        InlineKeyboardButton(text="❌ Tolak", callback_data=f"kaksi:no:{aksi_id}"),
    ]])


async def run_persetujuan_poller(bots: dict[str, Bot]) -> None:
    """Loop: kirim tombol persetujuan untuk setiap aksi Drive yang diajukan agen."""
    bot = bots.get("kantor")
    if bot is None:
        log.warning("Bot 'kantor' tak tersedia — poller persetujuan NONAKTIF.")
        return
    if not settings.admin_telegram_id:
        log.warning("ADMIN_TELEGRAM_ID kosong — poller persetujuan NONAKTIF.")
        return
    log.info("Poller persetujuan aktif (cek tiap %ss → pemilik %s)",
             _INTERVAL, settings.admin_telegram_id)
    while True:
        await asyncio.sleep(_INTERVAL)
        try:
            async with SessionLocal() as db:
                rows = (await db.execute(
                    select(AksiPending)
                    .where(AksiPending.status == pst.PENDING)
                    .order_by(AksiPending.id)
                    .limit(10)
                )).scalars().all()
                for row in rows:
                    # TEKS POLOS (bukan Markdown): ringkasan berisi nama file dengan
                    # karakter khusus (_TRANSIT, [DRAFT], *) yang merusak parser Markdown
                    # → tombol gagal terkirim. Polos = aman untuk nama file apa pun.
                    teks = (
                        f"🔴 Persetujuan aksi arsip (#{row.id})\n\n"
                        f"{row.ringkasan.replace('*', '')}\n\n"
                        "Aksi ini MENGUBAH Google Drive. Setujui hanya bila Anda yakin — "
                        "semua reversible & tercatat di audit."
                    )
                    try:
                        await bot.send_message(
                            settings.admin_telegram_id, teks,
                            reply_markup=_keyboard(row.id),
                        )
                        row.status = pst.MENUNGGU  # cegah kirim ulang
                    except Exception:
                        log.exception("Gagal kirim tombol persetujuan #%s", row.id)
                await db.commit()
        except Exception:
            log.exception("Loop poller persetujuan gagal (lanjut)")
