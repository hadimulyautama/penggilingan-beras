"""Pemantauan diri: denyut hidup + deteksi DOWNTIME.

Loop menulis `last_alive=now` tiap 2 menit. Saat STARTUP, bandingkan waktu sekarang
dengan denyut terakhir: bila jeda > 10 menit → bot sempat OFFLINE → kabari pemilik
("aku sempat offline ±X menit, sekarang online lagi"). Deploy normal (restart cepat)
jeda < 10 menit → senyap. Jadi pemilik tahu kalau asistennya sempat mati.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from app.config import settings
from app.database import SessionLocal
from app.kantor.models import Heartbeat

log = logging.getLogger("heartbeat")

_TICK = 120                 # tulis denyut tiap 2 menit
_AMBANG_DOWN = 12 * 60      # jeda > 12 menit = dianggap sempat offline
_WIB = timezone(timedelta(hours=7))


def _jam_wib(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_WIB).strftime("%H:%M %d/%m")


async def _tulis(now: datetime) -> None:
    async with SessionLocal() as db:
        row = await db.get(Heartbeat, 1)
        if row is None:
            db.add(Heartbeat(id=1, last_alive=now))
        else:
            row.last_alive = now
        await db.commit()


async def run_heartbeat(bots: dict[str, Bot]) -> None:
    bot = bots.get("kantor")
    now = datetime.now(timezone.utc)
    # STARTUP: deteksi downtime dari denyut terakhir
    try:
        async with SessionLocal() as db:
            row = await db.get(Heartbeat, 1)
        if row is not None:
            last = row.last_alive
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            jeda = (now - last).total_seconds()
            if jeda > _AMBANG_DOWN and bot and settings.admin_telegram_id:
                menit = int(jeda // 60)
                await bot.send_message(
                    settings.admin_telegram_id,
                    f"⚠️ Aku sempat OFFLINE ±{menit} menit "
                    f"(aktif terakhir {_jam_wib(last)} WIB). Sekarang online lagi 🟢")
        await _tulis(now)
    except Exception:  # noqa: BLE001
        log.exception("cek heartbeat startup gagal")
    # LOOP: perbarui denyut
    log.info("Heartbeat aktif (tiap %ss).", _TICK)
    while True:
        await asyncio.sleep(_TICK)
        try:
            await _tulis(datetime.now(timezone.utc))
        except Exception:  # noqa: BLE001
            log.warning("update heartbeat gagal", exc_info=True)
