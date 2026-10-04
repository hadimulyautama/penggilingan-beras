"""Scheduler latar: sinkron kontak Kledo otomatis tiap tengah malam LOKAL.

Permintaan pemilik: "kalau bisa sinkron otomatis setiap jam 12 malam." Dua hal
yang mudah salah pada scheduler semacam ini, dan keduanya dihindari di sini:

  · **BUKAN `asyncio.sleep(86400)`.** Tidur 24 jam dari saat SERVICE
    menyala akan melenceng dari tengah malam setiap kali ada deploy — dan
    deploy bisa terjadi beberapa kali sehari. Yang dihitung di sini
    bukan "24 jam dari sekarang", melainkan "detik sampai 00:00 BERIKUTNYA".
  · **Waktu LOKAL, bukan UTC.** Tengah malam UTC = jam 7 pagi di pabrik —
    persis saat truk pertama mulai ditimbang. Memakai `now_local()`
    (`app/database.py`) menghindari sinkron ~600 kontak berebut siklus
    dengan jam tersibuk, bukan jam paling sepi.

Aman berjalan sebagai satu task dalam satu proses karena `railway.json`
mengunci `numReplicas: 1` — lihat catatan panjang di
`app/services/kledo_sinkron.py` soal apa yang berubah bila itu tidak lagi
benar.

SATU fungsi, TIGA pemicu: scheduler ini memanggil `kledo_sinkron.mulai()`
yang SAMA dengan tombol Pengaturan dan endpoint internal Timbangan — tidak
ada jalur sinkron kedua yang bisa diam-diam berbeda aturannya.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from app.database import now_local
from app.services import kledo_sinkron
from hmu_core import kledo_kontak

log = logging.getLogger("kledo_scheduler")


def _detik_sampai_tengah_malam() -> float:
    sekarang = now_local()
    besok = (sekarang + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (besok - sekarang).total_seconds()


async def run_kledo_scheduler() -> None:
    """Loop tak berhenti: tunggu sampai 00:00 lokal, sinkron, ulangi."""
    if not kledo_kontak.terkonfigurasi():
        log.warning("KLEDO_API_KEY kosong — scheduler sinkron kontak NONAKTIF.")
        return

    log.info("Scheduler sinkron kontak Kledo aktif (tiap 00:00 waktu lokal).")
    while True:
        tunggu = _detik_sampai_tengah_malam()
        await asyncio.sleep(tunggu)
        try:
            # `mulai()` sendiri yang memeriksa-lalu-menyetel kunci —
            # seharusnya selalu `True` di sini (tak ada orang menekan tombol
            # tengah malam), tapi diperiksa juga: satu malam gagal diam-diam
            # ditelan ke sini TIDAK BOLEH mematikan putaran besok.
            if not kledo_sinkron.mulai():
                log.info("Sinkron tengah malam dilewati — sudah ada yang berjalan.")
                continue
            # `mulai()` hanya MEMULAI di latar (lihat docstring-nya) — di sini
            # justru DITUNGGU, supaya hasilnya bisa dicatat log malam ini,
            # bukan menghilang begitu loop lanjut ke putaran besok.
            while kledo_sinkron.status().sedang_berjalan:
                await asyncio.sleep(5)
            s = kledo_sinkron.status()
            if s.gagal_terakhir:
                log.error("Sinkron kontak Kledo tengah malam GAGAL: %s", s.gagal_terakhir)
            else:
                log.info("Sinkron kontak Kledo tengah malam selesai: %s", s.hasil_terakhir)
        except Exception:  # noqa: BLE001 — satu malam gagal tak boleh menghentikan scheduler
            log.exception("Loop scheduler sinkron kontak Kledo gagal (lanjut besok)")
