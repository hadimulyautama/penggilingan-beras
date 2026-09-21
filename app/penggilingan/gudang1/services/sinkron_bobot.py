"""Poller SINKRON BOBOT — isi bobot batch dari tiket timbang.

Batch bisa dibuat saat bongkar walau bobot belum ada (nota kosong & timbang-2 belum).
Poller ini periodik memeriksa tiket-tiket tsb; begitu tiket punya bobot (nota atau netto
saat timbang-2 selesai), bobot batch tertaut terisi otomatis. Referensi bobot tetap tiket
(shared DB) — poller hanya menyalinnya ke kolom batch (pendekatan A). Read-only ke timbangan.

Lima langkah tiap putaran, dan urutannya bukan kebetulan (`satu_putaran`):

  0. beri PERKIRAAN pada batch 'menunggu' yang truknya punya tara — timbang
     pertama − berat kosong terakhir nomor polisi itu (QA P6, Pilihan A);
  1. isi bobot batch yang masih menunggu / perkiraan begitu tiketnya punya
     angka sungguhan;
  2. perbarui batch yang tiketnya DIREVISI — dalam keadaan apa pun, termasuk
     yang sedang di dryer, di silo, atau sedang digiling;
  3. lengkapi berat PK yang masuk Gudang 2 sebelum bobotnya pasti;
  4. samakan bahan giling — yang sedang berjalan, DAN yang sudah selesai
     tetapi bobot masuknya belum final — dengan bobot batch yang baru.

Langkah 4 ada karena langkah 1–2 saja tidak cukup: `berat_gabah_masuk_kg`
dicuplik saat giling dimulai, dan cuplikan yang tak pernah dibaca ulang adalah
cara paling umum dua aplikasi mulai berbeda tanpa ada yang menyadarinya.
"""
from __future__ import annotations

import asyncio
import logging

from app.database import SessionLocal
from app.penggilingan.gudang1.services.milling import resinkron_bahan_berjalan
from app.penggilingan.gudang1.services.timbang_link import (
    resinkron_bobot_berubah,
    sinkron_bobot_menunggu,
    sinkron_perkiraan,
)
from app.penggilingan.gudang2.service import resinkron_intake_g2

log = logging.getLogger("sinkron.bobot")

_INTERVAL = 180  # 3 menit


async def satu_putaran() -> dict:
    """Kelima langkah, satu pintu — dipakai poller DAN uji, supaya yang diuji
    persis urutan yang berjalan di server (pelajaran QA P6-R02)."""
    hasil: dict = {}
    async with SessionLocal() as db:
        hasil["perkiraan"] = await sinkron_perkiraan(db)
    async with SessionLocal() as db:
        hasil["terisi"] = await sinkron_bobot_menunggu(db)
    async with SessionLocal() as db:
        hasil["direvisi"] = await resinkron_bobot_berubah(db)
    async with SessionLocal() as db:
        hasil["intake_g2"] = await resinkron_intake_g2(db)
    async with SessionLocal() as db:
        hasil["bahan_giling"] = await resinkron_bahan_berjalan(db)
    return hasil


async def run_sinkron_bobot_poller(bots=None) -> None:
    log.info("Poller sinkron bobot aktif (tiap %s detik).", _INTERVAL)
    while True:
        await asyncio.sleep(_INTERVAL)
        try:
            h = await satu_putaran()
            if h["perkiraan"]:
                log.info("Perkiraan dari tara truk: %s batch.", h["perkiraan"])
            if h["terisi"]:
                log.info("Sinkron bobot: %s batch terisi dari tiket timbang.", h["terisi"])
            if h["direvisi"]:
                log.info("Re-sinkron bobot (tiket direvisi): %s batch diperbarui.", h["direvisi"])
            if h["intake_g2"]:
                log.info("Intake Gudang 2 dilengkapi bobotnya: %s.", h["intake_g2"])
            # Bobot batch yang berubah harus SAMPAI ke bahan giling — yang
            # berjalan maupun yang selesai dengan bahan belum final.
            # `berat_gabah_masuk_kg` adalah penyebut rendemen: kalau ia
            # tertinggal, rendemen terbaca melambung dan yang melihatnya akan
            # mencari sebabnya di mesin, bukan di catatan.
            if h["bahan_giling"]:
                log.info("Bahan giling disamakan dengan bobot baru: %s.",
                         ", ".join(h["bahan_giling"]))
        except Exception:  # noqa: BLE001
            log.exception("Loop sinkron bobot gagal (lanjut)")
