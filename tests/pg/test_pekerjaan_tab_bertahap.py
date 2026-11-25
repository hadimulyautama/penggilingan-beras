"""Dua tab memakai kerangka, pembaca/izin serta transaksi tetap native."""
import json
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup

from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik, _isi

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role,warehouse', [('operator','g1'), ('operator','g2'), ('admin',None), ('superadmin',None)])
async def test_dua_tab_kerangka_tanpa_antrean_dan_isi_setara_native(pg,lengkap,monkeypatch,role,warehouse):
    from app.web import layar_pekerjaan as layar
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang'].get(warehouse)) as c:
        before=await _sidik(pg)
        for query,tab in [('', 'tindakan'), ('tab=tindakan','tindakan'), ('tab=berjalan','berjalan'),
                          ('tab=asing','tindakan'), ('tab=tindakan&jenis=packing&cari=tidak-ada&pemasok=Nama+uji&gudang=g2','tindakan'),
                          ('tab=berjalan&informasi=1&kepemilikan=jasa&halaman=2','berjalan')]:
            path='/pekerjaan'+('?' +query if query else '')
            async def no_operational_read(*a,**kw):
                pytest.fail('Kerangka menunggu antrean/data operasional')
            with monkeypatch.context() as m:
                m.setattr(layar,'siapkan_daftar_pekerjaan',no_operational_read)
                shell=await c.get(path,headers={'X-Kerangka-Halaman':'1'})
            assert shell.status_code==200
            doc=BeautifulSoup(shell.text,'html.parser');root=doc.select_one('[data-halaman-bertahap]')
            assert root and len(root.select('thead th'))==5
            selected=doc.select_one('nav[aria-label="Tab pekerjaan"] [aria-current="page"]')
            assert selected and ('Perlu tindakan' if tab=='tindakan' else 'Berjalan') in selected.get_text(), (query, [str(n) for n in doc.select('nav[aria-label="Tab pekerjaan"]')])
            assert root.select_one('input[name=cari]') is not None
            assert len(root.select('select[name=jenis]'))==1
            assert root.select_one('select[name=pemasok]').has_attr('disabled')
            prints=doc.select('[data-lk-cetak], [data-pk-cetak]')
            assert prints and all(x.has_attr('disabled') for x in prints)
            assert not root.select('[data-post],[data-kirim],.benda[data-cari],.proses-aktif-list__row')
            native=await c.get(path,headers={'X-Pindah':'1'})
            data=await c.get('/api/halaman-bertahap/pekerjaan'+('?' +query if query else ''))
            assert native.status_code==data.status_code==200
            assert data.json()['stamp']==root['data-stamp']
            assert _isi(data.json()['html'])==_isi(native.text)
            assert data.headers['cache-control']=='private, no-store'
        assert await _sidik(pg)==before


async def test_katalog_dua_tab_filter_native_tanpa_wildcard_atau_aksi(pg,lengkap):
    from app.web import kerangka_langsung as registry
    async with await _klien(pg,role='admin') as c:
        before=await _sidik(pg)
        source='/pekerjaan?tab=berjalan&jenis=packing&cari=Nama+%26+uji&kepemilikan=jasa&gudang=g2&halaman=2'
        response=await c.get(source,headers={'X-Pindah':'0'})
        doc=BeautifulSoup(response.text,'html.parser')
        data=json.loads(doc.select_one('#padi-kerangka-langsung').string)
        assert registry.sah_rujukan(data)
        links={x['href'] for x in doc.select('nav[aria-label="Tab pekerjaan"] a') if urlsplit(x['href']).path=='/pekerjaan'}
        assert len(links)==2
        assert set(data['frames'])==set(registry.LITERAL)|{'/jasa'}|links
        for address in links:
            assert 'halaman=' not in address and 'buka=' not in address and 'nilai=' not in address
            html=''.join(data['potongan'][i] for i in data['frames'][address])
            frame=BeautifulSoup(html,'html.parser')
            root=frame.select_one('[data-halaman-bertahap]')
            assert frame.select_one('.bingkai')['data-pindah-alamat']==address
            assert root['data-url']=='/api/halaman-bertahap/pekerjaan?'+urlsplit(address).query
            assert root.select_one('input[name=cari]')['value']=='Nama & uji'
            assert root.select_one('select[name=jenis] option[selected]')['value']=='packing'
            assert not root.select('[data-post],.benda[data-cari]')
        # Parameter non-kontrak tidak membuang enam kerangka dasar/Jasa Admin.
        extra=await c.get('/pekerjaan?token_fixture=tidak-dicatat')
        inert=json.loads(BeautifulSoup(extra.text,'html.parser').select_one('#padi-kerangka-langsung').string)
        assert set(inert['frames'])==set(registry.LITERAL)|{'/jasa'}
        assert await _sidik(pg)==before


