"""Bilah navigasi bawah — empat tab, dan angka yang memanggil.

**Di bawah, bukan di atas.** Layar dipegang satu tangan sambil berdiri, dan
bagian atas layar 390px tak terjangkau ibu jari tanpa memindah pegangan.
Aplikasi Timbangan di perusahaan yang sama sudah memakai pola ini, jadi orang
yang memegang keduanya tidak perlu belajar dua kebiasaan.

**Lencananya menghitung yang MENUNGGU ORANG, bukan semua yang berjalan.** Lot
yang sedang dikeringkan menunggu waktu; kalau ikut dihitung, lencananya tidak
pernah nol — dan lencana yang tidak pernah nol mengajari orang mengabaikannya.

**Bilah tidak muncul di mana-mana.** Tidak di halaman masuk (belum ada tujuan
yang boleh dituju), dan tidak di dalam lembar aksi (lembar itu menutupi layar
justru supaya satu tugas dikerjakan satu waktu; bilah di bawahnya adalah
undangan meninggalkan formulir yang baru terisi separuh).
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.models import User

log = logging.getLogger("web.nav")

#: (kunci layar, alamat, label). Label SELALU tertulis di layar — ikon saja
#: adalah ujian ingatan bagi orang yang tidak setiap hari memegang aplikasi.
TAB = (
    ("beranda",  "/",         "Beranda"),
    ("aksi",     "/aksi",     "Catat"),
    ("berjalan", "/berjalan", "Berjalan"),
    ("laporan",  "/laporan",  "Laporan"),
)


async def jumlah_menunggu(user: User | None) -> int:
    """Berapa hal yang menunggu tindakan orang ini. 0 = lencana disembunyikan.

    Database yang sedang terganggu TIDAK boleh menjatuhkan halaman yang
    sebenarnya bisa tampil tanpa angka ini — bilahnya tetap berguna tanpa
    lencana, dan halaman yang memang butuh database akan gagal pada kuerinya
    sendiri.
    """
    if user is None:
        return 0
    try:
        from app.services import berjalan
        async with SessionLocal() as db:
            return (await berjalan.untuk(db, user)).jumlah_menunggu
    except Exception:
        log.exception("Jumlah pekerjaan menunggu gagal dihitung (bilah tetap tampil)")
        return 0
