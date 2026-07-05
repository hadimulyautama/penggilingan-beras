"""Alur agentic bersama semua bot: fallback tanya-jawab bebas + konfirmasi tulis.

Dipakai sebagai JARING TERAKHIR setelah semua handler deterministik (perintah &
laporan baku) tidak cocok. Agent (Sonnet) boleh memanggil banyak tool READ untuk
menjawab, atau MENGUSULKAN perintah tulis yang lalu dikonfirmasi & dijalankan
lewat jalur deterministik bot (callback `dispatch`).
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from aiogram.types import Message

from app.ai.agent import run_agent
from app.bots.common import CANCEL_WORDS, CONFIRM_WORDS

log = logging.getLogger("bots.agent")

# dispatch(text) -> True bila perintah dikenali & dijalankan handler deterministik.
Dispatch = Callable[[str], Awaitable[bool]]


async def agent_confirm_pending(
    message: Message, lower: str, session, *, dispatch: Dispatch
) -> bool:
    """Tangani jawaban atas usulan tulis agent. True bila sudah ditangani."""
    if session.stage != "awaiting_agent_write" or not session.agent_command:
        return False
    cmd = session.agent_command
    if lower in CONFIRM_WORDS:
        session.stage = "idle"
        session.agent_command = None
        handled = await dispatch(cmd)
        if not handled:
            await message.answer(
                "Perintah itu belum bisa dijalankan otomatis. "
                "Coba ketik langsung, mis. sesuai contoh di /start."
            )
        return True
    if lower in CANCEL_WORDS:
        session.stage = "idle"
        session.agent_command = None
        await message.answer("Baik, dibatalkan. 👍")
        return True
    # Selain ya/batal: batalkan usulan & biarkan pesan diproses sebagai giliran baru.
    session.stage = "idle"
    session.agent_command = None
    return False


async def maybe_answer_agent(
    message: Message,
    *,
    role: str,
    financial: bool,
    allow_write: bool,
    session,
) -> bool:
    """Jaring terakhir: jawab pertanyaan bebas / ajukan usulan tulis. Selalu True."""
    text = (message.text or "").strip()
    try:
        reply = await run_agent(
            text=text, role=role, financial=financial, allow_write=allow_write
        )
    except Exception:
        log.exception("run_agent gagal")
        await message.answer("⚠️ Maaf, ada kendala saat memproses. Coba ulangi ya.")
        return True

    if allow_write and reply.propose_command:
        session.agent_command = reply.propose_command
        session.stage = "awaiting_agent_write"
        ringkas = reply.propose_summary or reply.propose_command
        await message.answer(
            f"📝 Saya akan: {ringkas}\n"
            f"Perintah: `{reply.propose_command}`\n\n"
            "Balas *ya* untuk jalankan, atau *batal* untuk urungkan.",
            parse_mode="Markdown",
        )
        return True

    await message.answer(reply.text or "Maaf, saya belum bisa menjawab itu.")
    return True
