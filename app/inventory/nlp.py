"""Parser NLP modul inventory (kemasan/karung)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from app.ai.base import _invoke_tool, _parse_hhmm, _parse_iso_date
from app.ai.tools import PROSES_KEMASAN


@dataclass
class ParsedKemasan:
    intent: str = "bukan_kemasan"
    material: str | None = None
    ukuran_kg: int | None = None
    jumlah_lembar: int | None = None
    harga_per_lembar: float | None = None
    tanggal: date | None = None
    jam: time | None = None


async def parse_kemasan(text: str) -> ParsedKemasan:
    """Klasifikasi & ekstraksi aksi kemasan/karung."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_KEMASAN)
    uk = data.get("ukuran_kg")
    jl = data.get("jumlah_lembar")
    mat = data.get("material")
    return ParsedKemasan(
        intent=data.get("intent", "bukan_kemasan"),
        material=mat.lower().strip() if isinstance(mat, str) else None,
        ukuran_kg=int(uk) if isinstance(uk, (int, float)) else None,
        jumlah_lembar=int(jl) if isinstance(jl, (int, float)) else None,
        harga_per_lembar=data.get("harga_per_lembar"),
        tanggal=_parse_iso_date(data.get("tanggal")),
        jam=_parse_hhmm(data.get("jam")),
    )
