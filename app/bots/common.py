"""Utilitas bersama bot: autentikasi user & state percakapan in-memory."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.nlp_parser import ParsedPurchase, ParsedVerification
from app.database import SessionLocal
from app.models import User

# ── Kata kunci sederhana (hemat panggilan AI untuk hal yang pasti) ──
CONFIRM_WORDS = {"ya", "iya", "y", "betul", "benar", "simpan", "ok", "oke", "sip", "gas", "yoi", "yup"}
CANCEL_WORDS = {"batal", "batalkan", "cancel", "gak", "nggak", "tidak", "no", "gajadi", "gngjadi"}
UNDO_PHRASES = ("batalkan input", "batal input", "undo", "hapus input", "batalkan tadi")


async def authenticate(db: AsyncSession, telegram_user_id: int) -> User | None:
    """Kembalikan User terdaftar berdasarkan telegram_user_id, atau None."""
    stmt = select(User).where(
        User.telegram_user_id == telegram_user_id, User.status == "aktif"
    )
    return (await db.execute(stmt)).scalars().first()


def can_see_financials(user: User | None) -> bool:
    """Hanya staff/admin boleh melihat data uang (harga gabah, nilai total
    pembelian, HPP). Operator TIDAK boleh."""
    return bool(user) and user.role in ("admin", "staff")


def can_transfer_pk(user: User | None) -> bool:
    """Pengiriman PK Gudang 1 → Gudang 2 hanya oleh staff (pelaksana utama);
    admin diizinkan sebagai override. Operator TIDAK boleh."""
    return bool(user) and user.role in ("staff", "admin")


async def user_wh_scope(db: AsyncSession, user: User | None) -> str:
    """Lingkup akses gudang user:
    - 'all'  : staff/admin (lihat & kerjakan semua)
    - 'g1'   : operator Gudang 1 (hanya Gudang 1)
    - 'g2'   : operator Gudang 2 (hanya Gudang 2)
    - 'none' : operator tanpa gudang / lainnya.
    Operator Gudang 1 & 2 dipisah tegas: tak boleh lintas gudang."""
    if not user:
        return "none"
    if user.role in ("admin", "staff"):
        return "all"
    if user.role == "operator" and user.default_warehouse_id:
        from app.models import Warehouse
        wh = await db.get(Warehouse, user.default_warehouse_id)
        nama = (wh.nama_gudang if wh else "") or ""
        if nama.startswith("Gudang 1"):
            return "g1"
        if nama.startswith("Gudang 2"):
            return "g2"
    return "none"


def share_contact_keyboard() -> ReplyKeyboardMarkup:
    """Tombol untuk membagikan nomor HP (aktivasi user pra-daftar via HP)."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Bagikan Nomor HP", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def unregistered_reply(message: Message) -> None:
    """Balasan standar untuk pengirim yang belum terdaftar (+ tombol kontak)."""
    await message.answer(
        "⛔ Nomor Telegram Anda belum terdaftar.\n"
        f"ID Telegram Anda: `{message.from_user.id}`\n\n"
        "Kalau admin sudah mendaftarkan Anda pakai *nomor HP*, tekan tombol "
        "*📱 Bagikan Nomor HP* di bawah untuk aktivasi otomatis. "
        "Kalau belum, sebutkan ID di atas ke admin.",
        parse_mode="Markdown",
        reply_markup=share_contact_keyboard(),
    )


async def handle_shared_contact(message: Message) -> None:
    """Tangani kontak yang dibagikan: cocokkan nomor HP -> aktifkan akun."""
    from app.services.user_admin import link_by_contact

    contact = message.contact
    # Hanya boleh mengaktifkan kontak MILIK SENDIRI.
    if contact is None or contact.user_id != message.from_user.id:
        await message.answer(
            "Mohon bagikan kontak *Anda sendiri* (tombol di bawah).",
            parse_mode="Markdown",
            reply_markup=share_contact_keyboard(),
        )
        return
    async with SessionLocal() as db:
        user = await link_by_contact(
            db, telegram_id=message.from_user.id, phone=contact.phone_number,
            nama=(contact.first_name or None),
        )
    if user is None:
        await message.answer(
            "Nomor HP Anda belum terdaftar oleh admin. "
            f"Sebutkan ID ini ke admin: `{message.from_user.id}`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    await message.answer(
        f"✅ Akun aktif! Selamat datang, *{user.nama}* ({user.role}).",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )


