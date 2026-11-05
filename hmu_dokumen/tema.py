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

TEMA = TemaPDF()
