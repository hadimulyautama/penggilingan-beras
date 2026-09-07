"""Menu navigasi — laci yang dibuka dari ikon sandwich.

**Dulu bilah lima tab di bawah**, dan alasannya masih benar: ibu jari
menjangkau bagian bawah layar, bukan bagian atas. Yang berubah adalah
jumlah layarnya. Tab yang dipaksa memuat enam tujuan menyempitkan tiap
sasaran jadi ~60px dengan label sembilan piksel — dan label sembilan
piksel tak terbaca di gudang yang kena matahari.

**Yang hilang bersama tab diganti; satu hal justru bertambah.** Dengan tab,
layar yang sedang dibuka selalu terlihat — maka judul layar naik ke bilah
atas, karena laci yang menyembunyikan posisi orang lebih buruk daripada tab
yang sempit. Sebaliknya laci memberi ruang yang tak pernah ada di tab:
KETERANGAN satu baris tiap tujuan, dan ANGKA yang lebih dari satu macam.

**Harganya disebut apa adanya:** tombol di sudut atas kiri adalah titik
terjauh dari ibu jari saat telepon dipegang satu tangan. Kalau kelak terasa
mengganggu, obatnya bukan kembali ke tab melainkan menambah usap dari tepi
kiri — tombolnya tetap ada untuk yang tak tahu usapan itu.

**Lencananya menghitung yang MENUNGGU ORANG, bukan semua yang berjalan.** Lot
yang sedang dikeringkan menunggu waktu; kalau ikut dihitung, lencananya tidak
pernah nol — dan lencana yang tidak pernah nol mengajari orang mengabaikannya.
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.models import User

log = logging.getLogger("web.nav")

#: (kunci layar, alamat, label). Label SELALU tertulis di layar — ikon saja
#: adalah ujian ingatan bagi orang yang tidak setiap hari memegang aplikasi.
#:
#: Lima tab menyempitkan tiap sasaran jadi ~72px pada layar 390px. Masih di
#: atas batas aman untuk ibu jari (tingginya tetap 56px), tetapi labelnya
#: harus pendek: "Pengaturan" patah dua baris di lebar itu, dan label yang
#: patah lebih buruk daripada label yang disingkat.
#: Kolom kelima: peran terendah yang boleh melihatnya. None = semua.
#:
#: List audit BUKAN milik operator. Ia memuat seluruh jejak pencatatan
#: berikut tombol yang membatalkannya — dan orang yang bisa membatalkan
#: catatannya sendiri membuat jejak itu tak ada gunanya sebagai jejak.
#:
#: Menyembunyikan pintunya di sini BUKAN penjagaan: alamatnya tetap bisa
#: diketik, dan yang menjaga sungguhan adalah `butuh_admin` di rutenya.
#: Yang dikerjakan di sini cuma menghindari menawarkan pintu yang akan
#: ditolak.
TAB = (
    ("beranda",    "/",           "Beranda",        "Seberapa jauh hari ini", None),
    ("aksi",       "/aksi",       "Antrian tunggu", "Yang menunggu Anda", None),
    ("berjalan",   "/berjalan",   "Sedang berjalan", "Mesin yang menyala", None),
    ("aksi_lain",  "/aksi-lain",  "Catat pekerjaan lain",
     "Harga, QC, barang keluar, batalkan", None),
    ("laporan",    "/laporan",    "Laporan",        "Yang sudah terjadi hari ini", None),
    ("audit",      "/audit",      "List audit",     "Semua catatan, bisa disaring",
     "admin"),
    ("pengaturan", "/pengaturan", "Pengaturan",     "Data diri, sandi, alat", None),
)

#: Judul yang naik ke bilah atas. Diambil dari daftar yang sama supaya nama
#: layar tak pernah berbeda antara menu dan judulnya.
JUDUL = {k: nama for k, _, nama, _, _ in TAB}


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
