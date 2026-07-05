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


from app.ai.tools import PROSES_BARANG_JADI  # noqa: E402


@dataclass
class ParsedBarangJadi:
    intent: str = "bukan_barang_jadi"
    kode: str | None = None
    kategori: str | None = None
    grade: str | None = None
    brand: str | None = None
    material: str | None = None
    ukuran_kg: int | None = None
    jumlah_karung: int | None = None
    berat_kg: float | None = None
    jenis_byproduct: str | None = None
    harga: float | None = None
    tanggal: date | None = None
    jam: time | None = None


async def parse_barang_jadi(text: str) -> ParsedBarangJadi:
    """Klasifikasi & ekstraksi aksi barang jadi (packing/bekatul/harga/HPP)."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_BARANG_JADI)
    def _i(v):
        return int(v) if isinstance(v, (int, float)) else None
    kode = data.get("kode")
    kategori = data.get("kategori") or None
    grade = data.get("grade") or None
    if kategori is None and grade:  # grade beras → kategori beras_putih
        kategori = "beras_putih"
    return ParsedBarangJadi(
        intent=data.get("intent", "bukan_barang_jadi"),
        kode=kode.upper().strip() if isinstance(kode, str) else None,
        kategori=kategori,
        grade=grade,
        brand=(data.get("brand") or None),
        material=(data.get("material") or None),
        ukuran_kg=_i(data.get("ukuran_kg")),
        jumlah_karung=_i(data.get("jumlah_karung")),
        berat_kg=data.get("berat_kg"),
        jenis_byproduct=(data.get("jenis_byproduct") or None),
        harga=data.get("harga"),
        tanggal=_parse_iso_date(data.get("tanggal")),
        jam=_parse_hhmm(data.get("jam")),
    )


from app.ai.tools import PROSES_KELUAR  # noqa: E402


@dataclass
class ParsedKeluar:
    intent: str = "bukan_keluar"
    kategori: str | None = None
    grade: str | None = None
    brand: str | None = None
    material: str | None = None
    ukuran_kg: int | None = None
    jumlah_karung: int | None = None
    berat_kg: float | None = None
    kode: str | None = None
    nama_pembeli: str | None = None
    metode: str | None = None
    no_polisi: str | None = None
    nama_ekspedisi: str | None = None
    harga_per_kg: float | None = None
    tanggal: date | None = None
    jam: time | None = None


async def parse_keluar(text: str) -> ParsedKeluar:
    """Klasifikasi & ekstraksi barang keluar / dikirim."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_KELUAR)
    def _i(v):
        return int(v) if isinstance(v, (int, float)) else None
    kode = data.get("kode")
    kategori = data.get("kategori") or None
    grade = data.get("grade") or None
    if kategori is None and grade:
        kategori = "beras_putih"
    return ParsedKeluar(
        intent=data.get("intent", "bukan_keluar"),
        kategori=kategori, grade=grade,
        brand=(data.get("brand") or None),
        material=(data.get("material") or None),
        ukuran_kg=_i(data.get("ukuran_kg")),
        jumlah_karung=_i(data.get("jumlah_karung")),
        berat_kg=data.get("berat_kg"),
        kode=kode.upper().strip() if isinstance(kode, str) else None,
        nama_pembeli=(data.get("nama_pembeli") or None),
        metode=(data.get("metode") or None),
        no_polisi=(data.get("no_polisi") or None),
        nama_ekspedisi=(data.get("nama_ekspedisi") or None),
        harga_per_kg=data.get("harga_per_kg"),
        tanggal=_parse_iso_date(data.get("tanggal")),
        jam=_parse_hhmm(data.get("jam")),
    )
