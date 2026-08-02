"""Register Aset Tetap — PT HMU. Fokus OPERASIONAL (pemeliharaan, lokasi,
dokumen kepemilikan, jadwal servis) — melengkapi Kledo, bukan menggantikan.

PENTING: penyusutan/akuntansi aset = OTORITAS ADA DI KLEDO. Kalkulator
`hitung_penyusutan` di bawah hanya ALAT CEK-SILANG (perkiraan garis lurus);
angka resmi diselaraskan saat integrasi Kledo. Jangan jadikan sumber kebenaran.

Kelompok masa manfaat (pajak) hanya rujukan cek-silang — konfirmasi ke Kledo/
konsultan: Kel.1=4th · Kel.2=8th · Kel.3=16th · Kel.4=20th · bangunan 10/20th.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Default masa manfaat (tahun) per kategori — mesin & kendaraan lazim Kelompok 2/3.
MASA_MANFAAT_DEFAULT = {"Mesin": 8, "Kendaraan": 8, "Bangunan": 20, "Alat": 4}


@dataclass(frozen=True)
class Penyusutan:
    penyusutan_tahunan: float
    akumulasi: float
    nilai_buku: float
    tersusut_penuh: bool


def _bulan_antara(a: date, b: date) -> int:
    """Jumlah bulan penuh dari a ke b (>=0)."""
    return max(0, (b.year - a.year) * 12 + (b.month - a.month))


def hitung_penyusutan(
    *,
    nilai_perolehan: float,
    tanggal_perolehan: date,
    masa_manfaat_tahun: int,
    per_tanggal: date,
    nilai_residu: float = 0.0,
    metode: str = "garis_lurus",
) -> Penyusutan:
    """Penyusutan garis lurus per `per_tanggal`.

    penyusutan_tahunan = (perolehan − residu) / masa_manfaat.
    Akumulasi dibatasi maksimal (perolehan − residu); nilai buku ≥ residu.
    """
    if metode != "garis_lurus":
        raise ValueError(f"metode belum didukung: {metode!r}")
    if masa_manfaat_tahun <= 0:
        raise ValueError("masa_manfaat_tahun harus > 0")
    dasar = max(0.0, nilai_perolehan - nilai_residu)
    per_tahun = dasar / masa_manfaat_tahun
    bulan = _bulan_antara(tanggal_perolehan, per_tanggal)
    akumulasi = min(dasar, per_tahun * bulan / 12)
    return Penyusutan(
        penyusutan_tahunan=round(per_tahun, 2),
        akumulasi=round(akumulasi, 2),
        nilai_buku=round(nilai_perolehan - akumulasi, 2),
        tersusut_penuh=akumulasi >= dasar - 0.005,
    )


# ─────────── Register awal: 38 aset (dari Kartu Pemeliharaan Aset HMU) ───────────
# nilai_perolehan & tanggal_perolehan menyusul (dari faktur pembelian).
def _m(kode, nama, lokasi):
    return {"kode": kode, "nama": nama, "kategori": "Mesin", "lokasi": lokasi,
            "masa_manfaat_tahun": MASA_MANFAAT_DEFAULT["Mesin"]}


REGISTER_AWAL: list[dict] = [
    {"kode": "07-KEND-001", "nama": "Truk Mitsubishi Canter", "kategori": "Kendaraan",
     "lokasi": "Operasional", "masa_manfaat_tahun": 8},
    {"kode": "07-KEND-002", "nama": "Truk Isuzu Elf", "kategori": "Kendaraan",
     "lokasi": "Operasional", "masa_manfaat_tahun": 8},
    # Gudang 1
    _m("07-MSN-G1-01", "Ayakan Sampah", "Gudang 1"),
    _m("07-MSN-G1-02", "Blower CO", "Gudang 1"),
    _m("07-MSN-G1-03", "Air Lock Sampah", "Gudang 1"),
    _m("07-MSN-G1-04", "Dryer", "Gudang 1"),
    _m("07-MSN-G1-05", "Tungku", "Gudang 1"),
    _m("07-MSN-G1-06", "Conveyor Atas", "Gudang 1"),
    _m("07-MSN-G1-07", "Conveyor Bawah", "Gudang 1"),
    _m("07-MSN-G1-08", "Paddy Husker", "Gudang 1"),
    _m("07-MSN-G1-09", "Paddy Separator", "Gudang 1"),
    _m("07-MSN-G1-10", "Elevator 1", "Gudang 1"),
    _m("07-MSN-G1-11", "Elevator 2", "Gudang 1"),
    _m("07-MSN-G1-12", "Elevator 3", "Gudang 1"),
    _m("07-MSN-G1-13", "Elevator 4", "Gudang 1"),
    _m("07-MSN-G1-14", "Elevator 5", "Gudang 1"),
    _m("07-MSN-G1-15", "Elevator 6", "Gudang 1"),
    _m("07-MSN-G1-16", "Elevator Sekam", "Gudang 1"),
    _m("07-MSN-G1-17", "Dust Collector", "Gudang 1"),
    _m("07-MSN-G1-18", "Blower Sekam", "Gudang 1"),
    _m("07-MSN-G1-19", "Airlock Sekam", "Gudang 1"),
    # Gudang 2
    _m("07-MSN-G2-01", "Ayakan Sampah", "Gudang 2"),
    _m("07-MSN-G2-02", "Separator", "Gudang 2"),
    _m("07-MSN-G2-03", "Abrasive Polisher CLJ", "Gudang 2"),
    _m("07-MSN-G2-04", "Abrasive Polisher CFM 25", "Gudang 2"),
    _m("07-MSN-G2-05", "Water Polisher Kinhe 01", "Gudang 2"),
    _m("07-MSN-G2-06", "Color Sorter Meyer 6 Chute", "Gudang 2"),
    _m("07-MSN-G2-07", "Rotary Shifter Crown", "Gudang 2"),
    _m("07-MSN-G2-08", "Rotary Shifter Toshi Sanli", "Gudang 2"),
    _m("07-MSN-G2-09", "Water Polisher Kinhe 02", "Gudang 2"),
    _m("07-MSN-G2-10", "Timbangan Auto Packaging", "Gudang 2"),
    _m("07-MSN-G2-11", "Cyclone System & Pipanisasi Bekatul", "Gudang 2"),
    _m("07-MSN-G2-12", "Conveyor Muat", "Gudang 2"),
    # Bersama
    _m("07-MSN-BSM-01", "Air Compressor JM Eagle 30 HP", "Bersama (2 gudang)"),
    _m("07-MSN-BSM-02", "Air Compressor Luowei 20 HP", "Bersama (2 gudang)"),
    _m("07-MSN-BSM-03", "Air Dryer", "Bersama (2 gudang)"),
    _m("07-MSN-BSM-04", "Jaringan Pipa Angin + Filter Sistem", "Bersama (2 gudang)"),
    _m("07-MSN-BSM-05", "Tabung Angin (Air Receiver) 1000 L", "Bersama (2 gudang)"),
]
