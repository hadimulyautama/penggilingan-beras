"""Penyegar mingguan daftar kontak vendor dari Kledo.

Kledo adalah sumber kebenaran identitas mitra; daftar `suppliers` mengikutinya
sekali seminggu agar pos timbang dan sistem penggilingan tidak perlu mengetik
ulang nama yang sudah ada di sana.

Sengaja mingguan, bukan tiap jam: kontak vendor jarang berubah, dan setiap
sinkronisasi menyentuh master bersama yang dipakai kedua modul.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from app.config import settings
from app.database import SessionLocal
from app.kantor import kledo_kontak

log = logging.getLogger(__name__)

_TICK = 900                    # periksa tiap 15 menit
_INTERVAL = 7 * 24 * 3600      # jalankan tiap 7 hari


async def sinkron_sekali() -> dict[str, kledo_kontak.HasilSinkron]:
    """Vendor DAN pelanggan. Keduanya dari sumber yang sama, sekali jalan."""
    async with SessionLocal() as db:
        return await kledo_kontak.sinkron_semua(db)


async def run_kledo_kontak_poller(bots: dict[str, Bot]) -> None:
    if not kledo_kontak.terkonfigurasi():
        log.warning("KLEDO_API_KEY kosong — penyegar kontak Kledo NONAKTIF.")
        return

    log.info("Penyegar kontak Kledo aktif (tiap %s hari)", _INTERVAL // 86400)
    bot = bots.get("kantor")
    terakhir: datetime | None = None

    while True:
        await asyncio.sleep(_TICK)
        try:
            now = datetime.now(timezone.utc)
            if terakhir is not None and (now - terakhir).total_seconds() < _INTERVAL:
                continue
            terakhir = now

            semua = await sinkron_sekali()
            for sebutan, hasil in semua.items():
                log.info("Kontak %s Kledo: %s", sebutan, hasil.ringkas)

            # Hanya melapor bila ada yang benar-benar berubah — laporan
            # mingguan yang selalu berbunyi "tidak ada perubahan" akan
            # berhenti dibaca, dan justru itu yang berbahaya.
            layak = any(h.dibuat or h.ditaut or h.ambigu for h in semua.values())
            if bot and settings.admin_telegram_id and layak:
                baris = [
                    f"· {sebutan}: {h.ringkas}" for sebutan, h in semua.items()
                ]
                pesan = "Kontak Kledo disegarkan.\n" + "\n".join(baris)
                ambigu = sorted({
                    n for h in semua.values() for n in h.ambigu
                })
                if ambigu:
                    pesan += (
                        "\n\nNama berikut ada lebih dari satu di daftar kita, "
                        "jadi tidak ditautkan otomatis (menebak berarti "
                        "timbangan bisa tercatat atas nama yang salah):\n· "
                        + "\n· ".join(ambigu[:10])
                    )
                await bot.send_message(settings.admin_telegram_id, pesan)
        except Exception:  # noqa: BLE001
            log.exception("Loop penyegar kontak Kledo gagal (lanjut)")
