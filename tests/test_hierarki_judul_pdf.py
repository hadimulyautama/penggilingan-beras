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
        text=' '.join(p.extract_text() for p in reader.pages)
        if render is pdf_serah_terima.buat_pdf:
            assert 'Nama & tanda tangan' in text
        else:
            assert 'tanda tangan' not in text.lower() and 'Pengesahan penerimaan' not in text
        assert all(size==getattr(TemaPDF(),{1:'ukuran_judul_dokumen',2:'ukuran_judul_halaman',3:'ukuran_judul_bagian',4:'ukuran_judul_subbagian'}[level]) for level,size in seen)


def test_semua_penyaji_memakai_tipografi_lega_sentral():
    from app.web.pdf_penerimaan import Laporan
    views=[PenyajiDokumen(),Laporan(dict(kode='UJI')),LaporanGiling(dict(kode='UJI'))]
    for v in views:
        assert v.normal.fontSize==10 and v.normal.leading==14
        assert v.small.fontSize==9 and v.small.leading>=12
    for v in views[1:]:
        t=v.tabel(['Kolom'],[['Isi satu baris']],[1])
        t.wrap(400,10000)
        assert min(t._rowHeights)>=v.tema.jarak_baris_rinci+2*v.tema.padding_tabel_rinci-2


def test_selisih_penerimaan_disorot_sebelum_rincian_timbang():
    from app.web.pdf_penerimaan import blok_selisih,Laporan
    def plain(cell):
        return ' '.join(plain(x) for x in cell) if isinstance(cell,list) else cell.getPlainText()
    v=Laporan(dict(kode='UJI'))
    box=blok_selisih(v,dict(berat_acuan_kg=11362,selisih_kg=-29.5,selisih_persen=-.26,status_kontrol='PERLU_PEMERIKSAAN'))
    text=' '.join(plain(cell) for row in box._content[0]._cellvalues for cell in row)
    assert 'LEBIH RINGAN' in text and '29,50 kg (0,26%)' in text and 'perlu pemeriksaan' in text
    box=blok_selisih(v,dict(status_kontrol='TANPA_KONTROL'))
    text=' '.join(plain(cell) for row in box._content[0]._cellvalues for cell in row)
    assert 'Belum dapat dibandingkan' in text and '0,00 kg' not in text


def test_judul_batch_dan_metadata_tidak_tertinggal_di_halaman_sebelumnya():
    from reportlab.platypus import Spacer
    from pypdf import PdfReader
    from io import BytesIO
    v=PenyajiDokumen()
    table=v.grid(['Pemeriksaan'],[[v.p('QC-ROW-01')],[v.p('QC-ROW-02')]],[400])
    table.wrap(400,100000)
    block=v.bagian_tabel('BATCH-UJI',table,sum(table._rowHeights[:2]),level=4,metadata=[v.p('Tanggal pemeriksaan 07/11/2026',v.small)])
    pdf=PdfReader(BytesIO(v.pdf([v.heading('Dokumen uji',1),Spacer(1,550),*block],judul='Dokumen uji',referensi='UJI')))
    assert len(pdf.pages)==2
    assert 'BATCH-UJI' not in pdf.pages[0].extract_text()
    text=pdf.pages[1].extract_text()
    assert all(x in text for x in ['BATCH-UJI','Tanggal pemeriksaan','QC-ROW-01','QC-ROW-02'])
