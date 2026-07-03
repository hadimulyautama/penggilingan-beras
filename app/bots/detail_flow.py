"""Alur bersama: menjawab detail/atribut sebuah entitas (read-only)."""
from __future__ import annotations

import logging
import re

from aiogram.types import Message

from app.ai.nlp_parser import parse_detail
from app.database import SessionLocal
from app.services.report import detail_query

log = logging.getLogger("bots.detail")

_RECENCY = ("terakhir", "terbaru", "barusan", "tadi")
_ASK_SOURCE = ("siapa", "punya", "bahan", "asal", "dari mana")
_DRY_WORDS = (
    "drying", "pengering", "keringkan", "dikeringkan", "oven", "dryer",
    "jemur", "pengeringan",
)
_MILL_WORDS = ("selep", "giling", "milling", "husking", "pecah kulit", "selepan")
_CODE_RE = re.compile(r"\b(?:gb|lot|mil)-", re.I)
_PK_RE = re.compile(r"\bpk\b", re.I)


def _is_ambiguous_last_process(text: str) -> bool:
    """True bila pertanyaan soal 'proses TERAKHIR ... dari siapa' tanpa
    menyebut jenis prosesnya (drying vs milling) — bot harus bertanya dulu."""
    t = text.lower()
    if "proses" not in t:
        return False  # bukan pertanyaan proses (mis. 'gabah terakhir dari siapa')
    if not any(w in t for w in _RECENCY):
        return False
    if not any(w in t for w in _ASK_SOURCE):
        return False
    if _CODE_RE.search(t) or _PK_RE.search(t):
        return False  # sudah spesifik (kode / PK=milling)
    if "silo" in t:
        return False  # pertanyaan isi silo, bukan ambigu
    if any(w in t for w in _DRY_WORDS) or any(w in t for w in _MILL_WORDS):
        return False  # jenis proses sudah disebut
    return True


async def maybe_answer_detail(message: Message, text: str, session=None) -> bool:
    """Jika pesan menanyakan detail entitas, jawab & kembalikan True.

    `session` (opsional) menyediakan konteks percakapan (ctx_batch/lot/mil)
    agar pertanyaan tanpa referensi ("berapa harganya") tetap terjawab.
    """
    if _is_ambiguous_last_process(text):
        await message.answer(
            "Maksudnya *proses terakhir* yang mana?\n"
            "• Pengeringan → ketik `proses pengeringan terakhir dari siapa`\n"
            "• Giling (selep) → ketik `proses giling terakhir dari siapa`",
            parse_mode="Markdown",
        )
        return True
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
            tanggal=p.tanggal,
            ctx_batch=getattr(session, "ctx_batch", None),
            ctx_lot=getattr(session, "ctx_lot", None),
            ctx_mil=getattr(session, "ctx_mil", None),
        )
    await message.answer(teks)
    return True
