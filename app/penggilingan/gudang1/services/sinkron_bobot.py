"""Poller SINKRON BOBOT — isi bobot batch 'menunggu' dari tiket timbang.

Batch bisa dibuat saat bongkar walau bobot belum ada (nota kosong & timbang-2 belum).
Poller ini periodik memeriksa tiket-tiket tsb; begitu tiket punya bobot (nota atau netto
saat timbang-2 selesai), bobot batch tertaut terisi otomatis. Referensi bobot tetap tiket
(shared DB) — poller hanya menyalinnya ke kolom batch (pendekatan A). Read-only ke timbangan.
"""
from __future__ import annotations

import asyncio
import logging

from app.database import SessionLocal
from app.penggilingan.gudang1.services.timbang_link import (
    resinkron_bobot_berubah,
    sinkron_bobot_menunggu,
)

log = logging.getLogger("sinkron.bobot")

_INTERVAL = 180  # 3 menit


async def run_sinkron_bobot_poller(bots=None) -> None:
    log.info("Poller sinkron bobot aktif (tiap %s detik).", _INTERVAL)
    while True:
        await asyncio.sleep(_INTERVAL)
        try:
            async with SessionLocal() as db:
                n = await sinkron_bobot_menunggu(db)
            if n:
                log.info("Sinkron bobot: %s batch terisi dari tiket timbang.", n)
            async with SessionLocal() as db:
                m = await resinkron_bobot_berubah(db)
            if m:
                log.info("Re-sinkron bobot (tiket direvisi): %s batch diperbarui.", m)
        except Exception:  # noqa: BLE001
            log.exception("Loop sinkron bobot gagal (lanjut)")
