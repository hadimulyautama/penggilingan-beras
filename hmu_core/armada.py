"""Aturan identitas armada yang harus sama di setiap aplikasi."""
from __future__ import annotations

import re


def normalisasi_nomor_polisi(nomor: str | None) -> str | None:
    """Rapikan nomor polisi agar variasi spasi/huruf menunjuk satu armada."""
    if not nomor:
        return None
    return re.sub(r"\s+", " ", str(nomor).strip().upper()) or None
