"""Isi laporan digambar, bukan ditumpahkan.

Teksnya bentuk peninggalan masa ketika laporan dibaca di Telegram. Ditaruh apa
adanya di dalam `<pre>` monospasi, ia terbaca seperti keluaran terminal:
seluruh barisnya seukuran, tak ada yang menonjol, dan angka yang dicari orang
tenggelam di antara tanda baca.
"""
import pathlib

AKAR = pathlib.Path(__file__).resolve().parents[1]
TPL = AKAR / "app/web/templates/laporan.html"
CSS = AKAR / "app/web/static/app.css"


def test_laporan_tidak_lagi_ditumpahkan_ke_pre():
    teks = TPL.read_text()
    assert "<pre" not in teks, "isi laporan kembali jadi blok monospasi"
    assert '<div class="lap" id="lap-isi">' in teks
    assert "function gambar(" in teks, "tak ada penggambar"


def test_teks_laporan_tidak_diubah_di_server():
    """Empat belas laporan menulis teksnya dengan tangan masing-masing.
    Menulis ulang semuanya demi tampilan berarti empat belas kesempatan
    mengubah ISInya tanpa sengaja — jadi yang berubah hanya penggambarnya."""
    lap = (AKAR / "app/web/laporan.py").read_text()
    assert "_TEBAL" in lap and "_MIRING" in lap, "penerjemah penanda hilang"
    # Rutenya tetap mengirim teks apa adanya.
    assert '"isi"' in lap


def test_penggambar_mengenali_pola_yang_memang_dipatuhi():
    """Kepala bagian berakhiran titik dua, butir '•', anak butir '–'. Yang tak
    cocok pola apa pun tetap jadi paragraf — laporan yang menyimpang tak lebih
    buruk daripada sebelumnya, hanya tak ikut membaik."""
    teks = TPL.read_text()
    for pola in (r"lap__bab", r"lap__baris", r"lap__anak", r"lap__teks"):
        assert pola in teks, pola
    assert "lap__sub" in teks, "kepala yang sebenarnya kalimat tak dibedakan"
    # Judul laporan tak boleh terulang: ia sudah ada di kepala lembar.
    assert "=== sapu" in teks or "toLowerCase() === sapu" in teks


def test_baris_membungkus_bukan_mengempis():
    """Dua kolom kaku memaksa nama menyempit sampai kode lot patah di tengah —
    "LOT-20260905-" lalu "01" di baris berikutnya — dan kode yang patah
    berhenti bisa dibaca sekilas."""
    css = CSS.read_text()
    blok = css[css.index(".lap__baris {"):]
    blok = blok[:blok.index("}")]
    assert "flex-wrap: wrap" in blok, "baris laporan kembali jadi dua kolom kaku"
    assert "grid-template-columns" not in blok
