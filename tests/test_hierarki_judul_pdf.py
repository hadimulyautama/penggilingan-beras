"""Judul dokumen, halaman dan bagian harus memiliki tingkat visual berbeda."""
from dataclasses import replace
import pytest
from hmu_dokumen.document import PenyajiDokumen
from hmu_dokumen.tema import TemaPDF
from app.web.pdf_giling import LaporanGiling


def test_hierarki_sentral_mengikuti_tema_dan_mengamankan_teks():
    theme=replace(TemaPDF(),font_tebal='Courier-Bold',utama='#663399')
    v=PenyajiDokumen(tema_pdf=theme)
    headings=[v.heading('<b>Judul & asli</b>',n) for n in (1,2,3,4)]
    sizes=[h.style.fontSize for h in headings]
    assert all(a>b for a,b in zip(sizes,sizes[1:]))
    assert len({h.style.name for h in headings})==4
    assert all(h.style.fontName=='Courier-Bold' and h.getKeepWithNext() for h in headings)
    assert all(h.getPlainText()=='<b>Judul & asli</b>' for h in headings)
    assert headings[1].style.textColor != headings[2].style.textColor
    with pytest.raises(ValueError):v.heading('Judul',5)


def test_laporan_proses_menggunakan_tingkat_sentral():
    v=LaporanGiling(dict(kode='LOT-UJI'))
    page=v.heading('Rincian penggilingan',2)
    section=v.bagian('Pencatatan hasil PK')
    assert page.style is v.page_heading
    assert section.style is v.section_heading
    assert page.style.fontSize>section.style.fontSize
