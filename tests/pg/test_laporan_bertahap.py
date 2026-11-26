"""Shell laporan tidak mengarang angka dan memakai pembaca/izin native."""
import json
import pytest
from bs4 import BeautifulSoup
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik, _isi
from tests.pg.test_ruang_perusahaan import siapkan, aktifkan, konfigurasi
from hmu_identitas.ruang_data import pasang_pagar
from app.web.laporan_bertahap import TUJUAN

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role,warehouse', [('admin',None),('operator','g1'),('operator','g2'),('operator',None)])
async def test_all_report_structures_native_parity(pg, lengkap, monkeypatch, role, warehouse):
    c = await _klien(pg, role=role, gudang_id=lengkap['gudang'][warehouse] if warehouse else None)
    space=await siapkan(pg);await aktifkan(pg,space);konfigurasi(monkeypatch,space);pasang_pagar(pg.kw['bind'],wajib=True)
    before=await _sidik(pg)
    try:
        r=await c.get('/barang-masuk',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        host=BeautifulSoup(r.text,'html.parser').select_one('#padi-laporan-kerangka');assert host
        data=json.loads(host.string);assert set(data['frames'])==set(TUJUAN.values())
        for kind,path in TUJUAN.items():
            prototype=BeautifulSoup(''.join(data['potongan'][i] for i in data['frames'][path]),'html.parser')
            if kind=='laporan':
                assert len(prototype.select('[data-laporan-catalogue] a[data-laporan]'))==13
                continue
            root=prototype.select_one('[data-laporan-shell]');assert root and root.get('aria-label')
            assert root.select('table thead th') and root.select_one('#periode') and root.select_one('[data-lp-proses]')
            assert all(x.get_text()=='—' for x in root.select('.lp-metrik dd'))
            assert not root.select('form[method=post],#laporan-data,a.lp-pdf-utama[href]')
            assert 'Tidak ada transaksi' not in root.get_text()
            query='?periode=khusus&dari=2020-01-01&sampai=2026-12-31'
            shell=await c.get(path+query,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            native=await c.get(path+query,headers={'X-Pindah':'1'})
            response=await c.get('/api/halaman-bertahap/'+kind+query)
            assert shell.status_code==native.status_code==response.status_code==200,(kind,shell.text[:300])
            assert BeautifulSoup(shell.text,'html.parser').select_one('[data-laporan-shell]')['data-stamp']==response.json()['stamp']
            assert _isi(native.text)==_isi(response.json()['html'])
            scripts=BeautifulSoup(_isi(native.text),'html.parser').select('script[src]')
            assert sorted(s['src'].split('/')[-1].split('?')[0] for s in scripts)==sorted(['laporan-periode-detail.js','menu-layar.js','kerangka-langsung.js','navigasi-daftar-bertahap.js'])
        assert await _sidik(pg)==before
    finally:await c.aclose()


async def test_report_shell_has_no_report_query(pg, lengkap, monkeypatch):
    from app.services import laporan_periode
    async def fail(*a,**k):pytest.fail('Shell must not read report transactions')
    monkeypatch.setattr(laporan_periode,'ambil',fail)
    async with await _klien(pg,role='admin') as c:
        before=await _sidik(pg)
        for path in TUJUAN.values():
            r=await c.get(path,headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
            assert r.status_code==200
        assert await _sidik(pg)==before


@pytest.mark.parametrize('query',['?periode=asing','?periode=khusus','?periode=khusus&dari=2026-11-12&sampai=2026-11-11','?dari=nope'])
async def test_report_validation_native_status(pg, lengkap, query):
    async with await _klien(pg,role='admin') as c:
        native=await c.get('/laporan/gabah_masuk'+query)
        staged=await c.get('/api/halaman-bertahap/laporan-gabah_masuk'+query)
        assert native.status_code==staged.status_code==422


@pytest.mark.parametrize('status',[503,403])
async def test_optional_report_failure_respects_context(pg, lengkap, monkeypatch, status):
    from fastapi import HTTPException
    from app.web import laporan_bertahap
    async def fail(*a,**k):raise HTTPException(status,'Synthetic unavailable')
    monkeypatch.setattr(laporan_bertahap,'susun',fail)
    async with await _klien(pg,role='admin') as c:
        r=await c.get('/barang-masuk',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        dom=BeautifulSoup(r.text,'html.parser')
        assert r.status_code==200 and not dom.select('#padi-laporan-kerangka')
        assert bool(dom.select('#padi-kerangka-langsung'))==(status==503)
