"""Alur bersama: analitik/pola jam kedatangan gabah (read-only, insight)."""
from __future__ import annotations

import logging

from aiogram.types import Message

from app.ai.nlp_parser import parse_jam
from app.database import SessionLocal
from app.services.report import insight_jam_kedatangan

log = logging.getLogger("bots.jam")


async def maybe_answer_jam(message: Message, text: str) -> bool:
    """Jika pesan menanyakan pola jam kedatangan gabah, jawab & kembalikan True."""
    try:
        p = await parse_jam(text)
    except Exception:
        log.exception("parse_jam gagal")
        return False
    if not p.is_tanya_jam:
        return False
    async with SessionLocal() as db:
        teks = await insight_jam_kedatangan(
            db, supplier=p.supplier_nama, periode=p.periode
        )
    await message.answer(teks)
    return True
