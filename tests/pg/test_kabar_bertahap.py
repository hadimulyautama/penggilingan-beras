"""Kerangka Kabar tidak membaca/menulis status; isi selalu handler native."""
import json
import pytest
from bs4 import BeautifulSoup
from tests.pg.test_konsolidasi_pekerjaan import lengkap,stok_lengkap,sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_kabar import _tulis
from tests.pg.test_halaman_bertahap import _sidik,_isi
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi
from hmu_identitas.ruang_data import pasang_pagar

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,warehouse',[('admin',None),('operator','g1'),('operator','g2'),('operator',None)])
async def test_kabar_prototype_unknown_data_native_parity(pg,lengkap,monkeypatch,role,warehouse):
    await _tulis(pg,tipe='pengeringan_telat',untuk='operator',pesan='UJI G1')
    await _tulis(pg,tipe='permintaan_pk',untuk='operator',pesan='UJI G2')
    await _tulis(pg,tipe='harga',untuk='admin',pesan='UJI ADMIN')
    c=await _klien(pg,role=role,gudang_id=lengkap['gudang'][warehouse] if warehouse else None)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    before=await _sidik(pg)
    try:
        initial=await c.get('/barang-masuk',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        dom=BeautifulSoup(initial.text,'html.parser');host=dom.select_one('#padi-kabar-kerangka');assert host
        data=json.loads(host.string);assert set(data['frames'])=={'/kabar'}
        html=''.join(data['potongan'][i] for i in data['frames']['/kabar']);frame=BeautifulSoup(html,'html.parser')
        root=frame.select_one('[data-halaman-bertahap][data-kind=kabar]')
        assert root and 'kb' not in root.get('class',[]) and 'kb-kerangka' in root['class']
        assert not root.select('form[method=post],.kb-empty')
        assert root.select_one('[data-kabar-belum]').text=='Belum dibaca (—)'
        assert root.select_one('#kb-jenis')['disabled']=='' and root.select_one('[data-kabar-semua]').has_attr('disabled')
        assert not any(x in html for x in ('UJI G1','UJI G2','UJI ADMIN'))
        assert ':is(.kb,.kb-kerangka)' in frame.select_one('style[data-kabar-aset-native]').text
        assert "document.querySelector('.kb-kerangka')" in frame.select_one('script[data-kabar-aset-native="kabar-kontrol.js"]').text
        for query in ('','?tab=belum','?tab=belum&jenis=permintaan_pk&batas=60&sampai=0','?tab=&jenis=harga&batas=1&sebelum=999999'):
            shell=await c.get('/kabar'+query,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            native=await c.get('/kabar'+query,headers={'X-Pindah':'1'})
            response=await c.get('/api/halaman-bertahap/kabar'+query)
            assert shell.status_code==native.status_code==response.status_code==200, (query,shell.status_code,native.status_code,response.status_code,response.text[:300])
            sr=BeautifulSoup(shell.text,'html.parser').select_one('[data-kind=kabar]');assert sr
            assert sr['data-stamp']==response.json()['stamp'] and _isi(native.text)==_isi(response.json()['html'])
        for query in ('?buka=unknown&nilai=synthetic','?tab=unknown','?tab=belum&tab='):
            r=await c.get('/kabar'+query,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            assert BeautifulSoup(r.text,'html.parser').select_one('[data-halaman-bertahap]') is None
        assert await _sidik(pg)==before
    finally:await c.aclose()

async def test_kabar_shell_does_not_read_notifications(pg,lengkap,monkeypatch):
    from app.services import kabar
    async def fail(*a,**k):pytest.fail('Prototype must not query account Kabar data')
    for name in ('jenis_tersedia','batas_histori','daftar','lengkapi','jumlah_baru'):monkeypatch.setattr(kabar,name,fail)
    async with await _klien(pg,role='admin') as c:
        before=await _sidik(pg)
        response=await c.get('/kabar',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        assert response.status_code==200 and BeautifulSoup(response.text,'html.parser').select_one('#padi-kabar-kerangka')
        assert await _sidik(pg)==before

@pytest.mark.parametrize('query',['?batas=0','?batas=101','?batas=no','?sampai=-1','?sebelum=0','?sebelum=bad'])
async def test_kabar_API_reuses_native_query_validation(pg,lengkap,query):
    async with await _klien(pg,role='admin') as c:
        assert (await c.get('/kabar'+query)).status_code==422
        assert (await c.get('/api/halaman-bertahap/kabar'+query)).status_code==422

@pytest.mark.parametrize('status',[503,403])
async def test_optional_kabar_error_preserves_session_boundary(pg,lengkap,monkeypatch,status):
    from fastapi import HTTPException
    from app.web import kabar_bertahap
    async def fail(*a,**k):raise HTTPException(status,'Synthetic unavailable')
    monkeypatch.setattr(kabar_bertahap,'susun',fail)
    async with await _klien(pg,role='admin') as c:
        before=await _sidik(pg)
        r=await c.get('/barang-masuk',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        dom=BeautifulSoup(r.text,'html.parser')
        assert r.status_code==200 and dom.select_one('#padi-kabar-kerangka') is None
        assert bool(dom.select_one('#padi-kerangka-langsung'))==(status==503)
        assert await _sidik(pg)==before
