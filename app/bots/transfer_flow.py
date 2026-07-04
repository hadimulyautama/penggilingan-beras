"""Alur bersama: laporan transfer G1->G2 (read-only) + arahan buat transfer."""
from __future__ import annotations

import logging

from aiogram.types import Message

from app.ai.nlp_parser import parse_transfer
from app.database import SessionLocal
from app.services.transfer import laporan_pk_siap_transfer, laporan_transfer

log = logging.getLogger("bots.transfer")


async def maybe_answer_transfer(
    message: Message, text: str, financial: bool = True
) -> bool:
    """Laporan PK siap-transfer / riwayat transfer (semua bot). True jika ditangani.

    Perintah MEMBUAT transfer diarahkan ke staff/admin (@hmuadmin_bot).
    `financial=False` menyembunyikan HPP (untuk operator).
    """
    try:
        p = await parse_transfer(text)
    except Exception:
        log.exception("parse_transfer gagal")
        return False
    if p.intent == "bukan_transfer":
        return False
    if p.intent == "buat_transfer":
        await message.answer(
            "ℹ️ Membuat transfer ke Gudang 2 dikerjakan *Staff/Admin* di "
            "`@hmuadmin_bot`.",
            parse_mode="Markdown",
        )
        return True
    async with SessionLocal() as db:
        if p.intent == "laporan_siap_transfer":
            await message.answer(await laporan_pk_siap_transfer(db))
        elif p.intent == "laporan_transfer":
            await message.answer(await laporan_transfer(db, financial=financial))
        else:
            return False
    return True
