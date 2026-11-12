"""Isi laporan digambar, bukan ditumpahkan.

Teksnya bentuk peninggalan masa ketika laporan dibaca di Telegram. Ditaruh apa
adanya di dalam `<pre>` monospasi, ia terbaca seperti keluaran terminal:
seluruh barisnya seukuran, tak ada yang menonjol, dan angka yang dicari orang
tenggelam di antara tanda baca.
"""
import pathlib

AKAR = pathlib.Path(__file__).resolve().parents[1]
#: Milik paket sejak 23 September 2026 — berkas ini dulu ada tiga, beda 0 baris.
TPL = AKAR / "hmu_tampilan/templates/laporan.html"
CSS = AKAR / "hmu_tampilan/static/app.css"


def test_laporan_dibaca_di_halaman_detail_tanpa_modal():
    katalog = TPL.read_text()
    detail = (TPL.parent / "laporan_periode_detail.html").read_text()
    assert '<pre' not in detail
    assert 'href="/laporan/' in katalog
    assert '<dialog' not in katalog
    assert 'data-laporan-detail' in detail
    assert 'id="laporan-data"' in detail


def test_penggambar_mempertahankan_kolom_dan_keterangan_terstruktur():
    renderer = (AKAR / "hmu_tampilan/static/laporan-periode-detail.js").read_text()
    assert 'd.kepala_tabel' in renderer and 'd.rincian' in renderer
    assert 'd.catatan' in renderer and 'aman(nilai)' in renderer


def test_baris_membungkus_bukan_mengempis():
    """Dua kolom kaku memaksa nama menyempit sampai kode lot patah di tengah —
    "LOT-20260905-" lalu "01" di baris berikutnya — dan kode yang patah
    berhenti bisa dibaca sekilas."""
    css = CSS.read_text()
    blok = css[css.index(".lap__baris {"):]
    blok = blok[:blok.index("}")]
    assert "flex-wrap: wrap" in blok, "baris laporan kembali jadi dua kolom kaku"
    assert "grid-template-columns" not in blok
