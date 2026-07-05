"""Bot Gudang 2 (Operator Penyosohan).

Aksi operator G2: terima kiriman PK dari G1, masukkan PK ke silo/tumpukan,
pindah tumpukan→silo (khusus operator G2), tanya stok. Beli PK luar + QC =
staff/admin di @hmuadmin_bot.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.ai.nlp_parser import parse_gudang2
from app.bots.common import (
    authenticate,
    can_see_financials,
    handle_shared_contact,
    unregistered_reply,
)
from app.bots.detail_flow import maybe_answer_detail
from app.bots.lookup_flow import maybe_answer_lookup
from app.bots.pending_flow import maybe_answer_pending
from app.bots.report_flow import maybe_answer_report
from app.bots.silo_flow import maybe_answer_silo_report
from app.bots.status_flow import maybe_answer_status
from app.bots.transfer_flow import maybe_answer_transfer
from app.database import BackdateError, SessionLocal
from app.gudang2.service import (
    Gudang2Error,
    laporan_stok_gudang2,
    masukkan_pk_luar,
    pindah_tumpukan,
    terima_transfer_g1,
)

router = Router(name="gudang2")
log = logging.getLogger("bots.gudang2")


def _kg(kg: float | None) -> str:
    return f"{kg:,.0f} kg".replace(",", ".") if kg is not None else "-"


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await unregistered_reply(message)
        return
    await message.answer(
        "🏭 *Bot Gudang 2 — Penyosohan*\n"
        "Contoh perintah:\n"
        "• `terima TRF-20260704-01 ke silo A`\n"
        "• `pindah tumpukan ke silo B` / `pindah 3 ton ke silo A`\n"
        "• `stok silo A` / `stok gudang 2`\n\n"
        "_Beli PK luar & QC dikerjakan Staff/Admin di_ `@hmuadmin_bot`.",
        parse_mode="Markdown",
    )


@router.message(F.contact)
async def on_contact(message: Message) -> None:
    """Aktivasi akun via kontak (untuk user yang didaftarkan pakai nomor HP)."""
    await handle_shared_contact(message)


async def _handle_gudang2(message: Message, db, user, text: str) -> bool:
    """Aksi Gudang 2. True jika ditangani."""
    try:
        p = await parse_gudang2(text)
    except Exception:
        log.exception("parse_gudang2 gagal")
        return False
    if p.intent == "bukan_gudang2":
        return False
    fin = can_see_financials(user)
    try:
        if p.intent == "terima_transfer":
            r = await terima_transfer_g1(
                db, user=user, kode_transfer=p.kode, tujuan=p.tujuan,
                tanggal=p.tanggal, jam=p.jam,
            )
            hpp = (
                f" · HPP {_rp(r.hpp_per_kg)}/kg"
                if r.hpp_per_kg is not None and fin else ""
            )
            await message.answer(
                f"✓ Diterima {p.kode} → {r.lokasi_label} Gudang 2: "
                f"{_kg(float(r.intake.berat_kg))}{hpp}"
            )
        elif p.intent == "masukkan_pk":
            r = await masukkan_pk_luar(
                db, user=user, kode=p.kode, tujuan=p.tujuan,
                tanggal=p.tanggal, jam=p.jam,
            )
            await message.answer(
                f"✓ {p.kode} masuk {r.lokasi_label} Gudang 2: "
                f"{_kg(float(r.intake.berat_kg))}"
            )
        elif p.intent == "pindah_tumpukan":
            r = await pindah_tumpukan(
                db, user=user, nama_silo=p.nama_silo, berat=p.berat_kg,
                tanggal=p.tanggal, jam=p.jam,
            )
            await message.answer(
                f"✓ Pindah {_kg(r.moved_kg)} dari tumpukan → *Silo {r.nama_silo}* "
                f"({len(r.kodes)} batch).\n• Sisa tumpukan: {_kg(r.sisa_tumpukan)}",
                parse_mode="Markdown",
            )
        elif p.intent == "laporan_stok_g2":
            await message.answer(await laporan_stok_gudang2(db, p.nama_silo, financial=fin))
        elif p.intent in ("beli_pk_luar", "verifikasi_pk_luar"):
            await message.answer(
                "ℹ️ Beli PK dari luar & QC/verifikasi dikerjakan *Staff/Admin* di "
                "`@hmuadmin_bot`.",
                parse_mode="Markdown",
            )
        else:
            return False
    except (Gudang2Error, BackdateError) as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan Gudang 2.")
    return True


@router.message()
async def handle_message(message: Message) -> None:
    if not message.text:
        await message.answer("Kirim pesan teks ya.")
        return
    text = message.text.strip()
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
        if not user:
            await unregistered_reply(message)
            return

        fin = can_see_financials(user)
        # Aksi Gudang 2 (tulis) — cek dulu sebelum flow baca.
        if await _handle_gudang2(message, db, user, text):
            return
        if await maybe_answer_transfer(message, text, financial=fin):
            return
        if await maybe_answer_silo_report(message, text):
            return
        if await maybe_answer_status(message, text):
            return
        if await maybe_answer_pending(message, text):
            return
        if await maybe_answer_detail(message, text, financial=fin):
            return
        if await maybe_answer_lookup(message, text):
            return
        if await maybe_answer_report(message, text):
            return
    await message.answer(
        "Maaf, belum paham. Contoh:\n"
        "• `terima TRF-... ke silo A`\n"
        "• `pindah tumpukan ke silo B`\n"
        "• `stok gudang 2`",
        parse_mode="Markdown",
    )
