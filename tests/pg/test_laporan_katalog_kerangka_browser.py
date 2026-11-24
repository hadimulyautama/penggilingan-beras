"""Native catalog first frame and GET-only retry; no report/journal mutation."""
import asyncio
import pytest
from bs4 import BeautifulSoup
from hmu_identitas import peran as P
from playwright.async_api import expect
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.OPERATOR,'g2')])
async def test_catalog_native_links_and_guards_are_not_replaced(pg,stok_lengkap,role,warehouse):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        shell=await client.get('/laporan',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        native=await client.get('/laporan',headers={'X-Pindah':'1'})
        assert shell.status_code==native.status_code==200
        a,b=(BeautifulSoup(x.text,'html.parser') for x in (shell,native))
        assert a.select_one('[data-laporan-katalog-kerangka]') and not b.select('[data-laporan-katalog-kerangka]')
        links=lambda d:[(x['href'],x.get_text(' ',strip=True)) for x in d.select('a[data-laporan]')]
        assert links(a)==links(b) and len(links(a))==13
        assert not a.select('[data-laporan-katalog-kerangka] h1,[data-laporan-katalog-kerangka] table')
        assert await _sidik(pg)==before

@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.OPERATOR,'g2')])
@pytest.mark.parametrize('width',[390,1280])
async def test_catalog_framework_before_html_and_get_retry(pg,stok_lengkap,role,warehouse,width):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/kabar',wait_until='load')
            await page.wait_for_function("()=>window.PadiKerangkaUI&&document.getElementById('padi-kerangka-ui')")
            entered,release=asyncio.Event(),asyncio.Event();t['gates']['/laporan']=(entered,release)
            requests=[];page.on('request',lambda r:requests.append((r.method,r.resource_type,r.url)))
            try:
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/laporan"]').click();await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-laporan-katalog-kerangka]');await expect(root).to_be_visible()
                await expect(root.locator('a[data-laporan]')).to_have_count(13)
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                await expect(root.locator('h1,form,table')).to_have_count(0)
                first=root.locator('a[data-laporan]').first;geometry=await first.bounding_box()
                button=root.locator('[data-lk-buka="lk-panduan"]').first;await button.focus();await page.keyboard.press('Enter')
                await expect(root.locator('#lk-panduan')).to_be_visible();await page.keyboard.press('Escape');await expect(button).to_be_focused()
                assert not any(kind=='document' and u==BASE+'/laporan' for _,kind,u in requests)
                release.set();await expect(root).to_have_count(0)
                await expect(page.locator('a[data-laporan]')).to_have_count(13)
                final=await page.locator('a[data-laporan]').first.bounding_box()
                assert all(abs(geometry[k]-final[k])<=2 for k in ('x','y','width','height')),(geometry,final)
                assert not t['posts'] and not t['errors']
            finally:release.set()
        assert await _sidik(pg)==before

async def test_catalog_failed_get_retry_keeps_framework_and_does_not_post(pg,stok_lengkap):
    async with await _klien(pg,role=P.ADMIN) as client:
        before=await _sidik(pg)
        async with peramban(client,390) as (page,t):
            await page.goto(BASE+'/kabar',wait_until='load');await page.wait_for_function('()=>window.PadiKerangkaUI')
            failed={'once':False}
            async def response(route):
                if not failed['once'] and (await route.request.all_headers()).get('x-pindah')=='1':
                    failed['once']=True;await route.fulfill(status=503,content_type='text/html',body='Fixture read unavailable')
                else:await route.fallback()
            await page.context.route('**/laporan',response)
            await page.locator('#buka-laci').click();await page.locator('#laci a[href="/laporan"]').click()
            root=page.locator('[data-laporan-katalog-kerangka]');await expect(root.locator('[data-katalog-native-retry]')).to_be_visible()
            await expect(root.locator('a[data-laporan]')).to_have_count(13)
            await root.locator('[data-katalog-native-retry]').click();await expect(root).to_have_count(0)
            await expect(page.locator('a[data-laporan]')).to_have_count(13)
            assert failed['once'] and not t['posts'] and not t['errors']
        assert await _sidik(pg)==before
