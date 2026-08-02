"""Aturan formal naskah dinas PT HMU — pola nomor, kode perihal, bulan Romawi.

Sumber kebenaran: Pedoman Tata Naskah Dinas (PDM/TND/PT-HMU/01).
Modul MURNI (tanpa DB/IO) → mudah diuji & dipakai lintas-peran.

Format (keputusan pemilik 2026-08-02 — garis miring + divisi):
  - Surat  : NNN/KODE/DIVISI/PT-HMU/BULAN(Romawi)/TAHUN  mis. 002/ST/HRGA/PT-HMU/VII/2026
  - Dokumen: JENIS/KODE/PT-HMU/NO                        mis. PDM/TND/PT-HMU/01
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ENTITAS = "PT-HMU"

# ─────────────────────────── Bulan Romawi ───────────────────────────
_ROMAWI = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
BULAN_KE_ROMAWI = {i + 1: r for i, r in enumerate(_ROMAWI)}
ROMAWI_KE_BULAN = {r: i + 1 for i, r in enumerate(_ROMAWI)}


def bulan_romawi(bulan: int) -> str:
    """1..12 → 'I'..'XII'. Raise bila di luar rentang."""
    if bulan not in BULAN_KE_ROMAWI:
        raise ValueError(f"bulan tidak valid: {bulan!r} (harus 1-12)")
    return BULAN_KE_ROMAWI[bulan]


# ─────────────────────────── Kode perihal ───────────────────────────
# Kode BAKU. Sebagian dari praktik nyata dokumen perusahaan (mis. offboarding
# Affifah: SPPD/BAST/BASTB/TTPH) — diadopsi agar asisten menguasai SOP yang ada.
KODE_BAKU: dict[str, str] = {
    "CSR": "Surat terkait CSR",
    "SK": "Surat Keputusan",
    "SPK": "Surat Perintah Kerja",
    "ST": "Surat Tugas",
    "SP": "Surat Peringatan",
    "BA": "Berita Acara",
    # ── Kode dari praktik nyata HR (Panduan Struktur Folder HRGA §C) ──
    "SPPD": "Surat Persetujuan Pengunduran Diri",
    "BAST": "Berita Acara Serah-Terima",
    "BASTB": "Berita Acara Serah-Terima (Akses Perbankan)",
    "TTPH": "Tanda Terima Penyelesaian Hak",
    "CLR": "Lembar Clearance",
    "PKL": "Paklaring (Surat Keterangan Kerja)",
    "SKK": "Sertifikat Kompetensi",
    "PGH": "Piagam Penghargaan",
    "PKWT": "Perjanjian Kerja Waktu Tertentu",
    "PKWTT": "Perjanjian Kerja Waktu Tidak Tertentu",
}

# Kode USULAN (belum disahkan) — dikenali tapi diberi peringatan oleh konsistensi.
KODE_USULAN: dict[str, str] = {
    "SKET": "Surat Keterangan",
    "SU": "Surat Undangan",
    "NK": "Nota Kesepahaman / MoU",
    "SPn": "Surat Permohonan",
    "LPJ": "Laporan Pertanggungjawaban",
}

# Jenis dokumen tata kelola (bagian JENIS pada pola slash).
JENIS_DOKUMEN: dict[str, str] = {
    "PDM": "Pedoman",
    "PDN": "Panduan",
    "SOP": "Standard Operating Procedure",
    "IK": "Instruksi Kerja",
}

# Kode DIVISI/unit penerbit (bagian DIVISI pada nomor surat). USULAN — selaras
# kategori arsip; tinggal disahkan pemilik. 'HR' diterima sbg alias 'HRGA'.
DIVISI: dict[str, str] = {
    "DIR": "Direksi & Sekretariat",
    "HR": "SDM & Umum (HRGA)",   # kode nyata di nomor = HR (bukan HRGA)
    "KEU": "Keuangan & Pajak",
    "OPS": "Operasional & Gudang",
    "MKT": "Penjualan & Pemasaran",
    "PBJ": "Pengadaan & Pemasok",
    "IT": "IT & Sistem",
}
_ALIAS_DIVISI = {"HRGA": "HR"}   # terima 'HRGA' → normalkan ke kode nyata 'HR'


def normal_divisi(divisi: str) -> str:
    d = divisi.upper()
    return _ALIAS_DIVISI.get(d, d)


def divisi_dikenali(divisi: str) -> bool:
    return normal_divisi(divisi) in DIVISI


def kode_dikenali(kode: str) -> bool:
    return kode in KODE_BAKU or kode in KODE_USULAN


def kode_disahkan(kode: str) -> bool:
    return kode in KODE_BAKU


# ─────────────────────────── Pola & parsing ───────────────────────────
# Urut 2-3 digit: praktik nyata perusahaan memakai 2 digit (mis. 01/SPPD/...),
# tetap terima 3 digit agar dokumen lama sah. Generasi baru → 2 digit (lihat build).
_RE_SURAT = re.compile(
    r"^(?P<urut>\d{2,3})/(?P<kode>[A-Za-z]{1,6})/(?P<divisi>[A-Za-z]{2,6})/PT-HMU/"
    r"(?P<romawi>[IVX]{1,4})/(?P<tahun>\d{4})$"
)
_RE_DOKUMEN = re.compile(
    r"^(?P<jenis>[A-Z]{2,4})/(?P<kode>[A-Z0-9-]{1,12})/PT-HMU/(?P<no>\d{2})$"
)


@dataclass(frozen=True)
class NomorSurat:
    urut: int
    kode: str
    divisi: str
    bulan: int
    tahun: int

    def format(self) -> str:
        return build_nomor_surat(self.urut, self.kode, self.divisi, self.bulan, self.tahun)


@dataclass(frozen=True)
class NomorDokumenTK:
    jenis: str
    kode: str
    no: int

    def format(self) -> str:
        return f"{self.jenis}/{self.kode}/{ENTITAS}/{self.no:02d}"


def build_nomor_surat(urut: int, kode: str, divisi: str, bulan: int, tahun: int) -> str:
    """Rakit nomor surat baku (garis miring + divisi). Kode/divisi → huruf besar.

    Urut dipad 3 digit (001, 002, …) — standar resmi (keputusan pemilik 2026-08).
    Dokumen lama ber-2-digit tetap diterima parser sbg warisan.
    """
    if not (1 <= urut <= 999):
        raise ValueError(f"urut di luar rentang 001-999: {urut}")
    return (
        f"{urut:03d}/{kode.upper()}/{normal_divisi(divisi)}/{ENTITAS}/"
        f"{bulan_romawi(bulan)}/{tahun}"
    )


def parse_nomor_surat(s: str) -> NomorSurat | None:
    """Uraikan string nomor surat → NomorSurat, atau None bila tak sesuai pola.

    Mengembalikan None juga bila bulan Romawi tidak valid (mis. 'XIII').
    """
    m = _RE_SURAT.match(s.strip())
    if not m:
        return None
    romawi = m.group("romawi")
    bulan = ROMAWI_KE_BULAN.get(romawi)
    if bulan is None:
        return None
    return NomorSurat(
        urut=int(m.group("urut")),
        kode=m.group("kode").upper(),
        divisi=normal_divisi(m.group("divisi")),
        bulan=bulan,
        tahun=int(m.group("tahun")),
    )


def parse_nomor_dokumen(s: str) -> NomorDokumenTK | None:
    """Uraikan string nomor dokumen tata kelola (pola slash)."""
    m = _RE_DOKUMEN.match(s.strip())
    if not m:
        return None
    return NomorDokumenTK(
        jenis=m.group("jenis"),
        kode=m.group("kode"),
        no=int(m.group("no")),
    )
