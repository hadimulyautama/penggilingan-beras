"""Isi sebuah database uji dengan sehari kerja yang tampak sungguhan.

Gunanya menguji LAYAR, bukan mesin: begitu database uji baru dibuat, seluruh
layarnya kosong dan tak ada yang bisa dinilai. Skrip ini mengisinya sampai
tiap layar punya sesuatu untuk ditunjukkan — antrean berisi beberapa tiket
dari pemasok berbeda, satu pengeringan yang sedang berjalan, silo terisi,
satu giling berjalan, dan beberapa harga yang belum diverifikasi.

**Datanya dibuat lewat HTTP, bukan lewat INSERT.** Baris yang disuntikkan
langsung ke tabel bisa saja mustahil menurut aturan aplikasinya sendiri —
gabah basah di silo, lot tanpa target kadar air — dan data uji yang mustahil
membuat layarnya terlihat benar padahal sedang menampilkan keadaan yang tak
pernah bisa terjadi. Satu-satunya yang disuntikkan langsung adalah tiket
timbang, karena ia memang datang dari aplikasi lain.

Pemasoknya diberi awalan "(UJI)" supaya siapa pun yang membuka database ini
tahu dalam sekali lihat bahwa isinya bukan pekerjaan sungguhan.

    IZIN_DUMMY=ya DATABASE_URL=postgresql+asyncpg://... \
        PYTHONPATH=. .venv/bin/python scripts/isi_dummy.py

Menolak berjalan tanpa `IZIN_DUMMY=ya`. Pagar itu bukan basa-basi: satu-
satunya beda antara database uji dan database sungguhan adalah alamatnya,
dan alamat paling mudah salah ketik justru saat sedang buru-buru.
"""
from __future__ import annotations

import asyncio
import os
import sys

if os.environ.get("IZIN_DUMMY") != "ya":
    print("\033[31mDitolak.\033[0m Skrip ini menulis data karangan ke database "
          "yang ditunjuk DATABASE_URL.\n"
          "Jalankan dengan IZIN_DUMMY=ya bila memang itu yang Anda mau, dan "
          "PASTIKAN alamatnya bukan database utama.")
    raise SystemExit(2)

os.environ.setdefault("SECRET_KEY", "kunci-dummy-jangan-dipakai-di-produksi")
os.environ.setdefault("ADMIN_TELEGRAM_ID", "0")
for _v in ("BOT_GUDANG1_TOKEN", "BOT_GUDANG2_TOKEN", "BOT_ADMIN_TOKEN"):
    os.environ.setdefault(_v, "")
os.environ.setdefault("ANTHROPIC_API_KEY", "x")

import httpx                                                    # noqa: E402
from sqlalchemy import select, text                             # noqa: E402

from app.database import SessionLocal                           # noqa: E402
from app.models import ProduksiAkun, Supplier, Warehouse        # noqa: E402
from app.services.seed import seed_master                       # noqa: E402
AWALAN = "(UJI) "

#: Pemasok karangan. Namanya sengaja beragam panjangnya — kartu yang hanya
#: pernah diuji dengan "Bu Sri" tak pernah ketahuan pecah pada nama panjang.
PEMASOK = ["H. Karyo", "Bu Sri", "Pak Tarno", "H. Sulaiman Abdurrahman",
           "Kelompok Tani Sumber Rejeki"]

#: (pemasok, jenis, plat, kg). Bobotnya kisaran satu truk: 8–11 ton.
TIKET = [
    (0, "GABAH_BASAH",  "AD 1234 XY",  9_850),
    (1, "GABAH_BASAH",  "AD 88 KK",   10_400),
    (2, "GABAH_KERING", "AD 21 LM",    8_600),
    (3, "GABAH_KERING", "AD 9 PP",    11_000),
    (4, "GABAH_BASAH",  "AD 7 CC",     9_200),
    (1, "GABAH_KERING", "AD 88 KK",    8_150),
    (0, "GABAH_KERING", "AD 1234 XY", 10_700),
]

GAGAL: list[str] = []


def cek(nama: str, syarat: bool, ket: str = "") -> bool:
    print(("  ✅ " if syarat else "  ❌ ") + nama + (f" — {ket}" if ket else ""))
    if not syarat:
        GAGAL.append(nama)
    return syarat


def babak(n: str) -> None:
    print(f"\n\033[1m{n}\033[0m")


async def main() -> None:
    """Siapkan orang & alat, lalu serahkan pengisiannya ke layanan yang sama
    dengan yang dipakai tombol "Kembalikan data uji" di layar Mode Uji.

    Dua jalan masuk, satu isi. Kalau skripnya punya salinannya sendiri, data
    yang dibuat dari laptop dan data yang dibuat dari layar akan berbeda —
    dan yang diuji orang jadi bukan yang dipakai orang.
    """
    from app.services import data_uji

    babak("0. Orang & alat")
    # Alat disemai; ORANG tidak. Akun uji karangan (uji_admin/uji_operator)
    # tak dibuat lagi sejak 21 September 2026 — app uji coba dipakai dengan
    # akun yang sudah ada, supaya yang menguji sama dengan yang memakai.
    await seed_master()
    async with SessionLocal() as db:
        akun = (await db.execute(select(ProduksiAkun))).scalars().first()
    cek("alat siap & sudah ada akun", akun is not None,
        "masuk dengan akun yang sudah ada; tak ada akun uji yang dibuat")

    babak("1. Mengisi data uji")
    for baris in await data_uji.isi(akun):
        print("  " + baris)

    print()
    if GAGAL:
        print(f"\033[31m{len(GAGAL)} langkah GAGAL:\033[0m")
        for g in GAGAL:
            print("  · " + g)
        sys.exit(1)
    print("\033[32mData uji siap. Masuk dengan akun yang sudah ada.\033[0m")


if __name__ == "__main__":
    asyncio.run(main())