@dataclass
class UserSession:
    """State percakapan sementara per user (in-memory).

    Fase berikutnya: dipindah ke tabel wa_sessions agar persisten.
    """

    stage: str = "idle"  # idle | collecting | awaiting_confirmation | awaiting_verif_confirmation
    draft: ParsedPurchase | None = None
    last_batch_id: int | None = None
    last_batch_kode: str | None = None
    last_batch_time: datetime | None = None
    # Verifikasi harga gabah (Bot Admin).
    verif_draft: ParsedVerification | None = None
    # Konteks percakapan: entitas terakhir yang disebut, agar pengguna bisa
    # merujuk "itu / tadi / barusan" atau menghilangkan kode sama sekali.
    ctx_batch: str | None = None  # GB-...
    ctx_lot: str | None = None    # LOT-...
    ctx_mil: str | None = None    # MIL-...
    ctx_silo: str | None = None   # A | B
    ctx_last: str | None = None   # jenis entitas terakhir: batch|lot|mil|silo
    # Konteks tanya-jawab beruntun (mis. "berapa batch hari ini" -> "apa saja
    # kodenya"): subjek & periode terakhir yang ditanyakan.
    ctx_topic: str | None = None    # batch | lot
    ctx_periode: str | None = None  # hari_ini | kemarin | minggu_ini | ...
    ctx_tanggal: object | None = None  # datetime.date spesifik (bila ditanya)
    # Konfirmasi gabung batch ke lot yang masih di dryer.
    merge_lot: str | None = None
    merge_kodes: list | None = None
    # Override akses: admin/staff mengerjakan aksi fisik operator (fallback).
    override_text: str | None = None   # perintah yang menunggu konfirmasi override
    override_active: bool = False      # True saat re-run setelah override disetujui
    # Agent (pola agentic): perintah TULIS yang diusulkan agent & menunggu
    # konfirmasi. stage 'awaiting_agent_write' saat aktif.
    agent_command: str | None = None
    # Kantor AI: aksi konsekuensial (dokumen/arsip) yang diusulkan & menunggu
    # konfirmasi. stage 'awaiting_kantor' saat aktif. Isi: {jenis,params,ringkasan}.
    kantor_pending: dict | None = None
    # Melengkapi data pembelian yang belum lengkap (bot tanya field kurang).
    # Simpan teks TERKUMPUL; tiap jawaban ditambahkan lalu di-parse ulang.
    kemasan_text: str | None = None  # stage 'awaiting_kemasan'
    pk_text: str | None = None       # stage 'awaiting_pk'
    # Gabah KERING menunggu tujuan (dryer / silo A / silo B). stage
    # 'awaiting_kering_tujuan'; simpan kode batch-nya.
    kering_batch: str | None = None


# Penyimpanan sesi in-memory, dikunci per (bot_id, telegram_user_id).
#
# Dikunci per bot — bukan hanya per user — karena satu orang (mis. admin)
# bisa memakai >1 bot dengan telegram_user_id yang sama. Tanpa namespace bot,
# draft/stage bocor antar bot dan menyebabkan salah-routing pesan
# (mis. stage 'awaiting_confirmation' dari Bot G1 ikut memengaruhi Bot Admin).
#
# Fase berikutnya: dipindah ke tabel wa_sessions (persisten); kunci komposit
# (bot_id, user) ini tinggal jadi primary key gabungan di sana.
_sessions: dict[tuple[int, int], UserSession] = {}


def get_session(bot_id: int, telegram_user_id: int) -> UserSession:
    return _sessions.setdefault((bot_id, telegram_user_id), UserSession())


def reset_draft(bot_id: int, telegram_user_id: int) -> None:
    s = get_session(bot_id, telegram_user_id)
    s.stage = "idle"
    s.draft = None


def reset_verif(bot_id: int, telegram_user_id: int) -> None:
    s = get_session(bot_id, telegram_user_id)
    s.stage = "idle"
    s.verif_draft = None
