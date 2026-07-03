"""Alur bersama: menjawab pertanyaan laporan pembelian gabah (read-only)."""
from __future__ import annotations

import logging

from aiogram.types import Message

from app.ai.nlp_parser import parse_report
from app.database import SessionLocal
from app.services.report import laporan_pembelian_gabah

log = logging.getLogger("bots.report")


async def maybe_answer_report(message: Message, text: str, session=None) -> bool:
    """Jika pesan adalah pertanyaan laporan gabah, jawab & kembalikan True.

    Kembalikan False bila bukan pertanyaan laporan (biar bot tampilkan fallback).
    """
    try:
        parsed = await parse_report(text)
    except Exception:
        log.exception("parse_report gagal")
        return False
    log.info("report intent for %r -> is_laporan=%s periode=%s", text, parsed.is_laporan_gabah, parsed.periode)
    if not parsed.is_laporan_gabah:
        return False
    async with SessionLocal() as db:
        teks = await laporan_pembelian_gabah(db, parsed.periode, parsed.tanggal)
    # Simpan konteks untuk pertanyaan lanjutan ("apa saja kodenya").
    if session is not None:
        session.ctx_topic = "batch"
        session.ctx_periode = parsed.periode or "hari_ini"
        session.ctx_tanggal = parsed.tanggal
    await message.answer(teks)  # teks polos (tanpa Markdown) — aman
    return True
