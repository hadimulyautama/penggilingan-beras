"""Parser NLP domain Gudang 2 (Penyosohan): PK masuk/silo/tumpukan/beli PK luar."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from app.ai.base import _invoke_tool, _parse_hhmm, _parse_iso_date, _silo_letter
from app.ai.tools import PROSES_GUDANG2


@dataclass
class ParsedGudang2:
    intent: str = "bukan_gudang2"
    kode: str | None = None
    nama_supplier: str | None = None
    berat_kg: float | None = None
    kadar_air: float | None = None
    broken_persen: float | None = None
    tujuan: str | None = None
    nama_silo: str | None = None
    keputusan: str | None = None
    potongan_kg: float | None = None
    harga_per_kg: float | None = None
    total_harga: float | None = None
    tanggal: date | None = None
    jam: time | None = None


async def parse_gudang2(text: str) -> ParsedGudang2:
    """Klasifikasi & ekstraksi aksi Gudang 2 (penyosohan — PK masuk/silo/tumpukan)."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_GUDANG2)
    kode = data.get("kode")
    return ParsedGudang2(
        intent=data.get("intent", "bukan_gudang2"),
        kode=kode.upper().strip() if isinstance(kode, str) else None,
        nama_supplier=data.get("nama_supplier"),
        berat_kg=data.get("berat_kg"),
        kadar_air=data.get("kadar_air"),
        broken_persen=data.get("broken_persen"),
        tujuan=data.get("tujuan"),
        nama_silo=_silo_letter(data.get("nama_silo")),
        keputusan=data.get("keputusan"),
        potongan_kg=data.get("potongan_kg"),
        harga_per_kg=data.get("harga_per_kg"),
        total_harga=data.get("total_harga"),
        tanggal=_parse_iso_date(data.get("tanggal")),
        jam=_parse_hhmm(data.get("jam")),
    )


from app.ai.tools import PROSES_PENYOSOHAN  # noqa: E402


@dataclass
class ParsedPenyosohan:
    intent: str = "bukan_penyosohan"
    kode: str | None = None
    nama_silo_list: list[str] | None = None
    jenis: str | None = None
    berat_kg: float | None = None
    nama_silo: str | None = None
    tanggal: date | None = None
    jam: time | None = None


async def parse_penyosohan(text: str) -> ParsedPenyosohan:
    """Klasifikasi & ekstraksi aksi penyosohan Gudang 2."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_PENYOSOHAN)
    silos = data.get("nama_silo_list")
    if isinstance(silos, list):
        silos = [s for s in (_silo_letter(x) for x in silos) if s] or None
    else:
        silos = None
    kode = data.get("kode")
    jenis = data.get("jenis")
    return ParsedPenyosohan(
        intent=data.get("intent", "bukan_penyosohan"),
        kode=kode.upper().strip() if isinstance(kode, str) else None,
        nama_silo_list=silos,
        jenis=jenis.lower().strip() if isinstance(jenis, str) else None,
        berat_kg=data.get("berat_kg"),
        nama_silo=_silo_letter(data.get("nama_silo")),
        tanggal=_parse_iso_date(data.get("tanggal")),
        jam=_parse_hhmm(data.get("jam")),
    )
