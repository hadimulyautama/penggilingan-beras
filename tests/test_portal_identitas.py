from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.web.portal.identitas_proses import identitas,petunjuk,terbaru


def test_nama_barang_mengikuti_komposisi_bukan_menebak_semua_sosoh_pk():
    kartu=SimpleNamespace(anak_grup=[('Bahan baku masuk per silo',[
        ('Silo A','3.000 kg','','silo'),('PK','2.000 kg','','sosoh-bahan'),
        ('Beras putih','1.000 kg','','sosoh-bahan')])])
    nama=identitas('sosoh',kartu)
    assert nama['judul']=='Penyosohan bahan campuran'
    assert nama['barang']=='Beras pecah kulit (PK), Beras'
    assert identitas('sosoh')['barang']=='Jenis bahan belum tercatat'
    assert identitas('pengeringan')['judul']=='Pengeringan gabah'


def test_waktu_kosong_tidak_menggunakan_waktu_buka_halaman():
    assert terbaru([(None,'Pengukuran')])==(None,'Pembaruan terakhir')
    a=datetime(2026,10,31,8,0,tzinfo=ZoneInfo('Asia/Jakarta'))
    b=datetime(2026,10,31,2,0,tzinfo=ZoneInfo('UTC'))
    assert terbaru([(a,'Mulai proses'),(b,'Pencatatan hasil giling')])==(b,'Pencatatan hasil giling')


def test_petunjuk_tidak_menyuruh_pelanggan_mengoperasikan_mesin_atau_menjanjikan_siap_ambil():
    assert 'petugas' in petunjuk('Dijeda') and 'belum perlu bertindak' in petunjuk('Dijeda')
    assert 'konfirmasikan' in petunjuk('Selesai') and 'siap diambil' not in petunjuk('Selesai')
    assert 'belum tersedia' in petunjuk(None) and 'belum perlu bertindak' not in petunjuk(None)


def test_ringkasan_menjaga_perkiraan_dan_rasio_tetap_tersedia_tanpa_mengulang_berat():
    from bs4 import BeautifulSoup
    from app.web.portal.identitas_proses import tampilkan_detail
    from app.web.tampilan import templates
    html='''<main class="pelanggan-detail proses-detail"><header class="riwayat-detail__hero"><h1>LOT-1</h1></header>
    <section class="proses-detail__statistik"><article><span>Gabah masuk</span><strong>Perkiraan · 10.000 kg</strong></article>
    <article><span>Total hasil giling</span><strong>6.500 kg</strong></article>
    <article><span>Rasio hasil sementara</span><strong>65,0%</strong></article></section></main>'''
    info=dict(judul='Penggilingan gabah',barang='Gabah',kode='LOT-1',status='Sedang berjalan',
        angka=('Jumlah bahan','Perkiraan · 10.000 kg'),lokasi='Gudang 1',catatan=None,
        petunjuk=petunjuk('Sedang berjalan'),diperbarui=None,sumber_waktu='Pembaruan terakhir')
    s=BeautifulSoup(tampilkan_detail(html,{'portal_inti_proses':info},templates.env),'html.parser')
    assert s.get_text().count('Perkiraan · 10.000 kg')==1
    assert 'Hasil giling sementara' in s.get_text() and '6.500 kg' in s.get_text()
    assert 'Waktu pembaruan belum tercatat' in s.get_text() and not s.select('time')
    ratio=s.select_one('.pelanggan-rasio-hasil')
    assert '65,0%' in ratio.get_text() and 'bukan persentase proses selesai' in ratio.get_text()
    assert not ratio.has_attr('open')
