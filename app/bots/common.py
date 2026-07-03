"""Utilitas bersama bot: autentikasi user & state percakapan in-memory."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.nlp_parser import ParsedPurchase, ParsedVerification
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
    # Override akses: admin/staff mengerjakan aksi fisik operator (fallback).
    override_text: str | None = None   # perintah yang menunggu konfirmasi override
    override_active: bool = False      # True saat re-run setelah override disetujui


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
