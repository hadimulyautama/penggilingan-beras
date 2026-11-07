"""Ubah tema di sumber core, lalu sinkronkan PadiFlow."""
from dataclasses import dataclass

@dataclass(frozen=True)
class TemaPDF:
    tinta: str = '#21332b'
    utama: str = '#32694b'
    redup: str = '#596f64'
    garis: str = '#d1ded3'
    latar: str = '#eff4ee'
    font: str = 'Helvetica'
    font_tebal: str = 'Helvetica-Bold'
    ukuran_isi: float = 8.5
    ukuran_kecil: float = 7.8
    ukuran_judul: float = 15
    margin_mm: float = 18
    atas_mm: float = 50
    bawah_mm: float = 18
    ukuran_judul_dokumen: float = 22
    ukuran_judul_halaman: float = 18
    ukuran_judul_bagian: float = 11.5
    ukuran_judul_subbagian: float = 9.5
    ukuran_isi_rinci: float = 10
    ukuran_catatan_rinci: float = 9
    jarak_baris_rinci: float = 14
    padding_tabel_rinci: float = 6

TEMA = TemaPDF()
