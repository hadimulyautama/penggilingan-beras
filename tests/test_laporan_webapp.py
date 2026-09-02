"""Uji layar laporan (Fase B3).

Laporan adalah satu-satunya tempat di aplikasi ini yang menampilkan angka uang
kepada orang yang sedang berdiri di gudang. Dua hal karenanya dijaga ketat:

  · siapa boleh melihat apa diputuskan di server, dan diputuskan ULANG saat
    laporannya diminta — bukan sekadar disaring dari daftar;
  · isi laporan berasal dari data yang diketik orang (nama supplier, catatan),
    jadi ia tidak boleh bisa menyelundupkan tag ke dalam halaman.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.web import laporan as lap


def _orang(role: str):
    return SimpleNamespace(id=1, nama="Rusdi", role=role)


# ─────────────────────── Siapa melihat apa ───────────────────────

def test_operator_tak_melihat_satu_pun_laporan_uang():
    """Bukan karena angkanya rahasia dari orangnya, melainkan karena perangkat
    gudang dipakai bergantian dan berdiri di tempat terbuka."""
    terlihat = lap.daftar_untuk(_orang("operator"))
    assert terlihat, "operator tetap butuh laporan kerja"
    assert not any(l.uang for l in terlihat)


def test_staff_dan_admin_melihat_seluruhnya():
    for role in ("staff", "admin"):
        assert len(lap.daftar_untuk(_orang(role))) == len(lap._daftar())


def test_laporan_uang_yang_diminta_langsung_tetap_ditolak():
    """Alamatnya bisa diketik. Menyaring daftar itu kenyamanan; yang menahan
    adalah pemeriksaan saat laporannya diminta."""
    uang = [l for l in lap._daftar() if l.uang]
    assert uang, "seharusnya ada laporan uang"
    for l in uang:
        assert not lap.boleh_lihat(_orang("operator"), l)


# ─────────────────────── Bentuk pendaftaran ───────────────────────

def test_kode_laporan_tidak_kembar():
    kode = [l.kode for l in lap._daftar()]
    assert len(kode) == len(set(kode))


def test_tiap_laporan_punya_cara_membuatnya():
    """Kecuali dua yang menerima rentang tanggal — keduanya ditangani khusus
    di rute, dan itu satu-satunya alasan `buat` boleh kosong."""
    berperiode = {l.kode for l in lap._daftar() if l.berperiode}
    assert berperiode == {"produksi", "pembelian_gabah"}
    for l in lap._daftar():
        assert (l.buat is not None) or l.berperiode, f"{l.kode} tanpa pembuat"


def test_tiap_laporan_menjelaskan_dirinya():
    for l in lap._daftar():
        assert l.nama and l.arti
        assert l.arti.endswith("."), f"{l.kode}: keterangan harus kalimat utuh"


# ─────────────────────── Rentang tanggal ───────────────────────

@pytest.mark.parametrize("periode", [k for k, _ in lap.PERIODE])
def test_tiap_periode_menghasilkan_rentang_yang_masuk_akal(periode):
    dari, sampai = lap._rentang(periode)
    assert dari <= sampai
    assert dari is not None and sampai is not None, \
        "laporan produksi tidak menerima tanggal kosong"


def test_periode_tak_dikenal_jatuh_ke_seluruh_data():
    dari, _ = lap._rentang("entah")
    assert dari.year <= 2020


# ─────────────────────── Teks laporan → layar ───────────────────────

def test_penanda_markdown_diterjemahkan_bukan_ditampilkan_mentah():
    hasil = lap.ke_html("*Total* gabah `PB-01` _kemarin_")
    assert "<b>Total</b>" in hasil
    assert "<code>PB-01</code>" in hasil
    assert "<i>kemarin</i>" in hasil
    assert "*" not in hasil


def test_isi_laporan_tak_bisa_menyelundupkan_tag():
    """Nama supplier diketik orang. Bila di-escape SETELAH markdown, sebuah
    nama seperti `<img onerror=...>` akan masuk halaman apa adanya."""
    hasil = lap.ke_html('Supplier <script>alert(1)</script> & "Toko"')
    assert "<script>" not in hasil
    assert "&lt;script&gt;" in hasil
    assert "&amp;" in hasil


def test_penanda_tak_menyeberang_baris():
    """Tanda bintang yatim di satu baris tidak boleh menebalkan sisa laporan."""
    hasil = lap.ke_html("Gabah *masuk\nGiling* selesai")
    assert "<b>" not in hasil


def test_teks_kosong_tidak_meledak():
    assert lap.ke_html("") == ""
    assert lap.ke_html(None) == ""
