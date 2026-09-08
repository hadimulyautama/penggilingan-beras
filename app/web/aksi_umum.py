"""Penolong yang dipakai semua modul aksi cepat.

Dipisahkan dari `miniapp.py` ketika aksi inventory pindah ke modulnya sendiri:
keduanya membutuhkan penolong yang sama, dan saling mengimpor akan melingkar.
Isinya sengaja tipis — hanya hal yang benar-benar dipakai lebih dari satu
modul, bukan tempat penampungan.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.models import User


def wajib(cond: bool, msg: str = "Aksi ini tidak tersedia untuk peran Anda.") -> None:
    """Hentikan permintaan bila peran pemakai tidak berhak.

    Hak akses ditentukan di SERVER, bukan dengan menyembunyikan tombol: menu
    yang disaring per peran itu kenyamanan, bukan pengamanan.
    """
    if not cond:
        raise HTTPException(status_code=403, detail=msg)


def rp(n: float) -> str:
    return f"{n:,.0f}".replace(",", ".")


def kg(n: float) -> str:
    return f"{n:,.0f}".replace(",", ".") + " kg"


def galat(e: Exception, default: str) -> HTTPException:
    """Ubah kesalahan layanan jadi 400 dengan pesan yang sudah siap dibaca.

    Layanan di aplikasi ini melemparkan kesalahan dengan pesan berbahasa
    manusia di `args[0]` — itulah yang naik ke layar. `default` hanya jaring
    pengaman untuk kesalahan yang tidak membawa pesan apa pun.
    """
    # Hanya argumen yang benar-benar KALIMAT yang naik ke layar. Sebuah
    # kesalahan yang membawa angka — batas harian dulu dilempar begitu —
    # akan tampil sebagai lembar galat bertuliskan "3", dan angka telanjang
    # tak memberi tahu apa pun tentang apa yang salah maupun apa yang harus
    # dilakukan. Yang begitu jatuh ke kalimat bawaan.
    pesan = e.args[0] if e.args else None
    if isinstance(pesan, str) and pesan.strip():
        return HTTPException(400, pesan)
    return HTTPException(400, default)


