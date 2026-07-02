"""Alur bersama: menjawab 'apa yang sedang berlangsung' (read-only)."""
from __future__ import annotations

import logging

from aiogram.types import Message

from app.ai.nlp_parser import parse_status
from app.database import SessionLocal
from app.services.report import status_gudang1

log = logging.getLogger("bots.status")


async def maybe_answer_status(message: Message, text: str) -> bool:
    """Jika pesan menanyakan status umum yang berjalan, jawab & kembalikan True."""
    try:
        is_status = await parse_status(text)
    except Exception:
        log.exception("parse_status gagal")
        return False
    if not is_status:
        return False
    async with SessionLocal() as db:
        await message.answer(await status_gudang1(db))
    return True
