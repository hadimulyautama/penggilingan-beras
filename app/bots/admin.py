"""Bot Admin (Staff & Admin) — kerangka Fase 1.

Auth aktif + utilitas /whoami & /daftar untuk mendaftarkan operator baru.
Verifikasi harga, analitik, dsb. menyusul di fase berikutnya.
"""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from app.ai.nlp_parser import (
    ParsedVerification,
    parse_analitik,
    parse_milling_admin,
    parse_transfer,
    parse_undo,
    parse_user_admin,
    parse_verification,
)
from app.bots.common import (
    CANCEL_WORDS,
    CONFIRM_WORDS,
    authenticate,
    get_session,
    handle_shared_contact,
    reset_verif,
    unregistered_reply,
)
from app.bots.detail_flow import maybe_answer_detail
from app.bots.jam_flow import maybe_answer_jam
from app.bots.lookup_flow import maybe_answer_lookup
from app.bots.pending_flow import maybe_answer_pending
from app.bots.report_flow import maybe_answer_report
from app.bots.status_flow import maybe_answer_status
from app.database import SessionLocal
from app.models import User, Warehouse
from app.services.milling import (
    MillingError,
    log_qc_milling,
    verify_milling_output,
)
from app.services.transfer import (
    TransferError,
    create_internal_transfer,
    laporan_pk_siap_transfer,
    laporan_transfer,
)
from app.services.analytics import (
    biaya_produksi_detail,
    hpp_trend,
    simulasi_hpp,
    supplier_scorecard,
)
from app.services.report import resolve_batch_kode_ref
from app.services.undo import UndoError, resolve_actor_ids, undo_last
from app.services.user_admin import (
    UserAdminError,
    list_users,
    register_user,
    set_user_status,
)
from app.services.verification import (
    compute_price,
    get_batch_by_kode,
    verify_gabah_price,
)

router = Router(name="admin")
log = logging.getLogger("bots.admin")

AI_ERROR_MSG = (
    "⚠️ Layanan AI sedang tidak bisa dihubungi. Coba lagi sebentar lagi."
)


def _rp(n: float) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".")


# Jaring pengaman: kenali kode batch GB-YYYYMMDD-NN meski Claude ragu / meleset.
_GB_RE = re.compile(r"GB[-\s]?(\d{8})[-\s]?(\d{2})", re.IGNORECASE)
_MIL_RE = re.compile(r"MIL[-\s]?(\d{8})[-\s]?(\d{2})", re.IGNORECASE)


def _extract_kode(text: str) -> str | None:
    m = _GB_RE.search(text)
    return f"GB-{m.group(1)}-{m.group(2)}" if m else None


def _extract_mil(text: str) -> str | None:
    m = _MIL_RE.search(text)
    return f"MIL-{m.group(1)}-{m.group(2)}" if m else None


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await message.answer(
            "⛔ Belum terdaftar sebagai admin/staff. ID Telegram Anda: "
            f"`{message.from_user.id}`",
            parse_mode="Markdown",
        )
        return
    await message.answer(
        "👤 *Bot Admin / Staff*\n\n"
        "*Verifikasi harga gabah* — cukup ketik natural, contoh:\n"
        "• `verifikasi GB-20260702-01 total 42 juta`\n"
        "• `verifikasi harga GB-20260702-01 5.250 per kg`\n\n"
        "*Milling* (QC & output PK):\n"
        "• `QC MIL-20260702-01 kadar air 13 broken 5 kondisi KS`\n"
        "• `verifikasi output MIL-20260702-01 14 ton`\n\n"
        "*Kelola pengguna* (admin) — ketik natural:\n"
        "• `daftarkan operator Budi id 12345678 gudang 1`\n"
        "• `tambah staff Sari hp 081234567890`\n"
        "• `daftar user` · `nonaktifkan Budi`\n"
        "  (via HP: orangnya tekan tombol *Bagikan Nomor HP* untuk aktivasi)\n\n"
        "Perintah lain:\n"
        "• `/whoami` — lihat identitas Anda",
        parse_mode="Markdown",
    )


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await message.answer(f"Belum terdaftar. ID: `{message.from_user.id}`", parse_mode="Markdown")
        return
    await message.answer(
        f"Nama: {user.nama}\nRole: {user.role}\nAkses: {user.access_level}",
    )


