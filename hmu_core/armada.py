"""Aturan identitas armada yang harus sama di setiap aplikasi."""
from __future__ import annotations

import re
from unicodedata import normalize

PESAN_FORMAT_NOPOL = "Format nomor polisi harus huruf, angka, lalu huruf. Contoh: AD 1234 XY."


def normalisasi_nomor_polisi(nomor: str | None) -> str | None:
    """Rapikan nomor polisi agar variasi spasi/huruf menunjuk satu armada."""
    if not nomor:
        return None
    bersih = re.sub(r"\s+", " ", normalize("NFKC", str(nomor)).strip().upper())
    cocok = re.fullmatch(r"([A-Z]+)([0-9]+)([A-Z]+)", re.sub(r"\s+", "", bersih))
    # Pembacaan catatan lama tetap boleh, termasuk nomor yang belum lengkap.
    return " ".join(cocok.groups()) if cocok else bersih or None


def validasi_nomor_polisi(nomor: str | None) -> str | None:
    """Sahkan isian baru; kosong mengikuti aturan wajib di masing-masing alur."""
    bersih = normalisasi_nomor_polisi(nomor)
    if bersih and (len(bersih) > 20 or not re.fullmatch(r"[A-Z]+ [0-9]+ [A-Z]+", bersih)):
        raise ValueError(PESAN_FORMAT_NOPOL)
    return bersih
