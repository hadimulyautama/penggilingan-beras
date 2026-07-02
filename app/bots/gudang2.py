"""Bot Gudang 2 (Operator Penyosohan) — kerangka Fase 1.

Auth sudah aktif; handler fitur (terima transfer, tumpukan->silo, penyosohan)
menyusul di fase berikutnya.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bots.common import authenticate
from app.bots.detail_flow import maybe_answer_detail
from app.bots.lookup_flow import maybe_answer_lookup
from app.bots.pending_flow import maybe_answer_pending
from app.bots.report_flow import maybe_answer_report
from app.bots.status_flow import maybe_answer_status
from app.bots.transfer_flow import maybe_answer_transfer
from app.database import SessionLocal

router = Router(name="gudang2")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await message.answer(
            "⛔ Belum terdaftar. ID Telegram Anda: "
            f"`{message.from_user.id}`",
            parse_mode="Markdown",
        )
        return
    await message.answer(
        "🏭 *Bot Gudang 2 — Penyosohan*\n"
        "Terhubung. Fitur input penyosohan menyusul di fase berikutnya.\n\n"
        "Sudah bisa dipakai untuk tanya data, contoh:\n"
        "• `kode gabah dari catur`\n"
        "• `berapa gabah masuk hari ini`",
        parse_mode="Markdown",
    )


@router.message()
async def handle_message(message: Message) -> None:
    if not message.text:
        await message.answer("Kirim pesan teks ya.")
        return
    text = message.text.strip()
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await message.answer(
            f"⛔ Belum terdaftar. ID Telegram Anda: `{message.from_user.id}`",
            parse_mode="Markdown",
        )
        return

    # Transfer G1->G2 (laporan / arahan)?
    if await maybe_answer_transfer(message, text):
        return
    # Status proses berjalan?
    if await maybe_answer_status(message, text):
        return
    # Tugas tertunda?
    if await maybe_answer_pending(message, text):
        return
    # Detail/atribut entitas?
    if await maybe_answer_detail(message, text):
        return
    # Cari kode batch/lot?
    if await maybe_answer_lookup(message, text):
        return
    # Laporan pembelian gabah?
    if await maybe_answer_report(message, text):
        return
    await message.answer(
        "Bot Gudang 2 baru mendukung pertanyaan data pada fase ini. Contoh:\n"
        "• `kode gabah dari catur`\n"
        "• `berapa gabah masuk hari ini`\n"
        "Fitur input penyosohan menyusul.",
        parse_mode="Markdown",
    )
