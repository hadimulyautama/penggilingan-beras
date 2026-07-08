"""Facade parser NLP: parser bersama/admin + re-export parser domain G1/G2.

Konsumen tetap `from app.ai.nlp_parser import parse_X / ParsedX`. Definisi
parser domain tinggal di app.gudang1.nlp / app.gudang2.nlp; infra di app.ai.base.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.ai.base import _invoke_tool, _parse_iso_date
from app.ai.tools import (
    CARI_KODE,
    KELOLA_USER,
    TANYA_ANALITIK,
    PROSES_MILLING_ADMIN,
    PROSES_TRANSFER,
    TANYA_DETAIL,
    TANYA_JAM,
    TANYA_LAPORAN_GABAH,
    TANYA_PENDING,
    TANYA_STATUS,
    UNDO_TERAKHIR,
    VERIFIKASI_HARGA_GABAH,
)

# Re-export parser domain (facade) — biar impor lama tetap jalan.
from app.gudang1.nlp import (  # noqa: F401
    ParsedMilling,
    ParsedPengeringan,
    ParsedPurchase,
    ParsedSilo,
    apply_correction,
    parse_milling,
    parse_pengeringan,
    parse_purchase,
    parse_silo,
)
from app.gudang2.nlp import ParsedGudang2, parse_gudang2  # noqa: F401


@dataclass
class ParsedVerification:
    is_verifikasi_harga: bool = False
    kode_batch: str | None = None
    metode_harga: str | None = None  # total | per_kg
    nilai_rupiah: float | None = None
    # Rujukan deskriptif batch (bila kode tidak disebut).
    urutan: int | None = None
    supplier_nama: str | None = None
    terbaru: bool = False


async def parse_verification(text: str) -> ParsedVerification:
    """Ekstrak data verifikasi harga gabah dari pesan staff/admin."""
    data = await _invoke_tool(
        [{"role": "user", "content": text}], VERIFIKASI_HARGA_GABAH
    )
    kode = data.get("kode_batch")
    urut = data.get("urutan")
    sup = data.get("supplier_nama")
    return ParsedVerification(
        is_verifikasi_harga=bool(data.get("is_verifikasi_harga", False)),
        kode_batch=kode.upper().strip() if isinstance(kode, str) else None,
        metode_harga=data.get("metode_harga"),
        nilai_rupiah=data.get("nilai_rupiah"),
        urutan=int(urut) if isinstance(urut, (int, float)) else None,
        supplier_nama=sup.strip() if isinstance(sup, str) and sup.strip() else None,
        terbaru=bool(data.get("terbaru", False)),
    )


@dataclass
class ParsedTransfer:
    intent: str = "bukan_transfer"
    kode_proses: str | None = None
    lokasi_tujuan: str | None = None
    berat_kg: float | None = None


async def parse_transfer(text: str) -> ParsedTransfer:
    """Klasifikasi & ekstraksi perintah transfer internal G1->G2 (bridge)."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_TRANSFER)
    kode = data.get("kode_proses")
    return ParsedTransfer(
        intent=data.get("intent", "bukan_transfer"),
        kode_proses=kode.upper().strip() if isinstance(kode, str) else None,
        lokasi_tujuan=data.get("lokasi_tujuan"),
        berat_kg=data.get("berat_kg"),
    )


@dataclass
class ParsedMillingAdmin:
    intent: str = "bukan_milling_admin"
    kode_proses: str | None = None
    kadar_air: float | None = None
    broken_persen: float | None = None
    susut_persen: float | None = None
    kondisi: str | None = None
    berat_output_kg: float | None = None


