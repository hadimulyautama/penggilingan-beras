"""Alur bersama: menjawab pertanyaan 'kode batch/lot apa' (read-only)."""
from __future__ import annotations

import logging

from aiogram.types import Message

from app.ai.nlp_parser import parse_lookup
from app.database import SessionLocal
from app.services.report import cari_kode

log = logging.getLogger("bots.lookup")


async def maybe_answer_lookup(message: Message, text: str) -> bool:
    """Jika pesan mencari kode batch/lot, jawab & kembalikan True."""
    try:
        p = await parse_lookup(text)
    except Exception:
        log.exception("parse_lookup gagal")
        return False
    if not p.is_cari_kode:
        return False
    async with SessionLocal() as db:
        teks = await cari_kode(
            db,
            target=p.target or "batch",
            supplier=p.supplier_nama,
            periode=p.periode,
            urutan=p.urutan,
            kondisi=p.kondisi,
            terbaru=p.terbaru,
        )
    await message.answer(teks)
    return True
