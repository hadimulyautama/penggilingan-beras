"""Infrastruktur NLP bersama: forced tool-use Claude + helper tanggal/jam/silo.

Dipakai oleh parser bersama (app.ai.nlp_parser) maupun parser domain
(app.penggilingan.gudang1.nlp, app.penggilingan.gudang2.nlp). TIDAK mengimpor modul parser → bebas siklus.
"""
from __future__ import annotations

from app.ai import guard
from app.ai.tanggal import (  # noqa: F401  (ekspor ulang: dipakai modul parser)
    _HARI_ID,
    _date_context,
    _parse_hhmm,
    _parse_iso_date,
)
from app.ai.tools import SYSTEM_PROMPT
from app.config import settings


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
