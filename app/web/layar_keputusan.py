"""Layar "Menunggu keputusan" — kerja MEJA, bukan kerja gudang.

Barisnya pernah menumpang di Antrian tunggu, dan itu menyalahi aturan yang
paling sering diucapkan pemilik: **begitu gabah punya tempat, ia keluar dari
antrean.** Gabah di baris-baris ini sudah lama punya tempat — sudah di mesin
pengering, sudah di silo, bahkan sudah digiling. Yang belum selesai bukan
gabahnya melainkan keputusannya: harganya belum diverifikasi, mutunya belum
diperiksa, outputnya belum dicocokkan.

Menaruhnya di antrean membuat orang mencari gabah yang sebenarnya sudah
ditempatkan — dan layar yang memerintahkan pencarian sia-sia akan berhenti
dipercaya, termasuk saat ia benar.

Hanya admin ke atas. Sejak awal ini memang pekerjaan admin; operator tak
pernah melihatnya, dan admin yang sedang memakai Mode operator pun tidak —
peran efektifnyalah yang ditanya, bukan peran aslinya.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.database import SessionLocal
from app.services import berjalan as svc
from app.web.security import butuh_admin
from app.web.tampilan import render

router = APIRouter(tags=["webapp"])

#: Blok layar ini, BERURUT: (id aksi, judul blok).
#:
#: Dulu daftar ini hidup di dalam templat, dan isinya tiga dari ENAM jenis yang
#: benar-benar dikirim `berjalan.untuk()` ke `b.meja`. Akibatnya harga PK luar,
#: mutu PK luar, dan pembetulan bobot giling ada di data tetapi tak digambar di
#: layar mana pun — pekerjaan yang menahan uang, tak tertagih, tanpa satu pun
#: tanda. (Yang PK luar terbaca di aplikasi Meja; `betulkan_bobot_giling` tak
#: terbaca di mana pun sejak ia lahir bersama perbaikan P6-03.)
#:
#: Di sini, bukan di templat, karena di sinilah ia bisa DIUJI terhadap apa yang
#: `b.meja` sungguh bawa — lihat `tests/test_keputusan_lengkap.py`. Templat yang
#: memegang daftarnya sendiri tak bisa tahu ia ketinggalan.
#:
#: Urutannya mengikuti uang yang tertahan paling lama: harga lebih dulu, lalu
#: pencocokan output, lalu mutu. Pembetulan bobot terakhir — ia perbaikan atas
#: keadaan yang jarang, bukan pekerjaan harian, dan bobot yang tak cocok
#: membuat rendemen & HPP salah sampai dibetulkan.
JENIS_KEPUTUSAN: tuple[tuple[str, str], ...] = (
    ("verify_gabah", "Harga gabah belum diverifikasi"),
    ("harga_pk_luar", "Harga PK luar belum diverifikasi"),
    ("verify_output", "Output giling belum dicocokkan"),
    ("qc_giling", "Mutu giling belum diperiksa"),
    ("qc_pk_luar", "Mutu PK luar belum dicatat"),
    ("betulkan_bobot_giling", "Bobot masuk giling tak cocok"),
)

#: Id yang sudah punya bloknya sendiri. Sisanya jatuh ke blok jaring di templat,
#: supaya jenis yang lahir nanti TERLIHAT — meski judulnya belum dipikirkan —
#: bukan hilang diam-diam seperti tiga jenis di atas.
AKSI_DIKENAL: tuple[str, ...] = tuple(a for a, _ in JENIS_KEPUTUSAN)


@router.get("/keputusan")
async def halaman_keputusan(request: Request, akun=Depends(butuh_admin)):
    async with SessionLocal() as db:
        b = await svc.untuk(db, akun.user)
    return render(
        request, "keputusan.html", layar="keputusan",
        meja=b.meja, lama=svc._lama,
        JENIS_KEPUTUSAN=JENIS_KEPUTUSAN, AKSI_DIKENAL=AKSI_DIKENAL,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        MENUNGGU=b.jumlah_menunggu, BERJALAN=b.jumlah_berjalan,
        KEPUTUSAN=b.jumlah_keputusan,
    )
