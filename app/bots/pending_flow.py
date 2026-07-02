"""Alur bersama: menjawab 'apa yang perlu diverifikasi' (read-only)."""
from __future__ import annotations

import logging

from aiogram.types import Message

from app.ai.nlp_parser import parse_pending
from app.database import SessionLocal
from app.services.report import pending_verifikasi

log = logging.getLogger("bots.pending")


async def maybe_answer_pending(message: Message, text: str) -> bool:
    """Jika pesan menanyakan tugas verifikasi tertunda, jawab & kembalikan True."""
    try:
        is_pending = await parse_pending(text)
    except Exception:
        log.exception("parse_pending gagal")
        return False
    if not is_pending:
        return False
    async with SessionLocal() as db:
        teks = await pending_verifikasi(db)
    await message.answer(teks)
    return True
