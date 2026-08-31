"""Parser NLP domain Gudang 1: pembelian, pengeringan, silo, milling."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, time

from app.ai.base import _invoke_tool, _parse_hhmm, _parse_iso_date, _silo_letter
from app.ai.tools import (
    CATAT_PEMBELIAN_GABAH,
    PROSES_MILLING,
    PROSES_PENGERINGAN,
    PROSES_SILO,
)


@dataclass
class ParsedPurchase:
    is_pembelian_gabah: bool = False
    nama_supplier: str | None = None
    berat_kg: float | None = None
    kondisi_gabah: str | None = None
    no_polisi_truk: str | None = None
    kadar_air_awal_persen: float | None = None
    tanggal: date | None = None
    jam: time | None = None

    def merge(self, other: "ParsedPurchase") -> "ParsedPurchase":
        """Gabungkan hasil koreksi: nilai baru (non-None) menimpa nilai lama."""
        data = asdict(self)
        for k, v in asdict(other).items():
            if k == "is_pembelian_gabah":
                continue
            if v is not None:
                data[k] = v
        return ParsedPurchase(**data)


async def _call_claude(messages: list[dict]) -> ParsedPurchase:
    data = await _invoke_tool(messages, CATAT_PEMBELIAN_GABAH)
    return ParsedPurchase(
        is_pembelian_gabah=bool(data.get("is_pembelian_gabah", False)),
        nama_supplier=data.get("nama_supplier"),
        berat_kg=data.get("berat_kg"),
        kondisi_gabah=data.get("kondisi_gabah"),
        no_polisi_truk=data.get("no_polisi_truk"),
        kadar_air_awal_persen=data.get("kadar_air_awal_persen"),
        tanggal=_parse_iso_date(data.get("tanggal")),
        jam=_parse_hhmm(data.get("jam")),
    )


async def parse_purchase(text: str) -> ParsedPurchase:
    """Ekstrak data pembelian dari satu pesan operator."""
    return await _call_claude([{"role": "user", "content": text}])


async def apply_correction(current: ParsedPurchase, text: str) -> ParsedPurchase:
    """Terapkan koreksi operator ke draft yang sudah ada.

    Contoh: draft berat 8000, operator bilang 'eh salah 9 ton' -> 9000.
    """
    context = (
        "Draft pembelian gabah saat ini:\n"
        f"- supplier: {current.nama_supplier}\n"
        f"- berat_kg: {current.berat_kg}\n"
        f"- kondisi: {current.kondisi_gabah}\n"
        f"- no_polisi: {current.no_polisi_truk}\n"
        f"- kadar_air: {current.kadar_air_awal_persen}\n\n"
        f"Operator mengoreksi: \"{text}\"\n"
        "Kembalikan HANYA field yang berubah (sisanya null)."
    )
    correction = await _call_claude([{"role": "user", "content": context}])
    return current.merge(correction)


@dataclass
class ParsedPengeringan:
    intent: str = "bukan_pengeringan"
    kode_batch_list: list[str] | None = None
    batch_urutan_list: list[int] | None = None
    semua_batch: bool = False
    kode_lot: str | None = None
    kadar_air_indikator: float | None = None
    kadar_air_tes_manual: float | None = None
    periode: str | None = None
    catatan: str | None = None
    tanggal: date | None = None
    jam: time | None = None


async def parse_pengeringan(text: str) -> ParsedPengeringan:
    """Klasifikasi & ekstraksi perintah pengeringan (Gudang 1)."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_PENGERINGAN)
    kodes = data.get("kode_batch_list")
    if isinstance(kodes, list):
        kodes = [k.upper().strip() for k in kodes if isinstance(k, str) and k.strip()]
    else:
        kodes = None
    urutan = data.get("batch_urutan_list")
    if isinstance(urutan, list):
        urutan = [int(u) for u in urutan if isinstance(u, (int, float))]
        urutan = urutan or None
    else:
        urutan = None
    lot = data.get("kode_lot")
    return ParsedPengeringan(
        intent=data.get("intent", "bukan_pengeringan"),
        kode_batch_list=kodes,
        batch_urutan_list=urutan,
        semua_batch=bool(data.get("semua_batch", False)),
        kode_lot=lot.upper().strip() if isinstance(lot, str) else None,
        kadar_air_indikator=data.get("kadar_air_indikator"),
        kadar_air_tes_manual=data.get("kadar_air_tes_manual"),
        periode=data.get("periode"),
        catatan=data.get("catatan"),
        tanggal=_parse_iso_date(data.get("tanggal")),
        jam=_parse_hhmm(data.get("jam")),
    )


@dataclass
class ParsedMilling:
    intent: str = "bukan_milling"
    nama_silo: str | None = None
    kode_proses: str | None = None
    berat_kg: float | None = None
    tujuan: str | None = None
    tanggal: date | None = None
    jam: time | None = None


async def parse_milling(text: str) -> ParsedMilling:
    """Klasifikasi & ekstraksi perintah milling / pecah kulit (Gudang 1)."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_MILLING)
    kode = data.get("kode_proses")
    return ParsedMilling(
        intent=data.get("intent", "bukan_milling"),
        nama_silo=_silo_letter(data.get("nama_silo")),
        kode_proses=kode.upper().strip() if isinstance(kode, str) else None,
        berat_kg=data.get("berat_kg"),
        tujuan=data.get("tujuan"),
        tanggal=_parse_iso_date(data.get("tanggal")),
        jam=_parse_hhmm(data.get("jam")),
    )


@dataclass
class ParsedSilo:
    intent: str = "bukan_silo"
    nama_silo: str | None = None
    kode_lot: str | None = None
    kode_batch: str | None = None
    tanggal: date | None = None
    jam: time | None = None


async def parse_silo(text: str) -> ParsedSilo:
    """Klasifikasi & ekstraksi perintah silo Gudang 1."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_SILO)
    lot = data.get("kode_lot")
    batch = data.get("kode_batch")
    return ParsedSilo(
        intent=data.get("intent", "bukan_silo"),
        nama_silo=_silo_letter(data.get("nama_silo")),
        kode_lot=lot.upper().strip() if isinstance(lot, str) else None,
        kode_batch=batch.upper().strip() if isinstance(batch, str) else None,
        tanggal=_parse_iso_date(data.get("tanggal")),
        jam=_parse_hhmm(data.get("jam")),
    )
