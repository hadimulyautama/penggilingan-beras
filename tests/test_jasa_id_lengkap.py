"""Setiap tabel yang membawa `jasa_id` WAJIB terdaftar di `jasa.TABEL_BER_
JASA_ID` — daftar tunggal yang dibaca `gabung_jasa()` untuk memindahkan
seluruh jejak satu pesanan ke survivor-nya.

CLAUDE.md pernah menyebut "SEBELAS tabel" dan sudah dua kali basi tanpa
ketahuan (migrasi 0072 `broken_ke_silo`, 0077 `gabah_kering_lots`, 0078
`beras_ke_silo` — tak satu pun memperbarui kalimat itu, ditemukan 10
Oktober 2026 saat membangun `gabung_jasa()`). Prosa bukan penjaga: tabel
KELIMA BELAS — kapan pun ia lahir — akan terlewat dari cakupan `gabung_
jasa()` dengan cara yang sama persis, meninggalkan baris yatim menunjuk
pesanan yang sudah diserap, kecuali ada uji yang membandingkan daftar
terhadap basis data sungguhan.
"""
from __future__ import annotations

import pathlib
import re

AKAR = pathlib.Path(__file__).resolve().parents[1]

#: `jasa.id` yang BUKAN "tabel data ber-jasa_id" — pengecualian SENGAJA,
#: dengan alasannya masing-masing.
_KECUALI = {
    # Tabel `jasa` itu sendiri (`digabung_ke_id`, self-referential) — ia
    # SUBJEK `gabung_jasa()`, bukan salah satu tabel yang dipindahkan olehnya.
    "Jasa",
}


def _kelas_ber_jasa_id() -> set[str]:
    kelas: set[str] = set()
    nama_kelas_sekarang: str | None = None
    for berkas in (AKAR / "app").rglob("*.py"):
        if "__pycache__" in berkas.parts:
            continue
        nama_kelas_sekarang = None
        for baris in berkas.read_text().splitlines():
            tanpa_spasi = baris.strip()
            if tanpa_spasi.startswith("#"):
                continue  # komentar/docstring boleh MENYEBUT polanya sendiri
            m = re.match(r"class (\w+)\(", baris)
            if m:
                nama_kelas_sekarang = m.group(1)
                continue
            if 'mapped_column(ForeignKey("jasa.id")' in baris and nama_kelas_sekarang:
                kelas.add(nama_kelas_sekarang)
    return kelas - _KECUALI


def test_setiap_tabel_ber_jasa_id_terdaftar_di_gabung_jasa():
    from app.services.jasa import TABEL_BER_JASA_ID

    terdaftar = {m.__name__ for m in TABEL_BER_JASA_ID}
    sungguh_ada = _kelas_ber_jasa_id()
    assert sungguh_ada, "pemindai tak menemukan satu pun ForeignKey(\"jasa.id\") — pemindainya sendiri rusak"
    hilang = sungguh_ada - terdaftar
    assert not hilang, (
        f"tabel ber-jasa_id belum terdaftar di TABEL_BER_JASA_ID: {hilang} — "
        "gabung_jasa() akan meninggalkan baris yatim untuk tabel ini. "
        "Daftarkan di app/services/jasa.py."
    )
    karangan = terdaftar - sungguh_ada
    assert not karangan, (
        f"TABEL_BER_JASA_ID menyebut kelas yang tak punya ForeignKey(\"jasa.id\") "
        f"sungguhan: {karangan}"
    )
