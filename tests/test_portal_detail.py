"""Detail lebih ringkas tanpa kehilangan angka, catatan, atau pembaca GET."""
from bs4 import BeautifulSoup
from app.web.portal.presentation import read_only


def test_detail_stok_mempertahankan_angka_dan_catatan_di_balik_rincian():
    html='''<main class="pk-detail"><a class="pk-detail__back" href="/stok">Kembali</a>
    <header><h1>LOT-ASAL-1</h1><div class="pk-detail__weight"><span>Berat tersedia</span><strong>1.250 kg</strong></div></header>
    <section class="pk-detail__owner">JAS-ADMIN</section>
    <dl><div><dt>ID jasa</dt><dd>JAS-ADMIN</dd></div><div><dt>Berat awal masuk</dt><dd>2.000 kg</dd></div></dl>
    <section class="pk-detail__quality"><h2>Nilai kualitas</h2><strong>87,5 / 100</strong><p>QC sesuai permintaan: 12,5%.</p></section>
    <a class="btn" href="/riwayat-giling/1">Lihat proses</a><a class="btn" href="/riwayat-giling/1?pelanggan_id=3">Lihat proses</a></main>'''
    s=BeautifulSoup(read_only(html,'/stok/pk/detail?gudang=g1&kode=LOT-ASAL-1'),'html.parser')
    assert s.h1.get_text()=='Beras pecah kulit (PK)'
    assert s.select_one('.pelanggan-detail-kode').get_text()=='LOT-ASAL-1'
    assert '1.250 kg' in s.get_text() and '2.000 kg' in s.get_text() and '87,5 / 100' in s.get_text()
    assert 'QC sesuai permintaan: 12,5%.' in s.get_text() and 'JAS-ADMIN' not in s.get_text()
    assert s.select_one('.pk-detail__quality').find_parent('details') and not s.details.has_attr('open')
    assert len(s.select('a.btn'))==1
    assert s.select_one('.pk-detail__back')['href']=='/pelanggan/barang-saya'


def test_detail_proses_menjaga_tab_paginasi_dan_hasil_tanpa_tombol_pengulang():
    html='''<main class="proses-detail"><header><h1>LOT-1</h1><span class="riwayat-status">Dijeda</span><p>Listrik padam.</p></header>
    <nav role="tablist"><a role="tab" href="/proses-aktif/giling/LOT-1?tab_detail=hasil">Hasil</a></nav>
    <section id="tindakan-proses"><h2>Tindakan saat ini</h2><p>Catat hasil.</p><p class="riwayat-detail__warning">Menunggu listrik menyala.</p></section>
    <a class="btn" href="/proses-aktif/giling/LOT-1?tab_detail=hasil#panel-hasil">Lihat hasil</a>
    <nav><a class="btn" href="/proses-aktif/giling/LOT-1?tab_detail=hasil&halaman_hasil=2">Lebih lama →</a></nav>
    <section><h2>Hasil sementara</h2><strong>250 kg</strong></section>
    <section id="kualitas-proses"><h2>Nilai kualitas QC PK</h2><p>KA 13,5% · hasil 87,25</p></section></main>'''
    s=BeautifulSoup(read_only(html,'/proses-aktif/giling/LOT-1'),'html.parser')
    assert s.h1.get_text()=='Penggilingan' and 'LOT-1' in s.get_text()
    assert '250 kg' in s.get_text() and 'Listrik padam.' in s.get_text() and 'Dijeda' in s.get_text()
    assert not s.select_one('#tindakan-proses')
    assert 'Menunggu listrik menyala.' in s.get_text()
    assert len(s.select('[role=tab]'))==1 and len(s.select('a.btn'))==1
    assert 'halaman_hasil=2' in s.select_one('a.btn')['href']
    assert 'KA 13,5% · hasil 87,25' in s.get_text() and s.select_one('#kualitas-proses').find_parent('details')


def test_laporan_yang_belum_tersedia_tetap_memiliki_rincian_proses():
    html='<main class="riwayat-detail"><h1>POL-1</h1><p>Hasil 250 kg</p><a class="btn" href="/riwayat-sosoh/1/laporan">Lihat PDF</a></main>'
    s=BeautifulSoup(read_only(html,'/riwayat-sosoh/1',report_available=False),'html.parser')
    assert 'Hasil 250 kg' in s.get_text() and 'POL-1' in s.get_text()
    assert 'PDF belum tersedia.' in s.get_text() and not s.select('a[href*=laporan]')
