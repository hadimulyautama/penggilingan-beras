"""Native shipping read parity and structure; no production/data writer change."""
import asyncio
from urllib.parse import urlsplit
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect

from tests.pg.test_barang_keluar import gudang, _klien, _perintah, _stok
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE

pytestmark=pytest.mark.asyncio
DOCUMENT={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}


def columns(doc):
    return [[n.get_text(' ',strip=True) for n in table.select('thead th')]
            for table in doc.select('table')]


async def test_shipping_shell_and_native_filtered_reader_have_same_columns_and_scope(pg,gudang):
    shipment=await _perintah(pg,gudang,karung=12)
    oid=shipment.rec.id
    stock=await _stok(pg,gudang)
    for uid,name,admin in [(gudang['adm'],'shipping-shell-admin',True),(gudang['op'],'shipping-shell-op',False)]:
        async with await _klien(pg,uid,name) as client:
            before=await _sidik(pg)
            for query in ('','?q=tidak-ada&status=perintah&sejak=2020-01-01'):
                shell=await client.get('/barang-keluar'+query,headers=DOCUMENT)
                assert shell.status_code==200
                doc=BeautifulSoup(shell.text,'html.parser')
                assert '&lt;tbody&gt;' not in shell.text
                root=doc.select_one('[data-halaman-bertahap][data-kind="pengiriman"]')
                assert root and not root.select('h1,.halaman-memuat,[data-detail-keluar]')
                assert [len(x) for x in columns(root)]==[4,7]
                assert all(x.has_attr('disabled') for x in root.select('[data-bk-cetak]'))
                assert bool(root.select('a[href="/barang-keluar/baru"]'))==admin
                assert not root.select('.bk-aksi-konteks')
                assert len(root.select('[data-pengiriman-alat] [data-bk-buat]'))==int(admin)
                assert not root.select('input[name="_csrf"]')
                native=await client.get('/barang-keluar'+query,headers={'X-Pindah':'1'})
                data=await client.get('/api/halaman-bertahap/pengiriman'+query)
                assert native.status_code==data.status_code==200
                actual=BeautifulSoup(data.json()['html'],'html.parser')
                legacy=BeautifulSoup(native.text,'html.parser')
                assert columns(root)==columns(actual)==columns(legacy)
                assert not actual.select('[data-halaman-bertahap]')
                assert data.json()['stamp']==root['data-stamp']
                links=lambda d:[n.get('data-detail-keluar') for n in d.select('[data-detail-keluar]')]
                assert links(actual)==links(legacy)
                assert any(urlsplit(link).path=='/barang-keluar/'+str(oid) for link in links(actual))==(not bool(query))
            for url in ('/barang-keluar?sebelum=invalid','/api/halaman-bertahap/pengiriman?sebelum=invalid'):
                assert (await client.get(url)).status_code==422
            assert await _sidik(pg)==before
    assert await _stok(pg,gudang)==stock


@pytest.mark.parametrize('width',[390,1280])
@pytest.mark.parametrize('role',['admin','operator'])
async def test_shipping_document_keeps_native_controls_while_data_is_pending(pg,gudang,width,role,monkeypatch):
    from app.web import halaman_bertahap
    negotiation=[]
    original=halaman_bertahap.memakai_kerangka
    def observed(request,kind):
        value=original(request,kind)
        if kind=='pengiriman':negotiation.append(dict(path=request.url.path,
            mode=request.headers.get('sec-fetch-mode'),dest=request.headers.get('sec-fetch-dest'),
            requested=request.headers.get('x-kerangka-halaman'),
            reading=getattr(request.state,'isi_halaman_bertahap',False),result=value))
        return value
    monkeypatch.setattr(halaman_bertahap,'memakai_kerangka',observed)
    uid=gudang['adm'] if role=='admin' else gudang['op']
    async with await _klien(pg,uid,'shipping-browser-'+role) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,transport):
            entered,release=asyncio.Event(),asyncio.Event()
            transport['gates']['/api/halaman-bertahap/pengiriman']=(entered,release)
            try:
                response=await page.goto(BASE+'/barang-keluar',wait_until='load')
                assert response.status==200
                root=page.locator('[data-halaman-bertahap][data-kind="pengiriman"]')
                await expect(root,'Native shipping negotiation: '+str(negotiation)).to_be_visible()
                assert not transport['errors'],transport['errors']
                try:
                    await asyncio.wait_for(entered.wait(),20)
                except TimeoutError:
                    pytest.fail('Native shipping GET not reached: '+str(dict(errors=transport['errors'],gets=transport['gets'],root=await root.get_attribute('data-url'))))
                await expect(root.locator('h1,.halaman-memuat')).to_have_count(0)
                await expect(root.locator('table')).to_have_count(2)
                await expect(root.locator('thead th')).to_have_count(11)
                await expect(root.locator('input[type=search]')).to_be_enabled()
                await expect(root.locator('[data-bk-cetak]').first).to_be_disabled()
                await root.locator('[data-bk-buka="bk-filter"]').first.click()
                await expect(root.locator('#bk-filter')).to_be_visible()
                await root.locator('#bk-filter [name=sejak]').fill('2020-01-01')
                release.set()
                await expect(root.locator('[data-shell-status]')).to_contain_text('pilihan tetap dipertahankan')
                await expect(root.locator('#bk-filter [name=sejak]')).to_have_value('2020-01-01')
                await page.keyboard.press('Escape')
                assert not transport['posts'] and not transport['errors']
            finally:release.set()
        assert await _sidik(pg)==before