@router.message(Command("daftar"))
async def cmd_daftar(message: Message) -> None:
    """Daftarkan pengguna baru. Hanya admin. Format: /daftar <tg_id> <nama> <role>."""
    async with SessionLocal() as db:
        actor = await authenticate(db, message.from_user.id)
        if not actor or actor.role != "admin":
            await message.answer("⛔ Hanya admin yang bisa mendaftarkan pengguna.")
            return

        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.answer(
                "Format: `/daftar <telegram_id> <nama> <role>`\n"
                "Contoh: `/daftar 12345678 Budi operator`",
                parse_mode="Markdown",
            )
            return
        _, tg_id_str, nama, role = parts
        if role not in {"operator", "staff", "admin"}:
            await message.answer("Role harus: operator | staff | admin")
            return
        try:
            tg_id = int(tg_id_str)
        except ValueError:
            await message.answer("telegram_id harus angka.")
            return

        exists = (
            await db.execute(select(User).where(User.telegram_user_id == tg_id))
        ).scalars().first()
        if exists:
            await message.answer(f"ID {tg_id} sudah terdaftar sebagai {exists.nama}.")
            return

        # Operator Gudang 1 default ke gudang pertama (Selepan).
        g1 = (
            await db.execute(select(Warehouse).order_by(Warehouse.id))
        ).scalars().first()
        db.add(
            User(
                nama=nama,
                role=role,
                telegram_user_id=tg_id,
                default_warehouse_id=g1.id if g1 else None,
                access_level="full" if role in {"admin", "staff"} else "operational",
            )
        )
        await db.commit()
        await message.answer(f"✓ {nama} terdaftar sebagai {role} (ID {tg_id}).")


@router.message(F.contact)
async def on_contact(message: Message) -> None:
    """Aktivasi akun via kontak (untuk user yang didaftarkan pakai nomor HP)."""
    await handle_shared_contact(message)


def _merge_verif(cur: ParsedVerification, new: ParsedVerification) -> ParsedVerification:
    """Isi field yang masih kosong dari jawaban lanjutan staff."""
    return ParsedVerification(
        is_verifikasi_harga=True,
        kode_batch=new.kode_batch or cur.kode_batch,
        metode_harga=new.metode_harga or cur.metode_harga,
        nilai_rupiah=new.nilai_rupiah if new.nilai_rupiah is not None else cur.nilai_rupiah,
    )


def _pct(v: float | None) -> str:
    return f"{v:g}%" if v is not None else "-"


def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def _handle_analitik(message: Message, db, text: str) -> bool:
    """Analitik strategis: supplier scorecard & tren HPP. True jika ditangani."""
    try:
        p = await parse_analitik(text)
    except Exception:
        log.exception("parse_analitik gagal")
        return False
    if p.intent == "supplier_scorecard":
        await message.answer(await supplier_scorecard(db), parse_mode="Markdown")
        return True
    if p.intent == "hpp_tren":
        await message.answer(await hpp_trend(db), parse_mode="Markdown")
        return True
    if p.intent == "rincian_biaya":
        kode = p.kode_proses or _extract_kode(text)
        await message.answer(await biaya_produksi_detail(db, kode), parse_mode="Markdown")
        return True
    if p.intent == "simulasi_hpp":
        await message.answer(
            simulasi_hpp(
                p.harga_gabah, p.rendemen,
                kondisi=p.kondisi or "basah", langsung_silo=p.langsung_silo,
            ),
            parse_mode="Markdown",
        )
        return True
    return False


async def _handle_undo_admin(message: Message, db, user, text: str) -> bool:
    """Admin undo tindakan terakhir (bisa dibatasi per orang/role). True jika ditangani."""
    try:
        p = await parse_undo(text)
    except Exception:
        log.exception("parse_undo gagal")
        return False
    if not p.is_undo:
        return False
    if user.role != "admin":
        await message.answer("⛔ Hanya admin yang bisa membatalkan input pengguna lain.")
        return True
    try:
        ids, label = await resolve_actor_ids(
            db, scope=p.scope, nama=p.nama, self_id=user.id
        )
        msg = await undo_last(db, actor=user, actor_ids=ids, scope_label=label)
        await message.answer(msg)
    except UndoError as e:
        await message.answer(str(e.args[0]) if e.args else "Tidak bisa di-undo.")
    return True


