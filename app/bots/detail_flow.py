"""Alur bersama: menjawab detail/atribut sebuah entitas (read-only)."""
from __future__ import annotations

import logging

from aiogram.types import Message

from app.ai.nlp_parser import parse_detail
from app.database import SessionLocal
from app.services.report import detail_query

log = logging.getLogger("bots.detail")


async def maybe_answer_detail(message: Message, text: str, session=None) -> bool:
    """Jika pesan menanyakan detail entitas, jawab & kembalikan True.

    `session` (opsional) menyediakan konteks percakapan (ctx_batch/lot/mil)
    agar pertanyaan tanpa referensi ("berapa harganya") tetap terjawab.
    """
    try:
        p = await parse_detail(text)
    except Exception:
        log.exception("parse_detail gagal")
        return False
    if not p.is_detail:
        return False
    async with SessionLocal() as db:
        teks = await detail_query(
            db,
            target=p.target,
            kode=p.kode,
            supplier=p.supplier_nama,
            periode=p.periode,
            urutan=p.urutan,
            kondisi=p.kondisi,
            terbaru=p.terbaru,
            ctx_batch=getattr(session, "ctx_batch", None),
            ctx_lot=getattr(session, "ctx_lot", None),
            ctx_mil=getattr(session, "ctx_mil", None),
        )
    await message.answer(teks)
    return True
