"""Alur bersama: menjawab pertanyaan 'kode batch/lot apa' (read-only)."""
from __future__ import annotations

import logging

from aiogram.types import Message

from app.ai.nlp_parser import parse_lookup
from app.database import SessionLocal
from app.services.report import cari_kode

log = logging.getLogger("bots.lookup")

# Kata waktu eksplisit; bila salah satunya ada, periode diambil dari pesan
# (bukan warisan konteks).
_TIME_WORDS = (
    "hari ini", "harini", "kemarin", "kmrn", "minggu", "bulan", "semua",
    "keseluruhan", "total", "tadi", "tanggal", "kemaren",
)


def _has_time_word(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in _TIME_WORDS)


async def maybe_answer_lookup(message: Message, text: str, session=None) -> bool:
    """Jika pesan mencari kode batch/lot, jawab & kembalikan True."""
    try:
        p = await parse_lookup(text)
    except Exception:
        log.exception("parse_lookup gagal")
        return False
    if not p.is_cari_kode:
        return False

    # Warisi konteks percakapan sebelumnya untuk pertanyaan lanjutan singkat
    # ("berapa batch hari ini" -> "apa saja kodenya").
    target = p.target
    periode = p.periode
    tanggal = p.tanggal
    if session is not None:
        if not target:
            target = session.ctx_topic
        # Bila pesan tak menyebut waktu, pakai periode/tanggal dari konteks
        # (bukan tebakan default parser seperti 'semua').
        if not _has_time_word(text) and not p.terbaru and not tanggal:
            if getattr(session, "ctx_tanggal", None):
                tanggal = session.ctx_tanggal
            elif session.ctx_periode:
                periode = session.ctx_periode
    target = target or "batch"

    async with SessionLocal() as db:
        teks = await cari_kode(
            db,
            target=target,
            supplier=p.supplier_nama,
            periode=periode,
            urutan=p.urutan,
            kondisi=p.kondisi,
            terbaru=p.terbaru,
            tanggal=tanggal,
        )
    if session is not None:
        session.ctx_topic = target
        session.ctx_tanggal = tanggal
        if periode:
            session.ctx_periode = periode
    await message.answer(teks)
    return True
