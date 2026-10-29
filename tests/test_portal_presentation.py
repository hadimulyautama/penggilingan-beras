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


def test_penerimaan_share_hanya_memakai_endpoint_portal_yang_diizinkan():
    html='''<button id="bagikan-pdf" data-penerimaan-share="/barang-masuk/5/laporan.pdf" disabled>Bagikan PDF</button>
      <script src="/static/pdf-penerimaan.js?v=482&bagikan=1" defer></script>
      <script src="https://other.example/static/pdf-penerimaan.js"></script>
      <a href="/barang-masuk/5/laporan.pdf?unduh=0" target="_blank">Lihat PDF</a>'''
    soup=BeautifulSoup(read_only(html,'/barang-masuk/5'),'html.parser')
    assert soup.button['data-penerimaan-share']=='/pelanggan/barang-masuk/5/laporan.pdf'
    assert soup.a['href']=='/pelanggan/barang-masuk/5/laporan.pdf?unduh=0'
    assert len(soup.find_all('script'))==1
    assert soup.script['src'].startswith('/static/pdf-penerimaan.js?')
    for invalid in ('https://other.example/barang-masuk/5/laporan.pdf','/api/aksi'):
        unsafe=BeautifulSoup(read_only(html.replace('/barang-masuk/5/laporan.pdf"',invalid+'"'),'/barang-masuk/5'),'html.parser')
        assert unsafe.find(id='bagikan-pdf') is None


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


def test_customer_cookies_are_secure_behind_railway_tls_termination(monkeypatch):
    from starlette.requests import Request
    from app.web.portal.security import secure_cookie
    request=Request({'type':'http','scheme':'http','server':('portal.example',80),'path':'/pelanggan','headers':[]})
    monkeypatch.delenv('RAILWAY_ENVIRONMENT_ID',raising=False)
    assert not secure_cookie(request)
    monkeypatch.setenv('RAILWAY_ENVIRONMENT_ID','test-platform-marker')
    assert secure_cookie(request)