async def parse_milling_admin(text: str) -> ParsedMillingAdmin:
    """Klasifikasi & ekstraksi aksi milling sisi staff/admin (QC / verifikasi)."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_MILLING_ADMIN)
    kode = data.get("kode_proses")
    kondisi = data.get("kondisi")
    return ParsedMillingAdmin(
        intent=data.get("intent", "bukan_milling_admin"),
        kode_proses=kode.upper().strip() if isinstance(kode, str) else None,
        kadar_air=data.get("kadar_air"),
        broken_persen=data.get("broken_persen"),
        susut_persen=data.get("susut_persen"),
        kondisi=kondisi.upper().strip() if isinstance(kondisi, str) else None,
        berat_output_kg=data.get("berat_output_kg"),
    )


@dataclass
class ParsedLookup:
    is_cari_kode: bool = False
    target: str | None = None  # batch | lot
    supplier_nama: str | None = None
    periode: str | None = None
    urutan: int | None = None
    kondisi: str | None = None
    terbaru: bool = False
    tanggal: date | None = None


async def parse_lookup(text: str) -> ParsedLookup:
    """Deteksi permintaan mencari kode batch/lot berdasarkan ciri."""
    data = await _invoke_tool([{"role": "user", "content": text}], CARI_KODE)
    urutan = data.get("urutan")
    return ParsedLookup(
        is_cari_kode=bool(data.get("is_cari_kode", False)),
        target=data.get("target"),
        supplier_nama=data.get("supplier_nama"),
        periode=data.get("periode"),
        urutan=int(urutan) if isinstance(urutan, (int, float)) else None,
        kondisi=data.get("kondisi"),
        terbaru=bool(data.get("terbaru", False)),
        tanggal=_parse_iso_date(data.get("tanggal")),
    )


@dataclass
class ParsedReport:
    is_laporan_gabah: bool = False
    periode: str | None = None
    tanggal: date | None = None


async def parse_report(text: str) -> ParsedReport:
    """Deteksi pertanyaan laporan pembelian gabah + periode."""
    data = await _invoke_tool([{"role": "user", "content": text}], TANYA_LAPORAN_GABAH)
    return ParsedReport(
        is_laporan_gabah=bool(data.get("is_laporan_gabah", False)),
        periode=data.get("periode"),
        tanggal=_parse_iso_date(data.get("tanggal")),
    )


async def parse_pending(text: str) -> bool:
    """True bila pengguna menanyakan daftar tugas/verifikasi yang tertunda."""
    data = await _invoke_tool([{"role": "user", "content": text}], TANYA_PENDING)
    return bool(data.get("is_pending", False))


async def parse_status(text: str) -> bool:
    """True bila pengguna menanyakan status umum apa yang sedang berlangsung."""
    data = await _invoke_tool([{"role": "user", "content": text}], TANYA_STATUS)
    return bool(data.get("is_status", False))


@dataclass
class ParsedUndo:
    is_undo: bool = False
    scope: str | None = None
    nama: str | None = None


@dataclass
class ParsedAnalitik:
    intent: str = "bukan_analitik"
    kode_proses: str | None = None
    harga_gabah: float | None = None
    rendemen: float | None = None
    berat_bahan: float | None = None   # simulasi: tonase bahan (gabah) masuk
    berat_hasil: float | None = None   # simulasi: tonase hasil (PK/beras)
    kondisi: str | None = None
    langsung_silo: bool = False


async def parse_analitik(text: str) -> ParsedAnalitik:
    """Intent analitik + parameter (rincian_biaya & simulasi_hpp)."""
    data = await _invoke_tool([{"role": "user", "content": text}], TANYA_ANALITIK)
    kode = data.get("kode_proses")
    return ParsedAnalitik(
        intent=data.get("intent", "bukan_analitik"),
        kode_proses=kode.upper().strip() if isinstance(kode, str) and kode.strip() else None,
        harga_gabah=data.get("harga_gabah"),
        rendemen=data.get("rendemen"),
        berat_bahan=data.get("berat_bahan"),
        berat_hasil=data.get("berat_hasil"),
        kondisi=data.get("kondisi"),
        langsung_silo=bool(data.get("langsung_silo", False)),
    )


async def parse_undo(text: str) -> ParsedUndo:
    """Deteksi permintaan undo tindakan terakhir (+ cakupan siapa)."""
    data = await _invoke_tool([{"role": "user", "content": text}], UNDO_TERAKHIR)
    nama = data.get("nama")
    return ParsedUndo(
        is_undo=bool(data.get("is_undo", False)),
        scope=data.get("scope"),
        nama=nama.strip() if isinstance(nama, str) and nama.strip() else None,
    )


@dataclass
class ParsedUserAdmin:
    intent: str = "bukan_user"
    nama: str | None = None
    role: str | None = None
    gudang: int | None = None
    telegram_id: int | None = None
    no_hp: str | None = None
    ref: str | None = None


async def parse_user_admin(text: str) -> ParsedUserAdmin:
    """Deteksi perintah admin mengelola pengguna."""
    data = await _invoke_tool([{"role": "user", "content": text}], KELOLA_USER)
    tid = data.get("telegram_id")
    gud = data.get("gudang")
    nama = data.get("nama")
    hp = data.get("no_hp")
    ref = data.get("ref")
    return ParsedUserAdmin(
        intent=data.get("intent", "bukan_user"),
        nama=nama.strip() if isinstance(nama, str) and nama.strip() else None,
        role=data.get("role"),
        gudang=int(gud) if isinstance(gud, (int, float)) else None,
        telegram_id=int(tid) if isinstance(tid, (int, float)) else None,
        no_hp=hp.strip() if isinstance(hp, str) and hp.strip() else None,
        ref=ref.strip() if isinstance(ref, str) and ref.strip() else None,
    )


@dataclass
class ParsedJam:
    is_tanya_jam: bool = False
    supplier_nama: str | None = None
    periode: str | None = None
    tanggal: date | None = None


async def parse_jam(text: str) -> ParsedJam:
    """Deteksi pertanyaan pola/analitik jam kedatangan gabah."""
    data = await _invoke_tool([{"role": "user", "content": text}], TANYA_JAM)
    sup = data.get("supplier_nama")
    return ParsedJam(
        is_tanya_jam=bool(data.get("is_tanya_jam", False)),
        supplier_nama=sup.strip() if isinstance(sup, str) and sup.strip() else None,
        periode=data.get("periode"),
        tanggal=_parse_iso_date(data.get("tanggal")),
    )


@dataclass
class ParsedDetail:
    is_detail: bool = False
    target: str | None = None  # batch | lot | milling
    kode: str | None = None
    supplier_nama: str | None = None
    periode: str | None = None
    urutan: int | None = None
    kondisi: str | None = None
    terbaru: bool = False
    tanggal: date | None = None


async def parse_detail(text: str) -> ParsedDetail:
    """Deteksi permintaan detail/atribut sebuah entitas tertentu."""
    data = await _invoke_tool([{"role": "user", "content": text}], TANYA_DETAIL)
    kode = data.get("kode")
    urutan = data.get("urutan")
    return ParsedDetail(
        is_detail=bool(data.get("is_detail", False)),
        target=data.get("target"),
        kode=kode.upper().strip() if isinstance(kode, str) else None,
        supplier_nama=data.get("supplier_nama"),
        periode=data.get("periode"),
        urutan=int(urutan) if isinstance(urutan, (int, float)) else None,
        kondisi=data.get("kondisi"),
        terbaru=bool(data.get("terbaru", False)),
        tanggal=_parse_iso_date(data.get("tanggal")),
    )
