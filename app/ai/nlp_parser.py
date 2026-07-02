"""Parser bahasa natural -> data pembelian gabah terstruktur (via Claude)."""
from __future__ import annotations

from dataclasses import dataclass, asdict

from app.ai.claude_client import get_client
from app.ai.tools import (
    CARI_KODE,
    CATAT_PEMBELIAN_GABAH,
    PROSES_MILLING,
    PROSES_MILLING_ADMIN,
    PROSES_PENGERINGAN,
    PROSES_SILO,
    PROSES_TRANSFER,
    SYSTEM_PROMPT,
    TANYA_DETAIL,
    TANYA_LAPORAN_GABAH,
    TANYA_PENDING,
    TANYA_STATUS,
    VERIFIKASI_HARGA_GABAH,
)
from app.config import settings


@dataclass
class ParsedPurchase:
    is_pembelian_gabah: bool = False
    nama_supplier: str | None = None
    berat_kg: float | None = None
    kondisi_gabah: str | None = None
    no_polisi_truk: str | None = None
    kadar_air_awal_persen: float | None = None

    def merge(self, other: "ParsedPurchase") -> "ParsedPurchase":
        """Gabungkan hasil koreksi: nilai baru (non-None) menimpa nilai lama."""
        data = asdict(self)
        for k, v in asdict(other).items():
            if k == "is_pembelian_gabah":
                continue
            if v is not None:
                data[k] = v
        return ParsedPurchase(**data)


async def _invoke_tool(messages: list[dict], tool: dict) -> dict:
    """Panggil Claude dengan forced tool-use dan kembalikan input tool (dict)."""
    client = get_client()
    resp = await client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=messages,
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return dict(block.input)
    return {}


async def _call_claude(messages: list[dict]) -> ParsedPurchase:
    data = await _invoke_tool(messages, CATAT_PEMBELIAN_GABAH)
    return ParsedPurchase(
        is_pembelian_gabah=bool(data.get("is_pembelian_gabah", False)),
        nama_supplier=data.get("nama_supplier"),
        berat_kg=data.get("berat_kg"),
        kondisi_gabah=data.get("kondisi_gabah"),
        no_polisi_truk=data.get("no_polisi_truk"),
        kadar_air_awal_persen=data.get("kadar_air_awal_persen"),
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
class ParsedVerification:
    is_verifikasi_harga: bool = False
    kode_batch: str | None = None
    metode_harga: str | None = None  # total | per_kg
    nilai_rupiah: float | None = None


@dataclass
class ParsedPengeringan:
    intent: str = "bukan_pengeringan"
    kode_batch_list: list[str] | None = None
    batch_urutan_list: list[int] | None = None
    kode_lot: str | None = None
    kadar_air_indikator: float | None = None
    kadar_air_tes_manual: float | None = None
    periode: str | None = None
    catatan: str | None = None


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
        kode_lot=lot.upper().strip() if isinstance(lot, str) else None,
        kadar_air_indikator=data.get("kadar_air_indikator"),
        kadar_air_tes_manual=data.get("kadar_air_tes_manual"),
        periode=data.get("periode"),
        catatan=data.get("catatan"),
    )


@dataclass
class ParsedMilling:
    intent: str = "bukan_milling"
    nama_silo: str | None = None
    kode_proses: str | None = None
    berat_kg: float | None = None
    tujuan: str | None = None


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
    )


@dataclass
class ParsedTransfer:
    intent: str = "bukan_transfer"
    kode_proses: str | None = None
    lokasi_tujuan: str | None = None


async def parse_transfer(text: str) -> ParsedTransfer:
    """Klasifikasi & ekstraksi perintah transfer internal G1->G2."""
    data = await _invoke_tool([{"role": "user", "content": text}], PROSES_TRANSFER)
    kode = data.get("kode_proses")
    return ParsedTransfer(
        intent=data.get("intent", "bukan_transfer"),
        kode_proses=kode.upper().strip() if isinstance(kode, str) else None,
        lokasi_tujuan=data.get("lokasi_tujuan"),
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
class ParsedSilo:
    intent: str = "bukan_silo"
    nama_silo: str | None = None
    kode_lot: str | None = None
    kode_batch: str | None = None


def _silo_letter(v) -> str | None:
    """Hanya terima 'A' atau 'B'; nilai lain (placeholder AI) -> None."""
    if isinstance(v, str):
        s = v.upper().strip()
        if s in ("A", "B"):
            return s
    return None


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
    )


@dataclass
class ParsedReport:
    is_laporan_gabah: bool = False
    periode: str | None = None


async def parse_report(text: str) -> ParsedReport:
    """Deteksi pertanyaan laporan pembelian gabah + periode."""
    data = await _invoke_tool([{"role": "user", "content": text}], TANYA_LAPORAN_GABAH)
    return ParsedReport(
        is_laporan_gabah=bool(data.get("is_laporan_gabah", False)),
        periode=data.get("periode"),
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
class ParsedDetail:
    is_detail: bool = False
    target: str | None = None  # batch | lot | milling
    kode: str | None = None
    supplier_nama: str | None = None
    periode: str | None = None
    urutan: int | None = None
    kondisi: str | None = None
    terbaru: bool = False


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
    )


async def parse_verification(text: str) -> ParsedVerification:
    """Ekstrak data verifikasi harga gabah dari pesan staff/admin."""
    data = await _invoke_tool(
        [{"role": "user", "content": text}], VERIFIKASI_HARGA_GABAH
    )
    kode = data.get("kode_batch")
    return ParsedVerification(
        is_verifikasi_harga=bool(data.get("is_verifikasi_harga", False)),
        kode_batch=kode.upper().strip() if isinstance(kode, str) else None,
        metode_harga=data.get("metode_harga"),
        nilai_rupiah=data.get("nilai_rupiah"),
    )
