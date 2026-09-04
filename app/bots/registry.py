"""Registry bot -> satu backend. Setiap bot punya Dispatcher sendiri.

Bot Kantor sudah pindah ke service sendiri — jangan didaftarkan lagi di sini.

**Bot operator (gudang1 & gudang2) DIHAPUS 3 September 2026.** Operator
mencatat pekerjaannya lewat Pos Produksi di peramban, dan Telegram tak lagi
punya peran bagi mereka: perangkat gudang dipakai bergantian, sedangkan akun
Telegram menempel pada orang — dua hal yang tidak pernah benar-benar cocok.
Yang tersisa hanya bot admin, untuk staff & Direksi.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent

from app.bots import admin
from app.config import settings

log = logging.getLogger("bots")

# Peta nama bot -> router handler-nya.
_ROUTERS = {
    "admin": admin.router,
}


async def _on_error(event: ErrorEvent) -> bool:
    """Jaring pengaman: apa pun error handler-nya, user tetap dapat balasan.

    Dikirim polos (tanpa Markdown) supaya tidak ikut gagal parse.
    """
    log.exception("Handler error", exc_info=event.exception)
    try:
        msg = getattr(event.update, "message", None)
        if msg is not None:
            await msg.answer("⚠️ Maaf, ada kendala teknis sesaat. Coba ulangi pesannya.")
    except Exception:
        log.exception("Gagal kirim pesan error fallback")
    return True


def build_bots() -> list[tuple[str, Bot, Dispatcher]]:
    """Bentuk (nama, Bot, Dispatcher) untuk setiap token yang terisi di .env."""
    built: list[tuple[str, Bot, Dispatcher]] = []
    for name, token in settings.bot_tokens.items():
        bot = Bot(token=token)
        dp = Dispatcher()
        dp.include_router(_ROUTERS[name])
        dp.errors.register(_on_error)
        built.append((name, bot, dp))
    return built


async def run_polling(built: list[tuple[str, Bot, Dispatcher]]) -> None:
    """Jalankan long-polling semua bot secara paralel."""
    if not built:
        log.warning("Tidak ada token bot terisi — tidak ada bot yang dijalankan.")
        return
    names = ", ".join(n for n, _, _ in built)
    log.info("Menjalankan bot: %s", names)
    await asyncio.gather(
        *(dp.start_polling(bot, handle_signals=False) for _, bot, dp in built)
    )