async def _handle_user_admin(message: Message, db, user, text: str) -> bool:
    """Kelola pengguna (admin): daftar/list/aktif/nonaktif. True jika ditangani."""
    try:
        p = await parse_user_admin(text)
    except Exception:
        log.exception("parse_user_admin gagal")
        return False
    if p.intent == "bukan_user":
        return False
    try:
        if p.intent == "daftar_user":
            teks = await register_user(
                db, actor=user, nama=p.nama, role=p.role, gudang=p.gudang,
                telegram_id=p.telegram_id, no_hp=p.no_hp,
            )
        elif p.intent == "list_user":
            teks = await list_users(db)
        elif p.intent == "aktifkan_user":
            teks = await set_user_status(db, actor=user, ref=p.ref or p.nama, aktif=True)
        elif p.intent == "nonaktifkan_user":
            teks = await set_user_status(db, actor=user, ref=p.ref or p.nama, aktif=False)
        else:
            return False
    except UserAdminError as e:
        await message.answer(str(e.args[0]) if e.args else "Kesalahan kelola user.", parse_mode="Markdown")
        return True
    await message.answer(teks, parse_mode="Markdown")
    return True


async def _handle_transfer(message: Message, db, user, text: str, session) -> bool:
    """Buat transfer G1->G2 / laporan (staff/admin). True jika ditangani."""
    try:
        p = await parse_transfer(text)
    except Exception:
        log.exception("parse_transfer gagal")
        return False
    if p.intent == "bukan_transfer":
        return False

    try:
        if p.intent == "buat_transfer":
            kode = p.kode_proses or _extract_mil(text) or session.ctx_mil
            if not kode:
                await message.answer(
                    "Sebutkan proses milling sumbernya, contoh:\n"
                    "`transfer PK MIL-20260702-01 ke silo A`",
                    parse_mode="Markdown",
                )
                return True
            if p.lokasi_tujuan not in ("silo_a", "silo_b", "ditumpuk"):
                await message.answer(
                    "Ditransfer ke mana di Gudang 2 — *Silo A*, *Silo B*, atau "
                    "*tumpukan*?",
                    parse_mode="Markdown",
                )
                return True
            r = await create_internal_transfer(
                db, user=user, kode_proses=kode, lokasi_tujuan=p.lokasi_tujuan
            )
            session.ctx_mil = r.kode_proses
            hpp = (
                f"\n• HPP snapshot: {_rp(float(r.hpp_per_kg))}/kg"
                if r.hpp_per_kg is not None
                else "\n• HPP: belum tersedia (output milling belum diverifikasi)"
            )
            await message.answer(
                f"✓ Transfer *{r.transfer.kode_transfer}*: "
                f"{_kg(float(r.transfer.berat_kg))} PK dari {r.kode_proses} → "
                f"{r.lokasi_label} Gudang 2.{hpp}",
                parse_mode="Markdown",
            )
        elif p.intent == "laporan_siap_transfer":
            await message.answer(await laporan_pk_siap_transfer(db))
        elif p.intent == "laporan_transfer":
            await message.answer(await laporan_transfer(db))
        else:
            return False
    except TransferError as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan transfer.")
    return True


async def _handle_milling_admin(message: Message, db, user, text: str, session) -> bool:
    """QC / verifikasi output milling (staff/admin). True jika ditangani."""
    try:
        p = await parse_milling_admin(text)
    except Exception:
        log.exception("parse_milling_admin gagal")
        return False
    if p.intent == "bukan_milling_admin":
        return False

    kode = p.kode_proses or _extract_mil(text) or session.ctx_mil
    try:
        if p.intent == "qc_milling":
            r = await log_qc_milling(
                db, user=user, kode_proses=kode, kadar_air=p.kadar_air,
                broken=p.broken_persen, susut=p.susut_persen, kondisi=p.kondisi,
            )
            session.ctx_mil = r.proc.kode_proses
            await message.answer(
                f"✓ QC {r.proc.kode_proses} tercatat (QC ke-{r.qc_count}).\n"
                f"• Kadar air: {_pct(r.kadar_air)} | Broken: {_pct(r.broken)} | "
                f"Susut: {_pct(r.susut)} | Kondisi: {r.kondisi or '-'}"
            )
        elif p.intent == "verifikasi_output":
            r = await verify_milling_output(
                db, user=user, kode_proses=kode, berat_output=p.berat_output_kg
            )
            session.ctx_mil = r.proc.kode_proses
            rend = f"\n• Rendemen: {r.rendemen_persen:.1f}%" if r.rendemen_persen else ""
            tag = "diperbarui" if r.re_verified else "tersimpan"
            total = f"{r.berat_output:,.0f}".replace(",", ".")
            await message.answer(
                f"✓ Verifikasi output {tag}. *{r.proc.kode_proses}*\n"
                f"• Output PK final: {total} kg{rend}",
                parse_mode="Markdown",
            )
        else:
            return False
    except MillingError as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan milling.")
    return True


