"""Kategori arsip FISIK (Pedoman Kearsipan Fisik v1.1) + peta-silang ke digital.

Melengkapi taksonomi digital (app/kantor/drive/taksonomi.py, kode 00–11) dengan
sistem FISIK (kode 01–09, warna, golongan, retensi) dan jembatan antar keduanya
(lihat docs/kantor/PETA-SILANG-ARSIP.md). MURNI (tanpa DB/IO).

Dipakai tool "panduan_arsip" agar asisten bisa MEMANDU: dokumen X → ordner fisik
mana (warna/golongan/retensi) + folder digital mana.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.kantor.drive import taksonomi as tx


@dataclass(frozen=True)
class KategoriFisik:
    kode: str
    nama: str
    warna: str
    golongan: str      # VITAL / AKTIF / INAKTIF (+kombinasi)
    retensi: str


# 9 kategori fisik berkode (Pedoman Kearsipan Fisik v1.1 Bab III & V).
FISIK: dict[str, KategoriFisik] = {
    "01": KategoriFisik("01", "Legalitas & Perizinan", "Merah", "VITAL", "Permanen"),
    "02": KategoriFisik("02", "Keuangan & Perbankan", "Hijau", "AKTIF", "10 tahun"),
    "03": KategoriFisik("03", "Perpajakan", "Kuning", "AKTIF", "10 tahun"),
    "04": KategoriFisik("04", "Pembelian & Pemasok", "Biru", "AKTIF", "10 tahun"),
    "05": KategoriFisik("05", "Penjualan & Pelanggan", "Oranye", "AKTIF", "10 tahun"),
    "06": KategoriFisik("06", "Produksi & Gudang", "Coklat", "AKTIF", "5 tahun"),
    "07": KategoriFisik("07", "SDM / Kepegawaian (HRGA)", "Ungu", "AKTIF + VITAL",
                        "selama bekerja + 5 tahun"),
    "08": KategoriFisik("08", "Aset, Mesin & Kendaraan", "Abu-abu", "AKTIF + VITAL",
                        "selama dimiliki + 5 tahun"),
    "09": KategoriFisik("09", "Umum & Korespondensi", "Hitam/Putih", "AKTIF", "3 tahun"),
}

# Jembatan DIGITAL (00–11) → FISIK (01–09). Sebagian digital tak punya padanan
# ordner khusus → jatuh ke 09 Umum.
DIGITAL_KE_FISIK: dict[str, str] = {
    "00": "01",  # Legalitas & Sekretariat → Legalitas
    "01": "09",  # Korespondensi → Umum & Korespondensi
    "02": "02",  # Keuangan & Pajak → Keuangan (pajak lihat catatan → 03)
    "03": "07",  # SDM & Umum (HRGA) → SDM
    "04": "06",  # Operasional & Gudang → Produksi & Gudang
    "05": "05",  # Penjualan & Pemasaran → Penjualan
    "06": "04",  # Pengadaan & Pemasok → Pembelian & Pemasok
    "07": "08",  # Aset & Pemeliharaan → Aset, Mesin & Kendaraan
    "08": "09",  # IT & Sistem → (fisik: Umum)
    "09": "09",  # Proyek → (fisik: Umum, kecuali dokumen khusus)
    "10": "09",  # CSR & Kegiatan → (fisik: Umum)
    "11": "09",  # Tata Kelola & Kearsipan → (fisik: Umum)
}


def fisik_dari_digital(digital_kode: str) -> KategoriFisik | None:
    return FISIK.get(DIGITAL_KE_FISIK.get(digital_kode, ""))


@dataclass
class PanduanArsip:
    digital_kode: str
    digital_nama: str
    fisik: KategoriFisik | None
    catatan: str = ""


def panduan(digital_kode: str) -> PanduanArsip:
    """Dari kode kategori DIGITAL → panduan arsip lengkap (digital + fisik)."""
    dkat = tx.kategori(digital_kode)
    fisik = fisik_dari_digital(digital_kode)
    catatan = ""
    if digital_kode == "02":
        catatan = "Dokumen PAJAK (faktur pajak/SPT/bukti setor) → ordner fisik 03 Perpajakan (Kuning)."
    elif digital_kode in ("08", "09", "10", "11"):
        catatan = "Umumnya native-digital; bila ada berkas fisik → ordner 09 Umum."
    return PanduanArsip(
        digital_kode=digital_kode,
        digital_nama=dkat.nama if dkat else "?",
        fisik=fisik,
        catatan=catatan,
    )
