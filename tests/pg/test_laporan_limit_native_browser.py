"""Oversized native response: explicit PDF fallback only, no larger body cap."""
import asyncio
import pytest
from playwright.async_api import expect
from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
pytestmark=pytest.mark.asyncio
PATH='/laporan/penggilingan';PDF='/laporan-periode/penggilingan.pdf'

@pytest.mark.parametrize('width',[390,1280])
async def test_size_rejection_offers_explicit_native_pdf_get_no_automatic_request(pg,stok_lengkap,width):
    async with await _klien(pg,role=P.ADMIN) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/laporan',wait_until='load')
            t['pad_html'][PATH]=8*1024*1024+64
            await page.locator('.lp-pintu[href="'+PATH+'"]').click()
            root=page.locator('[data-laporan-detail-native]')
            await expect(root.locator('[data-detail-native-status]')).to_contain_text('Laporan terlalu besar')
            link=root.locator('[data-detail-native-pdf-fallback]')
            await expect(link).to_be_visible();await expect(link).to_have_attribute('href',PDF)
            await expect(root.locator('[data-detail-native-retry]')).to_be_hidden()
            assert t['gets'].count(PDF)==0 and not t['posts']
            await expect(root.locator('select[name=periode]')).to_have_value('bulan_ini')
            async with page.context.expect_event('request',predicate=lambda req:req.url==BASE+PDF) as event:
                await link.click(no_wait_after=True)
            request=await event.value;assert request.method=='GET'
            response=await request.response();assert response and response.status==200
            assert (await response.all_headers()).get('content-type','').startswith('application/pdf')
            assert t['gets'].count(PDF)==1 and not t['posts'] and not t['errors']
            # A new range is a read-filter draft. It must hide the prior
            # fallback rather than download an old period behind the user.
            await root.locator('select[name=periode]').select_option('khusus')
            await expect(link).to_be_hidden();assert await link.get_attribute('href') is None
        assert await _sidik(pg)==before

@pytest.mark.parametrize('width',[390,1280])
async def test_leaving_before_large_response_keeps_new_page_and_no_pdf_request(pg,stok_lengkap,width):
    async with await _klien(pg,role=P.ADMIN) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/laporan',wait_until='load')
            entered,release,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
            t['gates'][PATH]=(entered,release);t['completed'][PATH]=done;t['pad_html'][PATH]=8*1024*1024+64
            try:
                await page.locator('.lp-pintu[href="'+PATH+'"]').click()
                await asyncio.wait_for(entered.wait(),20)
                await page.locator(('.bar__balik' if width<900 else '.desktop-back')+'[href="/laporan"]').click()
                await expect(page).to_have_url(BASE+'/laporan')
                release.set();await asyncio.wait_for(done.wait(),20)
                await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                await expect(page.locator('[data-laporan-detail-native],[data-detail-native-pdf-fallback]')).to_have_count(0)
                assert t['gets'].count(PDF)==0 and not t['posts'] and not t['errors']
            finally:release.set()
        assert await _sidik(pg)==before
