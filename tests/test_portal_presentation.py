"""Preserve production read controls while excluding transaction affordances."""
from bs4 import BeautifulSoup
from app.web.portal.presentation import read_only
from app.web.portal.navigation import portal_url


def test_read_controls_and_document_share_survive():
    html='''<details><summary>Rincian</summary>Hasil 6.500 kg</details>
      <form method="get" action="/pekerjaan"><select name="gudang"><option>G1</option></select><button>Tampilkan</button></form>
      <form method="post" action="/api/aksi"><button>Ubah hasil</button></form>
      <a href="/riwayat-giling/2/laporan">Baca PDF</a>
      <button id="bagikan-pdf" disabled>Bagikan PDF</button><iframe src="/riwayat-giling/2/laporan.pdf"></iframe>
      <script>alert(1)</script><script src="/static/saring-kerja.js?v=1" defer></script>'''
    soup=BeautifulSoup(read_only(html,'/pekerjaan'),'html.parser')
    assert soup.find('details').get_text(strip=True)=='RincianHasil 6.500 kg'
    assert soup.select_one('form')['action']=='/pelanggan/pekerjaan'
    assert soup.select_one('button#bagikan-pdf')['data-pdf-share']=='/pelanggan/riwayat-giling/2/laporan.pdf'
    assert 'Ubah hasil' not in soup.get_text()
    assert len(soup.find_all('script'))==1
    assert soup.find('a')['href']=='/pelanggan/riwayat-giling/2/laporan'


def test_return_comparison_does_not_disappear_with_the_form():
    html='''<form method="post" action="/barang-keluar/4/retur"><p>Dikirim 30 sak</p>
      <input name="jumlah" value="5"><button>Simpan</button><input name="_csrf" type="hidden" value="secret"></form>'''
    soup=BeautifulSoup(read_only(html,'/retur/pengajuan/2'),'html.parser')
    assert 'Dikirim 30 sak' in soup.get_text() and '5' in soup.get_text()
    assert not soup.select('form,button,input')


def test_closed_read_navigation():
    for value in ['https://evil.example/riwayat-giling','//evil.example/x','/pengguna','/api/aksi','/stok?buka=ambil_jasa']:
        assert portal_url(value) is None
    assert portal_url('/riwayat-qc/gabah-basah/GB-1')=='/pelanggan/riwayat-qc/gabah-basah/GB-1'


def test_native_absolute_same_origin_tab_and_pagination_reads_survive():
    html='''<a role="tab" href="https://portal.example/riwayat-transfer/2?tab_detail=bahan#panel-bahan">Bahan</a>
    <a href="https://other.example/riwayat-transfer/2">External</a>
    <a href="https://portal.example/riwayat-transfer/2?buka=koreksi">Koreksi</a>
    <form method="get" action="https://portal.example/pekerjaan"><button>Cari</button></form>'''
    soup=BeautifulSoup(read_only(html,'/riwayat-transfer/2',origin='https://portal.example/'),'html.parser')
    assert soup.select_one('[role=tab]')['href']=='/pelanggan/riwayat-transfer/2?tab_detail=bahan#panel-bahan'
    assert len(soup.select('a[href]'))==1
    assert soup.form['action']=='/pelanggan/pekerjaan'
