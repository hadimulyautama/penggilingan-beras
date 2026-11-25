"""Native notification framework is a read, never a mark/open action."""
import asyncio
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect
from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban,BASE
pytestmark=pytest.mark.asyncio
DOC={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}

@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.OPERATOR,'g2')])
async def test_document_has_no_notification_rows_watermark_or_write_controls(pg,stok_lengkap,role,warehouse):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        response=await client.get('/kabar?tab=belum',headers=DOC)
        doc=BeautifulSoup(response.text,'html.parser');root=doc.select_one('[data-kabar-native]')
        assert response.status_code==200 and root
        assert len(root.select('nav a'))==2
        assert not root.select('form,input,[name],.kb-item,[data-sampai]')
        actual=await client.get('/kabar?tab=belum',headers={'X-Pindah':'1'})
        assert actual.status_code==200 and 'data-kabar-native' not in actual.text
        assert await _sidik(pg)==before

@pytest.mark.parametrize('width',[390,1280])
@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.OPERATOR,'g2')])
async def test_menu_pending_error_retry_tab_and_leave_are_get_only(pg,stok_lengkap,width,role,warehouse):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/laporan',wait_until='load')
            entered,release=asyncio.Event(),asyncio.Event();t['gates']['/kabar']=(entered,release)
            try:
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/kabar"]').click()
                await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-kabar-native]');await expect(root).to_be_visible()
                await expect(root.locator('nav[aria-label="Status baca"] a')).to_have_count(2)
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                assert not await root.locator('form,input,[name]').count()
                await expect(root.locator('#kb-jenis')).to_be_disabled()
                release.set();await expect(root).to_have_count(0)
                await expect(page.locator('section.kb select[name=jenis]')).to_be_visible()
                # Re-enter through the same explicit public factory; a failed
                # optional GET keeps its structure and a GET-only retry.
                await page.goto(BASE+'/laporan',wait_until='load')
                async def fail_once(route):
                    await route.fulfill(status=503,body='Synthetic owner read unavailable')
                await page.route('**/kabar',fail_once,times=1)
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/kabar"]').click()
                root=page.locator('[data-kabar-native]')
                await expect(root.locator('[data-kabar-native-retry]')).to_be_visible()
                await root.locator('[data-kabar-native-retry]').press('Enter')
                await expect(root).to_have_count(0)
                await expect(page.locator('section.kb select[name=jenis]')).to_be_visible()
                entered2,release2,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
                t['gates']['/kabar']=(entered2,release2);t['completed']['/kabar']=done
                try:
                    await page.locator('section.kb a[data-kabar-belum]').click()
                    await asyncio.wait_for(entered2.wait(),20)
                    await expect(page.locator('[data-kabar-native]')).to_be_visible()
                    if width<900:await page.locator('#buka-laci').click()
                    await page.locator('#laci a[href="/barang-masuk"]').click()
                    await expect(page).to_have_url(BASE+'/barang-masuk')
                    release2.set();await asyncio.wait_for(done.wait(),20)
                    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                    await expect(page.locator('[data-kabar-native],section.kb')).to_have_count(0)
                finally:release2.set()
                assert not t['posts'] and not t['errors'],t
            finally:release.set()
        assert await _sidik(pg)==before
