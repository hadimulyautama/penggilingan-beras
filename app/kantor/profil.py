"""Profil PT Hadi Mulya Utama — satu sumber data perusahaan untuk semua peran.

Data non-sensitif = terverifikasi dari kop resmi dokumen (Pedoman Kearsipan, dll).
Data SENSITIF (NPWP, akta, rekening) TIDAK ditulis di kode — dibaca dari
"brankas" server (environment variable) saat berjalan, agar tak bocor lewat git.
Set di Railway: HMU_NPWP, HMU_NO_AKTA, HMU_TAHUN_BERDIRI, HMU_REKENING_BANK.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProfilPerusahaan:
    nama: str
    bidang: str
    alamat: str
    kota: str
    provinsi: str
    telepon: str
    email: str
    website: str
    direktur_utama: str
    kode_entitas: str          # dipakai di nomor surat: PT-HMU
    singkatan: str             # PT HMU

    # ── Fakta bisnis (terverifikasi dari Comprehensive Company Profile.docx) ──
    produk: str = "Beras putih sosoh (polished white rice)"
    merek: tuple[str, ...] = ("Lospulen", "Penyunesia", "Pulenesia")
    ukuran_kemasan: tuple[str, ...] = ("10 kg", "25 kg", "50 kg")
    kemitraan: tuple[str, ...] = (
        "BULOG", "PERPADI", "Preferred by Nature (program low-carbon rice)",
    )

    # ── Data SENSITIF: dibaca dari brankas server (env), bukan ditulis di kode ──
    @property
    def npwp(self) -> str | None:
        return os.getenv("HMU_NPWP")

    @property
    def no_akta_pendirian(self) -> str | None:
        return os.getenv("HMU_NO_AKTA")

    @property
    def tahun_berdiri(self) -> int | None:
        v = os.getenv("HMU_TAHUN_BERDIRI")
        return int(v) if v and v.isdigit() else None

    @property
    def rekening_bank(self) -> str | None:
        return os.getenv("HMU_REKENING_BANK")

    def sensitif_terisi(self) -> dict[str, bool]:
        """Status pengisian data sensitif (untuk pengecekan, tanpa bocorkan nilai)."""
        return {
            "npwp": self.npwp is not None,
            "no_akta_pendirian": self.no_akta_pendirian is not None,
            "tahun_berdiri": self.tahun_berdiri is not None,
            "rekening_bank": self.rekening_bank is not None,
        }


# Terverifikasi dari kop dokumen resmi (mis. Pedoman Kearsipan Digital).
PROFIL = ProfilPerusahaan(
    nama="PT Hadi Mulya Utama",
    bidang="Penggilingan Padi dan Penyosohan Beras",
    alamat="Tegalrejo RT 21/RW 07, Masaran",
    kota="Sragen",
    provinsi="Jawa Tengah",
    telepon="(+62) 851-7416-7950",
    email="info@hadimulya.com",
    website="hadimulya.com",
    direktur_utama="Ahmad Wahid Nurhani",
    kode_entitas="PT-HMU",
    singkatan="PT HMU",
)


def alamat_lengkap() -> str:
    p = PROFIL
    return f"{p.alamat}, {p.kota}, {p.provinsi}"


def kop_surat() -> str:
    """Blok kop surat standar (teks) untuk dokumen yang di-generate."""
    p = PROFIL
    return (
        f"{p.nama}\n{p.bidang}\n{alamat_lengkap()}\n"
        f"Telp. {p.telepon} · Email: {p.email}"
    )