@router.message()
async def handle_message(message: Message) -> None:
    if not message.text:
        await message.answer("Kirim pesan teks ya.")
        return

    tg_id = message.from_user.id
    text = message.text.strip()
    lower = text.lower()

    async with SessionLocal() as db:
        user = await authenticate(db, tg_id)
        if not user:
            await unregistered_reply(message)
            return
        if user.role not in {"admin", "staff"}:
            await message.answer(
                "⛔ Bot Admin khusus *Staff/Admin* (verifikasi harga, QC, output PK).\n"
                "Sebagai *Operator*, gunakan `@selepan_bot` untuk input fisik Gudang 1 "
                "(pembelian, pengeringan, silo, milling).",
                parse_mode="Markdown",
            )
            return

        session = get_session(message.bot.id, tg_id)

        # ── Menunggu konfirmasi verifikasi ──
        if session.stage == "awaiting_verif_confirmation" and session.verif_draft:
            if lower in CONFIRM_WORDS:
                await _save_verification(message, db, user, session)
                return
            if lower in CANCEL_WORDS:
                reset_verif(message.bot.id, tg_id)
                await message.answer("Baik, verifikasi dibatalkan.")
                return
            # anggap koreksi/pelengkap
            try:
                new = await parse_verification(text)
            except Exception:
                log.exception("parse_verification gagal")
                await message.answer(AI_ERROR_MSG)
                return
            session.verif_draft = _merge_verif(session.verif_draft, new)
            await _advance_verif(message, db, tg_id, session)
            return

        # ── Sedang melengkapi data verifikasi ──
        if session.stage == "collecting_verif" and session.verif_draft:
            try:
                new = await parse_verification(text)
            except Exception:
                log.exception("parse_verification gagal")
                await message.answer(AI_ERROR_MSG)
                return
            session.verif_draft = _merge_verif(session.verif_draft, new)
            await _advance_verif(message, db, tg_id, session)
            return

        # ── Analitik strategis (scorecard supplier / tren HPP) ──
        if await _handle_analitik(message, db, text):
            return

        # ── Undo tindakan terakhir (bisa per orang/role) ──
        if await _handle_undo_admin(message, db, user, text):
            return

        # ── Kelola pengguna (daftar/list/aktif/nonaktif) ──
        if await _handle_user_admin(message, db, user, text):
            return

        # ── Transfer G1->G2 (buat / laporan) ──
        if await _handle_transfer(message, db, user, text, session):
            return

        # ── Aksi milling (QC / verifikasi output) — cek sebelum verifikasi harga ──
        if await _handle_milling_admin(message, db, user, text, session):
            return

        # ── Verifikasi/penetapan harga gabah — cek SEBELUM detail, karena
        #    "gabah pertama harganya 7500/kg" itu PERINTAH, bukan pertanyaan ──
        try:
            parsed = await parse_verification(text)
        except Exception:
            log.exception("parse_verification gagal")
            await message.answer(AI_ERROR_MSG)
            return
        # Jaring pengaman: lengkapi kode bila terlewat. Paksa jadi verifikasi
        # HANYA bila ada NILAI harga (perintah) — jangan untuk pertanyaan
        # seperti "berapa harga GB-..." (itu biar ditangani modul detail).
        kode_regex = _extract_kode(text)
        if kode_regex:
            parsed.kode_batch = parsed.kode_batch or kode_regex
            if parsed.nilai_rupiah is not None:
                parsed.is_verifikasi_harga = True

        if parsed.is_verifikasi_harga:
            # Resolusi rujukan batch: kode > deskriptif (urutan/supplier/
            # terbaru) > konteks percakapan.
            if not parsed.kode_batch:
                if parsed.urutan or parsed.supplier_nama or parsed.terbaru:
                    kodes = await resolve_batch_kode_ref(
                        db, urutan=parsed.urutan, supplier=parsed.supplier_nama,
                        terbaru=parsed.terbaru,
                    )
                    if len(kodes) == 1:
                        parsed.kode_batch = kodes[0]
                    elif len(kodes) > 1:
                        await message.answer(
                            "Batch mana yang dimaksud? " + ", ".join(kodes[:10])
                            + "\nSebutkan kodenya, mis. `" + kodes[0] + " 7500 per kg`.",
                            parse_mode="Markdown",
                        )
                        return
                    # 0 -> biarkan _advance_verif menanyakan kode.
                else:
                    parsed.kode_batch = session.ctx_batch
            session.verif_draft = parsed
            await _advance_verif(message, db, tg_id, session)
            return

        # ── Status proses berjalan ("proses apa yang sedang berlangsung") ──
        if await maybe_answer_status(message, text):
            return

        # ── Pertanyaan tugas tertunda ("ada yang perlu diverifikasi?") ──
        if await maybe_answer_pending(message, text):
            return

        # ── Pola jam kedatangan gabah ("jam berapa biasanya gabah masuk") ──
        if await maybe_answer_jam(message, text):
            return

        # ── Detail/atribut entitas ("berapa harga gabah pertama") ──
        if await maybe_answer_detail(message, text, session):
            return

        # ── Mencari kode batch/lot ("batch dari budi kodenya apa")? ──
        if await maybe_answer_lookup(message, text, session):
            return

        # ── Pertanyaan laporan ("berapa gabah masuk hari ini")? ──
        if await maybe_answer_report(message, text, session):
            return

        await message.answer(
            "Belum paham 🙏. Contoh yang bisa saya lakukan:\n"
            "• Cek tugas: `ada yang perlu diverifikasi?`\n"
            "• Verifikasi harga: `verifikasi GB-20260702-01 total 42 juta`\n"
            "• QC milling: `QC MIL-20260702-01 kadar air 13 broken 5 kondisi KS`\n"
            "• Verifikasi output: `verifikasi output MIL-20260702-01 14 ton`\n"
            "• Cari kode: `batch dari budi kodenya apa`\n"
            "Atau /start untuk bantuan.",
            parse_mode="Markdown",
        )


