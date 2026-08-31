"""Pemformatan angka & tanggal gaya Indonesia untuk tampilan."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import settings

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


def lokal(nilai):
    """Ubah waktu berzona ke zona perusahaan sebelum ditampilkan.

    Postgres menyimpan kolom `timestamptz` dan mengembalikannya dalam UTC —
    apa pun zona yang dipakai saat menulis. Tanpa langkah ini, layar
    menampilkan jam UTC: timbangan pukul 22:15 WIB tertulis 15:14, dan
    petugas akan menganggap catatannya salah. Kolom yang default-nya dibuat
    server (`created_at`) paling terpengaruh, karena tidak lewat
    `db.sekarang()` sama sekali.

    Waktu tanpa zona dibiarkan apa adanya: itu sudah waktu setempat.
    """
    if isinstance(nilai, datetime) and nilai.tzinfo is not None:
        return nilai.astimezone(ZoneInfo(settings.app_timezone))
    return nilai


def tgl(nilai: date | datetime | None, singkat: bool = False) -> str:
    if nilai is None:
        return "-"
    nilai = lokal(nilai)
    nama = BULAN_SINGKAT if singkat else BULAN
    return f"{nilai.day} {nama[nilai.month]} {nilai.year}"


def tgl_jam(nilai: datetime | None) -> str:
    if nilai is None:
        return "-"
    nilai = lokal(nilai)
    return f"{tgl(nilai, singkat=True)} {nilai:%H:%M}"


def jam(nilai: datetime | None) -> str:
    """'14:35' — jam timbang, hal yang paling sering dilihat petugas."""
    return f"{lokal(nilai):%H:%M}" if nilai else "-"


def iso(nilai: date | datetime | None) -> str:
    return lokal(nilai).strftime("%Y-%m-%d") if nilai else ""


def audit_nilai(teks: str | None) -> list[tuple[str, str]]:
    """JSON yang tersimpan di jejak audit → pasangan (label, nilai).

    Nilai sebelum/sesudah disimpan sebagai JSON karena bentuknya berbeda-beda
    per aksi. Yang membaca halaman audit bukan pemrogram, jadi kurung kurawal
    dan tanda kutipnya diurai di sini. Teks yang tidak bisa diurai ditampilkan
    apa adanya — lebih baik terbaca janggal daripada hilang.
    """
    import json

    if not teks:
        return []
    try:
        data = json.loads(teks)
    except (TypeError, ValueError):
        return [("", teks)]
    if not isinstance(data, dict):
        return [("", str(data))]

    hasil: list[tuple[str, str]] = []
    for kunci, nilai in data.items():
        if isinstance(nilai, (list, dict)):
            nilai = json.dumps(nilai, ensure_ascii=False)
        hasil.append((
            str(kunci).replace("_", " "),
            "—" if nilai is None or nilai == "" else str(nilai),
        ))
    return hasil
