"""Infrastruktur NLP bersama: forced tool-use Claude + helper tanggal/jam/silo.

Dipakai oleh parser bersama (app.ai.nlp_parser) maupun parser domain
(app.penggilingan.gudang1.nlp, app.penggilingan.gudang2.nlp). TIDAK mengimpor modul parser → bebas siklus.
"""
from __future__ import annotations

from datetime import date, time, timedelta

from app.ai import guard
from app.ai.tools import SYSTEM_PROMPT
from app.config import settings
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


def _silo_letter(v) -> str | None:
    """Hanya terima 'A' atau 'B'; nilai lain (placeholder AI) -> None."""
    if isinstance(v, str):
        s = v.upper().strip()
        if s in ("A", "B"):
            return s
    return None


async def _invoke_tool(messages: list[dict], tool: dict) -> dict:
    """Panggil Claude dengan forced tool-use dan kembalikan input tool (dict)."""
    system = SYSTEM_PROMPT + (
        "\n\nKonteks waktu — tanggal 14 hari terakhir (pakai LOOKUP tabel ini, "
        "jangan menghitung manual):\n" + _date_context() + "\n\n"
        "Untuk rujukan tanggal spesifik/relatif (mis. 'kemarin', 'senin "
        "kemarin', 'kamis lalu', 'tanggal 1 juli', '2 hari lalu'), CARI di tabel "
        "lalu isikan tanggal ABSOLUT format YYYY-MM-DD ke field 'tanggal' bila "
        "tool menyediakannya. '[hari] kemarin'/'[hari] lalu' = baris PALING ATAS "
        "(terbaru) dengan hari itu. Nama bulan: Januari=01 … Juli=07 … Des=12."
    )
    resp = await guard.panggil(
        pemanggil="base_tanggal",
        model=settings.claude_model,
        max_tokens=1024,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=messages,
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return dict(block.input)
    return {}