async def test_default_dan_tab_tidak_membuka_data_tanpa_sesi(pg,lengkap):
    async with await _klien(pg,role='admin') as c:
        c.cookies.clear()
        for path in ('/pekerjaan','/pekerjaan?tab=tindakan','/pekerjaan?tab=berjalan',
                     '/api/halaman-bertahap/pekerjaan','/api/halaman-bertahap/pekerjaan?tab=tindakan'):
            response=await c.get(path,headers={'X-Kerangka-Halaman':'1'},follow_redirects=False)
            assert response.status_code==303 and response.headers['location'].startswith('/masuk')
            assert 'POL-UJIP-' not in response.text


@pytest.mark.parametrize('status',[404,403])
async def test_tujuan_tab_opsional_gagal_tidak_mengabaikan_akses(pg,lengkap,monkeypatch,status):
    from fastapi import HTTPException
    from app.web import halaman_bertahap as page, kerangka_langsung as registry
    original=page.kerangka
    async def unavailable(request,*a,**kw):
        if request.query_params.get('cari')=='tab-fixture' and request.query_params.get('tab')=='berjalan':
            raise HTTPException(status,'Fixture optional target unavailable')
        return await original(request,*a,**kw)
    monkeypatch.setattr(page,'kerangka',unavailable)
    async with await _klien(pg,role='admin') as c:
        before=await _sidik(pg)
        response=await c.get('/pekerjaan?tab=tindakan&cari=tab-fixture')
        assert response.status_code==200
        host=BeautifulSoup(response.text,'html.parser').select_one('#padi-kerangka-langsung')
        if status==403:
            assert host is None, 'Invalid access must not be softened into a partial registry'
        else:
            data=json.loads(host.string)
            assert registry.sah_rujukan(data)
            remaining_tabs={x['href'] for x in BeautifulSoup(response.text,'html.parser').select('nav[aria-label="Tab pekerjaan"] a')
                            if urlsplit(x['href']).path=='/pekerjaan'
                            and not ('tab=berjalan' in x['href'] and 'tab-fixture' in x['href'])}
            assert len(remaining_tabs)==1
            assert set(data['frames'])==set(registry.LITERAL)|{'/jasa'}|remaining_tabs
            assert not any('tab=berjalan' in u and 'tab-fixture' in u for u in data['frames'])
        assert await _sidik(pg)==before


@pytest.mark.parametrize('role',['operator','admin'])
@pytest.mark.parametrize('width',[390,1280])
async def test_default_gagal_coba_lagi_mempertahankan_filter_dan_keluar_tanpa_post(pg,lengkap,role,width):
    import asyncio
    import httpx
    from playwright.async_api import expect
    from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
    api='/api/halaman-bertahap/pekerjaan'
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang']['g2'] if role=='operator' else None) as c:
        before=await _sidik(pg);native=c.request;fault={'next':True}
        async def read(method,url,**kw):
            assert method=='GET','Navigasi/retry bukan izin untuk menulis'
            response=await native(method,url,**kw)
            if str(url).split('?')[0]==api and fault['next']:
                fault['next']=False
                return httpx.Response(503,json={'detail':'Fixture read unavailable'})
            return response
        c.request=read
        async with peramban(c,width) as (page,t):
            await page.goto(BASE+'/kabar')
            if width<900:await page.locator('#buka-laci').click()
            entered,release=asyncio.Event(),asyncio.Event();t['gates'][api]=(entered,release)
            try:
                await page.locator('#laci a[href="/pekerjaan"]').click()
                await asyncio.wait_for(entered.wait(),15)
                await expect(page.locator('[data-halaman-bertahap]')).to_be_visible()
                await expect(page.locator('section[aria-label="Pekerjaan"] nav a')).to_have_count(3)
                await expect(page.locator('[data-shell-table-wrap] th')).to_have_count(5)
                release.set()
                await expect(page.locator('[data-shell-message]')).to_contain_text('Gagal memuat data; ini bukan daftar kosong')
                await expect(page.locator('[data-shell-retry]')).to_be_visible()
                await page.locator('input[name=cari]:visible').fill('filter-belum-diterapkan')
                await page.locator('[data-shell-retry]').click()
                await expect(page.locator('[data-shell-status]')).to_contain_text('Data siap')
                await expect(page.locator('input[name=cari]:visible')).to_have_value('filter-belum-diterapkan')
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/kabar"]').focus()
                await page.locator('#laci a[href="/kabar"]').press('Enter')
                await expect(page).to_have_url(BASE+'/kabar')
                await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
                await page.goto(BASE+'/pekerjaan?tab=tindakan')
                await expect(page.locator('input[name=cari]:visible')).to_have_value('')
                assert not t['posts'] and not t['errors'],t['errors']
                assert await _sidik(pg)==before
            finally:
                release.set();t['gates'].pop(api,None)