async def _advance_verif(message: Message, db, tg_id: int, session) -> None:
    """Cek kelengkapan draft verifikasi, tanya yang kurang, atau tampilkan ringkasan."""
    d = session.verif_draft

    if not d.kode_batch:
        session.stage = "collecting_verif"
        await message.answer("Sebutkan kode batch, contoh: `GB-20260702-01`", parse_mode="Markdown")
        return

    batch = await get_batch_by_kode(db, d.kode_batch)
    if batch is None:
        session.stage = "collecting_verif"
        await message.answer(f"Batch *{d.kode_batch}* tidak ditemukan. Cek lagi kodenya.", parse_mode="Markdown")
        return

    if d.nilai_rupiah is None:
        session.stage = "collecting_verif"
        await message.answer("Berapa harganya? (mis. `total 42 juta` atau `5.250 per kg`)", parse_mode="Markdown")
        return

    if d.metode_harga not in {"total", "per_kg"}:
        session.stage = "collecting_verif"
        await message.answer("Nilai itu *total biaya* atau *harga per kg*?", parse_mode="Markdown")
        return

    # Lengkap → ringkasan + konfirmasi.
    berat = float(batch.berat_total_kg)
    total, per_kg = compute_price(berat, d.metode_harga, d.nilai_rupiah)
    session.stage = "awaiting_verif_confirmation"
    warn = ""
    if not batch.flag_unverified:
        warn = "\n_⚠️ Batch ini sudah pernah diverifikasi — akan ditimpa._"
    await message.answer(
        f"Verifikasi *{batch.kode_batch}*:\n"
        f"• Berat: {berat:,.0f} kg\n".replace(",", ".")
        + f"• Total biaya: {_rp(total)}\n"
        f"• Harga per kg: {_rp(per_kg)}\n"
        f"Konfirmasi? (ketik *ya* / *batal*){warn}",
        parse_mode="Markdown",
    )


async def _save_verification(message: Message, db, user, session) -> None:
    d = session.verif_draft
    batch = await get_batch_by_kode(db, d.kode_batch)
    if batch is None:
        reset_verif(message.bot.id, message.from_user.id)
        await message.answer("Batch tidak ditemukan lagi. Ulangi dari awal.")
        return
    result = await verify_gabah_price(
        db, user=user, batch=batch, metode=d.metode_harga, nilai_rupiah=d.nilai_rupiah
    )
    session.ctx_batch = batch.kode_batch
    reset_verif(message.bot.id, message.from_user.id)
    tag = "diperbarui" if result.re_verified else "tersimpan"
    await message.answer(
        f"✓ Verifikasi {tag}. *{batch.kode_batch}* ({result.supplier_nama})\n"
        f"• Total: {_rp(result.total_biaya)} | Per kg: {_rp(result.harga_per_kg)}\n"
        "Flag menunggu-verifikasi dihapus.",
        parse_mode="Markdown",
    )
