"""Rekap memakai kop bersama tanpa menghilangkan rincian atau mengubah bobot."""
from copy import deepcopy
from io import BytesIO
from pypdf import PdfReader
from app.web.rekap_jasa import buat_pdf
from app.web.identitas_dokumen import NAMA_PERUSAHAAN, ALAMAT, KONTAK


def contoh():
    return dict(pelanggan='PT Sumber Pangan (Contoh)', kode='JAS-2610-301',
        status='berjalan', pesanan_asal=[{'kode':'JAS-2610-302'}],
        masuk_kg=5000, kembali_kg=2500, selisih_kg=2000,
        dibawa=[dict(nama='Gabah basah',kode='GB-BASAH-001',kg=2000),
                dict(nama='Gabah kering',kode='GB-KERING-001',kg=3000)],
        kembali=[dict(nama='Beras PK',kode='OUT-001',kg=2500)],
        sisa=[dict(nama='Beras PK Gudang 1',kg=500)], bekatul=[])


def periksa_kop(reader):
    assert reader.metadata.author == NAMA_PERUSAHAAN
    assert reader.metadata.title == 'Rekap Barang Jasa'
    for n,page in enumerate(reader.pages,1):
        text=' '.join(page.extract_text().split())
        for value in [NAMA_PERUSAHAAN,*ALAMAT,KONTAK,'JAS-2610-301','Halaman '+str(n)]:
            assert ' '.join(value.split()) in text
        assert len(page.images)==1


def test_rekap_campuran_satu_halaman_dengan_kop_dan_rincian_utuh():
    data=contoh();before=deepcopy(data)
    reader=PdfReader(BytesIO(buat_pdf(data)))
    assert data==before
    periksa_kop(reader)
    assert len(reader.pages)==1
    text=' '.join(reader.pages[0].extract_text().split())
    for value in ['REKAP BARANG JASA','JAS-2610-302','GB-BASAH-001','GB-KERING-001',
                  'OUT-001','Gabah basah','Gabah kering','Beras PK Gudang 1',
                  '5.000 kg','3.000 kg','2.500 kg','2.000 kg','500 kg',
                  'Penerimaan bahan','Pengambilan hasil','Masih di pabrik','Neraca bobot',
                  'Bobot selama proses berlangsung belum final.']:
        assert value in text


def test_rekap_panjang_mengulang_kop_dan_header_tanpa_baris_hilang():
    data=contoh();data['pelanggan']='Pelanggan <Contoh> & Rekanan'
    data['dibawa']=[dict(nama='Gabah basah',kode=f'REF-MASUK-{n:03d}',kg=10)
                    for n in range(1,151)]
    data['bekatul']=[dict(kode='SOSOH-CONTOH-001',kg=100)]
    reader=PdfReader(BytesIO(buat_pdf(data)))
    periksa_kop(reader)
    assert len(reader.pages)>2
    text=' '.join('\n'.join(page.extract_text() for page in reader.pages).split())
    for n in range(1,151):
        assert f'REF-MASUK-{n:03d}' in text
    assert 'Pelanggan <Contoh> & Rekanan' in text
    assert 'SOSOH-CONTOH-001' in text and '100 kg' in text
    assert text.count('Referensi penerimaan')>1
