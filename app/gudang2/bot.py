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
from app.gudang2.nlp import parse_penyosohan
from app.gudang2.polishing import (
    catat_output,
    laporan_penyosohan,
    mulai_penyosohan,
    selesai_penyosohan,
)
from app.inventory.nlp import parse_barang_jadi
from app.inventory.packaging import InventoryError
from app.inventory.finished_goods import (
    catat_bekatul,
    catat_packing,
    laporan_stok_barang_jadi,
)
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


async def _handle_penyosohan(message: Message, db, user, text: str) -> bool:
    """Aksi penyosohan Gudang 2. True jika ditangani."""
    try:
        p = await parse_penyosohan(text)
    except Exception:
        log.exception("parse_penyosohan gagal")
        return False
    if p.intent == "bukan_penyosohan":
        return False
    try:
        if p.intent == "mulai_penyosohan":
            r = await mulai_penyosohan(
                db, user=user, nama_silos=p.nama_silo_list, tanggal=p.tanggal, jam=p.jam,
            )
            await message.answer(
                f"✓ Mulai penyosohan *{r.proc.kode_proses}* dari Silo "
                f"{'+'.join(r.silos)}.\n• Bahan: {_kg(r.berat_awal_total)}\n"
                "Catat hasil berkala, mis. `hasil premium 5 ton`.",
                parse_mode="Markdown",
            )
        elif p.intent == "catat_output":
            r = await catat_output(
                db, user=user, kode=p.kode, jenis=p.jenis,
                berat_kumulatif=p.berat_kg, tanggal=p.tanggal, jam=p.jam,
            )
            await message.answer(
                f"✓ Hasil *{r.jenis}* {r.proc.kode_proses}: "
                f"{_kg(r.berat_kumulatif)} _(kumulatif)_.",
                parse_mode="Markdown",
            )
        elif p.intent == "selesai_penyosohan":
            r = await selesai_penyosohan(
                db, user=user, kode=p.kode, nama_silo=p.nama_silo,
                sisa_kg=p.berat_kg, tanggal=p.tanggal, jam=p.jam,
            )
            if r.selesai:
                rend = f" · rendemen {r.rendemen:.1f}%" if r.rendemen is not None else ""
                await message.answer(
                    f"✓ *{r.proc.kode_proses} selesai.* PK terpakai "
                    f"{_kg(r.pk_terpakai_total)} → beras {_kg(r.beras_total)}{rend}.\n"
                    "_QC & verifikasi output oleh staff/admin menyusul._",
                    parse_mode="Markdown",
                )
            else:
                await message.answer(
                    f"✓ Silo {r.silo} sisa dicatat (terpakai {_kg(r.terpakai_silo)}). "
                    "Silo lain di proses ini belum ditandai selesai."
                )
        elif p.intent == "laporan_penyosohan":
            await message.answer(await laporan_penyosohan(db, p.kode))
        else:
            return False
    except (Gudang2Error, BackdateError) as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan penyosohan.")
    return True


async def _handle_barang_jadi(message: Message, db, user, text: str) -> bool:
    """Packing hasil penyosohan + bekatul + stok barang jadi (operator G2)."""
    try:
        p = await parse_barang_jadi(text)
    except Exception:
        log.exception("parse_barang_jadi gagal")
        return False
    if p.intent == "bukan_barang_jadi":
        return False
    try:
        if p.intent == "packing":
            r = await catat_packing(
                db, user=user, kode_pol=p.kode, kategori=p.kategori, grade=p.grade,
                brand_nama=p.brand, material_kode=p.material, ukuran=p.ukuran_kg,
                jumlah_karung=p.jumlah_karung, tanggal=p.tanggal, jam=p.jam,
            )
            grade = f" {r.grade}" if r.grade else ""
            warn = f"\n{r.warning}" if r.warning else ""
            await message.answer(
                f"✓ Packing {r.kategori}{grade}: {r.jumlah_karung} karung "
                f"({_kg(r.berat_total_kg)}).{warn}"
            )
        elif p.intent == "catat_bekatul":
            kg = await catat_bekatul(
                db, user=user, kode_pol=p.kode, berat_kg=p.berat_kg,
                tanggal=p.tanggal, jam=p.jam,
            )
            await message.answer(f"✓ Bekatul {_kg(kg)} tercatat (curah).")
        elif p.intent == "laporan_barang_jadi":
            await message.answer(await laporan_stok_barang_jadi(db))
        elif p.intent in ("harga_byproduct", "laporan_hpp"):
            await message.answer(
                "ℹ️ Harga byproduct & HPP dikerjakan *Staff/Admin* di `@hmuadmin_bot`.",
                parse_mode="Markdown",
            )
        else:
            return False
    except (InventoryError, BackdateError) as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan barang jadi.")
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
        if await _handle_penyosohan(message, db, user, text):
            return
        if await _handle_barang_jadi(message, db, user, text):
            return
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
