"""First click framework with authorized native fixture; intercepted transport.

The separate owner native-HTTP/PWA receipt checks ordinary browser headers;
this regression deliberately holds HTML and data as independent responses.
"""
import asyncio
import pytest
from playwright.async_api import expect
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
from tests.pg.test_barang_keluar import gudang,_klien,_stok
from tests.pg.test_halaman_bertahap import _sidik

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('role,path,kind',[('admin','/barang-keluar','pengiriman'),('operator','/barang-keluar','pengiriman'),('admin','/jasa','jasa')])
@pytest.mark.parametrize('width',[390,1280])
async def test_native_blueprint_before_html_and_data(pg,gudang,role,path,kind,width):
    async with await _klien(pg,gudang['adm' if role=='admin' else 'op'],'ui-click-'+role+str(width)+kind,mode=role) as client:
        before=await _sidik(pg);stock=await _stok(pg,gudang)
        async with peramban(client,width) as (page,t):
            # Explicit Doc/Data renderer contract; network-added Sec-Fetch is
            # tested by real HTTP outside interception, not fabricated here.
            await page.set_extra_http_headers({'X-Kerangka-Halaman':'1'})
            html_enter,html_release=asyncio.Event(),asyncio.Event()
            data_enter,data_release=asyncio.Event(),asyncio.Event()
            t['gates'][path]=(html_enter,html_release)
            t['gates']['/api/halaman-bertahap/'+kind]=(data_enter,data_release)
            try:
                await page.goto(BASE+'/kabar',wait_until='load')
                await page.wait_for_function("()=>window.PadiKerangkaUI&&document.getElementById('padi-kerangka-ui')")
                if width<900:await page.locator('#buka-laci').click()
                link=page.locator('#laci a[href="'+path+'"]').first
                summary=link.locator('xpath=ancestor::details[not(@open)][1]/summary')
                if await summary.count():await summary.click()
                await link.click();await asyncio.wait_for(data_enter.wait(),20)
                assert not html_enter.is_set()
                root=page.locator('[data-jasa-bertahap]' if kind=='jasa' else '[data-halaman-bertahap][data-kind="pengiriman"]')
                await expect(root).to_be_visible();await expect(page.locator('.halaman-memuat')).to_have_count(0)
                await expect(root.locator('h1')).to_have_count(0)
                search=root.locator('input[type=search]');await expect(search).to_be_enabled()
                geometry=await search.bounding_box()
                prefix='js' if kind=='jasa' else 'bk';button=root.locator('[data-'+prefix+'-buka="'+prefix+'-filter"]').first
                await button.focus();await page.keyboard.press('Enter');await expect(root.locator('#'+prefix+'-filter')).to_be_visible()
                await page.keyboard.press('Escape');await expect(button).to_be_focused();await button.blur()
                if kind=='jasa':
                    await expect(root.locator('.jasa-daftar')).to_be_visible();await expect(root.locator('[data-js-cetak]').first).to_be_disabled()
                else:await expect(root.locator('thead th')).to_have_count(11)
                data_release.set()
                if kind=='jasa':await expect(root.locator('[data-jasa-baca-status]')).to_have_text('Daftar pelanggan selesai dibaca.')
                else:await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
                final=await page.locator('input[type=search]').bounding_box()
                assert all(abs(geometry[k]-final[k])<=2 for k in ('x','y','width','height')),(geometry,final)
                assert not t['posts'] and not t['errors']
            finally:html_release.set();data_release.set()
        assert await _sidik(pg)==before and await _stok(pg,gudang)==stock
