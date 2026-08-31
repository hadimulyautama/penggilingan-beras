"""Poller PEMINDAI TAGIHAN (Fase 2b): scan email → usul pengingat tenggat.

Tiap ~3 jam (06:00–22:00 WIB), untuk tiap mailbox terkelola: cari email kandidat
tagihan (belum dicek), minta Haiku menilai + ekstrak tenggat, dan bila valid →
ajukan aksi `kalender_buat` ke gerbang tombol pemilik (persetujuan_poller yang
mengirim ✅/❌). Semua email kandidat DILABELI 'AI-Tagihan-Dicek' agar tak diproses
ulang (baik diusulkan maupun tidak).

Read-only terhadap email (hanya menambah label). Tenggat tak pernah masuk kalender
tanpa persetujuan pemilik.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from app.config import settings
from app.kantor import billing, mail_gmail

log = logging.getLogger("billing.poller")

_TICK = 300
_INTERVAL = 3 * 3600  # tiap 3 jam
_CAP = 8


async def _pindai_sekali() -> int:
    diusulkan = 0
    for mb in mail_gmail.daftar_mailbox():
        try:
            kandidat, lid = await asyncio.to_thread(mail_gmail.cari_tagihan_kandidat, mb, _CAP)
        except Exception:  # noqa: BLE001
            log.warning("cari kandidat tagihan gagal untuk %s", mb, exc_info=True)
            continue
        for e in kandidat:
            try:
                if await billing.proses_email_tagihan(mb, e):
                    diusulkan += 1
            except Exception:  # noqa: BLE001
                log.warning("proses tagihan gagal", exc_info=True)
        if kandidat:
            try:
                await asyncio.to_thread(
                    mail_gmail.tandai_tagihan_dicek, mb, [e["id"] for e in kandidat], lid)
            except Exception:  # noqa: BLE001
                log.warning("label tagihan gagal untuk %s", mb, exc_info=True)
    return diusulkan


async def run_billing_poller(bots: dict[str, Bot]) -> None:
    bot = bots.get("kantor")
    if bot is None or not settings.admin_telegram_id:
        log.warning("Pemindai tagihan NONAKTIF (bot 'kantor'/ADMIN_TELEGRAM_ID kosong).")
        return
    if not mail_gmail.terkonfigurasi():
        log.warning("Gmail belum terkonfigurasi — pemindai tagihan NONAKTIF.")
        return
    log.info("Pemindai tagihan aktif (tiap %sh, 24 jam)", _INTERVAL // 3600)
    terakhir: datetime | None = None
    while True:
        await asyncio.sleep(_TICK)
        try:
            now = datetime.now(timezone.utc)
            if terakhir is not None and (now - terakhir).total_seconds() < _INTERVAL:
                continue
            terakhir = now
            n = await _pindai_sekali()
            if n:
                log.info("Pemindai tagihan: %s tenggat diusulkan ke pemilik", n)
        except Exception:  # noqa: BLE001
            log.exception("Loop pemindai tagihan gagal (lanjut)")
