"""Poller EMAIL TERPADU: pilah inbox → rapikan rutin (diam) + lapor yang penting.

Tiap 30 menit (24 jam), untuk tiap mailbox terkelola, pilah email inbox baru (Haiku):
  • 'rutin'   → ARSIP OTOMATIS, DIAM (notifikasi/promo/bank-info tak dilaporkan).
  • 'penting' → dikumpulkan → dikirim 1 pesan Telegram ke pemilik.
  • 'ragu'    → diusulkan arsip lewat gerbang tombol pemilik.
Menggantikan poller notifikasi terpisah → tak ada lagi 'ngeping' untuk email rutin.
Semua email yang dipilah dilabeli 'AI-Rapi-Cek' (tak diproses ulang → tak dobel lapor).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from app.config import settings
from app.kantor import mail_gmail, rapi

log = logging.getLogger("email.poller")

_TICK = 300
_WIB = timezone(timedelta(hours=7))
_INTERVAL = 30 * 60  # 30 menit
_CAP = 12


def _label(mb: str) -> str:
    return mb.split("@", 1)[0] + ("" if mb.endswith("@gmail.com") else "@")


async def _proses_semua() -> tuple[int, int, str]:
    """Return (jumlah_arsip, jumlah_usul, teks_notif_penting)."""
    from app.kantor import aturan
    arsip = usul = 0
    blok = []
    rules = await aturan.daftar()  # aturan pemilik, dicek deterministik dulu
    for mb in mail_gmail.daftar_mailbox():
        try:
            kandidat, lid = await asyncio.to_thread(mail_gmail.cari_rapi_kandidat, mb, _CAP)
        except Exception:  # noqa: BLE001
            log.warning("cari kandidat gagal untuk %s", mb, exc_info=True)
            continue
        penting = []
        for e in kandidat:
            try:
                hasil = await rapi.proses(mb, e, aturan_list=rules)
            except Exception:  # noqa: BLE001
                log.warning("proses email gagal", exc_info=True)
                hasil = "penting"
            if hasil == "arsip":
                arsip += 1
            elif hasil == "usul":
                usul += 1
            elif hasil == "penting":
                penting.append(e)
        if kandidat:
            try:
                await asyncio.to_thread(
                    mail_gmail.tandai_rapi_cek, mb, [e["id"] for e in kandidat], lid)
            except Exception:  # noqa: BLE001
                log.warning("label rapi-cek gagal untuk %s", mb, exc_info=True)
        if penting:
            baris = [f"• {e['from']} — {e['subject']}" for e in penting]
            blok.append(f"{_label(mb)} ({len(penting)}):\n" + "\n".join(baris))
    teks = ("📬 Email PENTING baru:\n\n" + "\n\n".join(blok) +
            "\n\n(Notifikasi rutin sudah kurapikan otomatis.)") if blok else ""
    return arsip, usul, teks


async def run_email_rapi_poller(bots: dict[str, Bot]) -> None:
    bot = bots.get("kantor")
    if bot is None or not settings.admin_telegram_id:
        log.warning("Poller email NONAKTIF (bot 'kantor'/ADMIN_TELEGRAM_ID kosong).")
        return
    if not mail_gmail.terkonfigurasi():
        log.warning("Gmail belum terkonfigurasi — poller email NONAKTIF.")
        return
    log.info("Poller email terpadu aktif (tiap %s menit, 24 jam → pemilik %s)",
             _INTERVAL // 60, settings.admin_telegram_id)
    terakhir: datetime | None = None
    while True:
        await asyncio.sleep(_TICK)
        try:
            now = datetime.now(timezone.utc)
            if terakhir is not None and (now - terakhir).total_seconds() < _INTERVAL:
                continue
            terakhir = now
            arsip, usul, teks = await _proses_semua()
            if teks:
                await bot.send_message(settings.admin_telegram_id, teks)
            if arsip or usul or teks:
                log.info("Email: %s diarsip (diam), %s diusulkan, lapor_penting=%s",
                         arsip, usul, bool(teks))
        except Exception:  # noqa: BLE001
            log.exception("Loop poller email gagal (lanjut)")
