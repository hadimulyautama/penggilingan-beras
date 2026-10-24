"""Kop dan pemenggalan halaman harus menjaga seluruh isi dokumen bersama."""
from datetime import datetime
from io import BytesIO
from pypdf import PdfReader
import pytest
from app.web.pdf_serah_terima import buat_pdf
from app.web.identitas_dokumen import NAMA_PERUSAHAAN, ALAMAT, KONTAK


def contoh(penerimaan=False):
    return dict(
        judul='Serah Terima Penerimaan' if penerimaan else 'Serah Terima Pengeluaran',
        nomor='STP-T-ST-0' if penerimaan else 'STK-OUT-ST-0', siap=True,
        pelanggan='PT Sumber Pangan (Contoh)', pesanan=['JAS-2610-001'],
        label_tanggal='Tanggal QC selesai' if penerimaan else 'Tanggal verifikasi',
        tanggal='24/10/2026 09:10',
        identitas=[('Tiket penerimaan' if penerimaan else 'Referensi pengeluaran',
                    'T-ST-0' if penerimaan else 'OUT-ST-0'),
                   ('Nomor polisi', 'AD 1234 AB'), ('Sopir', 'Sopir Contoh'),
                   ('Petugas penerimaan' if penerimaan else 'Diverifikasi oleh', 'Petugas Contoh')],
        kolom=['Bahan diterima', 'Referensi penerimaan', 'Berat'] if penerimaan else
              ['Barang, merek & kemasan', 'Jumlah sak', 'Berat aktual'],
        baris=[['Gabah basah', 'GB-2610-001', '5.000 kg']] if penerimaan else
              [['Beras Medium · Merek Pelanggan · Karung 25 kg', '40', '1.000 kg']],
        total='5.000 kg' if penerimaan else '1.000 kg',
        label_total='Total diterima' if penerimaan else 'Total diserahkan',
        catatan='Sesuai catatan produksi yang telah diverifikasi.',
        serah='Pelanggan / pengirim' if penerimaan else 'Penyerah di pabrik',
        terima='Penerima di pabrik' if penerimaan else 'Pelanggan / penerima',
        qc=[dict(kode='GB-2610-001', status='Lengkap · 5/5 pemeriksaan', putaran=[
            dict(nomor=i, waktu=datetime(2026, 10, 24, 9, i), petugas='Petugas QC Contoh',
                 hasil=[('Kadar air 1', '24%'), ('Kadar air 2', '25%'),
                        ('Biji hijau', 'sedikit'), ('Densiti', 'padat'), ('Lamur', 'Tidak · 0 sak')])
            for i in range(1, 6)])] if penerimaan else [])


@pytest.mark.parametrize('penerimaan', [False, True])
def test_identitas_dan_logo_di_setiap_halaman_isi_terjaga(penerimaan):
    data = contoh(penerimaan)
    reader = PdfReader(BytesIO(buat_pdf(data)))
    assert len(reader.pages) == (2 if penerimaan else 1)
    assert reader.metadata.author == NAMA_PERUSAHAAN
    assert reader.metadata.title == data['judul'] + ' · ' + data['nomor']
    for n, page in enumerate(reader.pages, 1):
        text = ' '.join(page.extract_text().split())
        for value in [NAMA_PERUSAHAAN, *ALAMAT, KONTAK, data['nomor'], 'Halaman ' + str(n)]:
            assert ' '.join(value.split()) in text
        assert len(page.images) == 1
    main = ' '.join(reader.pages[0].extract_text().split())
    for value in [data['pelanggan'], data['total'], 'Pengesahan serah terima',
                  data['serah'], data['terima'], *data['baris'][0]]:
        assert value in main
    if penerimaan:
        assert reader.pages[1].extract_text().count('Pemeriksaan ') == 5


def test_banyak_baris_dan_teks_pelanggan_tetap_utuh_tanpa_menimpa_kop():
    data = contoh()
    data['pelanggan'] = 'Contoh <Pelanggan> & Rekanan '
    data['baris'] = [[f'Barang {i} · Merek Pelanggan & Kemasan 25 kg', f'REF-{i:03d}', '25 kg']
                     for i in range(1, 101)]
    reader = PdfReader(BytesIO(buat_pdf(data)))
    assert len(reader.pages) > 2
    all_text = '\n'.join(page.extract_text() for page in reader.pages)
    assert 'Contoh <Pelanggan> & Rekanan' in all_text
    for i in range(1, 101):
        assert f'REF-{i:03d}' in all_text
    for page in reader.pages:
        assert NAMA_PERUSAHAAN in page.extract_text()
        assert len(page.images) == 1
