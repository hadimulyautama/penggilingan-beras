"""Two native settings routes, no product or account writes."""
import asyncio
import json
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

@pytest.mark.parametrize('role,warehouse',[(P.ADMIN,None),(P.OPERATOR,'g2')])
@pytest.mark.parametrize('width',[390,1280])
async def test_settings_first_click_native_permissions_session_and_abandoned_read(pg,stok_lengkap,role,warehouse,width):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(warehouse)) as client:
        before=await _sidik(pg)
        native=await client.get('/pengaturan',headers={'X-Pindah':'1'})
        assert native.status_code==200
        expected=BeautifulSoup(native.text,'html.parser')
        expected_subtitles=[n.get_text() for n in expected.select('.pg-grup>header p')]
        expected_doors=[(n.name,n.select_one('strong').get_text(),n.get('href'),n.get('aria-disabled')) for n in expected.select('.pg-pintu')]
        async with peramban(client,width) as (page,t):
            await page.goto(BASE+'/barang-masuk',wait_until='load')
            await page.wait_for_function("()=>window.PadiKerangkaPengaturanUI&&document.getElementById('padi-pengaturan-kerangka')")
            entered,release=asyncio.Event(),asyncio.Event();t['gates']['/pengaturan']=(entered,release)
            try:
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/pengaturan"]').click()
                await asyncio.wait_for(entered.wait(),20)
                root=page.locator('[data-pengaturan-menu-kerangka]');await expect(root).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                actual=await root.locator('.pg-pintu').evaluate_all("nodes=>nodes.map(n=>[n.tagName.toLowerCase(),n.querySelector('strong').textContent,n.getAttribute('href'),n.getAttribute('aria-disabled')])")
                assert actual==[list(row) for row in expected_doors]
                assert await root.locator('.pg-grup>header p').all_text_contents()==expected_subtitles
                await expect(root.locator('.pg-terik button')).to_be_disabled()
                release.set();await expect(root).to_have_count(0)
                # Session shell must keep logout controls disabled until the
                # actual account/session, CSRF and existing policy are read.
                entered2,release2=asyncio.Event(),asyncio.Event();t['gates']['/pengaturan/sesi']=(entered2,release2)
                await page.locator('.pg-pintu[href="/pengaturan/sesi"]').press('Enter')
                await asyncio.wait_for(entered2.wait(),20)
                root=page.locator('[data-pengaturan-menu-kerangka]');await expect(root.locator('h1')).to_have_text('Sesi perangkat')
                assert await root.locator('.setelan-sesi button:disabled').count()==2
                await expect(root.locator('form')).to_have_count(0)
                release2.set();await expect(root).to_have_count(0)
                await expect(page.locator('form[action="/keluar-semua"]')).to_have_count(1)
                entered3,release3=asyncio.Event(),asyncio.Event();done=asyncio.Event()
                t['gates']['/pengaturan']=(entered3,release3);t['completed']['/pengaturan']=done
                await page.locator('a.pg-kembali[href="/pengaturan"]').click()
                await asyncio.wait_for(entered3.wait(),20)
                if width<900:await page.locator('#buka-laci').click()
                await page.locator('#laci a[href="/barang-masuk"]').click()
                await expect(page).to_have_url(BASE+'/barang-masuk')
                release3.set();await asyncio.wait_for(done.wait(),20)
                await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                await expect(page.locator('[data-pengaturan-menu-kerangka]')).to_have_count(0)
                assert not t['posts'] and not t['errors'],t
            finally:
                release.set()
                if 'release2' in locals():release2.set()
                if 'release3' in locals():release3.set()
        assert await _sidik(pg)==before
