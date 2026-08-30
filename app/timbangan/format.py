"""Pemformatan angka & tanggal gaya Indonesia untuk tampilan."""
from __future__ import annotations

from datetime import date, datetime

BULAN = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]
BULAN_SINGKAT = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
                 "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def angka(nilai, digit: int = 0) -> str:
    """1234.5 -> '1.234,5' (pemisah ribuan titik, desimal koma)."""
    if nilai is None:
        return "-"
    try:
        n = float(nilai)
    except (TypeError, ValueError):
        return str(nilai)
    teks = f"{n:,.{digit}f}"
    return teks.replace(",", "#").replace(".", ",").replace("#", ".")


def kg(nilai, digit: int = 0) -> str:
    if nilai is None:
        return "-"
    return f"{angka(nilai, digit)} kg"


def kg_tanda(nilai, digit: int = 0) -> str:
    """Selisih dengan tanda eksplisit: '-48 kg', '+12 kg', '0 kg'."""
    if nilai is None:
        return "-"
    n = float(nilai)
    tanda = "+" if n > 0 else ""
    return f"{tanda}{angka(n, digit)} kg"


def persen(nilai, digit: int = 2) -> str:
    if nilai is None:
        return "-"
    n = float(nilai)
    tanda = "+" if n > 0 else ""
    return f"{tanda}{angka(n, digit)}%"


def ton(nilai, digit: int = 2) -> str:
    if nilai is None:
        return "-"
    return f"{angka(float(nilai) / 1000, digit)} ton"


def tgl(nilai: date | datetime | None, singkat: bool = False) -> str:
    if nilai is None:
        return "-"
    nama = BULAN_SINGKAT if singkat else BULAN
    return f"{nilai.day} {nama[nilai.month]} {nilai.year}"


def tgl_jam(nilai: datetime | None) -> str:
    if nilai is None:
        return "-"
    return f"{tgl(nilai, singkat=True)} {nilai:%H:%M}"


def jam(nilai: datetime | None) -> str:
    """'14:35' — jam timbang, hal yang paling sering dilihat petugas."""
    return f"{nilai:%H:%M}" if nilai else "-"


def iso(nilai: date | datetime | None) -> str:
    return nilai.strftime("%Y-%m-%d") if nilai else ""
