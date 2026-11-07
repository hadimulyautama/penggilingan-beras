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


def test_semua_keluarga_pdf_memakai_judul_sentral(monkeypatch):
    from datetime import datetime,timezone
    from io import BytesIO
    from pypdf import PdfReader
    from app.web import pdf_penerimaan,pdf_serah_terima,rekap_jasa
    from app.web.layar_riwayat import _pdf_laporan_giling,_pdf_pengeringan
    from app.web.laporan_sosoh import buat_pdf as sosoh
    from tests.test_pdf_serah_terima import contoh as serah
    from tests.test_pdf_rekap_jasa import contoh as rekap
    from tests.test_laporan_giling_pdf import data_giling
    from tests.test_laporan_pengeringan_pdf import data_pengeringan
    from tests.test_laporan_sosoh_pdf import data_sosoh
    received=dict(timbang=None,tiket=dict(kode='MSK-UJI',jenis_nama='Beras'),jenis='beras',pihak={1:'Pemasok Uji'},label_pihak='Supplier',pesanan=[],catatan=[],berat=None,keterangan_berat='Belum diterima',qc=[],status='belum diterima',final=False,dibuat=datetime(2026,11,7,tzinfo=timezone.utc),pembuat='Penguji')
    cases=[(pdf_penerimaan.buat_pdf,received),(pdf_serah_terima.buat_pdf,serah(True)),
           (rekap_jasa.buat_pdf,rekap()),(_pdf_laporan_giling,data_giling()),
           (_pdf_pengeringan,data_pengeringan()),(sosoh,data_sosoh())]
    original=PenyajiDokumen.heading;seen=[]
    def record(self,value,level=3):
        result=original(self,value,level)
        seen.append((level,result.style.fontSize))
        return result
    monkeypatch.setattr(PenyajiDokumen,'heading',record)
    for render,data in cases:
        seen.clear()
        reader=PdfReader(BytesIO(render(data)))
        assert reader.pages and sum(level==1 for level,_ in seen)==1
        assert all(size==getattr(TemaPDF(),{1:'ukuran_judul_dokumen',2:'ukuran_judul_halaman',3:'ukuran_judul_bagian',4:'ukuran_judul_subbagian'}[level]) for level,size in seen)
