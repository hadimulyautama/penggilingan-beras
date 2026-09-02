"""Helper tanggal/jam murni untuk prompt AI — tanpa domain, tanpa LLM.

Dipisah dari `app.ai.base` supaya modul yang cuma butuh konteks tanggal (mis.
agen Kantor) tidak ikut menyeret `app.ai.tools` (prompt & ~20 tool PABRIK).
`app.ai.base` mengekspor ulang isinya, jadi impor lama tetap jalan.
"""
from __future__ import annotations

from datetime import date, time, timedelta

from app.database import now_local

_HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def _date_context() -> str:
    """Tabel tanggal 14 hari terakhir agar Claude memetakan rujukan hari
    (mis. 'kamis kemarin') lewat LOOKUP, bukan aritmetika (yang rawan salah)."""
    today = now_local().date()
    baris = []
    for i in range(14):
        d = today - timedelta(days=i)
        tag = " (hari ini)" if i == 0 else (" (kemarin)" if i == 1 else "")
        baris.append(f"{d:%Y-%m-%d} {_HARI_ID[d.weekday()]}{tag}")
    return "\n".join(baris)


def _parse_iso_date(v) -> date | None:
    """Ubah 'YYYY-MM-DD' dari Claude menjadi objek date; None bila tak valid."""
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        return date.fromisoformat(v.strip()[:10])
    except ValueError:
        return None


def _parse_hhmm(v) -> time | None:
    """Ubah 'HH:MM' (24 jam) dari Claude menjadi objek time; None bila tak valid."""
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip().replace(".", ":")
    try:
        return time.fromisoformat(s if len(s) > 5 else s[:5])
    except ValueError:
        try:
            hh, mm = s.split(":")[:2]
            return time(int(hh), int(mm))
        except (ValueError, IndexError):
            return None
