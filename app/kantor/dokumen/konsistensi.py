"""Pemeriksa konsistensi naskah — nomor surat & nama file vs aturan formal.

MURNI (tanpa DB). Dipakai saat dokumen baru masuk / dibuat staf:
memberi daftar temuan (error/peringatan) + usulan perbaikan. Register
DB (penomoran.py) menambah cek "nomor ganda / urut lompat" yang butuh data.

Acuan: Pedoman Tata Naskah Dinas (PDM/TND/PT-HMU/01) & Pedoman Kearsipan
Digital Bab IV (konvensi penamaan file).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from app.kantor.dokumen import format as fmt

# Akronim yang dipertahankan huruf besarnya saat merapikan nama (Title Case).
_AKRONIM = {
    "PT", "HMU", "CV", "PT-HMU", "CSR", "SK", "SPK", "ST", "SP", "BA", "NK",
    "SKET", "LPJ", "PDM", "PDN", "SOP", "IK", "BPJS", "PHK", "NPWP", "KTP",
    "HAKI", "RT", "RW", "MoU", "K3", "IT", "HRGA", "HPP", "BEP", "SPT",
    "PO", "BULOG", "BCA", "BRI", "BNI", "BMT", "KAK", "LAMP", "PM", "AM",
    "UD", "PPN", "PPh", "SPPD", "BAST", "BASTB", "TTPH", "CLR", "PKL", "PKWT",
}
# Token dilarang muncul di nama file (Pedoman Kearsipan Digital Bab IV & X).
# Urutan penting utk rapikan: frasa ("copy of") sebelum kata tunggal ("copy").
_DILARANG = [
    (re.compile(r"\(\d+\)"), "penanda salinan '(n)'"),
    (re.compile(r"\bcopy\s+of\b", re.I), "'copy of'"),
    (re.compile(r"\bcopy\b", re.I), "kata 'copy'"),
    (re.compile(r"\bfinal\b", re.I), "kata 'final'"),
    (re.compile(r"\bfix\b", re.I), "kata 'fix'"),
    (re.compile(r"\bvers?\.?\s*\d+\b", re.I), "penanda versi 'vN'"),
    (re.compile(r"\bnew\s*folder\b", re.I), "'new folder'"),
    (re.compile(r"\btester?\b", re.I), "kata 'test/tester'"),
]


@dataclass
class Temuan:
    # error = melanggar aturan; warning = sebaiknya diperbaiki
    level: str
    pesan: str
    saran: str | None = None


@dataclass
class HasilPeriksa:
    temuan: list[Temuan] = field(default_factory=list)
    nama_usulan: str | None = None

    @property
    def ok(self) -> bool:
        return not any(t.level == "error" for t in self.temuan)


# ─────────────────────────── Nomor surat ───────────────────────────
def validasi_nomor_surat(s: str) -> list[Temuan]:
    """Periksa satu string nomor surat terhadap pola & kode baku."""
    out: list[Temuan] = []
    parsed = fmt.parse_nomor_surat(s)
    if parsed is None:
        out.append(Temuan(
            "error",
            f"Nomor '{s}' tidak sesuai pola baku "
            f"NNN/KODE/DIVISI/PT-HMU/BULAN(Romawi)/TAHUN.",
            saran="Contoh benar: 002/ST/HRGA/PT-HMU/VII/2026.",
        ))
        return out
    if not fmt.kode_dikenali(parsed.kode):
        out.append(Temuan(
            "error",
            f"Kode perihal '{parsed.kode}' tidak dikenali.",
            saran=f"Gunakan salah satu kode baku: {', '.join(fmt.KODE_BAKU)}.",
        ))
    elif not fmt.kode_disahkan(parsed.kode):
        out.append(Temuan(
            "warning",
            f"Kode '{parsed.kode}' masih USULAN (belum disahkan Direksi).",
            saran="Sahkan kode ini di Tata Naskah Dinas atau ganti ke kode baku.",
        ))
    if not fmt.divisi_dikenali(parsed.divisi):
        out.append(Temuan(
            "warning",
            f"Kode divisi '{parsed.divisi}' tidak dikenali.",
            saran=f"Divisi baku: {', '.join(fmt.DIVISI)} (HR = alias HRGA).",
        ))
    return out


# ─────────────────────────── Nama file ───────────────────────────
def _title_case_preserve(teks: str) -> str:
    """Title Case tapi pertahankan akronim, angka, nomor Romawi, dan pola nomor."""
    def fix(word: str) -> str:
        bare = word.strip()
        if not bare:
            return word
        up = bare.upper()
        if up in _AKRONIM or up.replace("-", "") in {a.replace("-", "") for a in _AKRONIM}:
            return up if up != "PT-HMU" else "PT-HMU"
        if up in fmt.ROMAWI_KE_BULAN:            # bulan Romawi
            return up
        if any(c.isdigit() for c in bare):       # mengandung angka → biarkan
            return bare
        return bare[:1].upper() + bare[1:].lower()
    return " ".join(fix(w) for w in teks.split(" "))


def rapikan_nama(nama: str) -> str:
    """Usulkan nama file baku dari nama berantakan (heuristik, aman).

    Aman: bila pembersihan mengosongkan nama (mis. 'tester.xlsx'), KEMBALIKAN
    nama asli — jangan pernah menghasilkan nama kosong. Tanggal (2024-07-19) &
    tanda hubung dalam token dibiarkan utuh.
    """
    base, ext = os.path.splitext(nama)
    s = base.replace("_", " ")
    for pola, _ in _DILARANG:
        s = pola.sub(" ", s)
    s = re.sub(r"\s{2,}", " ", s)          # rapikan spasi (hyphen dalam kata dibiarkan)
    s = re.sub(r"( -){2,}", " -", s)       # runtuhkan deret ' - - - ' jadi satu
    s = re.sub(r"(?: -)+$", "", s)         # buang ' -' beruntun di akhir
    s = s.strip(" -")
    s = _title_case_preserve(s).strip(" -")
    if not s:                                    # pembersihan mengosongkan → jangan
        return nama
    return f"{s}{ext.lower()}"


def validasi_nama_file(nama: str) -> HasilPeriksa:
    """Periksa nama file terhadap konvensi; sertakan usulan nama bila perlu."""
    hasil = HasilPeriksa()
    base, _ = os.path.splitext(nama)

    for pola, label in _DILARANG:
        if pola.search(base):
            hasil.temuan.append(Temuan("error", f"Nama mengandung {label}."))

    if re.search(r"\s{2,}", base):
        hasil.temuan.append(Temuan("warning", "Ada spasi ganda."))

    # kata HURUF BESAR panjang (bukan akronim) → sebaiknya Title Case
    for w in re.findall(r"[A-Za-z]{4,}", base):
        if w.isupper() and w.upper() not in _AKRONIM:
            hasil.temuan.append(Temuan(
                "warning", f"Kata '{w}' HURUF BESAR — gunakan Title Case."))
            break

    usulan = rapikan_nama(nama)
    if usulan != nama:
        hasil.nama_usulan = usulan
        if hasil.ok and not hasil.temuan:
            hasil.temuan.append(Temuan(
                "warning", "Nama bisa dirapikan.", saran=usulan))
    return hasil
