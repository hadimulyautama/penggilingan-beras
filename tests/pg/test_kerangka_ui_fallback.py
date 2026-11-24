"""Asset unavailable: retain native navigation and editor guards, no fake frame."""
import pytest
from playwright.async_api import expect
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
from tests.pg.test_barang_keluar import gudang,_klien,_stok
from tests.pg.test_halaman_bertahap import _sidik
from pathlib import Path
import json,os

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('width',[390,1280])
async def test_unavailable_public_asset_uses_native_document_not_generic_transition(pg,gudang,width):
    async with await _klien(pg,gudang['adm'],'ui-fallback-'+str(width)) as client:
        before=await _sidik(pg);stock=await _stok(pg,gudang)
        async with peramban(client,width) as (page,t):
            await page.set_extra_http_headers({'X-Kerangka-Halaman':'1'})
            await page.context.route('**/static/kerangka-ui.js?*',lambda route:route.fulfill(status=503,content_type='text/javascript',body='/* fixture asset unavailable */'))
            await page.goto(BASE+'/kabar',wait_until='load')
            for path in ('/barang-keluar','/jasa'):
                link=page.locator('#laci a[href="'+path+'"]').first
                await expect(link).to_have_attribute('data-utuh','')
            if width<900:await page.locator('#buka-laci').click()
            reads=[];page.on('request',lambda req:reads.append((req.method,req.resource_type,req.url)))
            await page.locator('#laci a[href="/barang-keluar"]').click()
            await page.wait_for_url('**/barang-keluar')
            await expect(page.locator('thead th')).to_have_count(11)
            assert any(m=='GET' and kind=='document' and u==BASE+'/barang-keluar' for m,kind,u in reads)
            assert not t['posts'] and not t['errors']
        assert await _sidik(pg)==before and await _stok(pg,gudang)==stock
