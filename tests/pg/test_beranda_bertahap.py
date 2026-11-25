"""Beranda default: metadata lebih dulu; data/aksi tetap renderer native."""
import json
import pytest
from bs4 import BeautifulSoup
from hmu_identitas.ruang_data import pasang_pagar
from tests.pg.test_ruang_perusahaan import siapkan, aktifkan, konfigurasi
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik, _isi

pytestmark = pytest.mark.asyncio

@pytest.mark.parametrize('role,warehouse,sites', [('admin',None,{'g1','g2'}),
    ('operator','g1',{'g1'}),('operator','g2',{'g2'}),('operator',None,set())])
async def test_home_shell_native_data_scope_and_query_fallback(pg,lengkap,stok_lengkap,monkeypatch,role,warehouse,sites):
    client=await _klien(pg,role=role,gudang_id=lengkap['gudang'][warehouse] if warehouse else None)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    before=await _sidik(pg)
    try:
        shell=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        assert shell.status_code==200
        dom=BeautifulSoup(shell.text,'html.parser');root=dom.select_one('[data-halaman-bertahap][data-kind=beranda]')
        assert root and root['data-url']=='/api/halaman-bertahap/beranda'
        assert dom.select_one('#judul-beranda') and root.select_one('.beranda-tindaklanjut') and root.select_one('.beranda-aktivitas')
        assert not root.select('[data-proses],form[method=post],a[href^="/proses-aktif/"]')
        assert {a['href'].split('/')[-1] for a in root.select('.alur-gudang__buka')}==sites
        assert all('—' in n.text for n in root.select('.alur-masuk strong,.alur-stok strong'))
        host=json.loads(dom.select_one('#padi-beranda-kerangka').string)
        base=json.loads(dom.select_one('#padi-kerangka-langsung').string)
        assert set(host['frames'])=={'/'} and all(host[k]==base[k] for k in ('sesi','cap','konteks'))
        prototype=BeautifulSoup(''.join(host['potongan'][i] for i in host['frames']['/']),'html.parser')
        assert prototype.select_one('script[data-beranda-aset-native="halaman-bertahap.js"]')
        for query in ('','?kepemilikan=jasa','?pesan=sandi-diganti','?buka=unknown&nilai=synthetic'):
            native=await client.get('/'+query,headers={'X-Pindah':'1'})
            data=await client.get('/api/halaman-bertahap/beranda'+query)
            assert native.status_code==data.status_code==200
            assert _isi(native.text)==_isi(data.json()['html'])
            assert BeautifulSoup(native.text,'html.parser').select_one('[data-halaman-bertahap]') is None
            if not query:assert data.json()['stamp']==root['data-stamp']
            else:
                document=await client.get('/'+query,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
                assert BeautifulSoup(document.text,'html.parser').select_one('[data-halaman-bertahap]') is None
        assert await _sidik(pg)==before
    finally:await client.aclose()

async def test_home_shell_does_not_call_business_readers(pg,lengkap,monkeypatch):
    from app.services import berjalan,dashboard,alur_beranda,beranda,barang_keluar
    def deny(*a,**k):pytest.fail('Home prototype may not read operational data')
    for module,name in ((berjalan,'untuk'),(dashboard,'ringkasan_beranda'),(alur_beranda,'bangun'),(beranda,'papan'),(barang_keluar,'menunggu_muat')):
        monkeypatch.setattr(module,name,deny)
    async with await _klien(pg,role='admin') as client:
        before=await _sidik(pg)
        response=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        assert response.status_code==200 and BeautifulSoup(response.text,'html.parser').select_one('#padi-beranda-kerangka')
        assert await _sidik(pg)==before

@pytest.mark.parametrize('status',[503,403])
async def test_home_optional_provider_failure_keeps_session_boundary(pg,lengkap,monkeypatch,status):
    from fastapi import HTTPException
    from app.web import beranda_bertahap
    async def fail(*a,**k):raise HTTPException(status,'Synthetic unavailable')
    monkeypatch.setattr(beranda_bertahap,'susun',fail)
    async with await _klien(pg,role='admin') as client:
        before=await _sidik(pg)
        response=await client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        dom=BeautifulSoup(response.text,'html.parser')
        assert response.status_code==200 and dom.select_one('#padi-beranda-kerangka') is None
        assert bool(dom.select_one('#padi-kerangka-langsung'))==(status==503)
        assert await _sidik(pg)==before
