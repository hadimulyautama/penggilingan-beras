"""Penyusun surat resmi PT HMU — kop + nomor + isi baku. MURNI (tanpa DB/IO).

Meniru format template resmi perusahaan (mis. Template-Surat-Tugas). Nomor
diserahkan dari mesin penomoran (dokumen/penomoran.py) — di sini hanya menyusun
naskahnya. Peran HRD/Sekretariat memanggil fungsi ini.
"""
from __future__ import annotations

from datetime import date

from app.kantor import profil

_BULAN_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def tanggal_indonesia(d: date) -> str:
    """date → 'Sragen, 2 Agustus 2026' (kota dari profil)."""
    return f"{profil.PROFIL.kota}, {d.day} {_BULAN_ID[d.month]} {d.year}"


def _blok_ttd(jabatan: str, nama: str) -> str:
    p = profil.PROFIL
    return f"{p.nama}\n{jabatan},\n\n\n\n{nama}"


def surat(
    *,
    judul: str,
    nomor: str,
    tanggal: date,
    isi: str,
    jabatan_ttd: str = "Direktur Utama",
    nama_ttd: str | None = None,
) -> str:
    """Rangkai surat resmi umum: kop + judul + nomor + isi + tanggal + ttd."""
    nama_ttd = nama_ttd or profil.PROFIL.direktur_utama
    return (
        f"{profil.kop_surat()}\n"
        f"{'=' * 60}\n\n"
        f"{judul.upper()}\n"
        f"Nomor : {nomor}\n\n"
        f"{isi.strip()}\n\n"
        f"{tanggal_indonesia(tanggal)}\n\n"
        f"{_blok_ttd(jabatan_ttd, nama_ttd)}"
    )


def surat_tugas(
    *,
    nomor: str,
    nama: str,
    jabatan: str,
    tugas: str,
    tempat: str,
    waktu: str,
    tanggal: date,
    no_pegawai: str = "-",
    nama_ttd: str | None = None,
) -> str:
    """Surat Tugas — mengikuti struktur Template-Surat-Tugas.docx perusahaan."""
    isi = (
        "Yang bertanda tangan di bawah ini, Direktur Utama PT Hadi Mulya Utama, "
        "dengan ini menugaskan:\n\n"
        f"Nama         : {nama}\n"
        f"No. Pegawai  : {no_pegawai}\n"
        f"Jabatan      : {jabatan}\n\n"
        f"Untuk melaksanakan tugas: {tugas}\n\n"
        f"Tempat       : {tempat}\n"
        f"Waktu        : {waktu}\n\n"
        "Segala biaya yang timbul sehubungan dengan penugasan ini dibebankan pada "
        "anggaran Perusahaan sesuai ketentuan. Yang bersangkutan wajib melaksanakan "
        "tugas dengan penuh tanggung jawab dan menyampaikan laporan setelah selesai.\n\n"
        "Demikian Surat Tugas ini dibuat untuk dilaksanakan sebagaimana mestinya."
    )
    return surat(judul="Surat Tugas", nomor=nomor, tanggal=tanggal, isi=isi,
                 nama_ttd=nama_ttd)
