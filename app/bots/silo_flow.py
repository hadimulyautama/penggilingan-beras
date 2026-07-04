"""Alur bersama: laporan/status silo Gudang 1 (READ-ONLY, semua bot).

Perintah TULIS silo (masukkan/kosongkan) tetap aksi fisik operator di
@selepan_bot; di sini hanya pertanyaan status/isi silo yang dijawab.
"""
from __future__ import annotations

import logging

from aiogram.types import Message

from app.ai.nlp_parser import parse_silo
from app.database import SessionLocal
from app.services.silo import laporan_silo

log = logging.getLogger("bots.silo")


async def maybe_answer_silo_report(message: Message, text: str) -> bool:
    """Jawab pertanyaan status/isi silo ('status silo A', 'silo A gabah dari
    siapa', 'silo apa yang terisi'). True bila ditangani."""
    try:
        p = await parse_silo(text)
    except Exception:
        log.exception("parse_silo gagal")
        return False
    if p.intent != "laporan_silo":
        return False
    async with SessionLocal() as db:
        await message.answer(await laporan_silo(db, p.nama_silo))
    return True
