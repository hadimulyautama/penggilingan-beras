"""Pembatas percobaan masuk — per nama pengguna DAN per alamat IP.

Sampai 11 September 2026 halaman masuk menerima percobaan tanpa batas sama
sekali. Seluruh daftar sandi bisa dicoba satu per satu, dan tak ada satu baris
pun di mana pun yang mencatat bahwa itu sedang terjadi. Temuan QA P-S-04.

**Di memori, bukan di basis data.** Layanan ini berjalan satu replika (lihat
CLAUDE.md), jadi satu proses melihat seluruh percobaan. Menyimpannya di
Postgres berarti satu tulisan tiap kali ada yang salah ketik sandi, dan
hitungan yang hilang saat restart bukan kerugian: penebak yang sabar menunggu
deploy sudah tertahan oleh hal lain.

**Pasangan nama+IP, bukan salah satunya saja.** Mengunci berdasarkan nama saja
memberi penyerang cara mengunci orang lain: cukup salah ketik lima kali atas
nama korbannya, dan korbannya tak bisa bekerja. Mengunci berdasarkan IP saja
mengunci seluruh gudang, yang keluar lewat satu sambungan yang sama.
"""
from __future__ import annotations

import time
from collections import defaultdict

#: Percobaan gagal berturut-turut sebelum ditahan.
BATAS_GAGAL = 5

#: Lama penahanan (detik). Cukup panjang untuk membuat penebakan tak ada
#: gunanya, cukup pendek untuk tidak menghukum orang yang benar-benar lupa —
#: ia bisa menunggu sambil menelepon Super Admin.
JEDA_DETIK = 300

#: Hitungan dilupakan sesudah ini bila tak ada percobaan baru.
UMUR_DETIK = 900

_gagal: dict[tuple[str, str], list[float]] = defaultdict(list)


def _kunci(username: str, ip: str) -> tuple[str, str]:
    return ((username or "").strip().lower(), (ip or "").strip())


def _bersih(waktu: list[float], sekarang: float) -> list[float]:
    return [t for t in waktu if sekarang - t < UMUR_DETIK]


def boleh_coba(username: str, ip: str) -> float | None:
    """None bila boleh mencoba; selain itu sisa detik penahanan."""
    k = _kunci(username, ip)
    kini = time.monotonic()
    waktu = _bersih(_gagal.get(k, []), kini)
    _gagal[k] = waktu
    if len(waktu) < BATAS_GAGAL:
        return None
    sisa = JEDA_DETIK - (kini - waktu[-1])
    return sisa if sisa > 0 else None


def catat_gagal(username: str, ip: str) -> None:
    k = _kunci(username, ip)
    kini = time.monotonic()
    _gagal[k] = _bersih(_gagal.get(k, []), kini) + [kini]


def catat_berhasil(username: str, ip: str) -> None:
    """Masuk yang berhasil menghapus hitungannya.

    Tanpa ini, orang yang salah ketik empat kali lalu berhasil masuk tetap
    membawa empat hitungan itu, dan satu salah ketik berikutnya di hari yang
    sama menguncinya.
    """
    _gagal.pop(_kunci(username, ip), None)


def catat_sandi_benar(username: str, ip: str) -> None:
    """Sandinya BENAR tetapi masuknya tetap ditolak — pintu peran, bukan sandi.

    Hitungan di sini menjaga satu hal saja: penebakan sandi. Sandi yang sudah
    terbukti benar bukan tebakan, jadi penolakan sesudah itu tidak boleh
    menambah hitungan — dan hitungan yang sudah ada pun luruh, dengan alasan
    yang sama seperti `catat_berhasil`.

    QA 24 September 2026 (c) butir 1: operator Gudang 1 membuka app Meja lima
    kali, sandinya benar tiap kali, ditolak karena perannya — lalu Pos
    Produksi DAN app Gudang 2, kedua app yang sah baginya, menjawab "Terlalu
    banyak percobaan" selama lima menit. Ia tak pernah sekali pun salah ketik.
    """
    _gagal.pop(_kunci(username, ip), None)


def bersihkan() -> None:
    """Kosongkan seluruh hitungan. Dipakai uji; tak dipanggil aplikasi."""
    _gagal.clear()
